from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from langchain_deepseek import ChatDeepSeek

from app.schemas import (
    AnswerReference,
    AskSummaryResponse,
    MindMapNode,
    SummaryChapter,
    SummaryResult,
    SummaryTerm,
    TranscriptSegment,
)
from app.services.transcript_service import format_timestamp, transcript_to_text


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
SUMMARY_MODEL = "deepseek-reasoner"
CHAT_MODEL = "deepseek-chat"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

CHUNK_CHAR_LIMIT = 12000
FINAL_CHAR_LIMIT = 36000
QA_CONTEXT_CHAR_LIMIT = 42000

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


SUMMARY_CHUNK_SYSTEM = _load_prompt("summary_chunk.txt")
SUMMARY_FINAL_JSON_SYSTEM = _load_prompt("summary_final_json.txt")
SUMMARY_STREAM_MD_SYSTEM = _load_prompt("summary_stream_md.txt")
MINDMAP_MARKDOWN_SYSTEM = _load_prompt("mindmap_mermaid.txt")
QA_JSON_SYSTEM = _load_prompt("qa_json.txt")
QA_STREAM_SYSTEM = _load_prompt("qa_stream.txt")


class DeepSeekUnavailable(RuntimeError):
    pass


class DeepSeekService:
    def __init__(self) -> None:
        self._summary_llm = ChatDeepSeek(
            model_name=SUMMARY_MODEL,
            openai_api_key=DEEPSEEK_API_KEY,
            openai_api_base=DEEPSEEK_BASE_URL,
            temperature=0.1,
        )
        self._chat_json_llm = ChatDeepSeek(
            model_name=CHAT_MODEL,
            openai_api_key=DEEPSEEK_API_KEY,
            openai_api_base=DEEPSEEK_BASE_URL,
            temperature=0.3,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        self._chat_text_llm = ChatDeepSeek(
            model_name=CHAT_MODEL,
            openai_api_key=DEEPSEEK_API_KEY,
            openai_api_base=DEEPSEEK_BASE_URL,
            temperature=0.3,
        )

    def summarize(
        self,
        *,
        title: str,
        duration: float | None,
        transcript: list[TranscriptSegment],
        language: str,
    ) -> SummaryResult:
        self._check_api_key()
        chunks = self._split_transcript(transcript)
        partials: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks, start=1):
            partials.append(
                self._invoke_json(
                    self._summary_llm,
                    [
                        {"role": "system", "content": SUMMARY_CHUNK_SYSTEM},
                        {
                            "role": "user",
                            "content": (
                                f"请总结以下视频字幕分块，语言：{language}。\n"
                                f"视频标题：{title}\n"
                                f"分块：{index}/{len(chunks)}\n"
                                "输出 JSON 字段：overview(string), key_points(string[]), chapters([{start,title,summary}])。\n\n"
                                f"{transcript_to_text(chunk)}"
                            ),
                        },
                    ],
                )
            )

        final_payload = self._invoke_json(
            self._summary_llm,
            [
                {"role": "system", "content": SUMMARY_FINAL_JSON_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"视频标题：{title}\n"
                        f"视频时长：{duration or '未知'} 秒\n"
                        f"语言：{language}\n"
                        "请输出 JSON 字段：overview(string), chapters([{start,title,summary}]), "
                        "key_points(string[]), action_items(string[]), terms([{name,explanation}]), "
                        "mindmap({name,children}), markdown(string)。\n"
                        "要求章节 start 尽量使用字幕时间秒数；markdown 要适合作为学习笔记复制。\n\n"
                        f"分块摘要：\n{json.dumps(partials, ensure_ascii=False)}\n\n"
                        f"原始字幕节选：\n{transcript_to_text(transcript, FINAL_CHAR_LIMIT)}"
                    ),
                },
            ],
        )
        result = self._to_summary_result(title, transcript, final_payload)
        # 非流式路径也生成 mindmap_markdown
        mindmap_md = self._generate_mindmap(title, transcript, result.markdown)
        result.mindmap_markdown = mindmap_md
        return result

    def answer(
        self,
        *,
        question: str,
        summary: SummaryResult,
    ) -> AskSummaryResponse:
        self._check_api_key()
        payload = self._invoke_json(
            self._chat_json_llm,
            [
                {"role": "system", "content": QA_JSON_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        "输出 JSON 字段：answer(string), references([{start,text}])。"
                        "references 选择最能支撑答案的字幕片段，最多 5 条。\n\n"
                        f"视频摘要：{summary.overview}\n"
                        f"核心要点：{json.dumps(summary.key_points, ensure_ascii=False)}\n"
                        f"字幕：\n{transcript_to_text(summary.transcript, QA_CONTEXT_CHAR_LIMIT)}\n\n"
                        f"问题：{question}"
                    ),
                },
            ],
        )
        refs = [
            AnswerReference(start=self._float_or_none(item.get("start")), text=str(item.get("text") or ""))
            for item in payload.get("references", [])
            if isinstance(item, dict) and item.get("text")
        ]
        return AskSummaryResponse(answer=str(payload.get("answer") or "未能生成回答。"), references=refs[:5])

    def summarize_stream(
        self,
        *,
        title: str,
        duration: float | None,
        transcript: list[TranscriptSegment],
        language: str,
    ):
        """Stream summary generation, yielding SSE event strings."""
        self._check_api_key()
        chunks = self._split_transcript(transcript)
        partials: list[dict[str, Any]] = []
        total_chunks = len(chunks)

        for index, chunk in enumerate(chunks, start=1):
            yield f"data: {json.dumps({'type': 'progress', 'progress': int(15 + (index / total_chunks) * 30), 'message': f'正在分析字幕分块 {index}/{total_chunks}...'})}\n\n"
            partials.append(
                self._invoke_json(
                    self._summary_llm,
                    [
                        {"role": "system", "content": SUMMARY_CHUNK_SYSTEM},
                        {
                            "role": "user",
                            "content": (
                                f"请总结以下视频字幕分块，语言：{language}。\n"
                                f"视频标题：{title}\n"
                                f"分块：{index}/{total_chunks}\n"
                                "输出 JSON 字段：overview(string), key_points(string[]), chapters([{start,title,summary}])。\n\n"
                                f"{transcript_to_text(chunk)}"
                            ),
                        },
                    ],
                )
            )

        yield f"data: {json.dumps({'type': 'progress', 'progress': 50, 'message': '正在生成最终总结...'})}\n\n"

        # 流式输出 Markdown 文本（用 chat-text 模型，不输出 JSON）
        md_messages = [
            {"role": "system", "content": SUMMARY_STREAM_MD_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"视频标题：{title}\n"
                    f"视频时长：{duration or '未知'} 秒\n"
                    f"语言：{language}\n\n"
                    f"分块摘要参考：\n{json.dumps(partials, ensure_ascii=False)}\n\n"
                    f"原始字幕节选：\n{transcript_to_text(transcript, FINAL_CHAR_LIMIT)}\n\n"
                    "请生成 Markdown 学习笔记。"
                ),
            },
        ]

        accumulated = ""
        for chunk in self._chat_text_llm.stream(md_messages):
            content = chunk.content
            if isinstance(content, str) and content:
                accumulated += content
                yield f"data: {json.dumps({'type': 'stream', 'text': content})}\n\n"

        # 生成 Markdown 层级思维导图（markmap 格式）
        yield f"data: {json.dumps({'type': 'progress', 'progress': 85, 'message': '正在生成思维导图...'})}\n\n"
        mindmap_md = self._generate_mindmap(title, transcript, accumulated)
        yield f"data: {json.dumps({'type': 'mindmap', 'markdown': mindmap_md})}\n\n"

        # 用分块摘要 + 流式 MD 构建结构化结果
        result = self._build_result_from_partials(title, transcript, partials, accumulated, mindmap_md)
        yield f"data: {json.dumps({'type': 'done', 'progress': 100, 'result': result.model_dump(mode='json')})}\n\n"

    def answer_stream(
        self,
        *,
        question: str,
        summary: SummaryResult,
    ):
        """Stream AI Q&A answer token by token, yielding SSE event strings."""
        self._check_api_key()
        messages = [
            {"role": "system", "content": QA_STREAM_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"用户提问：{question}\n\n"
                    "--- 以下为视频参考信息 ---\n"
                    f"视频摘要：{summary.overview}\n"
                    f"核心要点：{json.dumps(summary.key_points, ensure_ascii=False)}\n"
                    f"字幕内容：\n{transcript_to_text(summary.transcript, QA_CONTEXT_CHAR_LIMIT)}\n"
                    "--- 参考信息结束 ---\n\n"
                    "请基于以上信息回答用户提问。如果问题与视频无关，请礼貌拒绝。"
                ),
            },
        ]

        accumulated = ""
        for chunk in self._chat_text_llm.stream(messages):
            content = chunk.content
            if isinstance(content, str) and content:
                accumulated += content
                yield f"data: {json.dumps({'type': 'stream', 'text': content})}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'answer': accumulated, 'references': []})}\n\n"

    # ── internal helpers ──────────────────────────────────────────────

    def _check_api_key(self) -> None:
        if not DEEPSEEK_API_KEY:
            raise DeepSeekUnavailable("服务端未配置 DEEPSEEK_API_KEY，请联系管理员。")

    def _invoke_json(self, llm: ChatDeepSeek, messages: list[dict[str, str]]) -> dict[str, Any]:
        response = llm.invoke(messages)
        return self._parse_json_content(str(response.content))

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        cleaned = content.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
        if fenced:
            cleaned = fenced.group(1).strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise
            parsed = json.loads(cleaned[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("DeepSeek 返回内容不是 JSON 对象")
        return parsed

    def _split_transcript(self, transcript: list[TranscriptSegment]) -> list[list[TranscriptSegment]]:
        chunks: list[list[TranscriptSegment]] = []
        current: list[TranscriptSegment] = []
        current_size = 0
        for segment in transcript:
            item_size = len(segment.text) + 24
            if current and current_size + item_size > CHUNK_CHAR_LIMIT:
                chunks.append(current)
                current = []
                current_size = 0
            current.append(segment)
            current_size += item_size
        if current:
            chunks.append(current)
        return chunks or [transcript]

    def _generate_mindmap(self, title: str, transcript: list[TranscriptSegment], markdown: str = "") -> str:
        """从视频字幕原文生成 Markdown 层级思维导图（markmap 格式）。"""
        transcript_text = transcript_to_text(transcript, 12000)
        try:
            response = self._chat_text_llm.invoke([
                {"role": "system", "content": MINDMAP_MARKDOWN_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"视频标题：{title}\n\n"
                        f"以下是完整的视频字幕内容：\n\n{transcript_text}\n\n"
                        + (f"视频学习笔记参考：\n\n{markdown[:8000]}\n\n" if markdown else "")
                    ),
                },
            ])
            raw = str(response.content).strip()
            # 去掉可能的 ```markdown / ``` 代码块包裹
            cleaned = re.sub(r"^```(?:markdown|md)?\s*", "", raw)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            return cleaned.strip()
        except Exception:
            return ""

    def _build_result_from_partials(
        self,
        title: str,
        transcript: list[TranscriptSegment],
        partials: list[dict[str, Any]],
        markdown: str,
        mindmap_md: str = "",
    ) -> SummaryResult:
        """Aggregate chunk partials + streamed Markdown into a SummaryResult."""
        # 合并章节（去重：按 title 去重，保留第一次出现的 start）
        seen_titles: set[str] = set()
        chapters: list[SummaryChapter] = []
        for p in partials:
            for item in p.get("chapters", []):
                if not isinstance(item, dict):
                    continue
                t = str(item.get("title") or "").strip()
                if not t or t in seen_titles:
                    continue
                seen_titles.add(t)
                chapters.append(SummaryChapter(
                    start=self._float_or_none(item.get("start")),
                    title=t,
                    summary=str(item.get("summary") or ""),
                ))

        # 合并核心要点（去重）
        seen_points: set[str] = set()
        key_points: list[str] = []
        for p in partials:
            for point in p.get("key_points", []):
                pt = str(point).strip()
                if pt and pt not in seen_points:
                    seen_points.add(pt)
                    key_points.append(pt)

        overview = self._extract_overview(markdown)
        final_md = markdown.strip() or self._build_markdown_str(title, overview, chapters, key_points)

        # 构建 MindMapNode 作为降级方案（前端优先用 mermaid）
        fallback_mindmap = self._build_mindmap_from_chapters(title, chapters, key_points)

        return SummaryResult(
            title=title,
            overview=overview,
            chapters=chapters,
            key_points=key_points,
            action_items=[],
            terms=[],
            transcript=transcript,
            mindmap=fallback_mindmap,
            mermaid="",
            mindmap_markdown=mindmap_md,
            markdown=final_md,
        )

    def _build_mindmap_from_chapters(
        self,
        title: str,
        chapters: list[SummaryChapter],
        key_points: list[str],
    ) -> MindMapNode:
        children: list[MindMapNode] = [
            MindMapNode(name=ch.title, children=[MindMapNode(name=ch.summary[:80])])
            for ch in chapters[:8]
        ]
        if not children:
            children = [MindMapNode(name=pt) for pt in key_points[:8]]
        return MindMapNode(name=title, children=children)

    def _to_summary_result(
        self,
        title: str,
        transcript: list[TranscriptSegment],
        payload: dict[str, Any],
    ) -> SummaryResult:
        chapters = [
            SummaryChapter(
                start=self._float_or_none(item.get("start")),
                title=str(item.get("title") or "未命名章节"),
                summary=str(item.get("summary") or ""),
            )
            for item in payload.get("chapters", [])
            if isinstance(item, dict)
        ]
        terms = [
            SummaryTerm(name=str(item.get("name") or ""), explanation=str(item.get("explanation") or ""))
            for item in payload.get("terms", [])
            if isinstance(item, dict) and item.get("name")
        ]
        mindmap = self._to_mindmap(payload.get("mindmap")) or self._fallback_mindmap(title, chapters, payload)
        markdown = str(payload.get("markdown") or "").strip()
        result = SummaryResult(
            title=title,
            overview=str(payload.get("overview") or "") or self._extract_overview(markdown),
            chapters=chapters,
            key_points=[str(item) for item in payload.get("key_points", []) if str(item).strip()],
            action_items=[str(item) for item in payload.get("action_items", []) if str(item).strip()],
            terms=terms,
            transcript=transcript,
            mindmap=mindmap,
            markdown=markdown,
        )
        if not result.markdown:
            result.markdown = self._build_markdown(result)
        return result

    def _to_mindmap(self, value: Any) -> MindMapNode | None:
        if not isinstance(value, dict) or not value.get("name"):
            return None
        children = [self._to_mindmap(child) for child in value.get("children", []) if isinstance(child, dict)]
        return MindMapNode(name=str(value["name"]), children=[child for child in children if child is not None])

    def _fallback_mindmap(
        self,
        title: str,
        chapters: list[SummaryChapter],
        payload: dict[str, Any],
    ) -> MindMapNode:
        children: list[MindMapNode] = [
            MindMapNode(name=chapter.title, children=[MindMapNode(name=chapter.summary[:80])])
            for chapter in chapters[:8]
        ]
        if not children:
            children = [MindMapNode(name=str(item)) for item in payload.get("key_points", [])[:8]]
        return MindMapNode(name=title, children=children)

    def _build_markdown(self, result: SummaryResult) -> str:
        return self._build_markdown_str(
            result.title, result.overview, result.chapters, result.key_points
        )

    @staticmethod
    def _build_markdown_str(
        title: str,
        overview: str,
        chapters: list[SummaryChapter],
        key_points: list[str],
    ) -> str:
        lines = [f"# {title}", "", "## 一句话概览", overview, ""]
        if chapters:
            lines.extend(["## 章节大纲"])
            for chapter in chapters:
                prefix = f"[{format_timestamp(chapter.start)}] " if chapter.start is not None else ""
                lines.append(f"- {prefix}{chapter.title}：{chapter.summary}")
            lines.append("")
        if key_points:
            lines.extend(["## 核心要点", *[f"- {item}" for item in key_points], ""])
        return "\n".join(lines).strip()

    def _extract_overview(self, markdown: str) -> str:
        """从 markdown 提取概览：跳过标题、表格行、空行，取第一段正文。"""
        if not markdown:
            return "未能生成概览。"
        in_table = False
        for line in markdown.splitlines():
            stripped = line.strip()
            # 跳过空行、标题
            if not stripped or stripped.startswith("#"):
                continue
            # 跳过表格分隔符
            if stripped.startswith("|") and "---" in stripped:
                in_table = True
                continue
            # 跳过表格行
            if in_table and stripped.startswith("|"):
                continue
            in_table = False
            if len(stripped) > 30:
                return stripped[:300]
        return "未能生成概览。"

    def _float_or_none(self, value: Any) -> float | None:
        try:
            if value is None or value == "":
                return None
            return float(value)
        except (TypeError, ValueError):
            return None


deepseek_service = DeepSeekService()
