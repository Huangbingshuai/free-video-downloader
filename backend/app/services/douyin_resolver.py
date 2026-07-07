from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import urljoin

import httpx

from app.schemas import VideoFormat, VideoInfo
from app.services.ytdlp_service import DEFAULT_FORMAT_SELECTOR

DOUYIN_HOST_MARKERS = ("douyin.com", "iesdouyin.com")
EXTERNAL_FORMAT_ID = "external-direct"


class DouyinUnavailableError(Exception):
    """Raised when a Douyin video is unavailable for a known reason (private, deleted, etc.)."""

    def __init__(self, notice: str, detail_msg: str = ""):
        self.notice = notice
        self.detail_msg = detail_msg
        super().__init__(detail_msg or notice or "该视频暂时无法查看，可能是私密作品或已被删除")


MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)

_ROUTER_DATA_RE = re.compile(r"window\._ROUTER_DATA\s*=\s*(\{[\s\S]*?\});?\s*</script>")
_AWEME_ID_RE = re.compile(r"/video/(\d+)|/share/video/(\d+)")
_MODAL_ID_RE = re.compile(r"[?&]modal_id=(\d+)")
_PLAYW_URL_RE = re.compile(r"/playwm?/")


def is_douyin_url(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in DOUYIN_HOST_MARKERS)


def _extract_aweme_id(url: str) -> str | None:
    m = _AWEME_ID_RE.search(url)
    if m:
        return m.group(1) or m.group(2)
    m = _MODAL_ID_RE.search(url)
    return m.group(1) if m else None


def _resolve_short_url(url: str, client: httpx.Client) -> str:
    """Follow v.douyin.com redirect to get the final URL containing the video ID."""
    response = client.head(url, follow_redirects=False, timeout=10)
    location = response.headers.get("location", "")
    if location:
        return location
    # Try GET fallback
    response = client.get(url, follow_redirects=True, timeout=15)
    return str(response.url)


def _remove_watermark(url: str) -> str:
    return _PLAYW_URL_RE.sub("/play/", url)


def _pick_url(container: Any) -> str | None:
    if not isinstance(container, dict):
        return None
    url_list = container.get("url_list") or container.get("urlList") or []
    for item in url_list:
        if isinstance(item, str) and item.startswith("http"):
            return item
    uri = container.get("uri")
    if isinstance(uri, str) and uri.startswith("http"):
        return uri
    return None


def _find_aweme_detail(data: Any) -> dict | None:
    if not isinstance(data, (dict, list)):
        return None
    stack: list[Any] = [data]
    seen = set()
    while stack:
        cur = stack.pop()
        if isinstance(cur, list):
            stack.extend(cur)
            continue
        if not isinstance(cur, dict):
            continue
        obj_id = id(cur)
        if obj_id in seen:
            continue
        seen.add(obj_id)
        has_id = "aweme_id" in cur or "awemeId" in cur
        has_media = "video" in cur or "images" in cur
        if has_id and has_media:
            return cur
        if "aweme_detail" in cur and isinstance(cur["aweme_detail"], dict):
            return cur["aweme_detail"]
        for v in cur.values():
            if isinstance(v, (dict, list)):
                stack.append(v)
    return None


def _normalize(raw: dict) -> dict[str, Any] | None:
    """Normalize raw aweme_detail into a flat dict we can build VideoInfo from."""
    aweme_id = raw.get("aweme_id") or raw.get("awemeId", "")
    desc = raw.get("desc", "")

    author = raw.get("author") or {}
    nickname = author.get("nickname", "")
    avatar = _pick_url(author.get("avatar_thumb") or author.get("avatarThumb"))

    video = raw.get("video")
    if video and isinstance(video, dict):
        play_addr = _pick_url(video.get("play_addr") or video.get("playAddr"))
        cover = _pick_url(video.get("cover") or video.get("origin_cover"))
        duration = video.get("duration")
        # Douyin API returns duration in milliseconds; normalize to seconds
        if isinstance(duration, (int, float)) and duration > 1000:
            duration = int(duration / 1000)
        if play_addr:
            return {
                "aweme_id": aweme_id,
                "title": desc or "抖音公开视频",
                "thumbnail": cover or avatar,
                "duration": duration,
                "author": nickname,
                "video_url": _remove_watermark(play_addr),
            }

    images = raw.get("images")
    if images and isinstance(images, list):
        img_urls = []
        for img in images:
            if isinstance(img, dict):
                u = _pick_url(img)
                if u:
                    img_urls.append(u)
        if img_urls:
            return {
                "aweme_id": aweme_id,
                "title": desc or "抖音公开图集",
                "thumbnail": img_urls[0] or avatar,
                "author": nickname,
                "image_urls": img_urls,
            }

    return None


class DouyinBuiltinParser:
    """Built-in Douyin parser using public share page HTML — no cookies needed.

    Approach adapted from open-source projects (dy-parser-web, douyin-tool):
    1. Resolve v.douyin.com short link → get aweme_id
    2. Fetch https://www.iesdouyin.com/share/video/{aweme_id}/ with mobile UA
    3. Parse window._ROUTER_DATA JSON from the HTML
    4. Extract video play_addr and rewrite playwm → play (watermark removal)
    """

    def extract(self, url: str) -> VideoInfo | None:
        if not is_douyin_url(url):
            return None

        with httpx.Client(timeout=httpx.Timeout(15)) as client:
            aweme_id = _extract_aweme_id(url)
            if not aweme_id:
                try:
                    resolved = _resolve_short_url(url, client)
                    aweme_id = _extract_aweme_id(resolved) if resolved else None
                except Exception:
                    pass
            if not aweme_id:
                return None

            try:
                share_url = f"https://www.iesdouyin.com/share/video/{aweme_id}/"
                headers = {
                    "User-Agent": MOBILE_UA,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                }
                response = client.get(share_url, headers=headers)
                response.raise_for_status()
            except DouyinUnavailableError:
                raise
            except Exception:
                return None

            data = self._parse_html(response.text)
            if not data:
                return None

        return self._build_video_info(url, data)

    def _parse_html(self, html: str) -> dict[str, Any] | None:
        m = _ROUTER_DATA_RE.search(html)
        if not m:
            return None
        try:
            router_data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None

        # Check for filter errors (private, deleted, etc.) before returning None
        filter_error = self._extract_filter_error(router_data)
        if filter_error:
            raise DouyinUnavailableError(*filter_error)

        raw = _find_aweme_detail(router_data)
        if not raw:
            return None
        return _normalize(raw)

    @staticmethod
    def _extract_filter_error(router_data: dict) -> tuple[str, str] | None:
        """Walk router_data looking for filter_list entries with a rejection reason."""
        stack: list[Any] = [router_data]
        seen = set()
        while stack:
            cur = stack.pop()
            if isinstance(cur, list):
                stack.extend(cur)
                continue
            if not isinstance(cur, dict):
                continue
            obj_id = id(cur)
            if obj_id in seen:
                continue
            seen.add(obj_id)
            filter_list = cur.get("filter_list")
            if isinstance(filter_list, list):
                for entry in filter_list:
                    if isinstance(entry, dict) and entry.get("filter_reason"):
                        return (entry.get("notice", ""), entry.get("detail_msg", ""))
            for v in cur.values():
                if isinstance(v, (dict, list)):
                    stack.append(v)
        return None

    def _build_video_info(self, url: str, data: dict[str, Any]) -> VideoInfo:
        formats: list[VideoFormat] = [
            VideoFormat(
                format_id=DEFAULT_FORMAT_SELECTOR,
                label="最佳质量（自动选择）",
                ext="mp4",
                resolution="auto",
            )
        ]
        video_url = data.get("video_url")
        if video_url:
            formats.insert(
                0,
                VideoFormat(
                    format_id=EXTERNAL_FORMAT_ID,
                    label="抖音直链（无水印）",
                    ext="mp4",
                    resolution="auto",
                    direct_url=video_url,
                ),
            )

        return VideoInfo(
            url=url,
            title=data.get("title", "抖音公开视频"),
            extractor="DouyinBuiltin",
            duration=data.get("duration"),
            thumbnail=data.get("thumbnail"),
            webpage_url=url,
            formats=formats,
            subtitles=[],
        )


class DouyinExternalResolver:
    """Optional adapter for a self-hosted/public-link Douyin parser API."""

    def __init__(self) -> None:
        self.api_base = os.getenv("DOUYIN_RESOLVER_API_BASE", "").strip()
        self.api_token = os.getenv("DOUYIN_RESOLVER_API_TOKEN", "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.api_base)

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": "free-video-downloader/0.1"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def _video_data_endpoint(self) -> str:
        endpoint = os.getenv("DOUYIN_RESOLVER_VIDEO_DATA_PATH", "/api/hybrid/video_data")
        return urljoin(self.api_base.rstrip("/") + "/", endpoint.lstrip("/"))

    def extract(self, url: str) -> VideoInfo | None:
        if not self.enabled or not is_douyin_url(url):
            return None
        response = httpx.get(
            self._video_data_endpoint(),
            params={"url": url, "minimal": "false"},
            headers=self._headers(),
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        video_url = _find_video_url(data)
        title = _find_first_string(data, ("title", "desc", "description", "text")) or "抖音公开视频"
        thumbnail = _find_thumbnail(data)
        formats = [
            VideoFormat(
                format_id=DEFAULT_FORMAT_SELECTOR,
                label="最佳质量（自动选择）",
                ext="mp4",
                resolution="auto",
            )
        ]
        if video_url:
            formats.insert(
                0,
                VideoFormat(
                    format_id=EXTERNAL_FORMAT_ID,
                    label="抖音直链（外部解析）",
                    ext="mp4",
                    resolution="auto",
                    direct_url=video_url,
                ),
            )
        return VideoInfo(
            url=url,
            title=title,
            extractor="DouyinExternal",
            thumbnail=thumbnail,
            webpage_url=url,
            formats=formats,
            subtitles=[],
        )


# ---- helpers for DouyinExternalResolver ----

def _walk_values(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


def _find_first_string(data: Any, keys: tuple[str, ...]) -> str | None:
    key_set = {k.lower() for k in keys}
    for value in _walk_values(data):
        if not isinstance(value, dict):
            continue
        for k, item in value.items():
            if k.lower() in key_set and isinstance(item, str) and item:
                return item
    return None


def _find_video_url(data: Any) -> str | None:
    direct = _find_first_string(
        data,
        (
            "video_url", "play_url", "play_addr", "download_url",
            "wmplay_url", "nwm_video_url", "nwm_video_url_h265",
        ),
    )
    if direct and direct.startswith("http"):
        return direct
    for value in _walk_values(data):
        if isinstance(value, str) and value.startswith("http") and any(
            token in value for token in (".mp4", "video")
        ):
            return value
    return None


def _find_thumbnail(data: Any) -> str | None:
    direct = _find_first_string(data, ("cover", "cover_url", "thumbnail", "dynamic_cover", "origin_cover"))
    if direct and direct.startswith("http"):
        return direct
    return None


# ---- unified resolver ----

builtin_parser = DouyinBuiltinParser()
douyin_external_resolver = DouyinExternalResolver()


def resolve(url: str) -> VideoInfo | None:
    """Try built-in parser first, fall back to external resolver if configured.

    Raises DouyinUnavailableError when the video is unavailable for a known reason
    (private, deleted, etc.). Returns None only for network errors or unsupported URLs.
    """
    try:
        result = builtin_parser.extract(url)
        if result:
            return result
    except DouyinUnavailableError:
        raise
    return douyin_external_resolver.extract(url)
