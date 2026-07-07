from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import videos
from app.schemas import VideoFormat, VideoInfo
from app.services.job_store import job_store
from app.services.ytdlp_service import DEFAULT_FORMAT_SELECTOR, ytdlp_service


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_analyze_with_mocked_ytdlp(monkeypatch, client):
    def fake_extract(url: str) -> VideoInfo:
        return VideoInfo(
            url=url,
            title="Demo",
            extractor="Test",
            formats=[VideoFormat(format_id="best", label="Best")],
        )

    monkeypatch.setattr(videos.ytdlp_service, "extract", fake_extract)
    response = client.post("/api/analyze", json={"urls": ["https://example.com/watch?v=1"]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["results"][0]["ok"] is True
    assert payload["results"][0]["video"]["title"] == "Demo"


def test_job_status_lifecycle(client):
    job = job_store.create("https://example.com/video", "best")
    job_store.update(job.job_id, status="running", progress=42)
    response = client.get(f"/api/jobs/{job.job_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "running"
    assert payload["progress"] == 42


def test_file_download_rejects_unknown_file(client):
    response = client.get("/api/files/missing/file")
    assert response.status_code == 404


def test_large_file_uses_streaming_response(monkeypatch, client):
    with TemporaryDirectory() as temp_dir:
        download_dir = Path(temp_dir)
        monkeypatch.setattr(videos, "DOWNLOAD_DIR", download_dir)
        monkeypatch.setattr(videos, "STREAM_THRESHOLD", 4)
        job = job_store.create("https://example.com/video", "best")
        job_dir = download_dir / job.job_id
        job_dir.mkdir()
        target = job_dir / "demo.mp4"
        target.write_bytes(b"123456789")
        record = job_store.add_file(job.job_id, target)
        assert record is not None

        response = client.get(f"/api/files/{job.job_id}/{record.id}")
        assert response.status_code == 200
        assert response.content == b"123456789"


def test_download_job_falls_back_when_primary_dir_is_not_writable(monkeypatch):
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        blocked = root / "downloads-as-file"
        blocked.write_text("not a directory", encoding="utf-8")
        fallback = root / "fallback"
        job = job_store.create("https://example.com/video", "best")

        def fake_download(job_id: str, url: str, format_id: str, output_dir: Path, store):
            assert job_id == job.job_id
            assert fallback.resolve() in output_dir.resolve().parents
            output_dir.mkdir(parents=True, exist_ok=True)
            target = output_dir / "demo.mp4"
            target.write_bytes(b"ok")
            store.add_file(job_id, target)
            store.update(job_id, status="success", progress=100)

        monkeypatch.setattr(videos, "DOWNLOAD_DIR", blocked)
        monkeypatch.setattr(videos, "FALLBACK_DOWNLOAD_DIR", fallback)
        monkeypatch.setattr(videos.ytdlp_service, "download", fake_download)

        videos._run_download_job(job.job_id, job.url, job.format_id)

        status = job_store.to_status(job)
        assert status.status == "success"
        assert status.files[0].filename == "demo.mp4"


def test_legacy_best_format_maps_to_merge_fallback_selector():
    assert ytdlp_service.normalize_format_id("best") == DEFAULT_FORMAT_SELECTOR
    assert ytdlp_service.normalize_format_id("") == DEFAULT_FORMAT_SELECTOR
    assert ytdlp_service.normalize_format_id("80") == "80"


def test_download_job_strips_ansi_error_codes(monkeypatch):
    job = job_store.create("https://example.com/video", "best")

    def fake_download(*args):
        raise RuntimeError("\x1b[0;31mERROR:\x1b[0m format failed")

    monkeypatch.setattr(videos, "_download_root", lambda: Path("."))
    monkeypatch.setattr(videos.ytdlp_service, "download", fake_download)

    videos._run_download_job(job.job_id, job.url, job.format_id)

    status = job_store.to_status(job)
    assert status.status == "failed"
    assert status.error == "ERROR: format failed"


def test_download_job_rewrites_cookie_login_errors(monkeypatch):
    job = job_store.create("https://v.douyin.com/example/", "best")

    def fake_download(*args):
        raise RuntimeError("Use --cookies-from-browser or login for authentication")

    monkeypatch.setattr(videos, "_download_root", lambda: Path("."))
    monkeypatch.setattr(videos.ytdlp_service, "download", fake_download)

    videos._run_download_job(job.job_id, job.url, job.format_id)

    status = job_store.to_status(job)
    assert status.status == "failed"
    assert "不接收、不代管平台 Cookie" in status.error
