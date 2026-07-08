from __future__ import annotations

import re

from app.schemas import VideoInfo

XHS_HOST_MARKERS = ("xiaohongshu.com", "xhslink.com")
_NOTE_ID_RE = re.compile(r"(?:discovery/item|explore|a)/([0-9a-fA-F]{24})")


def is_xiaohongshu_url(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in XHS_HOST_MARKERS)


def _extract_note_id(url: str) -> str | None:
    m = _NOTE_ID_RE.search(url)
    return m.group(1) if m else None


def resolve(url: str) -> VideoInfo | None:
    """XHS note data is loaded asynchronously and not embedded in page HTML.
    Falls through to yt-dlp for metadata extraction."""
    return None
