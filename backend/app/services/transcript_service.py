from __future__ import annotations

import html
import json
import os
import re
import tempfile
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

import httpx

from app.schemas import TranscriptSegment, VideoInfo
from app.services.ytdlp_service import _base_ytdlp_opts, _yt_dlp


class TranscriptUnavailable(RuntimeError):
    pass


TIMESTAMP_RE = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})(?P<ms>[,.]\d{1,3})?"
)
TAG_RE = re.compile(r"<[^>]+>")
VTT_STYLE_RE = re.compile(r"^(WEBVTT|Kind:|Language:|NOTE\b|STYLE\b|REGION\b)", re.IGNORECASE)
LANG_PRIORITY = ("zh-Hans", "zh-CN", "zh", "zh-Hant", "en")


def _seconds(value: str) -> float:
    match = TIMESTAMP_RE.search(value)
    if not match:
        return 0.0
    ms = (match.group("ms") or "").replace(",", ".")
    return (
        int(match.group("h")) * 3600
        + int(match.group("m")) * 60
        + int(match.group("s"))
        + (float(ms) if ms else 0.0)
    )


def _clean_text(value: str) -> str:
    value = TAG_RE.sub("", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def parse_vtt(content: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    blocks = re.split(r"\n\s*\n", content.replace("\r\n", "\n").replace("\r", "\n"))
    for block in blocks:
        lines = [line.strip("\ufeff ") for line in block.splitlines() if line.strip()]
        if not lines or VTT_STYLE_RE.match(lines[0]):
            continue
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        timing = lines[timing_index]
        start_raw, end_raw = [part.strip() for part in timing.split("-->", 1)]
        end_raw = end_raw.split()[0]
        text = _clean_text(" ".join(lines[timing_index + 1 :]))
        if text:
            segments.append(TranscriptSegment(start=_seconds(start_raw), end=_seconds(end_raw), text=text))
    return _merge_duplicate_segments(segments)


def parse_srt(content: str) -> list[TranscriptSegment]:
    return parse_vtt(content)


def parse_json3(content: str) -> list[TranscriptSegment]:
    payload = json.loads(content)
    segments: list[TranscriptSegment] = []
    for event in payload.get("events") or []:
        pieces = event.get("segs") or []
        text = _clean_text("".join(piece.get("utf8", "") for piece in pieces if isinstance(piece, dict)))
        if not text:
            continue
        start = float(event.get("tStartMs") or 0) / 1000
        duration = float(event.get("dDurationMs") or 0) / 1000
        segments.append(TranscriptSegment(start=start, end=start + duration if duration else None, text=text))
    return _merge_duplicate_segments(segments)


def parse_xml_danmaku(content: str) -> list[TranscriptSegment]:
    """解析 Bilibili 弹幕 XML 格式，提取时间戳和文本内容。"""
    segments: list[TranscriptSegment] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    for elem in root.iter("d"):
        p = elem.get("p", "")
        text = _clean_text(elem.text or "")
        if not text:
            continue
        try:
            start = float(p.split(",", 1)[0])
        except (ValueError, IndexError):
            start = 0.0
        segments.append(TranscriptSegment(start=start, end=None, text=text))
    segments.sort(key=lambda s: s.start)
    return _merge_duplicate_segments(segments)


def _merge_duplicate_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """合并连续相同文本的字幕段，保留时间范围而非丢弃。"""
    if not segments:
        return []
    merged: list[TranscriptSegment] = [segments[0]]
    for segment in segments[1:]:
        last = merged[-1]
        if segment.text == last.text:
            last.end = segment.end or last.end
        else:
            merged.append(segment)
    return merged


def transcript_to_text(segments: list[TranscriptSegment], max_chars: int | None = None) -> str:
    lines = [f"[{format_timestamp(item.start)}] {item.text}" for item in segments]
    text = "\n".join(lines)
    if max_chars and len(text) > max_chars:
        return text[:max_chars] + "\n..."
    return text


def format_timestamp(seconds: float | None) -> str:
    if seconds is None:
        return "00:00"
    seconds_int = max(0, int(seconds))
    h = seconds_int // 3600
    m = (seconds_int % 3600) // 60
    s = seconds_int % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class TranscriptService:
    BILIBILI_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com/",
    }

    def extract(self, url: str, preferred_language: str = "zh") -> tuple[VideoInfo, list[TranscriptSegment]]:
        # 抖音优先用内置解析器拿视频信息，避免直接走 yt-dlp 触发 cookie 校验
        from app.services.douyin_resolver import resolve as resolve_douyin
        builtin_video = resolve_douyin(url)
        if builtin_video:
            # 抖音字幕提取不使用 yt-dlp（需 cookie 且提取器不支持字幕下载），
            # 改为从页面已解析数据中提取可用文本内容
            segments = self._try_douyin_subtitles(builtin_video)
            if segments:
                return builtin_video, segments
            raise TranscriptUnavailable(
                "抖音视频暂未检测到平台内嵌字幕。"
                "部分抖音视频的字幕是画面内嵌的（烧录在视频中），无法以文本形式提取，请尝试其他平台（如 YouTube、Bilibili）带有独立字幕轨的视频。"
            )

        # 小红书：页面不含笔记数据，用 yt-dlp 取视频信息，字幕用简介代替
        from app.services.xiaohongshu_resolver import is_xiaohongshu_url
        if is_xiaohongshu_url(url):
            try:
                yt_dlp = _yt_dlp()
                opts = _base_ytdlp_opts()
                with yt_dlp.YoutubeDL(opts) as ydl:
                    raw = ydl.extract_info(url, download=False)
                    info = ydl.sanitize_info(raw)
                video = self._video_info(url, info)
                segments = self._try_builtin_subtitles(video, "小红书")
                if segments:
                    return video, segments
            except Exception:
                pass
            raise TranscriptUnavailable(
                "小红书笔记暂未检测到可提取的文本字幕。"
                "小红书视频的字幕通常是画面内嵌的，请尝试其他平台（如 YouTube、Bilibili）带有独立字幕轨的视频。"
            )

        # Bilibili 优先用官方 API 提取字幕（CC字幕 + AI字幕），比 yt-dlp 内建下载更可靠
        if self._is_bilibili_url(url):
            bili_result = self._extract_bilibili(url)
            if bili_result:
                return bili_result

        yt_dlp = _yt_dlp()
        opts = _base_ytdlp_opts()
        with yt_dlp.YoutubeDL(opts) as ydl:
            raw = ydl.extract_info(url, download=False)
            info = ydl.sanitize_info(raw)
        video = self._video_info(url, info)

        # YouTube 检查字幕可用性
        extractor = info.get("extractor_key") or ""
        if extractor.lower() in ("youtube",):
            has_subs = bool(info.get("subtitles")) or bool(info.get("automatic_captions"))
            if not has_subs:
                raise TranscriptUnavailable(
                    "该视频暂无字幕或自动生成的字幕。"
                    "请尝试带有字幕（CC 按钮可见）的 YouTube 视频，或 Bilibili 等有字幕的平台的视频。"
                )

        segments = self._download_and_parse_subtitles(url, preferred_language)
        if not segments:
            if extractor.lower() == "bilibili":
                raise TranscriptUnavailable(
                    "该 Bilibili 视频暂无字幕或弹幕数据。"
                    "请确认：1) 视频有 CC 字幕或弹幕；2) 后端已配置浏览器 cookies（B站字幕需要登录）。"
                )
            raise TranscriptUnavailable("字幕内容为空或无法解析，请尝试带字幕的公开视频。")
        return video, segments

    @staticmethod
    def _is_bilibili_url(url: str) -> bool:
        return "bilibili.com" in url or "b23.tv" in url

    @staticmethod
    def _try_douyin_subtitles(video_info: VideoInfo) -> list[TranscriptSegment]:
        return TranscriptService._try_builtin_subtitles(video_info, "抖音")

    @staticmethod
    def _try_builtin_subtitles(video_info: VideoInfo, platform: str) -> list[TranscriptSegment]:
        """从内置解析器已获取的视频信息中提取可用文本内容。

        适用于抖音、小红书等无独立字幕轨的平台，将视频简介作为文本内容返回。
        简介过短或为默认标题时视为无可用内容。
        """
        default_titles = {"抖音公开视频", "小红书笔记", "小红书图集"}
        desc = (video_info.title or "").strip()
        if desc and desc not in default_titles and len(desc) >= 10:
            return [TranscriptSegment(start=0, end=None, text=desc)]
        return []

    @staticmethod
    def _parse_bvid(url: str) -> Optional[str]:
        m = re.search(r"(BV[a-zA-Z0-9]+)", url)
        return m.group(1) if m else None

    def _extract_bilibili(self, url: str) -> tuple[VideoInfo, list[TranscriptSegment]] | None:
        """通过 Bilibili 官方 API 提取 CC 字幕和 AI 字幕，跳过 yt-dlp。"""
        bvid = self._parse_bvid(url)
        if not bvid:
            return None
        try:
            # 1. 获取视频基本信息 (aid, cid)
            view_resp = httpx.get(
                f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
                headers=self.BILIBILI_HEADERS, timeout=15,
            )
            view_data = view_resp.json().get("data", {})
            cid = view_data.get("cid")
            aid = view_data.get("aid")
            title = view_data.get("title", "未命名视频")
            duration = view_data.get("duration")
            if not cid or not aid:
                return None

            # 2. 获取字幕列表（CC 字幕 + AI 字幕）
            dm_resp = httpx.get(
                f"https://api.bilibili.com/x/v2/dm/view?aid={aid}&oid={cid}&type=1",
                headers=self.BILIBILI_HEADERS, timeout=15,
            )
            dm_data = dm_resp.json().get("data", {})
            subtitle_list = dm_data.get("subtitle", {}).get("subtitles", [])

            if not subtitle_list:
                return None

            # 3. 优先选中文字幕
            best = subtitle_list[0]
            for s in subtitle_list:
                lang = s.get("lan", "")
                if lang in ("zh", "zh-Hans", "zh-CN"):
                    best = s
                    break

            sub_url = best.get("subtitle_url", "")
            if sub_url.startswith("//"):
                sub_url = "https:" + sub_url
            if sub_url.startswith("http://"):
                sub_url = "https://" + sub_url[7:]
            if not sub_url:
                return None

            # 4. 下载并解析字幕 JSON
            sub_resp = httpx.get(sub_url, headers=self.BILIBILI_HEADERS, timeout=15)
            sub_json = sub_resp.json()
            body = sub_json.get("body", [])

            segments = [
                TranscriptSegment(
                    start=round(item.get("from", 0), 2),
                    end=round(item.get("to", 0), 2),
                    text=item.get("content", "").strip(),
                )
                for item in body
                if item.get("content", "").strip()
            ]
            if not segments:
                return None

            video = VideoInfo(
                url=url,
                title=title,
                extractor="bilibili",
                duration=float(duration) if duration else None,
                webpage_url=f"https://www.bilibili.com/video/{bvid}",
            )
            return video, segments
        except Exception:
            return None

    # 常见语言及其变体，覆盖 YouTube / Bilibili 主流字幕
    _LANG_VARIANTS: dict[str, list[str]] = {
        "zh": ["zh", "zh-Hans", "zh-Hant", "zh-CN", "zh-TW", "zh-HK", "danmaku"],
        "en": ["en", "en-US", "en-GB", "en-CA", "en-AU"],
        "es": ["es", "es-ES", "es-MX", "es-419"],
        "ja": ["ja", "ja-JP"],
        "ko": ["ko", "ko-KR"],
        "fr": ["fr", "fr-FR", "fr-CA"],
        "de": ["de", "de-DE", "de-AT"],
        "pt": ["pt", "pt-BR", "pt-PT"],
        "ru": ["ru", "ru-RU"],
        "ar": ["ar", "ar-SA", "ar-AE"],
        "hi": ["hi", "hi-IN"],
        "it": ["it", "it-IT"],
        "nl": ["nl", "nl-NL"],
        "pl": ["pl", "pl-PL"],
        "tr": ["tr", "tr-TR"],
        "vi": ["vi", "vi-VN"],
        "th": ["th", "th-TH"],
        "id": ["id", "id-ID"],
    }

    # 字幕回退语言：当首选语言不可用时，按此顺序尝试
    _FALLBACK_LANGS = [
        "en", "en-US", "en-GB",
        "zh", "zh-Hans", "zh-CN",
        "es", "es-ES",
        "ja", "ja-JP",
        "ko", "ko-KR",
        "fr", "fr-FR",
        "de", "de-DE",
        "pt", "pt-BR",
        "ru", "ru-RU",
        "ar", "ar-SA",
    ]

    @staticmethod
    def _expand_languages(lang: str) -> list[str]:
        """展开语言码为变体列表，包含 Bilibili 弹幕等特殊类型。"""
        base = lang.split("-")[0]
        return TranscriptService._LANG_VARIANTS.get(base, [lang])

    def _download_and_parse_subtitles(self, url: str, preferred_language: str) -> list[TranscriptSegment]:
        """使用 yt-dlp 内建字幕下载，优先尝试首选语言，失败则回退到常见语言。"""
        # 首选语言
        segments = self._try_download_subs(url, self._expand_languages(preferred_language))
        if segments:
            return segments

        # 回退：如果首选语言不可用，尝试常见语言
        fallback = self._FALLBACK_LANGS
        # 避免重复已尝试的语言
        preferred_set = set(l.lower() for l in self._expand_languages(preferred_language))
        deduped_fallback = [l for l in fallback if l.lower() not in preferred_set]
        if deduped_fallback:
            segments = self._try_download_subs(url, deduped_fallback)
        return segments

    def _try_download_subs(self, url: str, languages: list[str]) -> list[TranscriptSegment]:
        """单次尝试：用指定语言列表下载字幕，写入临时文件再解析。"""
        tmpdir = tempfile.mkdtemp(prefix="fvd_subs_")
        try:
            yt_dlp = _yt_dlp()
            base_opts = _base_ytdlp_opts()
            base_opts.pop("skip_download", None)
            # 按优先级尝试不同格式：json3（YouTube原生）→ vtt → xml（Bilibili弹幕）→ srt
            for fmt in ("json3", "vtt", "xml", "srt"):
                opts = {
                    **base_opts,
                    "skip_download": True,
                    "writesubtitles": True,
                    "writeautomaticsub": True,
                    "subtitleslangs": languages,
                    "subtitlesformat": fmt,
                    "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
                    "noplaylist": True,
                    "quiet": True,
                    "no_warnings": True,
                }
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                except Exception:
                    continue
                for fname in os.listdir(tmpdir):
                    fpath = os.path.join(tmpdir, fname)
                    ext = os.path.splitext(fname)[1].lstrip(".").lower()
                    with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                    if content.strip():
                        segments = self._parse_track(content, ext)
                        if segments:
                            return segments
                # 清空临时目录，尝试下一个格式
                for fname in os.listdir(tmpdir):
                    os.unlink(os.path.join(tmpdir, fname))
            return []
        except Exception:
            return []
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _parse_track(self, content: str, ext: str) -> list[TranscriptSegment]:
        ext = ext.lower()
        if ext == "json3":
            return parse_json3(content)
        elif ext == "srt":
            return parse_srt(content)
        elif ext == "xml":
            return parse_xml_danmaku(content)
        else:
            return parse_vtt(content)

    def _video_info(self, url: str, info: dict[str, Any]) -> VideoInfo:
        return VideoInfo(
            url=url,
            title=info.get("title") or "未命名视频",
            extractor=info.get("extractor_key") or info.get("extractor"),
            duration=info.get("duration"),
            thumbnail=info.get("thumbnail"),
            webpage_url=info.get("webpage_url") or url,
            formats=[],
            subtitles=[],
        )


transcript_service = TranscriptService()
