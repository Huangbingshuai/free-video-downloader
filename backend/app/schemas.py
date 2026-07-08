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


class TranscriptSegment(BaseModel):
    start: float
    end: float | None = None
    text: str


class SummaryChapter(BaseModel):
    start: float | None = None
    title: str
    summary: str


class SummaryTerm(BaseModel):
    name: str
    explanation: str


class MindMapNode(BaseModel):
    name: str
    children: list["MindMapNode"] = Field(default_factory=list)


class SummaryResult(BaseModel):
    title: str
    overview: str
    chapters: list[SummaryChapter] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    terms: list[SummaryTerm] = Field(default_factory=list)
    transcript: list[TranscriptSegment] = Field(default_factory=list)
    mindmap: MindMapNode | None = None
    mermaid: str = ""
    mindmap_markdown: str = ""
    markdown: str = ""


class CreateSummaryRequest(BaseModel):
    url: HttpUrl
    language: str = Field(default="zh", max_length=20)


class CreateSummaryResponse(BaseModel):
    summary_id: str
    status: str


class SummaryStatus(BaseModel):
    summary_id: str
    url: str
    status: Literal["queued", "running", "success", "failed"]
    progress: float = 0
    error: str | None = None
    result: SummaryResult | None = None


class AskSummaryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)


class AnswerReference(BaseModel):
    start: float | None = None
    text: str


class AskSummaryResponse(BaseModel):
    answer: str
    references: list[AnswerReference] = Field(default_factory=list)


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)


class AuthUser(BaseModel):
    id: str
    email: str
    is_vip: bool = False
    vip_activated_at: str | None = None


class AuthResponse(BaseModel):
    user: AuthUser | None = None


class MembershipStatus(BaseModel):
    is_authenticated: bool
    is_vip: bool
    vip_activated_at: str | None = None
    user: AuthUser | None = None


class CheckoutSessionResponse(BaseModel):
    status: str
    checkout_url: str | None = None
    session_id: str | None = None
    is_vip: bool = False


class ConfirmCheckoutSessionRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=255)
