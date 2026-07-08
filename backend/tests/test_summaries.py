from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import summaries
from app.schemas import AskSummaryResponse, MindMapNode, SummaryResult, TranscriptSegment, VideoInfo
from app.services.auth_service import activate_vip
from app.services.summary_store import summary_store
from app.services.transcript_service import parse_json3, parse_vtt


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    monkeypatch.setenv("FVD_DB_PATH", str(tmp_path / "app.sqlite3"))
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-auth-secret-with-at-least-32-bytes")
    yield


def _setup_api_key():
    os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-key")


def test_parse_vtt_segments():
    content = """WEBVTT

00:00:01.000 --> 00:00:03.500
<c>第一句字幕</c>

00:00:05.000 --> 00:00:06.000
第二句字幕
"""

    segments = parse_vtt(content)

    assert len(segments) == 2
    assert segments[0].start == 1
    assert segments[0].end == 3.5
    assert segments[0].text == "第一句字幕"


def test_parse_json3_segments():
    content = """
{
  "events": [
    {"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "hello"}, {"utf8": " world"}]}
  ]
}
"""

    segments = parse_json3(content)

    assert len(segments) == 1
    assert segments[0].start == 1
    assert segments[0].end == 3
    assert segments[0].text == "hello world"


def test_summary_job_success(monkeypatch):
    _setup_api_key()
    transcript = [TranscriptSegment(start=0, end=2, text="这是字幕")]
    video = VideoInfo(url="https://example.com/video", title="Demo", duration=120)
    result = SummaryResult(
        title="Demo",
        overview="概览",
        key_points=["要点"],
        transcript=transcript,
        mindmap=MindMapNode(name="Demo"),
        markdown="# Demo",
    )
    job = summary_store.create("https://example.com/video")

    monkeypatch.setattr(summaries.transcript_service, "extract", lambda url, lang: (video, transcript))
    monkeypatch.setattr(summaries.deepseek_service, "summarize", lambda **kwargs: result)

    summaries._run_summary_job(job.summary_id, job.url, "zh")

    status = summary_store.to_status(job)
    assert status.status == "success"
    assert status.progress == 100
    assert status.result is not None
    assert status.result.overview == "概览"


def test_ask_summary_endpoint(monkeypatch):
    _setup_api_key()
    with TestClient(app) as client:
        auth = client.post(
            "/api/auth/register",
            json={"email": "ask-summary@example.com", "password": "password123"},
        )
        user_id = auth.json()["user"]["id"]
        activate_vip(user_id)
        transcript = [TranscriptSegment(start=0, end=2, text="这是字幕")]
        job = summary_store.create("https://example.com/video", user_id=user_id)
        summary_store.update(
            job.summary_id,
            status="success",
            progress=100,
            result=SummaryResult(
                title="Demo",
                overview="概览",
                key_points=["要点"],
                transcript=transcript,
                mindmap=MindMapNode(name="Demo"),
                markdown="# Demo",
            ),
        )

        def fake_answer(**kwargs):
            return AskSummaryResponse(answer="回答", references=[{"start": 0, "text": "这是字幕"}])

        monkeypatch.setattr(summaries.deepseek_service, "answer", fake_answer)

        response = client.post(
            f"/api/summaries/{job.summary_id}/questions",
            json={"question": "讲了什么？"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "回答"
    assert payload["references"][0]["text"] == "这是字幕"


def test_create_summary_endpoint(monkeypatch):
    _setup_api_key()
    transcript = [TranscriptSegment(start=0, end=2, text="这是字幕")]
    video = VideoInfo(url="https://example.com/video", title="Demo", duration=120)

    monkeypatch.setattr(summaries.transcript_service, "extract", lambda url, lang: (video, transcript))
    monkeypatch.setattr(
        summaries.deepseek_service,
        "summarize",
        lambda **kwargs: SummaryResult(
            title="Demo", overview="概览", transcript=transcript,
            mindmap=MindMapNode(name="Demo"), markdown="# Demo",
        ),
    )

    with TestClient(app) as client:
        auth = client.post(
            "/api/auth/register",
            json={"email": "create-summary@example.com", "password": "password123"},
        )
        activate_vip(auth.json()["user"]["id"])
        response = client.post("/api/summaries", json={
            "url": "https://example.com/video",
            "language": "zh",
        })

    assert response.status_code == 200
    payload = response.json()
    assert "summary_id" in payload
    assert payload["status"] in ("queued", "running")


def test_create_summary_requires_vip():
    with TestClient(app) as client:
        response = client.post("/api/summaries", json={
            "url": "https://example.com/video",
            "language": "zh",
        })
        assert response.status_code == 401

        client.post(
            "/api/auth/register",
            json={"email": "free-summary@example.com", "password": "password123"},
        )
        response = client.post("/api/summaries", json={
            "url": "https://example.com/video",
            "language": "zh",
        })
        assert response.status_code == 403


def test_summary_without_api_key_returns_error(monkeypatch):
    from app.services.deepseek_service import DeepSeekService
    monkeypatch.setattr("app.services.deepseek_service.DEEPSEEK_API_KEY", "")
    svc = DeepSeekService()
    try:
        svc.summarize(title="Test", duration=60, transcript=[], language="zh")
        assert False, "should have raised"
    except Exception as exc:
        assert "DEEPSEEK_API_KEY" in str(exc)
