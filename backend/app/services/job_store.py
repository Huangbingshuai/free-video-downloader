from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from uuid import uuid4

from app.schemas import FileRecord, JobStatus


@dataclass
class StoredFile:
    id: str
    path: Path
    filename: str
    size: int


@dataclass
class Job:
    job_id: str
    url: str
    format_id: str
    status: str = "queued"
    progress: float = 0
    speed: float | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    error: str | None = None
    files: list[StoredFile] = field(default_factory=list)


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = Lock()

    def create(self, url: str, format_id: str) -> Job:
        job = Job(job_id=uuid4().hex, url=url, format_id=format_id)
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes: object) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for key, value in changes.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            return job

    def add_file(self, job_id: str, path: Path) -> StoredFile | None:
        resolved = path.resolve()
        if not resolved.is_file():
            return None
        record = StoredFile(
            id=uuid4().hex,
            path=resolved,
            filename=resolved.name,
            size=resolved.stat().st_size,
        )
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.files.append(record)
        return record

    def find_file(self, job_id: str, file_id: str) -> StoredFile | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return next((item for item in job.files if item.id == file_id), None)

    def to_status(self, job: Job) -> JobStatus:
        return JobStatus(
            job_id=job.job_id,
            url=job.url,
            format_id=job.format_id,
            status=job.status,  # type: ignore[arg-type]
            progress=job.progress,
            speed=job.speed,
            downloaded_bytes=job.downloaded_bytes,
            total_bytes=job.total_bytes,
            error=job.error,
            files=[
                FileRecord(
                    id=item.id,
                    filename=item.filename,
                    size=item.size,
                    download_url=f"/api/files/{job.job_id}/{item.id}",
                )
                for item in job.files
            ],
        )


job_store = JobStore()
