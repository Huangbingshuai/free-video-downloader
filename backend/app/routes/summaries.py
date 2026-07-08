from __future__ import annotations

import asyncio
import json
import re

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.schemas import (
    AskSummaryRequest,
    AskSummaryResponse,
    CreateSummaryRequest,
    CreateSummaryResponse,
    SummaryStatus,
)
from app.services.deepseek_service import DeepSeekUnavailable, deepseek_service
from app.services.summary_store import summary_store
from app.services.transcript_service import TranscriptUnavailable, transcript_service

router = APIRouter(prefix="/api", tags=["summaries"])

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def _friendly_ai_error(error: Exception | str) -> str:
    message = ANSI_ESCAPE_RE.sub("", str(error)).strip()
    lower = message.lower()
    if "401" in message or "unauthorized" in lower or "invalid api key" in lower:
        return "服务端 DeepSeek API Key 无效，请联系管理员配置。"
    if "429" in message or "rate limit" in lower:
        return "DeepSeek 调用频率或额度受限，请稍后重试。"
    if "timeout" in lower or "timed out" in lower:
        return "DeepSeek 请求超时，请稍后重试。"
    return message or "AI 分析失败，请稍后重试。"


def _run_summary_job(summary_id: str, url: str, language: str) -> None:
    try:
        summary_store.update(summary_id, status="running", progress=15)
        summary_store.send_event(summary_id, f"data: {json.dumps({'type': 'progress', 'progress': 15, 'message': '正在提取字幕...'})}\n\n")
        video, transcript = transcript_service.extract(url, language)
        summary_store.send_event(summary_id, f"data: {json.dumps({'type': 'progress', 'progress': 45, 'message': '字幕提取完成，开始 AI 分析...'})}\n\n")
        summary_store.update(summary_id, progress=45)
        result = deepseek_service.summarize(
            title=video.title,
            duration=video.duration,
            transcript=transcript,
            language=language,
        )
        summary_store.update(summary_id, status="success", progress=100, result=result)
        summary_store.send_event(summary_id, f"data: {json.dumps({'type': 'done', 'progress': 100, 'result': result.model_dump(mode='json')})}\n\n")
        summary_store.close_queue(summary_id)
    except TranscriptUnavailable as exc:
        summary_store.update(summary_id, status="failed", error=str(exc))
        summary_store.send_event(summary_id, f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n")
        summary_store.close_queue(summary_id)
    except DeepSeekUnavailable as exc:
        summary_store.update(summary_id, status="failed", error=str(exc))
        summary_store.send_event(summary_id, f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n")
        summary_store.close_queue(summary_id)
    except httpx.HTTPStatusError as exc:
        summary_store.update(summary_id, status="failed", error=_friendly_ai_error(exc))
        summary_store.send_event(summary_id, f"data: {json.dumps({'type': 'error', 'error': _friendly_ai_error(exc)})}\n\n")
        summary_store.close_queue(summary_id)
    except Exception as exc:
        summary_store.update(summary_id, status="failed", error=_friendly_ai_error(exc))
        summary_store.send_event(summary_id, f"data: {json.dumps({'type': 'error', 'error': _friendly_ai_error(exc)})}\n\n")
        summary_store.close_queue(summary_id)


def _run_summary_job_stream(summary_id: str, url: str, language: str) -> None:
    """Background job that streams summary generation events to the queue."""
    from app.schemas import SummaryResult, MindMapNode

    try:
        summary_store.update(summary_id, status="running", progress=10)
        summary_store.send_event(summary_id, f"data: {json.dumps({'type': 'progress', 'progress': 10, 'message': '正在提取字幕...'})}\n\n")
        video, transcript = transcript_service.extract(url, language)
        # 字幕已就绪，立即推送给前端，流式总结期间也能查看
        transcript_data = [t.model_dump() for t in transcript]
        summary_store.send_event(summary_id, f"data: {json.dumps({'type': 'transcript', 'segments': transcript_data, 'title': video.title})}\n\n")
        summary_store.update(summary_id, progress=30)
        summary_store.send_event(summary_id, f"data: {json.dumps({'type': 'progress', 'progress': 30, 'message': '字幕提取完成，开始 AI 深度分析...'})}\n\n")

        # Stream the AI generation
        last_event = ""
        for sse_event in deepseek_service.summarize_stream(
            title=video.title,
            duration=video.duration,
            transcript=transcript,
            language=language,
        ):
            summary_store.send_event(summary_id, sse_event)
            last_event = sse_event

        # Parse the final event to update the store
        try:
            data_str = last_event.strip()
            if data_str.startswith("data: "):
                payload = json.loads(data_str[6:])
                if payload.get("type") == "done" and "result" in payload:
                    result = SummaryResult(**payload["result"])
                    summary_store.update(summary_id, status="success", progress=100, result=result)
                else:
                    summary_store.update(summary_id, status="success", progress=100)
            else:
                summary_store.update(summary_id, status="success", progress=100)
        except Exception:
            summary_store.update(summary_id, status="success", progress=100)

        summary_store.close_queue(summary_id)
    except TranscriptUnavailable as exc:
        summary_store.update(summary_id, status="failed", error=str(exc))
        summary_store.send_event(summary_id, f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n")
        summary_store.close_queue(summary_id)
    except DeepSeekUnavailable as exc:
        summary_store.update(summary_id, status="failed", error=str(exc))
        summary_store.send_event(summary_id, f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n")
        summary_store.close_queue(summary_id)
    except httpx.HTTPStatusError as exc:
        summary_store.update(summary_id, status="failed", error=_friendly_ai_error(exc))
        summary_store.send_event(summary_id, f"data: {json.dumps({'type': 'error', 'error': _friendly_ai_error(exc)})}\n\n")
        summary_store.close_queue(summary_id)
    except Exception as exc:
        summary_store.update(summary_id, status="failed", error=_friendly_ai_error(exc))
        summary_store.send_event(summary_id, f"data: {json.dumps({'type': 'error', 'error': _friendly_ai_error(exc)})}\n\n")
        summary_store.close_queue(summary_id)


@router.post("/summaries", response_model=CreateSummaryResponse)
def create_summary(payload: CreateSummaryRequest, background_tasks: BackgroundTasks) -> CreateSummaryResponse:
    job = summary_store.create(str(payload.url))
    background_tasks.add_task(
        _run_summary_job_stream,
        job.summary_id,
        str(payload.url),
        payload.language,
    )
    return CreateSummaryResponse(summary_id=job.summary_id, status=job.status)


@router.get("/summaries/{summary_id}", response_model=SummaryStatus)
def get_summary(summary_id: str) -> SummaryStatus:
    job = summary_store.get(summary_id)
    if job is None:
        raise HTTPException(status_code=404, detail="AI 分析任务不存在")
    return summary_store.to_status(job)


@router.get("/summaries/{summary_id}/stream")
async def stream_summary(summary_id: str, request: Request):
    """SSE endpoint that streams summary generation events."""
    job = summary_store.get(summary_id)
    if job is None:
        raise HTTPException(status_code=404, detail="AI 分析任务不存在")

    async def event_generator():
        try:
            async for event in summary_store.event_stream(summary_id):
                if await request.is_disconnected():
                    break
                yield event
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/summaries/{summary_id}/questions", response_model=AskSummaryResponse)
def ask_summary(summary_id: str, payload: AskSummaryRequest) -> AskSummaryResponse:
    job = summary_store.get(summary_id)
    if job is None:
        raise HTTPException(status_code=404, detail="AI 分析任务不存在")
    if job.status != "success" or job.result is None:
        raise HTTPException(status_code=409, detail="AI 分析尚未完成，暂不能提问")
    try:
        return deepseek_service.answer(
            question=payload.question,
            summary=job.result,
        )
    except DeepSeekUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=_friendly_ai_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_friendly_ai_error(exc)) from exc


@router.post("/summaries/{summary_id}/questions/stream")
async def ask_summary_stream(summary_id: str, payload: AskSummaryRequest, request: Request):
    """SSE endpoint that streams AI Q&A answer token by token."""
    job = summary_store.get(summary_id)
    if job is None:
        raise HTTPException(status_code=404, detail="AI 分析任务不存在")
    if job.status != "success" or job.result is None:
        raise HTTPException(status_code=409, detail="AI 分析尚未完成，暂不能提问")

    async def event_generator():
        try:
            # Run the synchronous streaming generator in a thread pool
            loop = asyncio.get_event_loop()
            gen = await loop.run_in_executor(
                None,
                lambda: deepseek_service.answer_stream(
                    question=payload.question,
                    summary=job.result,
                ),
            )
            for event in gen:
                if await request.is_disconnected():
                    break
                yield event
        except DeepSeekUnavailable as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
        except httpx.HTTPStatusError as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': _friendly_ai_error(exc)})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': _friendly_ai_error(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
