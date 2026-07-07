<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from "vue";
import { Transformer } from "markmap-lib";
import { Markmap } from "markmap-view";

type VideoFormat = {
  format_id: string;
  label: string;
  ext?: string | null;
  resolution?: string | null;
  filesize?: number | null;
  filesize_approx?: number | null;
  direct_url?: string | null;
};

type VideoInfo = {
  url: string;
  title: string;
  extractor?: string | null;
  duration?: number | null;
  thumbnail?: string | null;
  webpage_url?: string | null;
  formats: VideoFormat[];
};

type AnalyzeItem = {
  url: string;
  ok: boolean;
  video?: VideoInfo | null;
  error?: string | null;
};

type JobStatus = {
  job_id: string;
  url: string;
  format_id: string;
  status: "queued" | "running" | "success" | "failed";
  progress: number;
  speed?: number | null;
  downloaded_bytes?: number | null;
  total_bytes?: number | null;
  error?: string | null;
  files: Array<{ id: string; filename: string; size: number; download_url: string }>;
};

type TranscriptSegment = {
  start: number;
  end?: number | null;
  text: string;
};

type MindMapNode = {
  name: string;
  children: MindMapNode[];
};

type SummaryResult = {
  title: string;
  overview: string;
  chapters: Array<{ start?: number | null; title: string; summary: string }>;
  key_points: string[];
  action_items: string[];
  terms: Array<{ name: string; explanation: string }>;
  transcript: TranscriptSegment[];
  mindmap?: MindMapNode | null;
  mermaid: string;
  mindmap_markdown: string;
  markdown: string;
};

type SummaryStatus = {
  summary_id: string;
  url: string;
  status: "queued" | "running" | "success" | "failed";
  progress: number;
  error?: string | null;
  result?: SummaryResult | null;
};

type QuestionAnswer = {
  question: string;
  answer: string;
  references: Array<{ start?: number | null; text: string }>;
};

const sampleUrls = `https://www.youtube.com/watch?v=dQw4w9WgXcQ`;
const urlInput = ref("");
const analyzing = ref(false);
const analyzeError = ref("");
const results = ref<AnalyzeItem[]>([]);
const selectedFormats = reactive<Record<string, string>>({});
const directErrors = reactive<Record<string, string>>({});
const jobs = ref<JobStatus[]>([]);
const pollers = new Map<string, number>();
const summaryLanguage = ref("zh");
const activeWorkflowTab = ref<"summary" | "download">("summary");
const summaryJobs = ref<SummaryStatus[]>([]);
const summaryPollers = new Map<string, number>();
const summaryStreams = new Map<string, AbortController>();
const summaryErrors = reactive<Record<string, string>>({});
const activeSummaryTabs = reactive<Record<string, "summary" | "transcript" | "mindmap" | "qa">>({});
const questionInputs = reactive<Record<string, string>>({});
const questionLoading = reactive<Record<string, boolean>>({});
const questionAnswers = reactive<Record<string, QuestionAnswer[]>>({});
const activeAnswerIndex = reactive<Record<string, number>>({});
const expandedRefs = reactive<Record<string, boolean>>({});
const lastQuestionText = reactive<Record<string, string>>({});
const streamingText = reactive<Record<string, string>>({});
const streamingQA = reactive<Record<string, string>>({});
const toastMessage = ref("");
let toastTimer: number | undefined;

function showToast(msg: string) {
  toastMessage.value = msg;
  if (toastTimer) window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { toastMessage.value = ""; }, 2000);
}

function isSummaryLoading(url: string) {
  const job = summaryForUrl(url);
  return job && !job.result && job.status !== "failed";
}

function handleTabClick(url: string, tab: "summary" | "transcript" | "mindmap" | "qa") {
  const job = summaryForUrl(url);
  if (!job?.result) {
    showToast("请等待 AI 分析完成后查看");
    return;
  }
  setSummaryTab(url, tab);
}

const urlPattern = /https?:\/\/[^\s，。；、"'<>]+/g;

const parsedUrls = computed(() =>
  Array.from(new Set((urlInput.value.match(urlPattern) || []).map((url) => url.replace(/[)\]}]+$/, "")))),
);

const canAnalyze = computed(() => parsedUrls.value.length > 0 && !analyzing.value);
function loadSample() {
  urlInput.value = sampleUrls;
}

function formatDuration(seconds?: number | null) {
  if (!seconds) return "未知时长";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

function formatTimestamp(seconds?: number | null) {
  if (seconds === null || seconds === undefined) return "00:00";
  const safe = Math.max(0, Math.floor(seconds));
  const h = Math.floor(safe / 3600);
  const m = Math.floor((safe % 3600) / 60);
  const s = safe % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

function formatBytes(value?: number | null) {
  if (!value) return "未知大小";
  if (value > 1024 * 1024 * 1024) return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatSpeed(value?: number | null) {
  if (!value) return "等待中";
  return `${formatBytes(value)}/s`;
}

function defaultFormat(video: VideoInfo) {
  return video.formats[0]?.format_id || "bv*+ba/b";
}

function displayFormatLabel(format: VideoFormat) {
  if (format.format_id === "bv*+ba/b" || format.format_id === "best") {
    return "最佳音画质量（自动合并）";
  }
  const resolution = format.resolution && format.resolution !== "audio only" ? format.resolution : "";
  const ext = format.ext ? format.ext.toUpperCase() : "";
  const size = format.filesize || format.filesize_approx ? formatBytes(format.filesize || format.filesize_approx) : "";
  return [resolution, ext, size].filter(Boolean).join(" · ") || format.label || format.format_id;
}

async function analyze() {
  if (!canAnalyze.value) return;
  analyzing.value = true;
  analyzeError.value = "";
  for (const key of Object.keys(directErrors)) {
    delete directErrors[key];
  }
  results.value = [];
  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls: parsedUrls.value }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "解析请求失败");
    }
    results.value = payload.results;
    for (const item of results.value) {
      if (item.ok && item.video) {
        selectedFormats[item.url] = defaultFormat(item.video);
      }
    }
  } catch (error) {
    analyzeError.value = error instanceof Error ? error.message : "解析失败";
  } finally {
    analyzing.value = false;
  }
}

function directDownload(item: AnalyzeItem) {
  if (!item.video) return;
  const formatId = selectedFormats[item.url] || "bv*+ba/b";
  const directUrl = `/api/direct?url=${encodeURIComponent(item.url)}&format_id=${encodeURIComponent(formatId)}`;
  directErrors[item.url] = "直链由浏览器直接处理，如需自定义保存目录请使用服务端下载。";
  window.open(directUrl, "_blank", "noopener,noreferrer");
}

async function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename.replace(/[/\\?%*:|"<>]/g, "_");
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  setTimeout(() => URL.revokeObjectURL(url), 100);
}

function downloadFile(url: string, filename: string) {
  fetch(url)
    .then(async (resp) => {
      if (!resp.ok) throw new Error("下载失败");
      const blob = await resp.blob();
      saveBlob(blob, filename);
    })
    .catch(() => {});
}

async function createJob(item: AnalyzeItem) {
  if (!item.video) return;
  const formatId = selectedFormats[item.url] || "bv*+ba/b";
  directErrors[item.url] = "";
  const response = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: item.url, format_id: formatId, download_mode: "proxy" }),
  });
  const payload = await response.json();
  if (!response.ok) {
    directErrors[item.url] = payload.detail || "服务端下载任务创建失败";
    return;
  }
  const initial: JobStatus = {
    job_id: payload.job_id,
    url: item.url,
    format_id: formatId,
    status: payload.status,
    progress: 0,
    files: [],
  };
  jobs.value = [initial, ...jobs.value.filter((job) => job.job_id !== payload.job_id)];
  startPolling(payload.job_id);
}

function startPolling(jobId: string) {
  if (pollers.has(jobId)) return;
  const tick = async () => {
    const response = await fetch(`/api/jobs/${jobId}`);
    if (!response.ok) return;
    const payload = (await response.json()) as JobStatus;
    jobs.value = jobs.value.map((job) => (job.job_id === jobId ? payload : job));
    if (payload.status === "success" || payload.status === "failed") {
      const timer = pollers.get(jobId);
      if (timer) window.clearInterval(timer);
      pollers.delete(jobId);
    }
  };
  void tick();
  pollers.set(jobId, window.setInterval(tick, 1200));
}

function summaryForUrl(url: string) {
  return summaryJobs.value.find((job) => job.url === url);
}

function renderMarkdown(md: string): string {
  if (!md) return "";
  let html = md
    // 转义 HTML
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    // 代码块
    .replace(/```(\w*)\n([\s\S]*?)```/g, "<pre class=\"my-3 rounded-lg bg-[#0a0c10] p-3 text-xs leading-5 overflow-x-auto\"><code>$2</code></pre>")
    // 行内代码
    .replace(/`([^`]+)`/g, "<code class=\"rounded bg-[#0a0c10] px-1 py-0.5 text-xs font-mono text-rose-300\">$1</code>")
    // 标题
    .replace(/^#### (.+)$/gm, "<h4 class=\"mt-4 mb-2 text-sm font-bold text-slate-100\">$1</h4>")
    .replace(/^### (.+)$/gm, "<h3 class=\"mt-5 mb-2 text-base font-bold text-blue-200\">$1</h3>")
    .replace(/^## (.+)$/gm, "<h2 class=\"mt-6 mb-3 text-lg font-extrabold text-blue-300\">$1</h2>")
    .replace(/^# (.+)$/gm, "<h1 class=\"mt-6 mb-4 text-xl font-extrabold text-white\">$1</h1>")
    // 水平线
    .replace(/^---$/gm, "<hr class=\"my-4 border-[#2a303a]\">")
    // 加粗
    .replace(/\*\*(.+?)\*\*/g, "<strong class=\"font-bold text-slate-100\">$1</strong>")
    // 斜体
    .replace(/\*(.+?)\*/g, "<em class=\"italic\">$1</em>")
    // 无序列表项
    .replace(/^- (.+)$/gm, "<li class=\"ml-4 list-disc text-sm leading-7 text-slate-300\">$1</li>")
    // 表格分隔符（跳过）
    .replace(/^\|[-:| ]+\|$/gm, "")
    // 表格行
    .replace(/^\|(.+)\|$/gm, (_: string, content: string) => {
      const cells = content.split("|").map((c: string) => `<td class="border border-[#2a303a] px-3 py-1.5 text-sm text-slate-300">${c.trim()}</td>`).join("");
      return `<tr>${cells}</tr>`;
    })
    // 段落（连续非空、非标记行）
    .replace(/^(?!<[a-zA-Z/]|$)(.+)$/gm, "<p class=\"text-sm leading-7 text-slate-300 my-2\">$1</p>");

  // 包裹连续 <li> 为 <ul>
  html = html.replace(/(<li class="[^"]*">[^<]*<\/li>\n?)+/g, (match) => `<ul class="my-2 space-y-1">${match}</ul>`);
  // 包裹连续 <tr> 为 <table>
  html = html.replace(/(<tr>[^<]*(?:<td[^>]*>[^<]*<\/td>)+<\/tr>\n?)+/g, (match) => `<table class="my-3 w-full border-collapse border border-[#2a303a] rounded-lg overflow-hidden">${match}</table>`);

  return html;
}

function flattenedMindmap(node?: MindMapNode | null, depth = 0): Array<{ name: string; depth: number }> {
  if (!node) return [];
  return [
    { name: node.name, depth },
    ...node.children.flatMap((child) => flattenedMindmap(child, depth + 1)),
  ];
}

function activeTabForUrl(url: string) {
  const summary = summaryForUrl(url);
  return summary ? activeSummaryTabs[summary.summary_id] || "summary" : "summary";
}

function summaryIdForUrl(url: string) {
  return summaryForUrl(url)?.summary_id || "";
}

function setSummaryTab(url: string, tab: "summary" | "transcript" | "mindmap" | "qa") {
  const summary = summaryForUrl(url);
  if (summary) activeSummaryTabs[summary.summary_id] = tab;
}

async function createSummary(item: AnalyzeItem) {
  if (!item.video) return;
  summaryErrors[item.url] = "";
  const response = await fetch("/api/summaries", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url: item.url,
      language: summaryLanguage.value.trim() || "zh",
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    summaryErrors[item.url] = payload.detail || "AI 分析任务创建失败";
    return;
  }
  const initial: SummaryStatus = {
    summary_id: payload.summary_id,
    url: item.url,
    status: payload.status,
    progress: 0,
  };
  summaryJobs.value = [initial, ...summaryJobs.value.filter((job) => job.url !== item.url)];
  activeSummaryTabs[payload.summary_id] = "summary";
  streamingText[payload.summary_id] = "";
  startSummaryStream(payload.summary_id);
}

function startSummaryStream(summaryId: string) {
  if (summaryStreams.has(summaryId)) return;
  const controller = new AbortController();
  summaryStreams.set(summaryId, controller);

  fetch(`/api/summaries/${summaryId}/stream`, {
    signal: controller.signal,
  })
    .then(async (resp) => {
      if (!resp.ok) return;
      const reader = resp.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const dataStr = line.slice(6);
          try {
            const event = JSON.parse(dataStr);
            handleSummaryEvent(summaryId, event);
          } catch {
            // skip malformed events
          }
        }
      }
    })
    .catch(() => {
      // connection aborted or failed
    })
    .finally(() => {
      summaryStreams.delete(summaryId);
    });
}

function handleSummaryEvent(summaryId: string, event: any) {
  const job = summaryJobs.value.find((j) => j.summary_id === summaryId);
  if (!job) return;

  if (event.type === "progress") {
    summaryJobs.value = summaryJobs.value.map((j) =>
      j.summary_id === summaryId ? { ...j, status: "running" as const, progress: event.progress } : j,
    );
  } else if (event.type === "stream") {
    streamingText[summaryId] = (streamingText[summaryId] || "") + event.text;
  } else if (event.type === "mindmap") {
    mindmapMarkdowns[summaryId] = event.markdown || "";
  } else if (event.type === "done") {
    summaryJobs.value = summaryJobs.value.map((j) =>
      j.summary_id === summaryId
        ? { ...j, status: "success" as const, progress: 100, result: event.result }
        : j,
    );
    streamingText[summaryId] = "";
    if (event.result?.mindmap_markdown) {
      mindmapMarkdowns[summaryId] = event.result.mindmap_markdown;
    }
  } else if (event.type === "error") {
    summaryJobs.value = summaryJobs.value.map((j) =>
      j.summary_id === summaryId ? { ...j, status: "failed" as const, error: event.error } : j,
    );
    streamingText[summaryId] = "";
  }
}

async function askSummary(summary: SummaryStatus) {
  const question = questionInputs[summary.summary_id]?.trim();
  if (!question) return;
  // 防抖去重：相同提问正在处理中则忽略
  if (questionLoading[summary.summary_id] && lastQuestionText[summary.summary_id] === question) return;
  questionLoading[summary.summary_id] = true;
  lastQuestionText[summary.summary_id] = question;
  questionInputs[summary.summary_id] = "";

  // 追加到对话列表末尾
  const pendingEntry: QuestionAnswer = { question, answer: "", references: [] };
  const list = questionAnswers[summary.summary_id] || [];
  questionAnswers[summary.summary_id] = [...list, pendingEntry];
  activeAnswerIndex[summary.summary_id] = list.length;
  streamingQA[summary.summary_id] = "";

  // 获取新条目的索引（即数组最后一个位置）
  const pendingIdx = list.length;
  void nextTick(() => scrollChatBot(summary.summary_id));

  try {
    const response = await fetch(`/api/summaries/${summary.summary_id}/questions/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: "提问失败" }));
      throw new Error(err.detail || "提问失败");
    }

    const reader = response.body?.getReader();
    if (!reader) throw new Error("浏览器不支持流式读取");

    const decoder = new TextDecoder();
    let buffer = "";
    let answerText = "";
    let references: Array<{ start?: number | null; text: string }> = [];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const dataStr = line.slice(6);
        try {
          const event = JSON.parse(dataStr);
          if (event.type === "stream") {
            answerText += event.text;
            streamingQA[summary.summary_id] = answerText;
            scrollChatBot(summary.summary_id);
          } else if (event.type === "done") {
            answerText = event.answer;
            references = event.references;
          } else if (event.type === "error") {
            throw new Error(event.error);
          }
        } catch (e) {
          if (e instanceof Error && e.message !== "提问失败") throw e;
        }
      }
    }

    // 更新已插入的 pending entry
    questionAnswers[summary.summary_id][pendingIdx].answer = answerText || "未能生成回答。";
    questionAnswers[summary.summary_id][pendingIdx].references = references;
    streamingQA[summary.summary_id] = "";
  } catch (error) {
    questionAnswers[summary.summary_id][pendingIdx].answer = error instanceof Error ? error.message : "提问失败";
    streamingQA[summary.summary_id] = "";
  } finally {
    questionLoading[summary.summary_id] = false;
  }
}

function scrollChatBot(summaryId: string) {
  const el = document.getElementById(`chat-scroll-${summaryId}`);
  if (el) el.scrollTop = el.scrollHeight;
}

function askSummaryForUrl(url: string) {
  const summary = summaryForUrl(url);
  if (summary) void askSummary(summary);
}

async function copyMarkdown(summary: SummaryStatus) {
  const markdown = summary.result?.markdown;
  if (!markdown) return;
  await navigator.clipboard.writeText(markdown);
}

function downloadMarkdown(summary: SummaryStatus) {
  const markdown = summary.result?.markdown;
  if (!markdown) return;
  const filename = (summary.result?.title || "视频总结").replace(/[/\\?%*:|"<>]/g, "_") + ".md";
  const blob = new Blob([markdown], { type: "text/markdown; charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

function copyMarkdownForUrl(url: string) {
  const summary = summaryForUrl(url);
  if (summary) void copyMarkdown(summary);
}

async function copyAnswerText(text: string) {
  await navigator.clipboard.writeText(text);
  showToast("已复制到剪贴板");
}

function regenerateAnswer(url: string, question: string) {
  questionInputs[summaryIdForUrl(url)] = question;
  const summary = summaryForUrl(url);
  if (summary) void askSummary(summary);
}

function downloadMarkdownForUrl(url: string) {
  const summary = summaryForUrl(url);
  if (summary) downloadMarkdown(summary);
}

function copyTranscriptForUrl(url: string) {
  const transcript = summaryForUrl(url)?.result?.transcript;
  if (!transcript?.length) return;
  const text = transcript.map((seg) => `[${formatTimestamp(seg.start)}] ${seg.text}`).join("\n");
  navigator.clipboard.writeText(text).then(() => showToast("已复制字幕文本"));
}

function downloadTranscriptForUrl(url: string) {
  const transcript = summaryForUrl(url)?.result?.transcript;
  if (!transcript?.length) return;
  const text = transcript.map((seg) => `[${formatTimestamp(seg.start)}] ${seg.text}`).join("\n");
  const filename = (summaryForUrl(url)?.result?.title || "字幕").replace(/[/\\?%*:|"<>]/g, "_") + "_字幕.txt";
  const blob = new Blob([text], { type: "text/plain; charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

// markmap 状态：每个 summary 独立存储 mindmap markdown、SVG 元素引用和实例
const mindmapMarkdowns: Record<string, string> = {};
const markmapInstances: Record<string, { instance: any; svgEl: SVGElement | null }> = {};

function renderMarkmap(summaryId: string, md: string) {
  const entry = markmapInstances[summaryId];
  if (!entry?.svgEl || !md) return;
  try {
    // 清除旧内容
    while (entry.svgEl.firstChild) entry.svgEl.removeChild(entry.svgEl.firstChild);
    const transformer = new Transformer();
    const { root } = transformer.transform(md);
    entry.instance = Markmap.create(entry.svgEl, { autoFit: true, duration: 300 }, root);
  } catch { /* ignore */ }
}

function setMarkmapRef(summaryId: string, el: SVGElement | null) {
  if (!el) return;
  const entry = markmapInstances[summaryId];
  if (entry && entry.svgEl === el) return; // already set
  markmapInstances[summaryId] = { instance: null, svgEl: el };
  nextTick(() => {
    const md = mindmapMarkdowns[summaryId] || summaryForUrlBySummaryId(summaryId)?.result?.mindmap_markdown || "";
    if (md) renderMarkmap(summaryId, md);
  });
}

function summaryForUrlBySummaryId(summaryId: string): SummaryStatus | undefined {
  return summaryJobs.value.find((j) => j.summary_id === summaryId);
}

function copyMindmapForUrl(url: string) {
  const r = summaryForUrl(url)?.result;
  const text = r?.mindmap_markdown || flattenedMindmap(r?.mindmap).map((n) => `${"  ".repeat(n.depth)}- ${n.name}`).join("\n");
  if (text) navigator.clipboard.writeText(text).then(() => showToast("已复制思维导图"));
}

function downloadMindmapForUrl(url: string) {
  const r = summaryForUrl(url)?.result;
  const text = r?.mindmap_markdown || flattenedMindmap(r?.mindmap).map((n) => `${"  ".repeat(n.depth)}- ${n.name}`).join("\n");
  if (!text) return;
  const filename = (r?.title || "思维导图").replace(/[/\\?%*:|"<>]/g, "_") + "_导图.md";
  const blob = new Blob([text], { type: "text/markdown; charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

onBeforeUnmount(() => {
  for (const timer of pollers.values()) {
    window.clearInterval(timer);
  }
  for (const timer of summaryPollers.values()) {
    window.clearInterval(timer);
  }
  for (const controller of summaryStreams.values()) {
    controller.abort();
  }
});

const successfulResults = computed(() => results.value.filter((item) => item.ok && item.video));
const failedResults = computed(() => results.value.filter((item) => !item.ok));

const platforms = ["抖音", "爱奇艺", "TikTok", "YouTube", "Bilibili", "X", "Instagram", "Vimeo", "更多站点"];
const summaryTabs = [
  { key: "summary", label: "总结摘要" },
  { key: "transcript", label: "字幕文本" },
  { key: "mindmap", label: "思维导图" },
  { key: "qa", label: "AI 问答" },
] as const;
</script>

<template>
  <div class="min-h-screen bg-[#0f1115] text-slate-100">
    <header class="sticky top-0 z-20 border-b border-[#2a303a] bg-[#0f1115]/92 backdrop-blur">
      <nav class="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6 lg:px-8">
        <a href="#" class="flex items-center gap-3">
          <span class="grid h-9 w-9 place-items-center rounded-lg bg-blue-500 text-sm font-black text-white">AI</span>
          <span class="text-base font-black text-white">AI 视频解析总结</span>
        </a>
        <div class="hidden items-center gap-8 text-sm font-medium text-slate-400 md:flex">
          <a href="#tool" class="hover:text-blue-300">视频解析</a>
          <a href="#results" class="hover:text-blue-300">AI 总结</a>
          <a href="#platforms" class="hover:text-blue-300">平台能力</a>
          <a href="#notice" class="hover:text-blue-300">安全边界</a>
        </div>
        <a href="#tool" class="rounded-full bg-blue-500 px-4 py-2 text-sm font-bold text-white shadow-sm hover:bg-blue-400">
          开始解析
        </a>
      </nav>
    </header>

    <!-- 轻提示 Toast -->
    <Transition name="toast-fade">
      <div v-if="toastMessage" class="fixed top-20 left-1/2 z-50 -translate-x-1/2 rounded-full border border-amber-400/30 bg-amber-500/90 px-5 py-3 text-sm font-bold text-white shadow-xl backdrop-blur">
        {{ toastMessage }}
      </div>
    </Transition>

    <main>
      <section id="tool" class="border-b border-[#2a303a]">
        <div class="mx-auto max-w-7xl px-4 py-12 sm:px-6 sm:py-16 lg:px-8">
          <div class="mx-auto max-w-4xl text-center">
            <p class="mb-4 text-sm font-bold text-emerald-300">字幕提取 · AI 摘要 · 思维导图 · 视频问答</p>
            <h1 class="text-4xl font-black tracking-normal text-white sm:text-5xl lg:text-6xl">
              AI 视频解析总结
            </h1>
            <p class="mx-auto mt-5 max-w-2xl text-base leading-8 text-slate-400 sm:text-lg">
              提取视频字幕，生成摘要、大纲、思维导图和问答素材；需要时可继续下载视频文件。
            </p>
          </div>

          <div class="mx-auto mt-9 max-w-4xl rounded-3xl border border-[#2a303a] bg-[#171a20] p-4 shadow-2xl shadow-black/20 sm:p-6">
            <label class="text-sm font-bold text-slate-200" for="urls">粘贴公开视频链接</label>
            <textarea
              id="urls"
              v-model="urlInput"
              rows="6"
              class="mt-3 w-full resize-y rounded-2xl border border-[#2a303a] bg-[#11141a] px-4 py-4 text-sm leading-7 text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-blue-400 focus:ring-4 focus:ring-blue-500/10"
              placeholder="每行一个链接，支持直接粘贴带文字的分享内容，例如：【视频标题】https://www.bilibili.com/video/BVxxx"
            />
            <div class="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div class="flex flex-wrap gap-2 text-xs font-semibold">
                <span class="rounded-full border border-blue-400/30 bg-blue-400/10 px-3 py-1.5 text-blue-200">AI 总结优先</span>
                <span class="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1.5 text-emerald-200">平台字幕提取</span>
                <span class="rounded-full border border-slate-500/40 bg-slate-700/30 px-3 py-1.5 text-slate-300">下载可选</span>
              </div>
              <div class="flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  class="rounded-full border border-[#2a303a] px-5 py-3 text-sm font-bold text-slate-300 hover:border-blue-400 hover:text-blue-200"
                  @click="loadSample"
                >
                  填入测试链接
                </button>
                <button
                  type="button"
                  :disabled="!canAnalyze"
                  class="rounded-full bg-blue-500 px-6 py-3 text-sm font-black text-white shadow-lg shadow-blue-950/40 transition hover:bg-blue-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400 disabled:shadow-none"
                  @click="analyze"
                >
                  {{ analyzing ? "解析中..." : "解析视频" }}
                </button>
              </div>
            </div>
            <p v-if="analyzeError" class="mt-4 rounded-2xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm font-medium text-red-200">
              {{ analyzeError }}
            </p>
          </div>
        </div>
      </section>

      <section v-if="results.length" id="results" class="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
        <div class="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p class="text-sm font-bold text-blue-300">解析结果</p>
            <h2 class="mt-1 text-2xl font-black text-white sm:text-3xl">选择接下来的工作流</h2>
            <p class="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
              默认进入 AI 视频总结，下载作为独立的可选功能，不再和总结操作混在一起。
            </p>
          </div>
          <div class="grid rounded-2xl border border-[#2a303a] bg-[#171a20] p-1 sm:grid-cols-2">
            <button
              type="button"
              class="rounded-xl px-5 py-3 text-sm font-black transition"
              :class="activeWorkflowTab === 'summary' ? 'bg-blue-500 text-white shadow-lg shadow-blue-950/30' : 'text-slate-400 hover:text-slate-100'"
              @click="activeWorkflowTab = 'summary'"
            >
              AI 视频总结
            </button>
            <button
              type="button"
              class="rounded-xl px-5 py-3 text-sm font-black transition"
              :class="activeWorkflowTab === 'download' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-100'"
              @click="activeWorkflowTab = 'download'"
            >
              视频下载
            </button>
          </div>
        </div>

        <div v-if="activeWorkflowTab === 'summary'" class="grid gap-6">
          <article
            v-for="item in successfulResults"
            :key="`summary-${item.url}`"
            class="rounded-3xl border border-[#2a303a] bg-[#171a20] p-5 shadow-xl shadow-black/10"
          >
            <div class="flex flex-col gap-4 border-b border-[#2a303a] pb-5 sm:flex-row sm:items-center">
              <div class="h-24 w-full overflow-hidden rounded-2xl bg-[#11141a] sm:w-40">
                <img
                  v-if="item.video?.thumbnail"
                  :src="item.video.thumbnail"
                  :alt="item.video.title"
                  referrerpolicy="no-referrer"
                  loading="lazy"
                  class="h-full w-full object-cover"
                />
                <div v-else class="grid h-full place-items-center text-sm font-bold text-slate-600">无封面</div>
              </div>
              <div class="min-w-0 flex-1">
                <div class="mb-2 flex flex-wrap gap-2 text-xs font-bold">
                  <span class="rounded-full border border-blue-400/30 bg-blue-400/10 px-2.5 py-1 text-blue-200">{{ item.video?.extractor || "公开视频" }}</span>
                  <span class="rounded-full border border-slate-500/40 bg-slate-700/40 px-2.5 py-1 text-slate-300">{{ formatDuration(item.video?.duration) }}</span>
                </div>
                <h3 class="text-xl font-black leading-8 text-white">{{ item.video?.title }}</h3>
              </div>
            </div>

            <div class="space-y-5 pt-5">
              <!-- 全局进度条 -->
              <div v-if="isSummaryLoading(item.url)" class="rounded-2xl border border-[#2a303a] bg-[#1d2129] p-4">
                <div class="mb-3 flex items-center justify-between text-xs">
                  <span class="font-bold text-slate-300">
                    {{ (summaryForUrl(item.url)?.progress || 0) < 45 ? '阶段 1/2：字幕提取中...' : '阶段 2/2：AI 内容解析中...' }}
                  </span>
                  <span class="text-slate-500">{{ Math.round(summaryForUrl(item.url)?.progress || 0) }}%</span>
                </div>
                <div class="h-2 overflow-hidden rounded-full bg-[#11141a]">
                  <div class="h-full rounded-full bg-gradient-to-r from-blue-500 to-emerald-400 transition-all duration-500" :style="{ width: `${Math.max(4, summaryForUrl(item.url)?.progress || 0)}%` }"></div>
                </div>
              </div>

              <!-- Block 2：AI 配置说明 -->
              <section class="rounded-2xl border border-[#2a303a] bg-[#1d2129] p-4 shadow-sm">
                <h4 class="text-sm font-black text-slate-200">AI 分析说明</h4>
                <ul class="mt-3 space-y-2 text-xs leading-6 text-slate-400">
                  <li class="flex items-start gap-2">
                    <span class="mt-0.5 shrink-0 text-emerald-400 font-black">1</span>
                    <span>优先自动提取平台内嵌字幕进行 AI 分析</span>
                  </li>
                  <li class="flex items-start gap-2">
                    <span class="mt-0.5 shrink-0 text-amber-400 font-black">2</span>
                    <span>无字幕视频暂不支持 AI 分析，请尝试其他视频</span>
                  </li>
                </ul>
              </section>

              <!-- Block 3：核心操作区 -->
              <div class="space-y-3">
                <div class="flex items-center gap-2">
                  <span class="rounded-full bg-emerald-400/10 px-3 py-1 text-xs font-black text-emerald-200">核心操作</span>
                </div>
                <button
                  type="button"
                  :disabled="isSummaryLoading(item.url)"
                  class="w-full rounded-2xl bg-emerald-500 px-5 py-4 text-base font-black text-white shadow-lg shadow-emerald-950/30 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-slate-700 disabled:text-slate-400 disabled:shadow-none"
                  @click="createSummary(item)"
                >
                  {{ isSummaryLoading(item.url) ? '分析中...' : '生成 AI 总结' }}
                </button>
                <p v-if="summaryErrors[item.url] || summaryForUrl(item.url)?.error" class="rounded-2xl border border-red-400/20 bg-red-500/10 p-3 text-sm leading-6 text-red-200">
                  {{ summaryErrors[item.url] || summaryForUrl(item.url)?.error }}
                </p>
              </div>

              <!-- Block 4：结果展示面板 -->
              <section v-if="summaryForUrl(item.url)" class="rounded-2xl border border-[#2a303a] bg-[#1d2129] p-4 shadow-lg shadow-black/10">
                <!-- 元数据信息栏 -->
                <div v-if="summaryForUrl(item.url)?.result" class="mb-4 flex flex-wrap gap-2 text-xs font-bold">
                  <span class="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2.5 py-1 text-emerald-200">
                    📝 字幕 {{ (summaryForUrl(item.url)?.result?.transcript || []).length }} 段
                  </span>
                  <span class="rounded-full border border-blue-400/30 bg-blue-400/10 px-2.5 py-1 text-blue-200">
                    📂 {{ (summaryForUrl(item.url)?.result?.chapters || []).length }} 章节
                  </span>
                  <span class="rounded-full border border-amber-400/30 bg-amber-400/10 px-2.5 py-1 text-amber-200">
                    💡 {{ (summaryForUrl(item.url)?.result?.key_points || []).length }} 要点
                  </span>
                  <span v-if="summaryForUrl(item.url)?.result?.markdown" class="rounded-full border border-purple-400/30 bg-purple-400/10 px-2.5 py-1 text-purple-200">
                    📄 笔记 {{ summaryForUrl(item.url)?.result?.markdown.length }} 字
                  </span>
                  <span v-if="summaryForUrl(item.url)?.result?.mindmap_markdown" class="rounded-full border border-pink-400/30 bg-pink-400/10 px-2.5 py-1 text-pink-200">
                    🧠 导图已生成
                  </span>
                </div>
                <!-- Tab 切换栏 -->
                <div class="mb-5 flex gap-1 border-b border-[#2a303a] pb-0">
                  <button
                    v-for="tab in summaryTabs"
                    :key="tab.key"
                    type="button"
                    class="relative px-4 py-3 text-sm font-bold transition"
                    :class="activeTabForUrl(item.url) === tab.key
                      ? 'text-white'
                      : summaryForUrl(item.url)?.result ? 'text-slate-400 hover:text-slate-200' : 'text-slate-600 cursor-not-allowed'"
                    @click="handleTabClick(item.url, tab.key)"
                  >
                    {{ tab.label }}
                    <span
                      v-if="activeTabForUrl(item.url) === tab.key"
                      class="absolute bottom-0 left-1/2 h-0.5 w-4/5 -translate-x-1/2 rounded-full bg-blue-500"
                    ></span>
                  </button>
                </div>

                <!-- 总结摘要 -->
                <div v-if="activeTabForUrl(item.url) === 'summary'">
                  <template v-if="summaryForUrl(item.url)?.result">
                    <div class="summary-md prose-sm max-w-none text-slate-300 leading-7" v-html="renderMarkdown(summaryForUrl(item.url)?.result?.markdown || '')"></div>
                    <div class="mt-4 flex gap-2 border-t border-[#2a303a] pt-4">
                      <button type="button" class="rounded-full border border-[#2a303a] px-3 py-2 text-xs font-black text-slate-200 hover:border-blue-400 hover:text-blue-200" @click="copyMarkdownForUrl(item.url)">复制</button>
                      <button type="button" class="rounded-full bg-blue-500 px-3 py-2 text-xs font-black text-white hover:bg-blue-400" @click="downloadMarkdownForUrl(item.url)">导出 Markdown</button>
                    </div>
                  </template>
                  <div v-else-if="streamingText[summaryIdForUrl(item.url)]" class="max-h-96 overflow-auto rounded-2xl bg-[#11141a] p-3 text-sm leading-6 text-slate-300 font-mono whitespace-pre-wrap">
                    {{ streamingText[summaryIdForUrl(item.url)] }}<span class="inline-block w-2 h-4 bg-blue-400 animate-pulse ml-0.5 align-middle"></span>
                  </div>
                </div>

                <!-- 字幕文本 -->
                <div v-else-if="activeTabForUrl(item.url) === 'transcript'">
                  <div class="max-h-96 overflow-auto rounded-2xl bg-[#11141a] p-3">
                    <div
                      v-for="segment in summaryForUrl(item.url)?.result?.transcript || []"
                      :key="`${segment.start}-${segment.text}`"
                      class="grid gap-2 border-b border-[#2a303a] py-2 text-sm last:border-b-0 sm:grid-cols-[76px_1fr]"
                    >
                      <span class="font-mono text-xs font-bold text-blue-300">{{ formatTimestamp(segment.start) }}</span>
                      <span class="leading-6 text-slate-300">{{ segment.text }}</span>
                    </div>
                    <p v-if="!summaryForUrl(item.url)?.result?.transcript?.length" class="py-8 text-center text-sm text-slate-500">暂无字幕数据</p>
                  </div>
                  <div v-if="summaryForUrl(item.url)?.result?.transcript?.length" class="mt-4 flex gap-2 border-t border-[#2a303a] pt-4">
                    <button type="button" class="rounded-full border border-[#2a303a] px-3 py-2 text-xs font-black text-slate-200 hover:border-blue-400 hover:text-blue-200" @click="copyTranscriptForUrl(item.url)">复制</button>
                    <button type="button" class="rounded-full bg-blue-500 px-3 py-2 text-xs font-black text-white hover:bg-blue-400" @click="downloadTranscriptForUrl(item.url)">导出文本</button>
                  </div>
                </div>

                <!-- 思维导图 -->
                <div v-else-if="activeTabForUrl(item.url) === 'mindmap'">
                  <div v-if="mindmapMarkdowns[summaryIdForUrl(item.url)] || summaryForUrl(item.url)?.result?.mindmap_markdown" class="rounded-2xl bg-[#11141a] p-3 overflow-hidden">
                    <svg
                      :ref="(el: any) => setMarkmapRef(summaryIdForUrl(item.url), el)"
                      class="w-full"
                      style="min-height: 460px;"
                    ></svg>
                  </div>
                  <div v-else-if="summaryForUrl(item.url)?.result?.mindmap" class="rounded-2xl bg-[#11141a] p-3">
                    <div
                      v-for="node in flattenedMindmap(summaryForUrl(item.url)?.result?.mindmap)"
                      :key="`${node.depth}-${node.name}`"
                      class="mb-2 flex items-start gap-2 text-sm"
                      :style="{ paddingLeft: `${node.depth * 18}px` }"
                    >
                      <span class="mt-2 h-2 w-2 shrink-0 rounded-full" :class="node.depth === 0 ? 'bg-blue-400' : 'bg-emerald-400'" />
                      <span class="rounded-xl border border-[#2a303a] bg-[#1d2129] px-3 py-2 font-semibold text-slate-200">{{ node.name }}</span>
                    </div>
                  </div>
                  <p v-else class="py-8 text-center text-sm text-slate-500">暂无思维导图数据</p>
                  <div v-if="mindmapMarkdowns[summaryIdForUrl(item.url)] || summaryForUrl(item.url)?.result?.mindmap_markdown || summaryForUrl(item.url)?.result?.mindmap" class="mt-4 flex gap-2 border-t border-[#2a303a] pt-4">
                    <button type="button" class="rounded-full border border-[#2a303a] px-3 py-2 text-xs font-black text-slate-200 hover:border-blue-400 hover:text-blue-200" @click="copyMindmapForUrl(item.url)">复制</button>
                    <button type="button" class="rounded-full bg-blue-500 px-3 py-2 text-xs font-black text-white hover:bg-blue-400" @click="downloadMindmapForUrl(item.url)">导出 Markdown</button>
                  </div>
                </div>

                <!-- AI 问答 -->
                <div v-else class="flex flex-col" style="min-height: 440px;">
                  <!-- 对话气泡主区域（可滚动） -->
                  <div
                    :id="`chat-scroll-${summaryIdForUrl(item.url)}`"
                    class="flex-1 overflow-y-auto px-3 custom-scroll"
                    :class="{ 'flex items-center justify-center': !(questionAnswers[summaryIdForUrl(item.url)] || []).length && !streamingQA[summaryIdForUrl(item.url)] }"
                    style="max-height: 420px;"
                  >
                    <!-- 空状态引导 -->
                    <div v-if="!(questionAnswers[summaryIdForUrl(item.url)] || []).length && !streamingQA[summaryIdForUrl(item.url)]" class="text-center">
                      <div class="mb-2 text-3xl opacity-30">💬</div>
                      <p class="text-sm text-slate-500">输入问题，基于视频内容获取答案</p>
                    </div>

                    <div v-else class="space-y-6 py-2">
                      <!-- 对话气泡列表 -->
                      <template v-for="(qa, qaIdx) in questionAnswers[summaryIdForUrl(item.url)] || []" :key="qaIdx">
                        <!-- ── 用户消息 ── -->
                        <div class="flex justify-end group/bubble">
                          <div class="max-w-[78%] rounded-2xl rounded-br-md bg-blue-500/90 px-5 py-3.5 text-sm leading-7 text-white shadow-md shadow-blue-500/10 hover:shadow-lg hover:shadow-blue-500/20 hover:bg-blue-500 transition-all duration-200">
                            <p class="whitespace-pre-wrap break-words">{{ qa.question }}</p>
                          </div>
                        </div>

                        <!-- ── AI 回复 ── -->
                        <div
                          v-if="qa.answer || !streamingQA[summaryIdForUrl(item.url)]"
                          class="flex flex-col gap-2 group/bubble"
                        >
                          <div class="flex justify-start">
                            <div class="max-w-[82%] rounded-2xl rounded-bl-md bg-[#1a1d24] border border-[#2a303a]/80 px-5 py-3.5 text-sm leading-7 text-slate-200 shadow-sm hover:shadow-md hover:border-[#3a4450] transition-all duration-200">
                              <p class="whitespace-pre-wrap break-words">{{ qa.answer }}</p>
                              <!-- 操作按钮 -->
                              <div class="mt-3 flex items-center gap-1.5 justify-end opacity-70 group-hover/bubble:opacity-100 transition-opacity">
                                <button
                                  type="button"
                                  class="rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-300 hover:text-white hover:bg-white/10 active:bg-white/15 transition"
                                  @click="copyAnswerText(qa.answer)"
                                >复制</button>
                                <button
                                  type="button"
                                  class="rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-300 hover:text-white hover:bg-white/10 active:bg-white/15 transition"
                                  @click="regenerateAnswer(item.url, qa.question)"
                                >重新生成</button>
                                <button
                                  v-if="qa.references.length"
                                  type="button"
                                  class="rounded-lg px-2.5 py-1.5 text-xs font-medium transition"
                                  :class="expandedRefs[`${summaryIdForUrl(item.url)}_${qaIdx}`] ? 'text-blue-400 bg-blue-400/15' : 'text-slate-300 hover:text-white hover:bg-white/10'"
                                  @click="expandedRefs[`${summaryIdForUrl(item.url)}_${qaIdx}`] = !expandedRefs[`${summaryIdForUrl(item.url)}_${qaIdx}`]"
                                >
                                  参考 {{ qa.references.length }}
                                </button>
                              </div>
                            </div>
                          </div>
                          <!-- 参考素材折叠面板 -->
                          <div
                            v-if="expandedRefs[`${summaryIdForUrl(item.url)}_${qaIdx}`] && qa.references.length"
                            class="ml-1 rounded-2xl border border-[#2a303a]/60 bg-[#13161c] px-4 py-3 shadow-inner"
                          >
                            <p class="text-xs font-bold text-slate-500 mb-2.5 uppercase tracking-wide">参考素材</p>
                            <div class="space-y-2 max-h-32 overflow-y-auto custom-scroll">
                              <p
                                v-for="ref in qa.references"
                                :key="`${ref.start}-${ref.text}`"
                                class="text-xs leading-5 text-slate-400"
                              >
                                <span class="inline-block font-mono font-bold text-blue-400 min-w-[40px]">{{ formatTimestamp(ref.start) }}</span>
                                <span class="text-slate-500">·</span>
                                <span>{{ ref.text }}</span>
                              </p>
                            </div>
                          </div>
                        </div>
                      </template>

                      <!-- 流式生成中的 AI 气泡 -->
                      <div v-if="streamingQA[summaryIdForUrl(item.url)]" class="flex justify-start">
                        <div class="max-w-[82%] rounded-2xl rounded-bl-md bg-[#1a1d24] border border-blue-400/40 px-5 py-3.5 text-sm leading-7 text-slate-200 shadow-md shadow-blue-400/5">
                          <p class="whitespace-pre-wrap break-words">
                            {{ streamingQA[summaryIdForUrl(item.url)] }}
                            <span class="typing-cursor"></span>
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>

                  <!-- 底部固定输入栏 -->
                  <div class="flex items-center gap-3 pt-3.5 mt-2 border-t border-[#2a303a]/80 px-1">
                    <input
                      v-model="questionInputs[summaryIdForUrl(item.url)]"
                      type="text"
                      class="min-w-0 flex-1 rounded-xl border border-[#2a303a] bg-[#11141a] px-4 py-3 text-sm text-white outline-none placeholder:text-slate-600 focus:border-blue-400/70 focus:ring-2 focus:ring-blue-500/10 transition disabled:opacity-40 disabled:cursor-not-allowed"
                      placeholder="针对这个视频提问..."
                      :disabled="!summaryForUrl(item.url)?.result"
                      @keyup.enter="askSummaryForUrl(item.url)"
                    />
                    <button
                      type="button"
                      class="shrink-0 rounded-xl bg-blue-500 px-7 py-3 text-sm font-bold text-white hover:bg-blue-400 active:bg-blue-600 disabled:bg-slate-700 disabled:text-slate-500 disabled:cursor-not-allowed transition shadow-sm shadow-blue-500/20"
                      :disabled="questionLoading[summaryIdForUrl(item.url)] || !summaryForUrl(item.url)?.result"
                      @click="askSummaryForUrl(item.url)"
                    >
                      {{ questionLoading[summaryIdForUrl(item.url)] ? "思考中" : "提问" }}
                    </button>
                  </div>
                </div>
              </section>
            </div>
          </article>
        </div>

        <div v-else class="grid gap-5 lg:grid-cols-2">
          <article
            v-for="item in successfulResults"
            :key="`download-${item.url}`"
            class="rounded-3xl border border-[#2a303a] bg-[#171a20] p-5 shadow-xl shadow-black/10"
          >
            <div class="flex flex-col gap-4 border-b border-[#2a303a] pb-5 sm:flex-row sm:items-center">
              <div class="h-20 w-full overflow-hidden rounded-2xl bg-[#11141a] sm:w-32">
                <img
                  v-if="item.video?.thumbnail"
                  :src="item.video.thumbnail"
                  :alt="item.video.title"
                  referrerpolicy="no-referrer"
                  loading="lazy"
                  class="h-full w-full object-cover"
                />
                <div v-else class="grid h-full place-items-center text-xs font-bold text-slate-600">无封面</div>
              </div>
              <div class="min-w-0">
                <div class="mb-2 flex flex-wrap gap-2 text-xs font-bold">
                  <span class="rounded-full border border-blue-400/30 bg-blue-400/10 px-2.5 py-1 text-blue-200">{{ item.video?.extractor || "公开视频" }}</span>
                  <span class="rounded-full border border-slate-500/40 bg-slate-700/40 px-2.5 py-1 text-slate-300">{{ formatDuration(item.video?.duration) }}</span>
                </div>
                <h3 class="line-clamp-2 text-lg font-black leading-7 text-white">{{ item.video?.title }}</h3>
              </div>
            </div>

            <div class="space-y-5 pt-5">
              <label class="block text-sm font-bold text-slate-300">
                下载格式
                <select
                  v-model="selectedFormats[item.url]"
                  class="mt-2 w-full rounded-2xl border border-[#2a303a] bg-[#11141a] px-3 py-3 text-sm text-white outline-none focus:border-blue-400 focus:ring-4 focus:ring-blue-500/10"
                >
                  <option v-for="format in item.video?.formats" :key="format.format_id" :value="format.format_id">
                    {{ displayFormatLabel(format) }}
                  </option>
                </select>
              </label>
              <div class="grid gap-3 sm:grid-cols-2">
                <div class="group relative">
                  <button
                    type="button"
                    class="w-full rounded-full border border-blue-400/40 px-4 py-3 text-sm font-black text-blue-200 hover:bg-blue-400/10"
                    @click="directDownload(item)"
                  >
                    直链下载
                  </button>
                  <div class="pointer-events-none absolute bottom-full left-0 z-10 mb-2 hidden w-72 rounded-2xl border border-[#2a303a] bg-[#11141a] p-3 text-xs leading-5 text-slate-300 shadow-xl group-hover:block">
                    优先跳转平台直链，速度快，不占用服务器存储。适合直链未过期的视频。
                  </div>
                </div>
                <div class="group relative">
                  <button
                    type="button"
                    class="w-full rounded-full bg-slate-700 px-4 py-3 text-sm font-black text-white hover:bg-slate-600"
                    @click="createJob(item)"
                  >
                    服务端下载
                  </button>
                  <div class="pointer-events-none absolute bottom-full left-0 z-10 mb-2 hidden w-72 rounded-2xl border border-[#2a303a] bg-[#11141a] p-3 text-xs leading-5 text-slate-300 shadow-xl group-hover:block">
                    由服务器代为下载后再提供文件，适合直链失效、防盗链或浏览器无法直接下载的情况。
                  </div>
                </div>
              </div>
              <p v-if="directErrors[item.url]" class="rounded-2xl border border-amber-300/20 bg-amber-300/10 p-3 text-xs leading-5 text-amber-100">
                {{ directErrors[item.url] }}
              </p>
            </div>
          </article>
        </div>

        <section v-if="activeWorkflowTab === 'download' && jobs.length" class="mt-6 rounded-3xl border border-[#2a303a] bg-[#171a20] p-5">
          <div class="mb-5">
            <p class="text-sm font-bold text-blue-300">任务队列</p>
            <h3 class="mt-1 text-xl font-black text-white">服务端下载进度</h3>
          </div>
          <div class="grid gap-4">
            <article v-for="job in jobs" :key="job.job_id" class="rounded-2xl border border-[#2a303a] bg-[#1d2129] p-4">
              <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div class="min-w-0">
                  <p class="truncate text-sm font-bold text-white">{{ job.url }}</p>
                  <p class="mt-1 text-xs text-slate-400">格式：{{ job.format_id }} · 速度：{{ formatSpeed(job.speed) }}</p>
                </div>
                <span class="w-fit rounded-full px-3 py-1 text-xs font-black" :class="{
                  'bg-blue-400/10 text-blue-200': job.status === 'queued' || job.status === 'running',
                  'bg-emerald-400/10 text-emerald-200': job.status === 'success',
                  'bg-red-400/10 text-red-200': job.status === 'failed'
                }">
                  {{ job.status }}
                </span>
              </div>
              <div class="mt-4 h-3 overflow-hidden rounded-full bg-[#11141a]">
                <div class="h-full rounded-full bg-blue-500 transition-all" :style="{ width: `${Math.max(2, job.progress || 0)}%` }" />
              </div>
              <div class="mt-3 flex flex-col gap-2 text-xs text-slate-400 sm:flex-row sm:items-center sm:justify-between">
                <span>{{ Math.round(job.progress || 0) }}% · {{ formatBytes(job.downloaded_bytes) }} / {{ formatBytes(job.total_bytes) }}</span>
                <span v-if="job.error" class="text-red-300">{{ job.error }}</span>
              </div>
              <div v-if="job.files.length" class="mt-4 flex flex-wrap gap-2">
                <button
                  v-for="file in job.files"
                  :key="file.id"
                  type="button"
                  class="rounded-full bg-blue-500 px-4 py-2 text-sm font-black text-white hover:bg-blue-400"
                  @click="downloadFile(file.download_url, file.filename)"
                >
                  下载 {{ file.filename }} · {{ formatBytes(file.size) }}
                </button>
              </div>
            </article>
          </div>
        </section>

        <div v-if="failedResults.length" class="mt-6 rounded-3xl border border-red-400/20 bg-red-500/10 p-5">
          <h3 class="font-black text-red-200">解析失败的链接</h3>
          <ul class="mt-3 space-y-2 text-sm text-red-100">
            <li v-for="item in failedResults" :key="item.url">{{ item.url }}：{{ item.error }}</li>
          </ul>
        </div>
      </section>

      <section id="platforms" class="border-y border-[#2a303a] bg-[#11141a]">
        <div class="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
          <div class="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p class="text-sm font-bold text-blue-300">平台展示</p>
              <h2 class="mt-1 text-2xl font-black text-white sm:text-3xl">常见公开视频平台</h2>
            </div>
            <p class="max-w-xl text-sm leading-6 text-slate-400">实际可用性以 yt-dlp 当前支持情况和平台公开访问策略为准。</p>
          </div>
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
            <div v-for="platform in platforms" :key="platform" class="rounded-2xl border border-[#2a303a] bg-[#171a20] px-4 py-5 text-center text-sm font-black text-slate-200">
              {{ platform }}
            </div>
          </div>
        </div>
      </section>

      <section id="notice" class="mx-auto max-w-7xl px-4 py-10 sm:px-6 lg:px-8">
        <div class="rounded-3xl border border-amber-300/20 bg-amber-300/10 p-6 text-sm leading-7 text-amber-100">
          <strong class="text-amber-200">风险提示：</strong>
          请仅下载和分析你有权使用的公开视频内容，尊重版权和平台规则。本项目不提供 DRM 绕过、验证码绕过、账号 cookies 上传或反风控能力。
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.toast-fade-enter-active,
.toast-fade-leave-active {
  transition: all 0.3s ease;
}
.toast-fade-enter-from,
.toast-fade-leave-to {
  opacity: 0;
  transform: translate(-50%, -12px);
}

.typing-cursor {
  display: inline-block;
  width: 8px;
  height: 16px;
  background-color: #60a5fa;
  vertical-align: middle;
  margin-left: 2px;
  border-radius: 1px;
  animation: blink 0.8s step-end infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.custom-scroll::-webkit-scrollbar {
  width: 4px;
}
.custom-scroll::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scroll::-webkit-scrollbar-thumb {
  background: #3a4450;
  border-radius: 4px;
}
.custom-scroll::-webkit-scrollbar-thumb:hover {
  background: #4a5568;
}
.custom-scroll {
  scrollbar-width: thin;
  scrollbar-color: #3a4450 transparent;
}
</style>
