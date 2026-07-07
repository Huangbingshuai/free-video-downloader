from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class AnalyzeRequest(BaseModel):
    urls: list[HttpUrl] = Field(..., min_length=1, max_length=20)


class VideoFormat(BaseModel):
    format_id: str
    label: str
    ext: str | None = None
    resolution: str | None = None
    filesize: int | None = None
    filesize_approx: int | None = None
    vcodec: str | None = None
    acodec: str | None = None
    direct_url: str | None = None


class SubtitleTrack(BaseModel):
    lang: str
    formats: list[str] = Field(default_factory=list)


class VideoInfo(BaseModel):
    url: str
    title: str
    extractor: str | None = None
    duration: float | None = None
    thumbnail: str | None = None
    webpage_url: str | None = None
    formats: list[VideoFormat] = Field(default_factory=list)
    subtitles: list[SubtitleTrack] = Field(default_factory=list)


class AnalyzeItem(BaseModel):
    url: str
    ok: bool
    video: VideoInfo | None = None
    error: str | None = None


class AnalyzeResponse(BaseModel):
    results: list[AnalyzeItem]


class DownloadMode(str, Enum):
    auto = "auto"
    direct = "direct"
    proxy = "proxy"


class CreateJobRequest(BaseModel):
    url: HttpUrl
    format_id: str = "bv*+ba/b"
    download_mode: DownloadMode = DownloadMode.proxy


class CreateJobResponse(BaseModel):
    job_id: str
    status: str


class FileRecord(BaseModel):
    id: str
    filename: str
    size: int
    download_url: str


class JobStatus(BaseModel):
    job_id: str
    url: str
    format_id: str
    status: Literal["queued", "running", "success", "failed"]
    progress: float = 0
    speed: float | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    error: str | None = None
    files: list[FileRecord] = Field(default_factory=list)
