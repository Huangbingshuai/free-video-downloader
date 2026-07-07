<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from "vue";

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

const sampleUrls = `https://www.youtube.com/watch?v=dQw4w9WgXcQ`;
const urlInput = ref("");
const analyzing = ref(false);
const analyzeError = ref("");
const results = ref<AnalyzeItem[]>([]);
const selectedFormats = reactive<Record<string, string>>({});
const directErrors = reactive<Record<string, string>>({});
const jobs = ref<JobStatus[]>([]);
const pollers = new Map<string, number>();

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
  directErrors[item.url] = "如果浏览器没有开始下载，说明平台直链可能已过期，请改用服务端下载。";
  window.open(directUrl, "_blank", "noopener,noreferrer");
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

onBeforeUnmount(() => {
  for (const timer of pollers.values()) {
    window.clearInterval(timer);
  }
});

const successfulResults = computed(() => results.value.filter((item) => item.ok && item.video));
const failedResults = computed(() => results.value.filter((item) => !item.ok));

const platforms = ["抖音", "爱奇艺", "TikTok", "YouTube", "Bilibili", "X", "Instagram", "Vimeo", "更多站点"];
const vipFeatures = ["批量队列增强", "字幕翻译", "AI 视频总结", "历史记录云同步"];
</script>

<template>
  <div class="min-h-screen">
    <header class="sticky top-0 z-20 border-b border-slate-200/80 bg-white/90 backdrop-blur">
      <nav class="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6 lg:px-8">
        <a href="#" class="flex items-center gap-3">
          <span class="grid h-9 w-9 place-items-center rounded-xl bg-blue-600 text-sm font-black text-white">VD</span>
          <span class="text-base font-black text-slate-950">万能视频下载助手</span>
        </a>
        <div class="hidden items-center gap-8 text-sm font-medium text-slate-600 md:flex">
          <a href="#tool" class="hover:text-blue-600">解析下载</a>
          <a href="#platforms" class="hover:text-blue-600">平台能力</a>
          <a href="#vip" class="hover:text-blue-600">VIP 增强</a>
          <a href="#notice" class="hover:text-blue-600">风险提示</a>
        </div>
        <a href="#tool" class="rounded-full bg-slate-950 px-4 py-2 text-sm font-bold text-white shadow-sm hover:bg-blue-600">
          立即体验
        </a>
      </nav>
    </header>

    <main>
      <section id="tool" class="hero-grid border-b border-slate-100">
        <div class="mx-auto max-w-7xl px-4 py-12 sm:px-6 sm:py-16 lg:px-8">
          <div class="mx-auto max-w-4xl text-center">
            <p class="mb-4 text-sm font-bold text-blue-600">基于开源 yt-dlp 内核，公开链接优先直链下载</p>
            <h1 class="text-4xl font-black tracking-normal text-slate-950 sm:text-5xl lg:text-6xl">
              万能视频下载助手
            </h1>
            <p class="mx-auto mt-5 max-w-2xl text-base leading-8 text-slate-600 sm:text-lg">
              批量解析公开视频链接，选择清晰度后即可下载。手机和电脑都能使用，直链优先，服务端下载兜底。
            </p>
          </div>

          <div class="mx-auto mt-9 max-w-4xl rounded-[28px] border border-blue-100 bg-white p-4 shadow-xl shadow-blue-100/70 sm:p-6">
            <label class="text-sm font-bold text-slate-800" for="urls">粘贴公开视频链接</label>
            <textarea
              id="urls"
              v-model="urlInput"
              rows="6"
              class="mt-3 w-full resize-y rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm leading-7 text-slate-900 outline-none transition focus:border-blue-500 focus:bg-white focus:ring-4 focus:ring-blue-100"
              placeholder="每行一个链接，支持直接粘贴带文字的分享内容，例如：【视频标题】https://www.bilibili.com/video/BVxxx"
            />
            <div class="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div class="flex flex-wrap gap-2 text-xs font-semibold text-slate-600">
                <span class="rounded-full bg-blue-50 px-3 py-1.5 text-blue-700">批量解析</span>
                <span class="rounded-full bg-emerald-50 px-3 py-1.5 text-emerald-700">高清格式</span>
                <span class="rounded-full bg-slate-100 px-3 py-1.5 text-slate-700">移动端友好</span>
              </div>
              <div class="flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  class="rounded-full border border-slate-200 px-5 py-3 text-sm font-bold text-slate-700 hover:border-blue-200 hover:text-blue-600"
                  @click="loadSample"
                >
                  填入测试链接
                </button>
                <button
                  type="button"
                  :disabled="!canAnalyze"
                  class="rounded-full bg-blue-600 px-6 py-3 text-sm font-black text-white shadow-lg shadow-blue-200 transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none"
                  @click="analyze"
                >
                  {{ analyzing ? "解析中..." : `立即解析 ${parsedUrls.length || ""}` }}
                </button>
              </div>
            </div>
            <p v-if="analyzeError" class="mt-4 rounded-2xl bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
              {{ analyzeError }}
            </p>
          </div>
        </div>
      </section>

      <section v-if="results.length" class="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
        <div class="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p class="text-sm font-bold text-blue-600">解析结果</p>
            <h2 class="mt-1 text-2xl font-black text-slate-950 sm:text-3xl">选择格式并开始下载</h2>
          </div>
          <p class="text-sm text-slate-500">优先直链下载，失败后使用服务端下载。</p>
        </div>

        <div class="grid gap-5 lg:grid-cols-2">
          <article
            v-for="item in successfulResults"
            :key="item.url"
            class="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm"
          >
            <div class="grid gap-0 sm:grid-cols-[220px_1fr]">
              <div class="aspect-video bg-slate-100 sm:aspect-auto">
                <img
                  v-if="item.video?.thumbnail"
                  :src="item.video.thumbnail"
                  :alt="item.video.title"
                  referrerpolicy="no-referrer"
                  loading="lazy"
                  class="h-full w-full object-cover"
                />
                <div v-else class="grid h-full min-h-40 place-items-center text-sm font-bold text-slate-400">无封面</div>
              </div>
              <div class="flex min-w-0 flex-col gap-4 p-5">
                <div>
                  <div class="mb-2 flex flex-wrap gap-2 text-xs font-bold">
                    <span class="rounded-full bg-blue-50 px-2.5 py-1 text-blue-700">{{ item.video?.extractor || "公开视频" }}</span>
                    <span class="rounded-full bg-slate-100 px-2.5 py-1 text-slate-600">{{ formatDuration(item.video?.duration) }}</span>
                  </div>
                  <h3 class="line-clamp-2 text-lg font-black leading-7 text-slate-950">{{ item.video?.title }}</h3>
                </div>
                <label class="block text-sm font-bold text-slate-700">
                  下载格式
                  <select
                    v-model="selectedFormats[item.url]"
                    class="mt-2 w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                  >
                    <option v-for="format in item.video?.formats" :key="format.format_id" :value="format.format_id">
                      {{ format.label }}
                    </option>
                  </select>
                </label>
                <div class="grid gap-2 sm:grid-cols-2">
                  <button
                    type="button"
                    class="rounded-full border border-blue-200 px-4 py-3 text-sm font-black text-blue-700 hover:bg-blue-50"
                    @click="directDownload(item)"
                  >
                    直链下载
                  </button>
                  <button
                    type="button"
                    class="rounded-full bg-slate-950 px-4 py-3 text-sm font-black text-white hover:bg-blue-600"
                    @click="createJob(item)"
                  >
                    服务端下载
                  </button>
                </div>
                <p v-if="directErrors[item.url]" class="text-xs leading-5 text-amber-700">{{ directErrors[item.url] }}</p>
              </div>
            </div>
          </article>
        </div>

        <div v-if="failedResults.length" class="mt-6 rounded-3xl border border-red-100 bg-red-50 p-5">
          <h3 class="font-black text-red-800">解析失败的链接</h3>
          <ul class="mt-3 space-y-2 text-sm text-red-700">
            <li v-for="item in failedResults" :key="item.url">{{ item.url }}：{{ item.error }}</li>
          </ul>
        </div>
      </section>

      <section v-if="jobs.length" class="border-y border-slate-100 bg-slate-50">
        <div class="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
          <div class="mb-6">
            <p class="text-sm font-bold text-blue-600">任务队列</p>
            <h2 class="mt-1 text-2xl font-black text-slate-950 sm:text-3xl">服务端下载进度</h2>
          </div>
          <div class="grid gap-4">
            <article v-for="job in jobs" :key="job.job_id" class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div class="min-w-0">
                  <p class="truncate text-sm font-bold text-slate-900">{{ job.url }}</p>
                  <p class="mt-1 text-xs text-slate-500">格式：{{ job.format_id }} · 速度：{{ formatSpeed(job.speed) }}</p>
                </div>
                <span class="w-fit rounded-full px-3 py-1 text-xs font-black" :class="{
                  'bg-blue-50 text-blue-700': job.status === 'queued' || job.status === 'running',
                  'bg-emerald-50 text-emerald-700': job.status === 'success',
                  'bg-red-50 text-red-700': job.status === 'failed'
                }">
                  {{ job.status }}
                </span>
              </div>
              <div class="mt-4 h-3 overflow-hidden rounded-full bg-slate-100">
                <div class="h-full rounded-full bg-blue-600 transition-all" :style="{ width: `${Math.max(2, job.progress || 0)}%` }" />
              </div>
              <div class="mt-3 flex flex-col gap-2 text-xs text-slate-500 sm:flex-row sm:items-center sm:justify-between">
                <span>{{ Math.round(job.progress || 0) }}% · {{ formatBytes(job.downloaded_bytes) }} / {{ formatBytes(job.total_bytes) }}</span>
                <span v-if="job.error" class="text-red-600">{{ job.error }}</span>
              </div>
              <div v-if="job.files.length" class="mt-4 flex flex-wrap gap-2">
                <a
                  v-for="file in job.files"
                  :key="file.id"
                  :href="file.download_url"
                  class="rounded-full bg-blue-600 px-4 py-2 text-sm font-black text-white hover:bg-blue-700"
                >
                  下载 {{ file.filename }} · {{ formatBytes(file.size) }}
                </a>
              </div>
            </article>
          </div>
        </div>
      </section>

      <section id="vip" class="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
        <div class="grid gap-6 lg:grid-cols-[1fr_360px]">
          <div class="rounded-3xl border border-blue-100 bg-blue-600 p-8 text-white shadow-xl shadow-blue-100">
            <p class="text-sm font-black text-blue-100">VIP 增强能力预告</p>
            <h2 class="mt-3 text-3xl font-black">把下载工具升级成内容工作台</h2>
            <p class="mt-4 max-w-2xl leading-8 text-blue-50">
              首版先跑通核心下载链路，后续可接入字幕翻译、AI 总结、云端历史和批量额度，让高频用户有清晰的付费理由。
            </p>
          </div>
          <div class="grid gap-3">
            <div v-for="feature in vipFeatures" :key="feature" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <p class="font-black text-slate-950">{{ feature }}</p>
              <p class="mt-1 text-sm text-slate-500">当前为产品入口展示，真实能力将在后续阶段接入。</p>
            </div>
          </div>
        </div>
      </section>

      <section id="platforms" class="border-y border-slate-100 bg-slate-50">
        <div class="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
          <div class="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p class="text-sm font-bold text-blue-600">平台展示</p>
              <h2 class="mt-1 text-2xl font-black text-slate-950 sm:text-3xl">常见公开视频平台</h2>
            </div>
            <p class="max-w-xl text-sm leading-6 text-slate-500">实际可用性以 yt-dlp 当前支持情况和平台公开访问策略为准。</p>
          </div>
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
            <div v-for="platform in platforms" :key="platform" class="rounded-2xl border border-slate-200 bg-white px-4 py-5 text-center text-sm font-black text-slate-800 shadow-sm">
              {{ platform }}
            </div>
          </div>
        </div>
      </section>

      <section id="notice" class="mx-auto max-w-7xl px-4 py-10 sm:px-6 lg:px-8">
        <div class="rounded-3xl border border-amber-200 bg-amber-50 p-6 text-sm leading-7 text-amber-900">
          <strong>风险提示：</strong>
          请仅下载你有权保存的公开视频内容，尊重版权和平台规则。本项目不提供 DRM 绕过、验证码绕过、账号 cookies 上传或反风控能力。
        </div>
      </section>
    </main>
  </div>
</template>
