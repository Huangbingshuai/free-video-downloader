from __future__ import annotations

import hashlib
import os
import re
import time
from typing import Any
from urllib.parse import urljoin

import httpx
import requests

from app.schemas import VideoFormat, VideoInfo
from app.services.ytdlp_service import DEFAULT_FORMAT_SELECTOR

IQIYI_HOST_MARKERS = ("iqiyi.com", "pps.tv", "qy.net")
IQIYI_FORMAT_ID_PREFIX = "iqiyi-"

_VIDEO_CODE_RE = re.compile(r"[vwp]_(\S+)\.html")
_TVID_QUERY_RE = re.compile(r"[?&]tvid=(\d+)")
_MAGIC = 0x75706971676c
_API_KEY = "d5fb4bd9d50c4be6948c97edd7254b0e"
_API_SRC = "76f90cbd92f94a2e925d83e8ccd22cb7"
_CACHE_API = "http://cache.m.iqiyi.com/jp/tmts/{tvid}/{video_id}/"

_SSR_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

_QUALITY_LABELS: dict[str, str] = {
    "96": "流畅 240P",
    "1": "标清 360P",
    "2": "高清 480P",
    "21": "高清 504P",
    "4": "超清 720P",
    "17": "超清 720P",
    "5": "蓝光 1080P",
    "18": "蓝光 1080P",
}


def is_iqiyi_url(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in IQIYI_HOST_MARKERS)


def _decode_tvid(video_code: str) -> int:
    """Decode iQiyi video code from URL path (e.g. '2f1sx772wzo') to tvid."""
    a = list(reversed(bin(_MAGIC)[2:]))
    r = list(reversed(bin(int(video_code, 36))[2:]))
    o = []
    for i in range(max(len(r), len(a))):
        ri = int(r[i]) if i < len(r) else 0
        ai = int(a[i]) if i < len(a) else 0
        o.append(ri ^ ai)
    n = int("".join(map(str, reversed(o))), 2)
    if n < 900000:
        n = 100 * (n + 900000)
    return n


def _encode_tvid(tvid: int) -> str | None:
    """Encode tvid back to video code (reverse of _decode_tvid).

    The result can be used to construct iQiyi video page URLs
    (e.g. v_{code}.html) for metadata scraping.
    """
    n = tvid
    # Try direct encoding; also try reverse adjustment for the lossy < 900000 case
    candidates = [n]
    if n % 100 == 0:
        candidates.append(n // 100 - 900000)

    for candidate in candidates:
        if candidate < 0:
            continue
        a = list(reversed(bin(_MAGIC)[2:]))
        r = list(reversed(bin(candidate)[2:]))
        o = []
        for i in range(max(len(r), len(a))):
            ri = int(r[i]) if i < len(r) else 0
            ai = int(a[i]) if i < len(a) else 0
            o.append(ri ^ ai)
        result = int("".join(map(str, reversed(o))), 2)
        if result <= 0:
            continue
        chars = "0123456789abcdefghijklmnopqrstuvwxyz"
        code = ""
        temp = result
        while temp > 0:
            code = chars[temp % 36] + code
            temp //= 36
        if code:
            return code
    return None


def _extract_video_code(url: str) -> str | None:
    m = _VIDEO_CODE_RE.search(url)
    return m.group(1) if m else None


def _call_cache_api(tvid: int) -> dict[str, Any] | None:
    video_id = hashlib.md5(str(tvid).encode()).hexdigest()
    tm = int(time.time() * 1000)
    sc = hashlib.md5(f"{tm}{_API_KEY}{tvid}".encode()).hexdigest()
    params = {
        "tvid": tvid,
        "vid": video_id,
        "src": _API_SRC,
        "sc": sc,
        "t": tm,
    }
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.iqiyi.com/"}
    resp = requests.get(
        _CACHE_API.format(tvid=tvid, video_id=video_id),
        params=params,
        headers=headers,
        timeout=10,
    )
    raw = resp.text
    if raw.startswith("var tvInfoJs="):
        raw = raw[len("var tvInfoJs=") :]
    if not raw or raw.strip() == "":
        return None
    import json

    return json.loads(raw)  # type: ignore[no-any-return]


def _fetch_page_meta(url: str, tvid: int = 0, video_code: str = "") -> dict[str, str]:
    """Fetch title and thumbnail from SSR page using Googlebot UA."""
    result: dict[str, str] = {"title": "爱奇艺视频", "thumbnail": ""}
    if tvid:
        result["title"] = f"爱奇艺视频 {tvid}"

    urls_to_try = [url]
    if video_code:
        urls_to_try.append(f"https://www.iqiyi.com/v_{video_code}.html")
        urls_to_try.append(f"https://www.iqiyi.com/w_{video_code}.html")
    if tvid:
        urls_to_try.append(f"https://www.iqiyi.com/v_{tvid}.html")

    for page_url in urls_to_try:
        try:
            resp = httpx.get(page_url, headers=_SSR_HEADERS, timeout=10, follow_redirects=True)
            html = resp.text

            # Always capture thumbnail if found (may be refined by later URLs)
            m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
            if m:
                thumb = m.group(1)
                if thumb.startswith("//"):
                    thumb = "https:" + thumb
                result["thumbnail"] = thumb

            m = re.search(r"<title>([^<]+)</title>", html)
            if m:
                title = m.group(1).strip()
                # Filter out 404 error pages and generic site titles
                if "404错误" not in title and "404" not in title and "爱奇艺-在线视频网站" not in title:
                    result["title"] = title
                    # Got a real title + thumbnail, stop trying more URLs
                    break
        except Exception:
            continue

    return result


class IqiyiBuiltinParser:
    """Built-in iQiyi parser using direct API calls — no cookies needed.

    1. Decode tvid from URL path (XOR + base-36 algorithm)
    2. Compute video_id = md5(tvid)
    3. Call cache.m.iqiyi.com API with signature
    4. Parse vidl streams as VideoFormat list
    5. Fetch page title via SSR (Googlebot UA)
    """

    def extract(self, url: str) -> VideoInfo | None:
        if not is_iqiyi_url(url):
            return None

        tvid = self._resolve_tvid(url)
        if not tvid:
            return None

        # Get video_code from URL or encode from tvid (for constructing proper page URL)
        video_code = _extract_video_code(url) or _encode_tvid(tvid) or ""

        data = _call_cache_api(tvid)
        if not data or data.get("code") != "A00000":
            return None

        api_data = data.get("data", {})
        vidl = api_data.get("vidl", [])
        if not vidl:
            return None

        declared_duration = api_data.get("duration", 0)

        meta = _fetch_page_meta(url, tvid, video_code=video_code)
        formats = self._build_formats(vidl, declared_duration)

        return VideoInfo(
            url=url,
            title=meta["title"],
            extractor="IqiyiBuiltin",
            duration=declared_duration or None,
            thumbnail=meta.get("thumbnail") or None,
            webpage_url=url,
            formats=formats,
            subtitles=[],
        )

    @staticmethod
    def _resolve_tvid(url: str) -> int | None:
        """Extract tvid from various iQiyi URL formats."""
        # Format 1: /v_XXX.html or /w_XXX.html (encoded tvid)
        video_code = _extract_video_code(url)
        if video_code:
            try:
                return _decode_tvid(video_code)
            except Exception:
                pass

        # Format 2: ?tvid=<number> in query string
        m = _TVID_QUERY_RE.search(url)
        if m:
            return int(m.group(1))

        # Format 3: qy.net short link → follow redirect to get tvid
        if "qy.net" in url:
            try:
                resp = httpx.get(url, headers=_SSR_HEADERS, timeout=10, follow_redirects=True)
                final_url = str(resp.url)
                m = _TVID_QUERY_RE.search(final_url)
                if m:
                    return int(m.group(1))
                video_code = _extract_video_code(final_url)
                if video_code:
                    return _decode_tvid(video_code)
            except Exception:
                pass

        return None

    def _build_formats(self, vidl: list[dict], declared_duration: int = 0) -> list[VideoFormat]:
        trial_warning = ""
        if declared_duration > 0 and vidl:
            # Sample the first m3utx to detect trial restriction
            trial_duration = self._fetch_m3u8_duration(vidl[-1].get("m3utx", ""))
            if trial_duration and trial_duration < declared_duration * 0.5:
                trial_warning = f" [试看{trial_duration // 60}分钟，全片{declared_duration // 60}分钟]"

        formats: list[VideoFormat] = [
            VideoFormat(
                format_id=DEFAULT_FORMAT_SELECTOR,
                label=f"最佳质量（自动选择）{trial_warning}",
                ext="mp4",
                resolution="auto",
            )
        ]
        for stream in vidl:
            if "m3utx" not in stream:
                continue
            vd = str(stream.get("vd", ""))
            screen = stream.get("screenSize", "")
            label = _QUALITY_LABELS.get(vd, f"质量 {vd}")
            if screen:
                label = f"{label} ({screen})"
            if trial_warning:
                label += trial_warning
            formats.append(
                VideoFormat(
                    format_id=f"{IQIYI_FORMAT_ID_PREFIX}{vd}",
                    label=label,
                    ext="mp4",
                    resolution=stream.get("screenSize"),
                    direct_url=stream["m3utx"],
                )
            )
        return formats

    @staticmethod
    def _fetch_m3u8_duration(m3u8_url: str) -> int:
        """Fetch m3u8 playlist and sum EXTINF durations (seconds)."""
        try:
            r = requests.get(
                m3u8_url,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.iqiyi.com/"},
                timeout=10,
            )
            durations = re.findall(r"#EXTINF:([\d.]+)", r.text)
            return int(sum(float(d) for d in durations))
        except Exception:
            return 0


class IqiyiExternalResolver:
    """Optional adapter for a self-hosted iQiyi parser API."""

    def __init__(self) -> None:
        self.api_base = os.getenv("IQIYI_RESOLVER_API_BASE", "").strip()
        self.api_token = os.getenv("IQIYI_RESOLVER_API_TOKEN", "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.api_base)

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": "free-video-downloader/0.1"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def extract(self, url: str) -> VideoInfo | None:
        if not self.enabled or not is_iqiyi_url(url):
            return None
        endpoint = os.getenv("IQIYI_RESOLVER_API_PATH", "/api/parse")
        api_url = urljoin(self.api_base.rstrip("/") + "/", endpoint.lstrip("/"))
        resp = httpx.get(api_url, params={"url": url}, headers=self._headers(), timeout=20)
        resp.raise_for_status()
        data = resp.json()
        formats = [
            VideoFormat(
                format_id=DEFAULT_FORMAT_SELECTOR,
                label="最佳质量（自动选择）",
                ext="mp4",
                resolution="auto",
            )
        ]
        if data.get("video_url"):
            formats.insert(
                0,
                VideoFormat(
                    format_id=f"{IQIYI_FORMAT_ID_PREFIX}direct",
                    label="直链下载",
                    ext="mp4",
                    resolution="auto",
                    direct_url=data["video_url"],
                ),
            )
        return VideoInfo(
            url=url,
            title=data.get("title", "爱奇艺视频"),
            extractor="IqiyiExternal",
            thumbnail=data.get("thumbnail"),
            webpage_url=url,
            formats=formats,
            subtitles=[],
        )


builtin_parser = IqiyiBuiltinParser()
iqiyi_external_resolver = IqiyiExternalResolver()


def resolve(url: str) -> VideoInfo | None:
    """Try built-in parser first, fall back to external resolver if configured."""
    result = builtin_parser.extract(url)
    if result:
        return result
    return iqiyi_external_resolver.extract(url)
