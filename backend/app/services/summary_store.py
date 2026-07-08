from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4

from app.schemas import SummaryResult, SummaryStatus


@dataclass
class SummaryJob:
    summary_id: str
    url: str
    user_id: str | None = None
    status: str = "queued"
    progress: float = 0
    error: str | None = None
    result: SummaryResult | None = None
    _event_queue: asyncio.Queue[str] | None = field(default=None, repr=False)


class SummaryStore:
    def __init__(self) -> None:
        self._jobs: dict[str, SummaryJob] = {}
        self._lock = Lock()

    def create(self, url: str, user_id: str | None = None) -> SummaryJob:
        job = SummaryJob(summary_id=uuid4().hex, url=url, user_id=user_id)
        with self._lock:
            self._jobs[job.summary_id] = job
        return job

    def get(self, summary_id: str) -> SummaryJob | None:
        with self._lock:
            return self._jobs.get(summary_id)

    def update(self, summary_id: str, **changes: object) -> SummaryJob | None:
        with self._lock:
            job = self._jobs.get(summary_id)
            if job is None:
                return None
            for key, value in changes.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            return job

    def to_status(self, job: SummaryJob) -> SummaryStatus:
        return SummaryStatus(
            summary_id=job.summary_id,
            url=job.url,
            status=job.status,  # type: ignore[arg-type]
            progress=job.progress,
            error=job.error,
            result=job.result,
        )

    # ── streaming helpers ──────────────────────────────────────────────

    def ensure_queue(self, summary_id: str) -> asyncio.Queue[str]:
        """Get or create an asyncio.Queue for the job's SSE events."""
        with self._lock:
            job = self._jobs.get(summary_id)
            if job is None:
                raise KeyError(summary_id)
            if job._event_queue is None:
                job._event_queue = asyncio.Queue()
            return job._event_queue

    def send_event(self, summary_id: str, event: str) -> None:
        """Thread-safe: push an SSE event string into the job's queue."""
        # asyncio.Queue.put_nowait is thread-safe
        with self._lock:
            job = self._jobs.get(summary_id)
            if job is not None and job._event_queue is not None:
                try:
                    job._event_queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

    def close_queue(self, summary_id: str) -> None:
        """Signal the queue is done by putting a sentinel, then remove the queue ref."""
        self.send_event(summary_id, "__CLOSE__")

    async def event_stream(self, summary_id: str):
        """Async generator that yields SSE events from the job's queue."""
        queue = self.ensure_queue(summary_id)
        while True:
            event = await queue.get()
            if event == "__CLOSE__":
                break
            yield event


summary_store = SummaryStore()
