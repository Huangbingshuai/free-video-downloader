from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
import shutil
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.schemas import SubtitleTrack, VideoFormat, VideoInfo
from app.services.job_store import JobStore

DEFAULT_FORMAT_SELECTOR = "bv*+ba/b"


class YtDlpUnavailable(RuntimeError):
    pass


def _yt_dlp() -> Any:
    try:
        import yt_dlp  # type: ignore
    except ModuleNotFoundError as exc:
        raise YtDlpUnavailable(
            "yt-dlp is not installed. Run `pip install -r backend/requirements.txt` first."
        ) from exc
    return yt_dlp


def _ffmpeg_location() -> str | None:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg  # type: ignore
    except ModuleNotFoundError:
        return None
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _format_label(item: dict[str, Any]) -> str:
    resolution = item.get("resolution") or item.get("format_note") or ""
    ext = item.get("ext") or "unknown"
    fps = f"{item.get('fps')}fps" if item.get("fps") else ""
    size = item.get("filesize") or item.get("filesize_approx")
    size_label = f"{round(size / 1024 / 1024, 1)}MB" if size else ""
    parts = [part for part in [resolution, ext, fps, size_label] if part]
    return " / ".join(parts) or item.get("format_id", "best")


def _collect_formats(info: dict[str, Any]) -> list[VideoFormat]:
    formats: list[VideoFormat] = [
        VideoFormat(
            format_id=DEFAULT_FORMAT_SELECTOR,
            label="最佳质量（自动选择，可合并音视频）",
            ext=info.get("ext"),
            resolution="auto",
        )
    ]
    seen = {DEFAULT_FORMAT_SELECTOR}
    for item in info.get("formats") or []:
        format_id = str(item.get("format_id") or "")
        if not format_id or format_id in seen:
            continue
        seen.add(format_id)
        formats.append(
            VideoFormat(
                format_id=format_id,
                label=_format_label(item),
                ext=item.get("ext"),
                resolution=item.get("resolution") or item.get("format_note"),
                filesize=item.get("filesize"),
                filesize_approx=item.get("filesize_approx"),
                vcodec=item.get("vcodec"),
                acodec=item.get("acodec"),
                direct_url=item.get("url"),
            )
        )
    return formats[:25]


def _collect_subtitles(info: dict[str, Any]) -> list[SubtitleTrack]:
    tracks: list[SubtitleTrack] = []
    subtitles = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    for lang, entries in {**automatic, **subtitles}.items():
        formats = sorted({entry.get("ext", "unknown") for entry in entries if isinstance(entry, dict)})
        tracks.append(SubtitleTrack(lang=str(lang), formats=formats))
    return tracks[:20]


class YtDlpService:
    def extract(self, url: str) -> VideoInfo:
        from app.services.douyin_resolver import is_douyin_url, resolve as resolve_douyin
        from app.services.iqiyi_resolver import is_iqiyi_url, resolve as resolve_iqiyi

        builtin_info = resolve_douyin(url)
        if builtin_info:
            return builtin_info

        if is_douyin_url(url):
            raise RuntimeError("该抖音视频无法公开访问，可能是私密作品、已删除或触发了平台验证")

        builtin_info = resolve_iqiyi(url)
        if builtin_info:
            return builtin_info

        if is_iqiyi_url(url):
            raise RuntimeError("该爱奇艺视频无法解析，可能是VIP内容、已下架或区域限制")

        yt_dlp = _yt_dlp()
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": 15,
            "retries": 1,
            "fragment_retries": 1,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            raw = ydl.extract_info(url, download=False)
            info = ydl.sanitize_info(raw)
        return VideoInfo(
            url=url,
            title=info.get("title") or "未命名视频",
            extractor=info.get("extractor_key") or info.get("extractor"),
            duration=info.get("duration"),
            thumbnail=info.get("thumbnail"),
            webpage_url=info.get("webpage_url") or url,
            formats=_collect_formats(info),
            subtitles=_collect_subtitles(info),
        )

    def get_direct_url(self, url: str, format_id: str = DEFAULT_FORMAT_SELECTOR) -> str | None:
        format_id = self.normalize_format_id(format_id)
        info = self.extract(url)
        external_candidate = next(
            (item.direct_url for item in info.formats if item.format_id == format_id and item.direct_url),
            None,
        )
        if external_candidate:
            return external_candidate
        if format_id == DEFAULT_FORMAT_SELECTOR:
            return None
        if format_id == "b":
            candidate = next((item.direct_url for item in info.formats if item.direct_url), None)
        else:
            candidate = next((item.direct_url for item in info.formats if item.format_id == format_id), None)
        if candidate and self.probe_direct_url(candidate):
            return candidate
        return None

    def probe_direct_url(self, url: str) -> bool:
        try:
            req = Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=8) as response:
                return 200 <= response.status < 400
        except Exception:
            try:
                req = Request(
                    url,
                    method="GET",
                    headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-1"},
                )
                with urlopen(req, timeout=8) as response:
                    return response.status in {200, 206}
            except (URLError, TimeoutError, ValueError, OSError):
                return False

    def normalize_format_id(self, format_id: str | None) -> str:
        if not format_id or format_id == "best":
            return DEFAULT_FORMAT_SELECTOR
        return format_id

    def download(self, job_id: str, url: str, format_id: str, output_dir: Path, store: JobStore) -> None:
        from app.services.iqiyi_resolver import is_iqiyi_url

        output_dir.mkdir(parents=True, exist_ok=True)
        resolved_format_id = self.normalize_format_id(format_id)

        # iQiyi: use built-in parser + ffmpeg for m3u8 streams
        if is_iqiyi_url(url):
            self._download_iqiyi(job_id, url, resolved_format_id, output_dir, store)
            return

        external_url = self.get_direct_url(url, resolved_format_id)
        if external_url:
            self._download_direct_url(job_id, external_url, output_dir, store)
            return
        yt_dlp = _yt_dlp()

        def progress_hook(data: dict[str, Any]) -> None:
            status = data.get("status")
            downloaded = data.get("downloaded_bytes")
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            progress = 0.0
            if total and downloaded:
                progress = min(100.0, round(downloaded / total * 100, 2))
            if status == "downloading":
                store.update(
                    job_id,
                    status="running",
                    progress=progress,
                    speed=data.get("speed"),
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                )
            elif status == "finished":
                store.update(job_id, progress=100.0, downloaded_bytes=downloaded, total_bytes=total)

        opts = {
            "format": resolved_format_id,
            "outtmpl": str(output_dir / "%(title).180B-%(id)s.%(ext)s"),
            "noplaylist": True,
            "restrictfilenames": True,
            "progress_hooks": [progress_hook],
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 15,
            "retries": 1,
            "fragment_retries": 1,
        }
        ffmpeg_location = _ffmpeg_location()
        if ffmpeg_location:
            opts["ffmpeg_location"] = ffmpeg_location
        store.update(job_id, status="running")
        before = {path.resolve() for path in output_dir.glob("*") if path.is_file()}
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        after = {path.resolve() for path in output_dir.glob("*") if path.is_file()}
        new_files = sorted(after - before, key=lambda item: item.stat().st_mtime)
        if not new_files:
            new_files = sorted(after, key=lambda item: item.stat().st_mtime)
        for path in new_files:
            store.add_file(job_id, path)
        store.update(job_id, status="success", progress=100.0)

    def _download_iqiyi(self, job_id: str, url: str, format_id: str, output_dir: Path, store: JobStore) -> None:
        from app.services.iqiyi_resolver import builtin_parser

        info = builtin_parser.extract(url)
        if not info:
            raise RuntimeError("无法解析该爱奇艺视频，可能是VIP内容或已下架")

        # Find the matching format or pick the best available
        m3u8_url: str | None = None
        if format_id and format_id != DEFAULT_FORMAT_SELECTOR:
            m3u8_url = next((f.direct_url for f in info.formats if f.format_id == format_id and f.direct_url), None)
        if not m3u8_url:
            # Pick highest quality (formats[1:] skips the default "auto" format, last is highest)
            for f in reversed(info.formats[1:]):
                if f.direct_url:
                    m3u8_url = f.direct_url
                    break
        if not m3u8_url:
            raise RuntimeError("该爱奇艺视频无可下载的流")

        self._download_m3u8(job_id, m3u8_url, output_dir, store)

    def _download_m3u8(self, job_id: str, m3u8_url: str, output_dir: Path, store: JobStore) -> None:
        ffmpeg = _ffmpeg_location()
        if not ffmpeg:
            raise RuntimeError("下载m3u8流需要ffmpeg，请安装ffmpeg后重试")

        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"{job_id}.mp4"

        store.update(job_id, status="running")

        cmd = [
            ffmpeg, "-y", "-nostdin",
            "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "-headers", "Referer: https://www.iqiyi.com/",
            "-i", m3u8_url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            str(target),
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            errors="replace",
        )

        duration_s: float | None = None
        _time_re = re.compile(r"time=(\d+):(\d+):(\d+)\.(\d+)")

        for line in proc.stderr or []:
            if duration_s is None:
                dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", line)
                if dur_match:
                    duration_s = (
                        int(dur_match.group(1)) * 3600
                        + int(dur_match.group(2)) * 60
                        + int(dur_match.group(3))
                        + int(dur_match.group(4)) / 100
                    )
            time_match = _time_re.search(line)
            if time_match and duration_s:
                current = (
                    int(time_match.group(1)) * 3600
                    + int(time_match.group(2)) * 60
                    + int(time_match.group(3))
                    + int(time_match.group(4)) / 100
                )
                progress = min(99, round(current / duration_s * 100, 2))
                downloaded = target.stat().st_size if target.is_file() else 0
                store.update(
                    job_id,
                    status="running",
                    progress=progress,
                    downloaded_bytes=downloaded,
                )

        proc.wait()

        if proc.returncode != 0:
            raise RuntimeError("ffmpeg 下载失败，请稍后重试")

        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError("下载完成但文件为空，可能是平台限制了该资源")

        store.add_file(job_id, target)
        store.update(job_id, status="success", progress=100.0)

    def _download_direct_url(self, job_id: str, url: str, output_dir: Path, store: JobStore) -> None:
        store.update(job_id, status="running")
        target = output_dir / f"{job_id}.mp4"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.douyin.com/"})
        with urlopen(req, timeout=30) as response, target.open("wb") as handle:
            total_header = response.headers.get("Content-Length")
            total = int(total_header) if total_header and total_header.isdigit() else None
            downloaded = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                progress = round(downloaded / total * 100, 2) if total else 0.0
                store.update(
                    job_id,
                    status="running",
                    progress=progress,
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                )
        store.add_file(job_id, target)
        store.update(job_id, status="success", progress=100.0)


ytdlp_service = YtDlpService()
