from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import os
from pathlib import Path
import re
import tempfile

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from app.schemas import (
    AnalyzeItem,
    AnalyzeRequest,
    AnalyzeResponse,
    CreateJobRequest,
    CreateJobResponse,
    JobStatus,
)
from app.services.job_store import job_store
from app.services.ytdlp_service import DEFAULT_FORMAT_SELECTOR, YtDlpUnavailable, ytdlp_service

router = APIRouter(prefix="/api", tags=["videos"])

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR = Path(os.getenv("FVD_DOWNLOAD_DIR", DEFAULT_DOWNLOAD_DIR))
FALLBACK_DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "free-video-downloader" / "downloads"
STREAM_THRESHOLD = 500 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024
EXTRACT_TIMEOUT_SECONDS = 25
extract_executor = ThreadPoolExecutor(max_workers=4)
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
LOGIN_ERROR_RE = re.compile(
    r"(cookie|cookies-from-browser|login|log in|sign in|authentication|authenticate|登录|验证码|verify)",
    re.IGNORECASE,
)


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _download_root() -> Path:
    if _is_writable_dir(DOWNLOAD_DIR):
        return DOWNLOAD_DIR.resolve()
    if _is_writable_dir(FALLBACK_DOWNLOAD_DIR):
        return FALLBACK_DOWNLOAD_DIR.resolve()
    raise RuntimeError(f"下载目录不可写：{DOWNLOAD_DIR}；备用目录也不可写：{FALLBACK_DOWNLOAD_DIR}")


def _allowed_download_roots() -> list[Path]:
    roots = [DOWNLOAD_DIR, FALLBACK_DOWNLOAD_DIR]
    return [root.resolve() for root in roots if root.exists()]


def _friendly_error(error: Exception | str) -> str:
    message = ANSI_ESCAPE_RE.sub("", str(error)).strip()
    if LOGIN_ERROR_RE.search(message):
        return "该内容需要登录态或验证。出于用户安全，本网站服务端不接收、不代管平台 Cookie；请改用公开视频链接。"
    return message


def _run_download_job(job_id: str, url: str, format_id: str) -> None:
    try:
        ytdlp_service.download(job_id, url, format_id, _download_root() / job_id, job_store)
    except Exception as exc:
        job_store.update(job_id, status="failed", error=_friendly_error(exc))


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest) -> AnalyzeResponse:
    results: list[AnalyzeItem] = []
    for raw_url in payload.urls:
        url = str(raw_url)
        try:
            future = extract_executor.submit(ytdlp_service.extract, url)
            video = future.result(timeout=EXTRACT_TIMEOUT_SECONDS)
            results.append(AnalyzeItem(url=url, ok=True, video=video))
        except TimeoutError:
            results.append(AnalyzeItem(url=url, ok=False, error="解析超时，请稍后重试或更换公开链接"))
        except YtDlpUnavailable as exc:
            results.append(AnalyzeItem(url=url, ok=False, error=str(exc)))
        except Exception as exc:
            results.append(AnalyzeItem(url=url, ok=False, error=f"解析失败：{_friendly_error(exc)}"))
    return AnalyzeResponse(results=results)


@router.post("/jobs", response_model=CreateJobResponse)
def create_job(payload: CreateJobRequest, background_tasks: BackgroundTasks) -> CreateJobResponse:
    job = job_store.create(str(payload.url), payload.format_id)
    background_tasks.add_task(_run_download_job, job.job_id, str(payload.url), payload.format_id)
    return CreateJobResponse(job_id=job.job_id, status=job.status)


@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str) -> JobStatus:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job_store.to_status(job)


@router.get("/direct")
def direct_download(
    url: str = Query(..., min_length=8),
    format_id: str = Query(DEFAULT_FORMAT_SELECTOR),
) -> RedirectResponse:
    try:
        direct_url = ytdlp_service.get_direct_url(url, format_id)
    except YtDlpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"直链解析失败，请改用服务端下载：{_friendly_error(exc)}") from exc
    if not direct_url:
        raise HTTPException(status_code=409, detail="直链不可用或已过期，请改用服务端下载")
    return RedirectResponse(direct_url, status_code=302)


def _iter_file(path: Path):
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            yield chunk


@router.get("/files/{job_id}/{file_id}")
def get_file(job_id: str, file_id: str):
    record = job_store.find_file(job_id, file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="文件不存在或任务已过期")
    allowed_roots = _allowed_download_roots()
    path = record.path.resolve()
    if not any(root == path or root in path.parents for root in allowed_roots):
        raise HTTPException(status_code=403, detail="非法文件路径")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件已被清理")
    if path.stat().st_size > STREAM_THRESHOLD:
        return StreamingResponse(
            _iter_file(path),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{record.filename}"'},
        )
    return FileResponse(path, filename=record.filename, media_type="application/octet-stream")
