<script setup lang="ts">
import type { Component } from "vue";
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import {
  Bot,
  Brain,
  CheckCircle2,
  Clipboard,
  Cloud,
  Copy,
  CreditCard,
  Download,
  FileText,
  Globe2,
  HelpCircle,
  Link2,
  ListChecks,
  MessageCircle,
  Play,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  LogOut,
  User,
  Video,
  X,
  Zap,
} from "lucide-vue-next";
import { Transformer } from "markmap-lib";
import { Markmap } from "markmap-view";
import { marked } from "marked";

marked.setOptions({ breaks: true, gfm: true });

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

type AuthUser = {
  id: string;
  email: string;
  display_name?: string | null;
  avatar_url?: string | null;
  is_vip: boolean;
  vip_activated_at?: string | null;
  daily_ai_remaining: number;
};

type PaymentRecord = {
  id: string;
  status: string;
  amount_total?: number | null;
  currency?: string | null;
  stripe_checkout_session_id?: string | null;
  stripe_payment_intent_id?: string | null;
  stripe_refund_id?: string | null;
  refund_status?: string | null;
  refund_error?: string | null;
  refund_requested_at?: string | null;
  refunded_at?: string | null;
  created_at: string;
  updated_at: string;
};

type QuestionAnswer = {
  question: string;
  answer: string;
  references: Array<{ start?: number | null; text: string }>;
};

type DrawerTab = "platforms" | "download" | "compliance";
type ToastTone = "info" | "success" | "error";
type IconCard = {
  title: string;
  text: string;
  icon: Component;
  tone: string;
};

const urlInput = ref("");
const analyzing = ref(false);
const analyzeError = ref("");
const results = ref<AnalyzeItem[]>([]);
const selectedFormats = reactive<Record<string, string>>({});
const directErrors = reactive<Record<string, string>>({});
const jobs = ref<JobStatus[]>([]);
const pollers = new Map<string, number>();
const summaryLanguage = ref("zh");
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
const toastTone = ref<ToastTone>("info");
const showComplianceModal = ref(false);
const complianceAccepted = ref(localStorage.getItem("fvd_compliance_ok") === "1");
const complianceChecked = ref(false);
const infoDrawerOpen = ref(false);
const activeDrawerTab = ref<DrawerTab>("platforms");
const authUser = ref<AuthUser | null>(null);
const authChecking = ref(false);
const authModalOpen = ref(false);
const authMode = ref<"login" | "register">("login");
const authEmail = ref("");
const authPassword = ref("");
const authCode = ref("");
const authUseCode = ref(false);
const codeSending = ref(false);
const codeCountdown = ref(0);
const authError = ref("");
const authSubmitting = ref(false);
let codeTimer: number | undefined;
const billingLoading = ref(false);
const userMenuOpen = ref(false);
const profileModalOpen = ref(false);
const profileName = ref("");
const profileAvatarFile = ref<File | null>(null);
const profileAvatarPreview = ref("");
const profileSaving = ref(false);
const profileError = ref("");
const paymentHistory = ref<PaymentRecord[]>([]);
const paymentsLoading = ref(false);
const refundingPayments = reactive<Record<string, boolean>>({});
let toastTimer: number | undefined;

function showToast(msg: string, tone: ToastTone = "info") {
  toastMessage.value = msg;
  toastTone.value = tone;
  if (toastTimer) window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { toastMessage.value = ""; }, 2600);
}

function isSummaryLoading(url: string) {
  const job = summaryForUrl(url);
  return job && !job.result && job.status !== "failed";
}

function summaryStageLabel(url: string) {
  const job = summaryForUrl(url);
  if (!job) return "等待启动";
  if (job.status === "failed") return "生成失败";
  if (job.status === "success") return "总结完成";
  return (job.progress || 0) < 45 ? "字幕提取中" : "AI 内容解析中";
}

function handleTabClick(url: string, tab: "summary" | "transcript" | "mindmap" | "qa") {
  setSummaryTab(url, tab);
}

const urlPattern = /https?:\/\/[^\s，。；、"'<>]+/g;

const parsedUrls = computed(() =>
  Array.from(new Set((urlInput.value.match(urlPattern) || []).map((url) => url.replace(/[)\]}]+$/, "")))),
);

const rawUrlCount = computed(() => (urlInput.value.match(urlPattern) || []).length);
const duplicateUrlCount = computed(() => Math.max(0, rawUrlCount.value - parsedUrls.value.length));
const inputIssues = computed(() => collectInputIssues(urlInput.value));
const canAnalyze = computed(() => parsedUrls.value.length > 0 && !analyzing.value);
const isVip = computed(() => Boolean(authUser.value?.is_vip));
const toastClass = computed(() => {
  if (toastTone.value === "success") {
    return "border-emerald-400/40 bg-emerald-500/95 text-white shadow-emerald-500/20";
  }
  if (toastTone.value === "error") {
    return "border-rose-400/40 bg-rose-500/95 text-white shadow-rose-500/20";
  }
  return "border-slate-900/10 bg-slate-900/90 text-white shadow-slate-900/20";
});

const profileDisplayName = computed(() =>
  authUser.value?.display_name?.trim() || authUser.value?.email?.split("@")[0] || "用户",
);

const profileAvatarSrc = computed(() => profileAvatarPreview.value || authUser.value?.avatar_url || "");

async function loadAuth() {
  authChecking.value = true;
  try {
    const response = await fetch("/api/auth/me", { credentials: "include" });
    if (response.ok) {
      const payload = await response.json();
      authUser.value = payload.user || null;
    }
  } finally {
    authChecking.value = false;
  }
}

async function loadPaymentHistory() {
  if (!authUser.value) return;
  paymentsLoading.value = true;
  try {
    const response = await fetch("/api/billing/payments", { credentials: "include" });
    const payload = await response.json().catch(() => ({}));
    if (response.ok) paymentHistory.value = payload.payments || [];
  } finally {
    paymentsLoading.value = false;
  }
}

function openProfileModal() {
  if (!authUser.value) return;
  profileName.value = authUser.value.display_name || authUser.value.email.split("@")[0] || "";
  profileAvatarFile.value = null;
  profileAvatarPreview.value = "";
  profileError.value = "";
  profileModalOpen.value = true;
  userMenuOpen.value = false;
  void loadPaymentHistory();
}

function onAvatarFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] || null;
  if (profileAvatarPreview.value) {
    URL.revokeObjectURL(profileAvatarPreview.value);
    profileAvatarPreview.value = "";
  }
  profileAvatarFile.value = null;
  if (!file) return;
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
    profileError.value = "头像仅支持 JPG、PNG 或 WEBP";
    input.value = "";
    return;
  }
  if (file.size > 2 * 1024 * 1024) {
    profileError.value = "头像不能超过 2MB";
    input.value = "";
    return;
  }
  profileError.value = "";
  profileAvatarFile.value = file;
  profileAvatarPreview.value = URL.createObjectURL(file);
}

async function saveProfile() {
  profileSaving.value = true;
  profileError.value = "";
  try {
    const response = await fetch("/api/auth/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({
        display_name: profileName.value.trim(),
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "保存失败");
    authUser.value = payload.user;
    if (profileAvatarFile.value) {
      const formData = new FormData();
      formData.append("file", profileAvatarFile.value);
      const avatarResponse = await fetch("/api/auth/avatar", {
        method: "POST",
        credentials: "include",
        body: formData,
      });
      const avatarPayload = await avatarResponse.json().catch(() => ({}));
      if (!avatarResponse.ok) throw new Error(avatarPayload.detail || "头像上传失败");
      authUser.value = avatarPayload.user;
      profileAvatarFile.value = null;
      if (profileAvatarPreview.value) {
        URL.revokeObjectURL(profileAvatarPreview.value);
        profileAvatarPreview.value = "";
      }
    }
    profileModalOpen.value = false;
    showToast("个人资料已更新", "success");
  } catch (error) {
    profileError.value = error instanceof Error ? error.message : "保存失败";
    showToast(profileError.value, "error");
  } finally {
    profileSaving.value = false;
  }
}

function paymentStatusLabel(status: string) {
  const map: Record<string, string> = {
    paid: "支付成功",
    pending: "待支付",
    failed: "支付失败",
    expired: "已过期",
    refund_pending: "退款处理中",
    refunded: "已退款",
  };
  return map[status] || status;
}

function paymentStatusClass(status: string) {
  if (status === "paid") return "bg-emerald-50 text-emerald-700 border-emerald-200";
  if (status === "refunded") return "bg-slate-100 text-slate-600 border-slate-200";
  if (status === "refund_pending") return "bg-cyan-50 text-cyan-700 border-cyan-200";
  if (status === "failed" || status === "expired") return "bg-rose-50 text-rose-700 border-rose-200";
  return "bg-amber-50 text-amber-700 border-amber-200";
}

function formatPaymentAmount(payment: PaymentRecord) {
  if (payment.amount_total === null || payment.amount_total === undefined) return "金额待确认";
  const currency = (payment.currency || "cny").toUpperCase();
  const amount = (payment.amount_total / 100).toFixed(2);
  return currency === "CNY" ? `¥${amount}` : `${amount} ${currency}`;
}

function formatPaymentTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function shortPaymentId(payment: PaymentRecord) {
  const id = payment.stripe_checkout_session_id || payment.stripe_payment_intent_id || payment.id;
  return id.length > 18 ? `${id.slice(0, 10)}...${id.slice(-6)}` : id;
}

function canRefundPayment(payment: PaymentRecord) {
  return payment.status === "paid" && Boolean(payment.stripe_payment_intent_id);
}

async function requestRefund(payment: PaymentRecord) {
  if (!canRefundPayment(payment) || refundingPayments[payment.id]) return;
  const confirmed = window.confirm("确定申请这笔 VIP 订单退款吗？退款提交后会立即关闭 VIP AI 功能。");
  if (!confirmed) return;
  refundingPayments[payment.id] = true;
  try {
    const response = await fetch(`/api/billing/payments/${payment.id}/refund`, {
      method: "POST",
      credentials: "include",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "退款申请失败");
    const updated = payload.payment as PaymentRecord;
    paymentHistory.value = paymentHistory.value.map((item) => item.id === updated.id ? updated : item);
    authUser.value = payload.user || authUser.value;
    showToast(updated.status === "refunded" ? "退款成功，VIP 已关闭" : "退款已提交，VIP 已关闭", "success");
  } catch (error) {
    showToast(error instanceof Error ? error.message : "退款申请失败", "error");
  } finally {
    refundingPayments[payment.id] = false;
  }
}

function openAuthModal(mode: "login" | "register" = "login") {
  authMode.value = mode;
  authError.value = "";
  authCode.value = "";
  authUseCode.value = false;
  codeSending.value = false;
  codeCountdown.value = 0;
  if (codeTimer) { clearInterval(codeTimer); codeTimer = undefined; }
  authModalOpen.value = true;
}

async function sendAuthCode() {
  const email = authEmail.value.trim();
  if (!email) return;
  codeSending.value = true;
  authError.value = "";
  try {
    const response = await fetch("/api/auth/send-code", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ email, purpose: authMode.value }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "发送失败");
    codeCountdown.value = 60;
    codeTimer = window.setInterval(() => {
      codeCountdown.value--;
      if (codeCountdown.value <= 0 && codeTimer) { clearInterval(codeTimer); codeTimer = undefined; }
    }, 1000);
    showToast("验证码已发送", "success");
  } catch (error) {
    authError.value = error instanceof Error ? error.message : "发送失败";
  } finally {
    codeSending.value = false;
  }
}

async function submitAuth() {
  const email = authEmail.value.trim();
  if (!email) return;
  if (authMode.value === "register") {
    if (!authPassword.value || !authCode.value) return;
  } else if (authUseCode.value) {
    if (!authCode.value) return;
  } else {
    if (!authPassword.value) return;
  }
  authSubmitting.value = true;
  authError.value = "";
  try {
    const body: Record<string, string> = { email };
    if (authMode.value === "register") {
      body.password = authPassword.value;
      body.code = authCode.value;
    } else if (authUseCode.value) {
      body.code = authCode.value;
    } else {
      body.password = authPassword.value;
    }
    const response = await fetch(`/api/auth/${authMode.value}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "操作失败");
    authUser.value = payload.user;
    authModalOpen.value = false;
    authPassword.value = "";
    authCode.value = "";
    showToast(authMode.value === "register" ? "注册成功" : "登录成功", "success");
  } catch (error) {
    authError.value = error instanceof Error ? error.message : "操作失败";
  } finally {
    authSubmitting.value = false;
  }
}

async function logout() {
  await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
  authUser.value = null;
  userMenuOpen.value = false;
  profileModalOpen.value = false;
  resetSummaryState();
  showToast("已退出登录");
}

function scrollToPricing() {
  document.getElementById("pricing")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function promptVipForAi() {
  if (!authUser.value) {
    openAuthModal("login");
    showToast("请先登录");
    return;
  }
  scrollToPricing();
  showToast("今日免费 AI 次数已用完，请开通 VIP");
}

async function startVipCheckout() {
  if (!authUser.value) {
    openAuthModal("login");
    return;
  }
  if (authUser.value.is_vip) {
    showToast("你已经是 VIP");
    return;
  }
  billingLoading.value = true;
  try {
    const response = await fetch("/api/billing/create-checkout-session", {
      method: "POST",
      credentials: "include",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "创建支付会话失败");
    if (payload.is_vip) {
      await loadAuth();
      await loadPaymentHistory();
      showToast("VIP 已生效", "success");
      return;
    }
    if (payload.checkout_url) {
      window.location.href = payload.checkout_url;
      return;
    }
    showToast("支付会话已创建，请稍后重试");
  } catch (error) {
    showToast(error instanceof Error ? error.message : "创建支付会话失败", "error");
  } finally {
    billingLoading.value = false;
  }
}

async function handleCheckoutReturn() {
  const params = new URLSearchParams(window.location.search);
  const checkout = params.get("checkout");
  if (!checkout) return;
  if (checkout === "success") {
    const sessionId = params.get("session_id");
    if (sessionId) {
      try {
        const response = await fetch("/api/billing/confirm-checkout-session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ session_id: sessionId }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || "支付确认失败");
        if (payload.is_vip) {
          await loadAuth();
          await loadPaymentHistory();
          showToast("支付成功，VIP 已开通", "success");
        } else {
          await loadAuth();
          showToast("支付已完成，正在等待 Stripe 最终确认");
        }
      } catch (error) {
        await loadAuth();
        showToast(error instanceof Error ? error.message : "支付确认失败，请稍后刷新", "error");
      }
    } else {
      await loadAuth();
      if (authUser.value?.is_vip) {
        await loadPaymentHistory();
        showToast("VIP 已开通", "success");
      } else {
        showToast("支付已完成，正在等待 Stripe 回调确认");
      }
    }
  } else if (checkout === "cancel") {
    await loadAuth();
    showToast("已取消支付");
  }
  window.history.replaceState({}, "", `${window.location.pathname}${window.location.hash || ""}`);
}

function collectInputIssues(text: string) {
  const tokens = text.split(/\s+/).map((token) => token.trim()).filter(Boolean);
  const issues: string[] = [];
  for (const token of tokens) {
    const cleaned = token.replace(/[，。；、,.;)\]}]+$/, "");
    if (/^[a-z]+:\/\//i.test(cleaned) && !/^https?:\/\//i.test(cleaned)) {
      issues.push(`暂不支持的链接协议：${cleaned}`);
      continue;
    }
    if (/^https?:\/\//i.test(cleaned)) {
      try {
        const url = new URL(cleaned);
        if (!url.hostname.includes(".")) {
          issues.push(`链接域名不完整：${cleaned}`);
        }
      } catch {
        issues.push(`链接格式有误：${cleaned}`);
      }
    }
  }
  return Array.from(new Set(issues)).slice(0, 4);
}

function requestAnalyze() {
  if (!complianceAccepted.value) {
    showComplianceModal.value = true;
    return;
  }
  void analyze();
}

function confirmCompliance() {
  if (!complianceChecked.value) return;
  complianceAccepted.value = true;
  localStorage.setItem("fvd_compliance_ok", "1");
  showComplianceModal.value = false;
  void analyze();
}

function openInfoDrawer(tab: DrawerTab = "platforms") {
  activeDrawerTab.value = tab;
  infoDrawerOpen.value = true;
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

function formatSrtTimestamp(seconds?: number | null): string {
  if (seconds === null || seconds === undefined) return "00:00:00,000";
  const safe = Math.max(0, seconds);
  const h = Math.floor(safe / 3600);
  const m = Math.floor((safe % 3600) / 60);
  const s = Math.floor(safe % 60);
  const ms = Math.round((safe % 1) * 1000);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")},${String(ms).padStart(3, "0")}`;
}

function transcriptToSrt(segments: TranscriptSegment[]): string {
  return segments.map((seg, i) => {
    const start = formatSrtTimestamp(seg.start);
    const end = formatSrtTimestamp(seg.end ?? seg.start + 5);
    return `${i + 1}\n${start} --> ${end}\n${seg.text}`;
  }).join("\n\n");
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
  if (!complianceAccepted.value) {
    showComplianceModal.value = true;
    return;
  }
  analyzing.value = true;
  analyzeError.value = "";
  for (const key of Object.keys(directErrors)) {
    delete directErrors[key];
  }
  resetSummaryState();
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
    void autoCreateSummaries(results.value);
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

function jobsForUrl(url: string) {
  return jobs.value.filter((job) => job.url === url);
}

function resetSummaryState() {
  for (const controller of summaryStreams.values()) {
    controller.abort();
  }
  summaryStreams.clear();
  for (const timer of summaryPollers.values()) {
    window.clearInterval(timer);
  }
  summaryPollers.clear();
  summaryJobs.value = [];
  clearRecord(summaryErrors);
  clearRecord(activeSummaryTabs);
  clearRecord(questionInputs);
  clearRecord(questionLoading);
  clearRecord(questionAnswers);
  clearRecord(activeAnswerIndex);
  clearRecord(expandedRefs);
  clearRecord(lastQuestionText);
  clearRecord(streamingText);
  clearRecord(streamingQA);
  clearRecord(earlyTranscripts);
  clearRecord(earlyTitles);
  clearRecord(mindmapMarkdowns);
  clearRecord(mindmapFullscreen);
  for (const [summaryId, timer] of Object.entries(mindmapRenderTimers)) {
    clearTimeout(timer);
    delete mindmapRenderTimers[summaryId];
  }
  for (const summaryId of Object.keys(markmapInstances)) {
    delete markmapInstances[summaryId];
  }
}

function clearRecord(record: Record<string, unknown>) {
  for (const key of Object.keys(record)) {
    delete record[key];
  }
}

function renderMarkdown(md: string): string {
  if (!md) return "";
  return marked.parse(md) as string;
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

function aiGateState(url: string): "content" | "login" | "trial" | "upgrade" | "loading" {
  if (summaryForUrl(url)) return "content";
  if (!authUser.value) return "login";
  if (!isVip.value && (authUser.value?.daily_ai_remaining ?? 0) > 0) return "trial";
  if (!isVip.value) return "upgrade";
  return "loading";
}

async function autoCreateSummaries(items: AnalyzeItem[]) {
  if (!authUser.value) return;
  const successfulItems = items.filter((item) => item.ok && item.video);
  await Promise.allSettled(successfulItems.map((item) => createSummary(item)));
}

async function createSummary(item: AnalyzeItem, force = false) {
  if (!item.video) return;
  if (!authUser.value) {
    openAuthModal("login");
    return;
  }
  const existing = summaryForUrl(item.url);
  if (existing && !force) return;
  if (existing && force) {
    cleanupSummaryArtifacts(existing.summary_id);
  }
  summaryErrors[item.url] = "";
  const response = await fetch("/api/summaries", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({
      url: item.url,
      language: summaryLanguage.value.trim() || "zh",
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    summaryErrors[item.url] = payload.detail || "AI 分析任务创建失败";
    if (response.status === 403) await loadAuth();
    return;
  }
  if (!authUser.value.is_vip) await loadAuth();
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

function cleanupSummaryArtifacts(summaryId: string) {
  const controller = summaryStreams.get(summaryId);
  if (controller) {
    controller.abort();
    summaryStreams.delete(summaryId);
  }
  delete activeSummaryTabs[summaryId];
  delete questionInputs[summaryId];
  delete questionLoading[summaryId];
  delete questionAnswers[summaryId];
  delete activeAnswerIndex[summaryId];
  delete lastQuestionText[summaryId];
  delete streamingText[summaryId];
  delete streamingQA[summaryId];
  delete earlyTranscripts[summaryId];
  delete earlyTitles[summaryId];
  delete mindmapMarkdowns[summaryId];
  delete mindmapFullscreen[summaryId];
  if (mindmapRenderTimers[summaryId]) {
    clearTimeout(mindmapRenderTimers[summaryId]);
    delete mindmapRenderTimers[summaryId];
  }
  delete markmapInstances[summaryId];
  for (const key of Object.keys(expandedRefs)) {
    if (key.startsWith(`${summaryId}_`)) delete expandedRefs[key];
  }
}

function startSummaryStream(summaryId: string) {
  if (summaryStreams.has(summaryId)) return;
  const controller = new AbortController();
  summaryStreams.set(summaryId, controller);

  fetch(`/api/summaries/${summaryId}/stream`, {
    signal: controller.signal,
    credentials: "include",
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
  } else if (event.type === "transcript") {
    // 字幕提前到达，前端立即可查看，不受流式状态限制
    earlyTranscripts[summaryId] = (event.segments || []).map((s: any) => ({
      start: s.start as number,
      end: s.end as number | null,
      text: s.text as string,
    }));
    if (event.title) earlyTitles[summaryId] = event.title;
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
      credentials: "include",
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

function proxyThumbnail(url: string | null | undefined): string {
  if (!url) return "";
  return `/api/thumbnail?url=${encodeURIComponent(url)}`;
}

function transcriptForUrl(url: string): TranscriptSegment[] {
  const sid = summaryIdForUrl(url);
  return earlyTranscripts[sid] || summaryForUrl(url)?.result?.transcript || [];
}

function copyTranscriptForUrl(url: string) {
  const transcript = transcriptForUrl(url);
  if (!transcript?.length) return;
  const text = transcript.map((seg) => `[${formatTimestamp(seg.start)}] ${seg.text}`).join("\n");
  navigator.clipboard.writeText(text).then(() => showToast("已复制字幕文本"));
}

function downloadTranscriptSrt(url: string) {
  const transcript = transcriptForUrl(url);
  if (!transcript?.length) return;
  const srt = transcriptToSrt(transcript);
  const title = earlyTitles[summaryIdForUrl(url)] || summaryForUrl(url)?.result?.title || "字幕";
  const filename = title.replace(/[/\\?%*:|"<>]/g, "_") + "_字幕.srt";
  triggerDownloadBlob(new Blob([srt], { type: "text/plain; charset=utf-8" }), filename);
}

function downloadTranscriptTxt(url: string) {
  const transcript = transcriptForUrl(url);
  if (!transcript?.length) return;
  const text = transcript.map((seg) => `[${formatTimestamp(seg.start)}] ${seg.text}`).join("\n");
  const title = earlyTitles[summaryIdForUrl(url)] || summaryForUrl(url)?.result?.title || "字幕";
  const filename = title.replace(/[/\\?%*:|"<>]/g, "_") + "_字幕.txt";
  triggerDownloadBlob(new Blob([text], { type: "text/plain; charset=utf-8" }), filename);
}

function lockedFeature(name: string) {
  showToast(`${name} 即将开放`);
}

// markmap 状态：每个 summary 独立存储 mindmap markdown、SVG 元素引用和实例
const mindmapMarkdowns: Record<string, string> = reactive({});
const markmapInstances: Record<string, { instance: any; svgEl: SVGElement | null }> = {};
const mindmapFullscreen: Record<string, boolean> = reactive({});
const earlyTranscripts: Record<string, TranscriptSegment[]> = reactive({});
const earlyTitles: Record<string, string> = reactive({});

type MindmapExportSvg = {
  svgStr: string;
  width: number;
  height: number;
};

const mindmapRenderTimers: Record<string, ReturnType<typeof setTimeout>> = {};
const mindmapRendering: Record<string, boolean> = reactive({});

function renderMarkmap(summaryId: string, md: string) {
  const entry = markmapInstances[summaryId];
  if (!entry?.svgEl || !md) return;
  // 取消防抖队列中待执行的旧渲染任务
  if (mindmapRenderTimers[summaryId]) {
    clearTimeout(mindmapRenderTimers[summaryId]);
  }
  const svgEl = entry.svgEl;
  mindmapRendering[summaryId] = true;
  mindmapRenderTimers[summaryId] = setTimeout(() => {
    try {
      while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);
      const transformer = new Transformer();
      const { root } = transformer.transform(md);
      entry.instance = Markmap.create(svgEl, { autoFit: true, duration: 300 }, root);
    } catch { /* ignore */ }
    delete mindmapRenderTimers[summaryId];
    mindmapRendering[summaryId] = false;
  }, 80); // 80ms 防抖 + setTimeout 让出主线程给 UI 交互
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

// ── 全屏 ──
function toggleMindmapFullscreen(summaryId: string) {
  mindmapFullscreen[summaryId] = !mindmapFullscreen[summaryId];
  nextTick(() => {
    markmapInstances[summaryId]?.instance?.fit();
  });
}

function findDirectSvgGroup(svgEl: SVGElement): SVGGElement | null {
  return Array.from(svgEl.children).find((child): child is SVGGElement => child.tagName.toLowerCase() === "g") || null;
}

function getMindmapExportBounds(entry: { instance: any; svgEl: SVGElement | null }) {
  const rect = entry.instance?.state?.rect;
  if (rect) {
    const x = Number(rect.x1);
    const y = Number(rect.y1);
    const width = Number(rect.x2) - Number(rect.x1);
    const height = Number(rect.y2) - Number(rect.y1);
    if ([x, y, width, height].every(Number.isFinite) && width > 0 && height > 0) {
      return { x, y, width, height };
    }
  }

  const g = entry.svgEl ? findDirectSvgGroup(entry.svgEl) : null;
  if (g) {
    try {
      const bbox = g.getBBox();
      if (bbox.width > 0 && bbox.height > 0) {
        return { x: bbox.x, y: bbox.y, width: bbox.width, height: bbox.height };
      }
    } catch {
      // fall through to default bounds
    }
  }

  return { x: 0, y: 0, width: 800, height: 600 };
}

function replaceForeignObjectsWithText(svgEl: SVGElement) {
  svgEl.querySelectorAll("foreignObject").forEach((fo) => {
    const text = fo.textContent?.trim() || "";
    if (!text) {
      fo.remove();
      return;
    }

    const x = parseFloat(fo.getAttribute("x") || "0");
    const y = parseFloat(fo.getAttribute("y") || "0");
    const h = parseFloat(fo.getAttribute("height") || "20");
    const textEl = document.createElementNS("http://www.w3.org/2000/svg", "text");
    textEl.setAttribute("x", String(x + 4));
    textEl.setAttribute("y", String(y + h / 2 + 5));
    textEl.setAttribute("font-size", "14");
    textEl.setAttribute("font-family", "sans-serif");
    textEl.setAttribute("fill", "#1e293b");
    textEl.textContent = text;
    fo.parentNode?.replaceChild(textEl, fo);
  });
}

// ── 导出 SVG / PNG 公用：基于内容边界生成静态、居中的 SVG ──
function serializeSvgForExport(entry: { instance: any; svgEl: SVGElement | null }): MindmapExportSvg | null {
  const svgEl = entry.svgEl;
  if (!svgEl) return null;

  const clone = svgEl.cloneNode(true) as SVGElement;
  const contentGroup = findDirectSvgGroup(clone);
  if (contentGroup) {
    contentGroup.removeAttribute("transform");
  }

  replaceForeignObjectsWithText(clone);

  const bounds = getMindmapExportBounds(entry);
  const padding = 48;
  const viewX = bounds.x - padding;
  const viewY = bounds.y - padding;
  const width = Math.ceil(bounds.width + padding * 2);
  const height = Math.ceil(bounds.height + padding * 2);

  clone.setAttribute("viewBox", `${viewX} ${viewY} ${width} ${height}`);
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));

  const serializer = new XMLSerializer();
  let svgStr = serializer.serializeToString(clone);
  // 确保命名空间
  if (!svgStr.includes("xmlns=")) {
    svgStr = svgStr.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"');
  }

  return { svgStr, width, height };
}

function setSvgPixelSize(svgStr: string, width: number, height: number) {
  return svgStr.replace(/<svg\b([^>]*)>/i, (match, attrs: string) => {
    const nextAttrs = attrs
      .replace(/\swidth="[^"]*"/i, "")
      .replace(/\sheight="[^"]*"/i, "");
    return `<svg${nextAttrs} width="${width}" height="${height}">`;
  });
}

// ── 导出 SVG ──
function downloadMindmapSvg(summaryId: string) {
  const entry = markmapInstances[summaryId];
  if (!entry?.svgEl) return;
  const exportSvg = serializeSvgForExport(entry);
  if (!exportSvg) return;
  triggerDownloadBlob(new Blob([exportSvg.svgStr], { type: "image/svg+xml;charset=utf-8" }), "mindmap.svg");
}

// ── 导出高清 PNG ──
async function downloadMindmapPng(summaryId: string) {
  const entry = markmapInstances[summaryId];
  if (!entry?.svgEl) return;
  const exportSvg = serializeSvgForExport(entry);
  if (!exportSvg) return;
  const { svgStr, width: vw, height: vh } = exportSvg;
  // 4K 高清：宽度至少 3840px，最小 4x 缩放保证细节锐利
  const scale = Math.max(4, Math.ceil(3840 / Math.min(vw, vh)));
  const width = Math.ceil(vw * scale);
  const height = Math.ceil(vh * scale);
  const pngSvgStr = setSvgPixelSize(svgStr, width, height);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  // 在 img 标签内加载处理后的 SVG
  const img = new Image();
  const blob = new Blob([pngSvgStr], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  await new Promise<void>((resolve) => {
    img.onload = () => {
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      resolve();
    };
    img.onerror = () => { URL.revokeObjectURL(url); resolve(); };
    img.src = url;
  });
  canvas.toBlob((png) => {
    if (png) triggerDownloadBlob(png, "mindmap.png");
  }, "image/png");
}

// 监听 streaming mindmap 数据更新，实时刷新渲染
watch(mindmapMarkdowns, (newVal, oldVal) => {
  for (const [summaryId, md] of Object.entries(newVal)) {
    if (md && md !== oldVal?.[summaryId]) {
      renderMarkmap(summaryId, md);
    }
  }
});

function triggerDownloadBlob(blob: Blob, filename: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

function summaryForUrlBySummaryId(summaryId: string): SummaryStatus | undefined {
  return summaryJobs.value.find((j) => j.summary_id === summaryId);
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
  if (profileAvatarPreview.value) {
    URL.revokeObjectURL(profileAvatarPreview.value);
  }
});

onMounted(() => {
  void loadAuth().then(handleCheckoutReturn);
});

const successfulResults = computed(() => results.value.filter((item) => item.ok && item.video));
const failedResults = computed(() => results.value.filter((item) => !item.ok));

const domesticPlatforms = ["抖音", "Bilibili", "爱奇艺", "腾讯视频", "优酷", "小红书"];
const overseasPlatforms = ["YouTube", "TikTok", "Vimeo", "Instagram", "X", "Facebook"];
const heroPlatforms = ["YouTube", "Bilibili", "抖音", "TikTok", "小红书", "Vimeo"];
const featureCards: IconCard[] = [
  { title: "支持主流平台", text: "覆盖 YouTube、Bilibili、抖音、TikTok、小红书、Vimeo 等常见公开视频平台。", icon: Globe2, tone: "cyan" },
  { title: "极速解析下载", text: "粘贴视频链接后自动识别可用格式，优先直链下载，复杂链接可切换云端处理。", icon: Zap, tone: "amber" },
  { title: "手机也能用", text: "打开网页即可使用，无需安装桌面软件，适合临时保存课程、讲座和公开视频素材。", icon: Clipboard, tone: "cyan" },
  { title: "多种清晰度", text: "按视频实际可用格式选择清晰度、文件类型和下载方式，满足学习、归档和复盘场景。", icon: Video, tone: "rose" },
  { title: "视频总结整理", text: "解析后自动生成摘要、章节、字幕、思维导图和问答素材，看长视频更省时间。", icon: Bot, tone: "amber" },
];
const useSteps = [
  {
    title: "复制视频链接",
    text: "在 YouTube、Bilibili、抖音等平台找到想保存或整理的公开视频，复制视频分享链接或地址栏 URL。",
  },
  {
    title: "粘贴链接并解析",
    text: "把链接粘贴到输入框中，点击下载视频，系统会自动识别视频信息、平台来源和可用格式。",
  },
  {
    title: "选择清晰度并下载",
    text: "从解析结果中选择需要的清晰度或格式，点击极速下载或云端处理，并可继续导出字幕、摘要和思维导图。",
  },
];
const comparisonRows = [
  { label: "支持平台范围", ours: "常见主流平台", online: "部分平台", desktop: "依赖软件版本" },
  { label: "视频总结整理", ours: "支持", online: "较少支持", desktop: "通常不支持" },
  { label: "思维导图生成", ours: "支持", online: "通常不支持", desktop: "通常不支持" },
  { label: "字幕导出", ours: "TXT / SRT", online: "部分支持", desktop: "部分支持" },
  { label: "抖音公开视频解析", ours: "支持公开链接", online: "部分支持", desktop: "常需额外配置" },
  { label: "安装门槛", ours: "无需安装", online: "无需安装", desktop: "需要安装" },
  { label: "移动端使用", ours: "浏览器可用", online: "部分可用", desktop: "通常不可用" },
  { label: "适合场景", ours: "下载 + 学习整理", online: "临时下载", desktop: "批量下载" },
];
const faqItems = [
  {
    question: "影知和普通视频下载器有什么区别？",
    answer: "它不仅提供公开视频解析、格式选择和下载任务，还会把可提取字幕整理成摘要、章节大纲、核心要点、术语解释、思维导图和可追问的问答素材。",
  },
  {
    question: "适合用来整理哪些视频内容？",
    answer: "适合整理你有权使用的公开课程、公开视频素材、讲座、教程、运营参考视频和内部学习资料，并把内容沉淀成摘要、字幕和笔记。",
  },
  {
    question: "这个工具的安全和版权边界是什么？",
    answer: "它仅面向授权内容分析、学习整理和内部资料归档，不支持私密内容、受保护内容、DRM 绕过、验证码绕过、登录态绕过、平台 Cookie 上传或账号池代管。",
  },
];
const summaryTabs = [
  { key: "summary", label: "总结摘要", icon: FileText },
  { key: "transcript", label: "字幕文本", icon: ListChecks },
  { key: "mindmap", label: "思维导图", icon: Brain },
  { key: "qa", label: "AI 问答", icon: MessageCircle },
] as const;
</script>

<template>
  <div class="min-h-screen overflow-x-hidden bg-[#fff8f3] text-slate-800">
    <header class="sticky top-0 z-20 border-b border-[#f2ded3] bg-white/92 backdrop-blur">
      <nav class="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6 lg:px-8">
        <a href="#" class="flex items-center gap-3">
          <span class="grid h-9 w-9 place-items-center rounded-lg bg-[#ff5a5f] text-white shadow-sm shadow-[#ff5a5f]/30">
            <Video class="h-5 w-5" />
          </span>
          <span class="text-base font-black text-slate-800">影知</span>
        </a>
        <div class="hidden items-center gap-6 text-sm font-semibold text-slate-500 md:flex">
          <a href="#tool" class="hover:text-[#ff5a5f]">下载</a>
          <a href="#features" class="hover:text-[#ff5a5f]">功能</a>
          <a href="#how-to-use" class="hover:text-[#ff5a5f]">用法</a>
          <a href="#comparison" class="hover:text-[#ff5a5f]">对比</a>
          <a href="#pricing" class="hover:text-[#ff5a5f]">套餐价格</a>
          <button type="button" class="hover:text-[#ff5a5f]" @click="openInfoDrawer('platforms')">支持平台</button>
        </div>
        <div class="flex items-center gap-2">
          <template v-if="authUser">
            <button
              v-if="!authUser.is_vip"
              type="button"
              class="hidden items-center gap-2 rounded-full bg-[#ff5a5f] px-4 py-2 text-sm font-black text-white shadow-sm shadow-[#ff5a5f]/25 hover:bg-[#ef4444] sm:inline-flex"
              :disabled="billingLoading"
              @click="startVipCheckout"
            >
              <Sparkles class="h-4 w-4" />
              {{ billingLoading ? "处理中..." : "开通 VIP" }}
            </button>
            <div class="relative">
              <button
                type="button"
                class="inline-flex items-center gap-2 rounded-full border border-[#f2ded3] bg-white px-2 py-1.5 text-sm font-black text-slate-700 shadow-sm hover:bg-[#fff8f3]"
                @click="userMenuOpen = !userMenuOpen"
              >
                <span class="grid h-8 w-8 place-items-center overflow-hidden rounded-full bg-[#fff1ed] text-[#ff5a5f]">
                  <img v-if="authUser.avatar_url" :src="authUser.avatar_url" alt="用户头像" class="h-full w-full object-cover" />
                  <User v-else class="h-4 w-4" />
                </span>
                <span class="hidden max-w-[96px] truncate sm:inline">{{ profileDisplayName }}</span>
              </button>
              <div v-if="userMenuOpen" class="absolute right-0 mt-3 w-72 rounded-2xl border border-[#f2ded3] bg-white p-3 text-sm shadow-2xl shadow-slate-900/10">
                <div class="flex items-center gap-3 rounded-xl bg-[#fff8f3] p-3">
                  <span class="grid h-11 w-11 shrink-0 place-items-center overflow-hidden rounded-full bg-white text-[#ff5a5f]">
                    <img v-if="authUser.avatar_url" :src="authUser.avatar_url" alt="用户头像" class="h-full w-full object-cover" />
                    <User v-else class="h-5 w-5" />
                  </span>
                  <div class="min-w-0">
                    <p class="truncate font-black text-slate-900">{{ profileDisplayName }}</p>
                    <p class="truncate text-xs font-semibold text-slate-500">{{ authUser.email }}</p>
                  </div>
                </div>
                <div class="mt-3 flex items-center justify-between rounded-xl border px-3 py-2 text-xs font-black" :class="authUser.is_vip ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'">
                  <span class="inline-flex items-center gap-1.5">
                    <Sparkles class="h-3.5 w-3.5" />
                    {{ authUser.is_vip ? "VIP 已开通" : `免费用户 · 今日剩余 ${authUser.daily_ai_remaining} 次` }}
                  </span>
                  <button v-if="!authUser.is_vip" type="button" class="text-[#ff5a5f] hover:underline" @click="userMenuOpen = false; scrollToPricing()">升级</button>
                </div>
                <div class="mt-3 grid gap-2">
                  <button type="button" class="inline-flex items-center gap-2 rounded-xl px-3 py-2 font-bold text-slate-700 hover:bg-[#fff8f3]" @click="openProfileModal">
                    <Settings class="h-4 w-4 text-[#ff5a5f]" />
                    个人中心
                  </button>
                  <button type="button" class="inline-flex items-center gap-2 rounded-xl px-3 py-2 font-bold text-slate-700 hover:bg-[#fff8f3]" @click="logout">
                    <LogOut class="h-4 w-4 text-slate-500" />
                    退出登录
                  </button>
                </div>
              </div>
            </div>
          </template>
          <template v-else>
            <button type="button" class="hidden items-center gap-2 rounded-full border border-[#f2ded3] bg-white px-3 py-2 text-xs font-bold text-slate-600 hover:bg-[#fff1ed] sm:inline-flex" @click="openAuthModal('login')">
              <User class="h-3.5 w-3.5" />
              登录
            </button>
            <button type="button" class="inline-flex items-center gap-2 rounded-full bg-[#ff5a5f] px-4 py-2 text-sm font-black text-white shadow-sm shadow-[#ff5a5f]/25 hover:bg-[#ef4444]" @click="startVipCheckout">
              <Sparkles class="h-4 w-4" />
              开通 VIP
            </button>
          </template>
        </div>
      </nav>
    </header>

    <!-- 轻提示 Toast -->
    <Transition name="toast-fade">
      <div v-if="toastMessage" class="fixed top-20 left-1/2 z-50 -translate-x-1/2 rounded-full border px-5 py-3 text-sm font-bold shadow-xl backdrop-blur" :class="toastClass">
        {{ toastMessage }}
      </div>
    </Transition>

    <main>
      <section id="tool" class="overflow-hidden border-b border-[#f2ded3] bg-white">
        <div class="mx-auto grid w-full max-w-7xl gap-6 px-4 py-10 sm:px-6 sm:py-12 lg:grid-cols-2 lg:items-stretch lg:px-8">
          <div class="min-w-0 flex h-full flex-col justify-center rounded-[32px] border border-[#f2ded3] bg-[#fff8f3] p-5 shadow-xl shadow-[#f1c7b8]/25 sm:p-7 lg:p-8">
            <p class="inline-flex w-fit items-center gap-2 rounded-full border border-[#ffd0c7] bg-[#fff1ed] px-4 py-2 text-sm font-bold text-[#e11d48]">
              <Sparkles class="h-4 w-4" />
              下载、字幕、总结一次完成
            </p>
            <h1 class="mt-5 text-4xl font-black leading-tight tracking-normal text-slate-950 sm:text-5xl lg:text-6xl">
              免费视频下载器
            </h1>
            <p class="mt-5 max-w-xl text-base leading-8 text-slate-500">
              粘贴公开视频链接，即刻解析视频信息，并自动生成摘要、字幕、思维导图和问答素材。
            </p>

            <div class="mt-6 flex flex-wrap gap-2">
              <span
                v-for="platform in heroPlatforms"
                :key="platform"
                class="inline-flex items-center gap-1.5 rounded-full border border-[#f2ded3] bg-white px-3 py-1.5 text-xs font-bold text-slate-600 shadow-sm"
              >
                <CheckCircle2 class="h-3.5 w-3.5 text-[#14b8a6]" />
                {{ platform }}
              </span>
            </div>
          </div>

          <section class="min-w-0 flex h-full w-full max-w-full flex-col gap-3 rounded-[32px] border border-[#f2ded3] bg-[#fff8f3] p-3 shadow-xl shadow-[#f1c7b8]/25 sm:p-4">
            <div class="min-w-0 rounded-[28px] bg-white p-4 sm:p-5">
              <div class="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div class="flex items-center gap-2 text-xs font-black text-slate-500">
                  <Link2 class="h-4 w-4 text-[#0f766e]" />
                  粘贴链接后自动识别并排队解析
                </div>
                <button type="button" class="inline-flex items-center justify-center gap-1.5 rounded-full px-3 py-2 text-xs font-black text-[#0f766e] hover:bg-cyan-50 hover:text-[#14b8a6]" @click="openInfoDrawer('platforms')">
                  <Globe2 class="h-3.5 w-3.5" />
                  查看支持平台
                </button>
              </div>
              <textarea
                id="urls"
                v-model="urlInput"
                rows="4"
                class="block h-28 max-h-36 w-full resize-none overflow-auto border-0 bg-white px-2 py-2 text-base leading-7 text-slate-800 outline-none placeholder:text-slate-400"
                :class="inputIssues.length ? 'border-red-300' : 'border-[#f2ded3]'"
                placeholder="请在这里粘贴视频链接，支持 YouTube、B站、抖音、TikTok 等公开视频链接"
              />
              <div class="mt-2 grid grid-cols-2 gap-2 border-t border-[#f2ded3] pt-3 text-xs font-semibold sm:grid-cols-4">
                <span class="inline-flex w-full items-center justify-center gap-1.5 rounded-full border border-cyan-400/30 bg-cyan-400/10 px-3 py-1.5 text-cyan-700">
                  <Search class="h-3.5 w-3.5" />
                  已识别 {{ parsedUrls.length }} 条
                </span>
                <span v-if="duplicateUrlCount" class="inline-flex w-full items-center justify-center gap-1.5 rounded-full border border-amber-300 bg-amber-50 px-3 py-1.5 text-amber-700">
                  <RefreshCw class="h-3.5 w-3.5" />
                  去重 {{ duplicateUrlCount }} 条
                </span>
                <span class="inline-flex w-full items-center justify-center gap-1.5 rounded-full border border-slate-300 bg-slate-100 px-3 py-1.5 text-slate-600">
                  <ListChecks class="h-3.5 w-3.5" />
                  批量链接
                </span>
                <span class="inline-flex w-full items-center justify-center gap-1.5 rounded-full border border-slate-300 bg-slate-100 px-3 py-1.5 text-slate-600">
                  <Bot class="h-3.5 w-3.5" />
                  自动总结
                </span>
                <button
                  type="button"
                  :disabled="!canAnalyze || inputIssues.length > 0"
                  class="inline-flex w-full items-center justify-center gap-1.5 rounded-full bg-[#ff5a5f] px-4 py-1.5 font-black text-white shadow-md shadow-[#ff5a5f]/25 transition hover:bg-[#ef4444] disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500 disabled:shadow-none sm:col-start-4"
                  @click="requestAnalyze"
                >
                  <component :is="analyzing ? RefreshCw : Download" class="h-3.5 w-3.5" :class="{ 'animate-spin': analyzing }" />
                  {{ analyzing ? "解析中..." : "下载视频" }}
                </button>
              </div>
            </div>
              <div v-if="inputIssues.length" class="mt-3 rounded-2xl border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-600">
                <p v-for="issue in inputIssues" :key="issue">{{ issue }}</p>
              </div>

              <div v-if="parsedUrls.length" class="mt-4 rounded-2xl border border-[#f2ded3] bg-[#fff8f3] p-3">
                <div class="mb-2 flex items-center justify-between text-xs font-black text-slate-500">
                  <span>待解析队列</span>
                  <span>{{ parsedUrls.length }} 条</span>
                </div>
                <div class="max-h-36 space-y-2 overflow-auto custom-scroll">
                  <div v-for="url in parsedUrls" :key="url" class="flex items-center gap-2 rounded-xl bg-white px-3 py-2 text-xs text-slate-600">
                    <span class="h-2 w-2 shrink-0 rounded-full bg-cyan-500"></span>
                    <span class="truncate">{{ url }}</span>
                  </div>
                </div>
              </div>

              <p class="mt-3 flex items-start gap-2 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-800">
                <ShieldCheck class="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  请仅解析、下载或导出你有权使用的视频内容。
                  <button type="button" class="font-black underline underline-offset-2" @click="openInfoDrawer('compliance')">查看合规说明</button>
                </span>
              </p>

              <p v-if="analyzeError" class="mt-4 rounded-2xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm font-medium text-red-600">
                {{ analyzeError }}
              </p>
          </section>
        </div>
      </section>

      <section v-if="results.length" id="results" class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div class="mb-4 flex items-center gap-2 text-sm font-bold text-[#ff5a5f]">
          <CheckCircle2 class="h-4 w-4" />
          解析结果
        </div>

        <div class="grid gap-6">
          <article
            v-for="item in successfulResults"
            :key="`workbench-${item.url}`"
            class="overflow-hidden rounded-3xl border border-[#f2ded3] bg-white shadow-xl shadow-[#f1c7b8]/30"
          >
            <div class="grid xl:grid-cols-[minmax(280px,380px)_1fr]">
              <aside class="border-b border-[#f2ded3] bg-white p-5 xl:h-[680px] xl:overflow-auto xl:border-b-0 xl:border-r custom-scroll">
                <div class="overflow-hidden rounded-2xl border border-[#f2ded3] bg-[#fff8f3]">
                  <div class="relative aspect-video">
                    <img
                      v-if="item.video?.thumbnail"
                      :src="proxyThumbnail(item.video.thumbnail)"
                      :alt="item.video.title"
                      referrerpolicy="no-referrer"
                      loading="lazy"
                      class="h-full w-full object-cover"
                    />
                    <div v-else class="grid h-full place-items-center text-sm font-bold text-slate-400">无封面</div>
                    <span class="absolute inset-0 grid place-items-center bg-slate-950/10">
                      <span class="grid h-14 w-14 place-items-center rounded-full bg-white/90 text-[#ff5a5f] shadow-lg">
                        <Play class="ml-0.5 h-7 w-7 fill-current" />
                      </span>
                    </span>
                  </div>
                </div>

                <div class="mt-4 flex flex-wrap gap-2 text-xs font-bold">
                  <span class="inline-flex items-center gap-1.5 rounded-full border border-cyan-400/30 bg-cyan-400/10 px-2.5 py-1 text-cyan-700">
                    <Globe2 class="h-3.5 w-3.5" />
                    {{ item.video?.extractor || "公开视频" }}
                  </span>
                  <span class="inline-flex items-center gap-1.5 rounded-full border border-slate-300 bg-slate-100 px-2.5 py-1 text-slate-600">
                    <Video class="h-3.5 w-3.5" />
                    {{ formatDuration(item.video?.duration) }}
                  </span>
                </div>
                <h3 class="mt-3 line-clamp-3 text-xl font-black leading-8 text-slate-800">{{ item.video?.title }}</h3>
                <p class="mt-2 break-all text-xs leading-5 text-slate-400">{{ item.url }}</p>

                <div v-if="!authUser" class="mt-5 rounded-2xl border border-[#ffc9bd] bg-[#fff8f3] p-4">
                  <p class="inline-flex items-center gap-1.5 text-xs font-black text-[#ff5a5f]">
                    <Sparkles class="h-3.5 w-3.5" />
                    AI 总结
                  </p>
                  <h4 class="mt-2 text-base font-black text-slate-900">登录后免费试用</h4>
                  <p class="mt-2 text-xs leading-5 text-slate-600">每日 2 次免费 AI 总结，登录即可使用。下载功能不受影响。</p>
                  <button
                    type="button"
                    class="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-full bg-[#ff5a5f] px-4 py-2.5 text-sm font-black text-white shadow-sm shadow-[#ff5a5f]/25 hover:bg-[#ef4444]"
                    @click="openAuthModal('login')"
                  >
                    登录
                  </button>
                </div>

                <div v-else-if="summaryForUrl(item.url)" class="mt-5 rounded-2xl border border-[#f2ded3] bg-[#fff8f3] p-4">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <p class="inline-flex items-center gap-1.5 text-xs font-bold text-rose-600">
                        <Bot class="h-3.5 w-3.5" />
                        自动总结
                      </p>
                      <p class="mt-1 text-sm font-black text-slate-700">
                        <span v-if="isSummaryLoading(item.url)">分析中</span>
                        <span v-else-if="summaryForUrl(item.url)?.status === 'success'">已完成</span>
                        <span v-else-if="summaryForUrl(item.url)?.status === 'failed'">生成失败</span>
                        <span v-else>等待启动</span>
                      </p>
                    </div>
                    <button
                      type="button"
                      class="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-[#f2ded3] bg-white px-3 py-2 text-xs font-black text-slate-600 transition hover:border-rose-300 hover:text-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
                      :disabled="isSummaryLoading(item.url)"
                      @click="createSummary(item, true)"
                    >
                      <RefreshCw class="h-3.5 w-3.5" :class="{ 'animate-spin': isSummaryLoading(item.url) }" />
                      {{ isSummaryLoading(item.url) ? "生成中" : summaryForUrl(item.url)?.status === "success" ? "重新生成" : "重新生成" }}
                    </button>
                  </div>
                  <p v-if="!isVip && authUser.daily_ai_remaining > 0" class="mt-2 text-xs font-semibold text-emerald-600">今日剩余 {{ authUser.daily_ai_remaining }} 次免费</p>
                  <p v-else-if="!isVip" class="mt-2 text-xs font-semibold text-amber-600">今日免费次数已用完</p>
                </div>

                <div v-else-if="!isVip && authUser.daily_ai_remaining > 0" class="mt-5 rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
                  <p class="inline-flex items-center gap-1.5 text-xs font-black text-emerald-700">
                    <Sparkles class="h-3.5 w-3.5" />
                    免费试用 · 今日剩余 {{ authUser.daily_ai_remaining }} 次
                  </p>
                  <h4 class="mt-2 text-base font-black text-slate-900">AI 智能分析</h4>
                  <p class="mt-2 text-xs leading-5 text-slate-600">摘要、章节、字幕、思维导图和视频问答。每日 2 次免费，开通 VIP 无限使用。</p>
                  <button
                    type="button"
                    class="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-full bg-emerald-600 px-4 py-2.5 text-sm font-black text-white shadow-sm shadow-emerald-600/25 hover:bg-emerald-700"
                    @click="createSummary(item, true)"
                  >
                    <Bot class="h-4 w-4" />
                    免费生成 AI 总结
                  </button>
                </div>

                <div v-else-if="!isVip" class="mt-5 rounded-2xl border border-[#ffc9bd] bg-[#fff8f3] p-4">
                  <p class="inline-flex items-center gap-1.5 text-xs font-black text-[#ff5a5f]">
                    <Sparkles class="h-3.5 w-3.5" />
                    今日免费次数已用完
                  </p>
                  <h4 class="mt-2 text-base font-black text-slate-900">开通 VIP 无限使用</h4>
                  <p class="mt-2 text-xs leading-5 text-slate-600">解锁摘要、章节大纲、字幕整理、思维导图和视频问答。下载功能仍可免费使用。</p>
                  <button
                    type="button"
                    class="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-full bg-[#ff5a5f] px-4 py-2.5 text-sm font-black text-white shadow-sm shadow-[#ff5a5f]/25 hover:bg-[#ef4444]"
                    @click="startVipCheckout()"
                  >
                    <Sparkles class="h-4 w-4" />
                    开通 VIP
                  </button>
                </div>

                <div v-else class="mt-5 rounded-2xl border border-[#f2ded3] bg-[#fff8f3] p-4">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <p class="inline-flex items-center gap-1.5 text-xs font-bold text-rose-600">
                        <Bot class="h-3.5 w-3.5" />
                        自动总结
                      </p>
                      <p class="mt-1 text-sm font-black text-slate-700">
                        <span v-if="isSummaryLoading(item.url)">分析中</span>
                        <span v-else-if="summaryForUrl(item.url)?.status === 'success'">已完成</span>
                        <span v-else-if="summaryForUrl(item.url)?.status === 'failed'">生成失败</span>
                        <span v-else>等待启动</span>
                      </p>
                    </div>
                    <button
                      type="button"
                      class="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-[#f2ded3] bg-white px-3 py-2 text-xs font-black text-slate-600 transition hover:border-rose-300 hover:text-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
                      :disabled="isSummaryLoading(item.url)"
                      @click="createSummary(item, true)"
                    >
                      <RefreshCw class="h-3.5 w-3.5" />
                      重新生成
                    </button>
                  </div>
                  <div v-if="summaryForUrl(item.url)" class="mt-4">
                    <div class="mb-2 flex items-center justify-between text-xs">
                      <span class="font-bold text-slate-500">
                        {{ summaryStageLabel(item.url) }}
                      </span>
                      <span class="text-slate-400">{{ Math.round(summaryForUrl(item.url)?.progress || 0) }}%</span>
                    </div>
                    <div class="h-2 overflow-hidden rounded-full bg-white">
                      <div class="h-full rounded-full bg-gradient-to-r from-rose-500 to-amber-400 transition-all duration-500" :style="{ width: `${Math.max(4, summaryForUrl(item.url)?.progress || 0)}%` }"></div>
                    </div>
                  </div>
                  <p v-if="summaryErrors[item.url] || summaryForUrl(item.url)?.error" class="mt-3 rounded-xl border border-red-400/20 bg-red-500/10 p-3 text-xs leading-5 text-red-600">
                    {{ summaryErrors[item.url] || summaryForUrl(item.url)?.error }}
                  </p>
                </div>

                <div class="mt-5 space-y-4">
                  <label class="block text-sm font-bold text-slate-700">
                    下载格式
                    <select
                      v-model="selectedFormats[item.url]"
                      class="mt-2 w-full rounded-2xl border border-[#f2ded3] bg-white px-3 py-3 text-sm text-slate-800 outline-none focus:border-[#ff9f80] focus:ring-4 focus:ring-[#ff5a5f]/10"
                    >
                      <option v-for="format in item.video?.formats" :key="format.format_id" :value="format.format_id">
                        {{ displayFormatLabel(format) }}
                      </option>
                    </select>
                  </label>
                  <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                    <button
                      type="button"
                      class="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-amber-400/50 px-4 py-3 text-sm font-black text-amber-700 transition hover:bg-amber-400/10"
                      @click="directDownload(item)"
                    >
                      <Zap class="h-4 w-4" />
                      极速下载
                    </button>
                    <button
                      type="button"
                      class="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-[#f2ded3] bg-[#fff8f3] px-4 py-3 text-sm font-black text-slate-700 transition hover:bg-[#fff1ed]"
                      @click="createJob(item)"
                    >
                      <Cloud class="h-4 w-4" />
                      云端处理下载
                    </button>
                  </div>
                  <p v-if="directErrors[item.url]" class="rounded-2xl border border-amber-300/20 bg-amber-300/10 p-3 text-xs leading-5 text-amber-700">
                    {{ directErrors[item.url] }}
                  </p>
                </div>

                <div v-if="jobsForUrl(item.url).length" class="mt-5 space-y-3">
                  <p class="text-xs font-black text-slate-500">下载任务</p>
                  <article v-for="job in jobsForUrl(item.url)" :key="job.job_id" class="rounded-2xl border border-[#f2ded3] bg-[#fff8f3] p-3">
                    <div class="flex items-center justify-between gap-3">
                      <p class="truncate text-xs font-bold text-slate-600">格式：{{ job.format_id }}</p>
                      <span class="shrink-0 rounded-full px-2.5 py-1 text-[11px] font-black" :class="{
                        'bg-rose-400/10 text-rose-700': job.status === 'queued' || job.status === 'running',
                        'bg-cyan-400/10 text-cyan-700': job.status === 'success',
                        'bg-red-400/10 text-red-600': job.status === 'failed'
                      }">
                        {{ job.status }}
                      </span>
                    </div>
                    <div class="mt-3 h-2 overflow-hidden rounded-full bg-white">
                      <div class="h-full rounded-full bg-rose-500 transition-all" :style="{ width: `${Math.max(2, job.progress || 0)}%` }" />
                    </div>
                    <div class="mt-2 text-xs leading-5 text-slate-500">
                      {{ Math.round(job.progress || 0) }}% · {{ formatBytes(job.downloaded_bytes) }} / {{ formatBytes(job.total_bytes) }} · {{ formatSpeed(job.speed) }}
                    </div>
                    <p v-if="job.error" class="mt-2 text-xs leading-5 text-red-500">{{ job.error }}</p>
                    <div v-if="job.files.length" class="mt-3 flex flex-wrap gap-2">
                      <button
                        v-for="file in job.files"
                        :key="file.id"
                        type="button"
                        class="rounded-full bg-[#ff5a5f] px-3 py-1.5 text-xs font-black text-white hover:bg-[#ef4444]"
                        @click="downloadFile(file.download_url, file.filename)"
                      >
                        下载 {{ formatBytes(file.size) }}
                      </button>
                    </div>
                  </article>
                </div>
              </aside>

              <section class="flex min-w-0 flex-col bg-[#fff8f3] p-4 sm:h-[680px] sm:p-5">
                <div v-if="summaryForUrl(item.url)?.result || earlyTranscripts[summaryIdForUrl(item.url)]?.length" class="mb-4 flex flex-wrap gap-2 text-xs font-bold">
                  <span class="inline-flex items-center gap-1.5 rounded-full border border-cyan-400/30 bg-cyan-400/10 px-2.5 py-1 text-cyan-700">
                    <ListChecks class="h-3.5 w-3.5" />
                    字幕 {{ (transcriptForUrl(item.url) || []).length }} 段
                  </span>
                  <span class="inline-flex items-center gap-1.5 rounded-full border border-rose-400/30 bg-rose-400/10 px-2.5 py-1 text-rose-700">
                    <FileText class="h-3.5 w-3.5" />
                    {{ (summaryForUrl(item.url)?.result?.chapters || []).length }} 章节
                  </span>
                  <span class="inline-flex items-center gap-1.5 rounded-full border border-amber-400/30 bg-amber-400/10 px-2.5 py-1 text-amber-700">
                    <Sparkles class="h-3.5 w-3.5" />
                    {{ (summaryForUrl(item.url)?.result?.key_points || []).length }} 要点
                  </span>
                  <span v-if="summaryForUrl(item.url)?.result?.markdown" class="inline-flex items-center gap-1.5 rounded-full border border-purple-400/30 bg-purple-400/10 px-2.5 py-1 text-purple-700">
                    <Clipboard class="h-3.5 w-3.5" />
                    笔记 {{ summaryForUrl(item.url)?.result?.markdown.length }} 字
                  </span>
                  <span v-if="summaryForUrl(item.url)?.result?.mindmap_markdown" class="inline-flex items-center gap-1.5 rounded-full border border-pink-400/30 bg-pink-400/10 px-2.5 py-1 text-pink-700">
                    <Brain class="h-3.5 w-3.5" />
                    导图已生成
                  </span>
                </div>

                <div class="mb-5 flex flex-wrap gap-1 rounded-2xl border border-[#f2ded3] bg-white p-1">
                  <button
                    v-for="tab in summaryTabs"
                    :key="tab.key"
                    type="button"
                    class="rounded-xl px-3 py-2 text-sm font-bold transition"
                    :class="activeTabForUrl(item.url) === tab.key
                      ? 'bg-[#ff5a5f] text-white shadow-sm'
                      : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'"
                    @click="handleTabClick(item.url, tab.key)"
                  >
                    <component :is="tab.icon" class="mr-1.5 inline h-4 w-4 align-[-3px]" />
                    {{ tab.label }}
                  </button>
                </div>

                <div v-if="aiGateState(item.url) === 'login'" class="flex min-h-[360px] flex-1 items-center justify-center rounded-2xl border border-dashed border-[#ffc9bd] bg-white p-6">
                  <div class="max-w-md text-center">
                    <div class="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-full bg-[#fff1ed] text-[#ff5a5f]">
                      <Sparkles class="h-6 w-6" />
                    </div>
                    <h3 class="text-xl font-black text-slate-900">登录后免费试用</h3>
                    <p class="mt-3 text-sm leading-7 text-slate-500">每日 2 次免费 AI 总结，登录即可使用。视频下载功能不受影响。</p>
                    <button type="button" class="mt-5 rounded-full bg-[#ff5a5f] px-6 py-3 text-sm font-black text-white shadow-sm shadow-[#ff5a5f]/25 hover:bg-[#ef4444]" @click="openAuthModal('login')">
                      登录
                    </button>
                  </div>
                </div>

                <div v-else-if="aiGateState(item.url) === 'trial'" class="flex min-h-[360px] flex-1 items-center justify-center rounded-2xl border border-dashed border-emerald-200 bg-white p-6">
                  <div class="max-w-md text-center">
                    <div class="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-full bg-emerald-50 text-emerald-600">
                      <Sparkles class="h-6 w-6" />
                    </div>
                    <h3 class="text-xl font-black text-slate-900">免费试用 AI 总结</h3>
                    <p class="mt-3 text-sm leading-7 text-slate-500">今日剩余 <span class="font-black text-emerald-600">{{ authUser?.daily_ai_remaining ?? 0 }}</span> 次免费 AI 分析。开通 VIP 即可无限使用。</p>
                    <button type="button" class="mt-5 rounded-full bg-emerald-600 px-6 py-3 text-sm font-black text-white shadow-sm shadow-emerald-600/25 hover:bg-emerald-700" @click="createSummary(item, true)">
                      <Bot class="mr-1.5 inline h-4 w-4 align-[-3px]" />
                      免费生成 AI 总结
                    </button>
                  </div>
                </div>

                <div v-else-if="aiGateState(item.url) === 'upgrade'" class="flex min-h-[360px] flex-1 items-center justify-center rounded-2xl border border-dashed border-[#ffc9bd] bg-white p-6">
                  <div class="max-w-md text-center">
                    <div class="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-full bg-[#fff1ed] text-[#ff5a5f]">
                      <Sparkles class="h-6 w-6" />
                    </div>
                    <h3 class="text-xl font-black text-slate-900">今日免费次数已用完</h3>
                    <p class="mt-3 text-sm leading-7 text-slate-500">每日 2 次免费 AI 已用完，开通 VIP 即可无限使用。视频下载功能不受影响。</p>
                    <button type="button" class="mt-5 rounded-full bg-[#ff5a5f] px-6 py-3 text-sm font-black text-white shadow-sm shadow-[#ff5a5f]/25 hover:bg-[#ef4444]" @click="startVipCheckout()">
                      立即开通 VIP
                    </button>
                  </div>
                </div>

                <div v-else-if="aiGateState(item.url) === 'loading'" class="flex min-h-[360px] flex-1 items-center justify-center rounded-2xl border border-dashed border-[#cbd5e1] bg-white">
                  <div class="text-center">
                    <div class="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-[3px] border-slate-300 border-t-[#ff5a5f]"></div>
                    <p class="text-sm font-bold text-slate-500">正在启动自动总结...</p>
                  </div>
                </div>

                <div v-else-if="activeTabForUrl(item.url) === 'summary'" class="flex min-h-0 flex-1 flex-col rounded-2xl border border-[#f2ded3] bg-white p-4">
                  <template v-if="summaryForUrl(item.url)?.result">
                    <div class="prose prose-theme prose-sm min-h-0 max-w-none flex-1 overflow-auto pr-1 custom-scroll" v-html="renderMarkdown(summaryForUrl(item.url)?.result?.markdown || '')"></div>
                    <div class="mt-4 flex gap-2 border-t border-[#f2ded3] pt-4">
                      <button type="button" class="inline-flex items-center gap-1.5 rounded-full border border-[#f2ded3] px-3 py-2 text-xs font-black text-slate-700 hover:border-cyan-300 hover:text-cyan-700" @click="copyMarkdownForUrl(item.url)">
                        <Copy class="h-3.5 w-3.5" />
                        复制
                      </button>
                      <button type="button" class="inline-flex items-center gap-1.5 rounded-full bg-[#ff5a5f] px-3 py-2 text-xs font-black text-white hover:bg-[#ef4444]" @click="downloadMarkdownForUrl(item.url)">
                        <Download class="h-3.5 w-3.5" />
                        笔记
                      </button>
                      <button type="button" class="inline-flex items-center gap-1.5 rounded-full border border-[#f2ded3] bg-[#fff8f3] px-3 py-2 text-xs font-black text-slate-600 hover:bg-[#fff1ed]" @click="lockedFeature('报告导出')">
                        <FileText class="h-3.5 w-3.5" />
                        报告
                      </button>
                    </div>
                  </template>
                  <div v-else-if="streamingText[summaryIdForUrl(item.url)]" class="min-h-0 flex-1 overflow-auto rounded-2xl bg-slate-50 p-3 text-sm leading-6 text-slate-600 font-mono whitespace-pre-wrap custom-scroll">
                    {{ streamingText[summaryIdForUrl(item.url)] }}<span class="ml-0.5 inline-block h-4 w-2 animate-pulse bg-[#ff5a5f] align-middle"></span>
                  </div>
                  <div v-else class="flex min-h-[320px] flex-1 items-center justify-center">
                    <div class="text-center">
                      <div class="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-[3px] border-slate-300 border-t-[#ff5a5f]"></div>
                      <p class="text-sm font-bold text-slate-500">正在生成总结...</p>
                    </div>
                  </div>
                </div>

                <!-- 字幕文本 -->
                <div v-else-if="activeTabForUrl(item.url) === 'transcript'" class="flex min-h-0 flex-1 flex-col rounded-2xl border border-[#f2ded3] bg-white p-4">
                  <div class="min-h-0 flex-1 resize-y overflow-auto rounded-2xl bg-slate-50 p-3 custom-scroll">
                    <div
                      v-for="segment in transcriptForUrl(item.url) || []"
                      :key="`${segment.start}-${segment.text}`"
                      class="grid gap-2 border-b border-[#f2ded3] py-2 text-sm last:border-b-0 sm:grid-cols-[76px_1fr]"
                    >
                      <span class="font-mono text-xs font-bold text-cyan-700">{{ formatTimestamp(segment.start) }}</span>
                      <span class="leading-6 text-slate-600">{{ segment.text }}</span>
                    </div>
                    <p v-if="!transcriptForUrl(item.url)?.length" class="py-8 text-center text-sm text-slate-400">暂无字幕数据</p>
                  </div>
                  <div v-if="transcriptForUrl(item.url)?.length" class="mt-3 flex gap-2 border-t border-[#f2ded3] pt-3">
                    <button type="button" class="rounded-full border border-[#f2ded3] px-3 py-2 text-xs font-black text-slate-700 hover:border-cyan-300 hover:text-cyan-700" @click="copyTranscriptForUrl(item.url)">复制</button>
                    <button type="button" class="rounded-full border border-[#f2ded3] px-3 py-2 text-xs font-black text-slate-700 hover:border-cyan-300 hover:text-cyan-700" @click="downloadTranscriptTxt(item.url)">导出 TXT</button>
                    <button type="button" class="rounded-full bg-[#ff5a5f] px-3 py-2 text-xs font-black text-white hover:bg-[#ef4444]" @click="downloadTranscriptSrt(item.url)">导出 SRT</button>
                  </div>
                </div>

                <!-- 思维导图 -->
                <div v-else-if="activeTabForUrl(item.url) === 'mindmap'" class="flex min-h-0 flex-1 flex-col rounded-2xl border border-[#f2ded3] bg-white p-4">
                  <template v-if="mindmapMarkdowns[summaryIdForUrl(item.url)] || summaryForUrl(item.url)?.result?.mindmap_markdown">
                    <div class="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl bg-slate-50" :class="mindmapFullscreen[summaryIdForUrl(item.url)] ? 'fixed inset-0 z-50 rounded-none flex flex-col' : ''">
                      <!-- 工具栏：始终可交互 -->
                      <div class="flex shrink-0 items-center justify-end gap-2 border-b border-[#f2ded3] px-3 py-2">
                        <span v-if="mindmapRendering[summaryIdForUrl(item.url)]" class="mr-auto text-xs text-slate-400">渲染中...</span>
                        <button type="button" class="rounded-lg border border-[#f2ded3] px-2.5 py-1.5 text-xs font-bold text-slate-600 transition hover:bg-[#fff1ed] hover:text-slate-800" @click="toggleMindmapFullscreen(summaryIdForUrl(item.url))">
                          {{ mindmapFullscreen[summaryIdForUrl(item.url)] ? '退出全屏' : '全屏' }}
                        </button>
                        <button type="button" class="rounded-lg border border-[#f2ded3] px-2.5 py-1.5 text-xs font-bold text-slate-600 transition hover:bg-[#fff1ed] hover:text-slate-800" @click="downloadMindmapPng(summaryIdForUrl(item.url))">下载 PNG</button>
                        <button type="button" class="rounded-lg border border-[#f2ded3] px-2.5 py-1.5 text-xs font-bold text-slate-600 transition hover:bg-[#fff1ed] hover:text-slate-800" @click="downloadMindmapSvg(summaryIdForUrl(item.url))">下载 SVG</button>
                      </div>
                      <svg
                        :ref="(el: any) => setMarkmapRef(summaryIdForUrl(item.url), el)"
                        class="min-h-0 w-full flex-1"
                        :style="mindmapFullscreen[summaryIdForUrl(item.url)] ? '' : 'min-height: 0;'"
                      ></svg>
                    </div>
                  </template>
                  <div v-else-if="summaryForUrl(item.url)?.result?.mindmap" class="rounded-2xl bg-white p-3">
                    <div
                      v-for="node in flattenedMindmap(summaryForUrl(item.url)?.result?.mindmap)"
                      :key="`${node.depth}-${node.name}`"
                      class="mb-2 flex items-start gap-2 text-sm"
                      :style="{ paddingLeft: `${node.depth * 18}px` }"
                    >
                      <span class="mt-2 h-2 w-2 shrink-0 rounded-full" :class="node.depth === 0 ? 'bg-rose-400' : 'bg-cyan-400'" />
                      <span class="rounded-xl border border-[#f2ded3] bg-[#fff8f3] px-3 py-2 font-semibold text-slate-700">{{ node.name }}</span>
                    </div>
                  </div>
                  <div v-else-if="isSummaryLoading(item.url)" class="flex items-center justify-center py-16">
                    <div class="flex flex-col items-center gap-3">
                      <div class="h-7 w-7 animate-spin rounded-full border-[3px] border-slate-600 border-t-[#ff5a5f]"></div>
                      <span class="text-xs text-slate-400">正在生成思维导图...</span>
                    </div>
                  </div>
                  <p v-else class="py-8 text-center text-sm text-slate-400">暂无思维导图数据</p>
                </div>

                <!-- AI 问答 -->
                <div v-else class="flex min-h-0 flex-1 flex-col rounded-2xl border border-[#f2ded3] bg-white p-4">
                  <!-- 对话气泡主区域（可滚动） -->
                  <div
                    :id="`chat-scroll-${summaryIdForUrl(item.url)}`"
                    class="min-h-0 flex-1 resize-y overflow-y-auto px-3 custom-scroll"
                    :class="{ 'flex items-center justify-center': !(questionAnswers[summaryIdForUrl(item.url)] || []).length && !streamingQA[summaryIdForUrl(item.url)] }"
                  >
                    <!-- 加载中 / 空状态引导 -->
                    <div v-if="isSummaryLoading(item.url)" class="flex items-center justify-center py-16">
                      <div class="flex flex-col items-center gap-3">
                        <div class="h-7 w-7 animate-spin rounded-full border-[3px] border-slate-600 border-t-[#ff5a5f]"></div>
                        <span class="text-xs text-slate-400">AI 分析完成后即可提问...</span>
                      </div>
                    </div>
                    <div v-else-if="!(questionAnswers[summaryIdForUrl(item.url)] || []).length && !streamingQA[summaryIdForUrl(item.url)]" class="text-center">
                      <div class="mb-2 text-3xl opacity-30">💬</div>
                      <p class="text-sm text-slate-400">输入问题，基于视频内容获取答案</p>
                    </div>

                    <div v-else class="space-y-6 py-2">
                      <!-- 对话气泡列表 -->
                      <template v-for="(qa, qaIdx) in questionAnswers[summaryIdForUrl(item.url)] || []" :key="qaIdx">
                        <!-- ── 用户消息 ── -->
                        <div class="flex justify-end group/bubble">
                          <div class="max-w-[78%] rounded-2xl rounded-br-md bg-[#ff5a5f] px-5 py-3.5 text-sm leading-7 text-white shadow-md shadow-[#ff5a5f]/10 transition-all duration-200 hover:bg-[#ef4444] hover:shadow-lg hover:shadow-[#ff5a5f]/20">
                            <p class="whitespace-pre-wrap break-words">{{ qa.question }}</p>
                          </div>
                        </div>

                        <!-- ── AI 回复 ── -->
                        <div
                          v-if="qa.answer"
                          class="flex flex-col gap-2 group/bubble"
                        >
                          <div class="flex justify-start">
                            <div class="max-w-[82%] rounded-2xl rounded-bl-md border border-[#f2ded3] bg-[#fff8f3] px-5 py-3.5 text-sm leading-7 text-slate-700 shadow-sm transition-all duration-200 hover:border-[#e7c6b9] hover:shadow-md">
                              <div class="prose prose-theme prose-sm max-w-none" v-html="renderMarkdown(qa.answer)"></div>
                              <!-- 操作按钮 -->
                              <div class="mt-3 flex items-center gap-1.5 justify-end opacity-70 group-hover/bubble:opacity-100 transition-opacity">
                                <button
                                  type="button"
                                  class="rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-700 hover:bg-slate-200 active:bg-slate-300 transition"
                                  @click="copyAnswerText(qa.answer)"
                                >复制</button>
                                <button
                                  type="button"
                                  class="rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-700 hover:bg-slate-200 active:bg-slate-300 transition"
                                  @click="regenerateAnswer(item.url, qa.question)"
                                >重新生成</button>
                                <button
                                  v-if="qa.references.length"
                                  type="button"
                                  class="rounded-lg px-2.5 py-1.5 text-xs font-medium transition"
                                  :class="expandedRefs[`${summaryIdForUrl(item.url)}_${qaIdx}`] ? 'bg-rose-400/15 text-rose-500' : 'text-slate-600 hover:bg-[#fff1ed] hover:text-slate-700'"
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
                            class="ml-1 rounded-2xl border border-[#f2ded3] bg-[#fff8f3] px-4 py-3 shadow-inner"
                          >
                            <p class="text-xs font-bold text-slate-400 mb-2.5 uppercase tracking-wide">参考素材</p>
                            <div class="space-y-2 max-h-32 overflow-y-auto custom-scroll">
                              <p
                                v-for="ref in qa.references"
                                :key="`${ref.start}-${ref.text}`"
                                class="text-xs leading-5 text-slate-500"
                              >
                                <span class="inline-block min-w-[40px] font-mono font-bold text-cyan-600">{{ formatTimestamp(ref.start) }}</span>
                                <span class="text-slate-400">·</span>
                                <span>{{ ref.text }}</span>
                              </p>
                            </div>
                          </div>
                        </div>
                      </template>

                      <div v-if="questionLoading[summaryIdForUrl(item.url)] && !streamingQA[summaryIdForUrl(item.url)]" class="flex justify-start">
                        <div class="inline-flex items-center gap-2 rounded-2xl rounded-bl-md border border-[#f2ded3] bg-[#fff8f3] px-4 py-3 text-xs font-bold text-slate-500 shadow-sm">
                          <span class="h-2 w-2 animate-pulse rounded-full bg-[#ff5a5f]"></span>
                          AI 正在思考...
                        </div>
                      </div>

                      <!-- 流式生成中的 AI 气泡 -->
                      <div v-if="streamingQA[summaryIdForUrl(item.url)]" class="flex justify-start">
                        <div class="max-w-[82%] rounded-2xl rounded-bl-md border border-rose-400/40 bg-[#fff8f3] px-5 py-3.5 text-sm leading-7 text-slate-700 shadow-md shadow-rose-400/5">
                          <p class="whitespace-pre-wrap break-words">
                            {{ streamingQA[summaryIdForUrl(item.url)] }}
                            <span class="typing-cursor"></span>
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>

                  <!-- 底部固定输入栏 -->
                  <div class="mt-2 flex items-center gap-3 border-t border-[#f2ded3] px-1 pt-3.5">
                    <input
                      v-model="questionInputs[summaryIdForUrl(item.url)]"
                      type="text"
                      class="min-w-0 flex-1 rounded-xl border border-[#f2ded3] bg-white px-4 py-3 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-[#ff9f80] focus:ring-2 focus:ring-[#ff5a5f]/10 disabled:cursor-not-allowed disabled:opacity-40"
                      placeholder="针对这个视频提问..."
                      :disabled="!summaryForUrl(item.url)?.result"
                      @keyup.enter="askSummaryForUrl(item.url)"
                    />
                    <button
                      type="button"
                      class="shrink-0 rounded-xl bg-[#ff5a5f] px-7 py-3 text-sm font-bold text-white shadow-sm shadow-[#ff5a5f]/20 transition hover:bg-[#ef4444] active:bg-[#dc2626] disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
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

        <div v-if="failedResults.length" class="mt-6 rounded-3xl border border-red-400/20 bg-red-500/10 p-5">
          <h3 class="font-black text-red-600">解析失败的链接</h3>
          <ul class="mt-3 space-y-2 text-sm text-red-600">
            <li v-for="item in failedResults" :key="item.url">{{ item.url }}：{{ item.error }}</li>
          </ul>
        </div>
      </section>

      <section id="pricing" class="border-b border-[#f2ded3] bg-white">
        <div class="mx-auto max-w-5xl px-4 py-14 sm:px-6 lg:px-8">
          <div class="text-center">
            <h2 class="text-3xl font-black text-slate-950 sm:text-4xl">选择适合你的视频下载方案</h2>
            <p class="mt-4 text-sm leading-7 text-slate-500">免费版每日 2 次 AI 总结，满足日常使用。VIP 解锁无限 AI 功能</p>
          </div>

          <div class="mt-10 grid gap-6 md:grid-cols-2">
            <article class="flex min-h-[460px] flex-col rounded-2xl border border-[#f2ded3] bg-white p-7 shadow-sm shadow-[#f1c7b8]/20">
              <div>
                <h3 class="text-xl font-black text-slate-950">免费版</h3>
                <p class="mt-2 text-base font-medium leading-7 text-slate-500">每日 2 次免费 AI 总结</p>
                <p class="mt-8 flex items-end gap-2 text-4xl font-black leading-none text-slate-950">
                  ¥0 <span class="pb-1 text-sm font-bold text-slate-400">/永久</span>
                </p>
              </div>
              <ul class="mt-9 space-y-4 text-base font-semibold leading-7 text-slate-500">
                <li class="grid grid-cols-[20px_1fr] items-start gap-4"><CheckCircle2 class="mt-[5px] h-4 w-4 text-[#14b8a6]" /><span>每日 2 次免费 AI 总结</span></li>
                <li class="grid grid-cols-[20px_1fr] items-start gap-4"><CheckCircle2 class="mt-[5px] h-4 w-4 text-[#14b8a6]" /><span>公开视频解析</span></li>
                <li class="grid grid-cols-[20px_1fr] items-start gap-4"><CheckCircle2 class="mt-[5px] h-4 w-4 text-[#14b8a6]" /><span>直链下载与云端处理下载</span></li>
                <li class="grid grid-cols-[20px_1fr] items-start gap-4"><CheckCircle2 class="mt-[5px] h-4 w-4 text-[#14b8a6]" /><span>多清晰度格式选择</span></li>
                <li class="grid grid-cols-[20px_1fr] items-start gap-4"><CheckCircle2 class="mt-[5px] h-4 w-4 text-[#14b8a6]" /><span>基础视频信息解析</span></li>
              </ul>
              <div class="mt-auto pt-8">
                <button type="button" class="w-full rounded-full border border-[#f2ded3] bg-[#fff8f3] px-5 py-3 text-base font-black text-slate-700" disabled>
                  当前方案
                </button>
              </div>
            </article>

            <article class="relative flex min-h-[460px] flex-col overflow-hidden rounded-2xl border border-[#ffc9bd] bg-[#fff8f3] p-7 text-slate-900 shadow-xl shadow-[#f1c7b8]/35">
              <div class="absolute -right-20 -top-20 h-52 w-52 rounded-full bg-[#ff5a5f]/10"></div>
              <div class="relative">
                <div class="flex items-start justify-between gap-4">
                  <div>
                    <h3 class="text-xl font-black text-slate-950">VIP 高级版</h3>
                    <p class="mt-2 text-base font-medium leading-7 text-slate-500">
                      AI 学习整理能力，永久解锁
                    </p>
                  </div>
                  <span class="rounded-full px-3 py-1 text-xs font-black" :class="authUser?.is_vip ? 'bg-emerald-50 text-emerald-700' : 'bg-[#ff5a5f] text-white'">
                    {{ authUser?.is_vip ? "已开通" : "推荐" }}
                  </span>
                </div>
                <p class="mt-8 flex flex-wrap items-end gap-2 text-4xl font-black leading-none text-slate-950">
                  ¥9.9 <span class="pb-1 text-sm font-bold text-[#ff5a5f]">永久</span>
                </p>
                <p v-if="authUser?.is_vip" class="mt-3 inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-black text-emerald-700">
                  <CheckCircle2 class="h-3.5 w-3.5" />
                  AI 功能已解锁
                </p>
              </div>
              <ul class="relative mt-9 space-y-4 text-base font-semibold leading-7 text-slate-600">
                <li class="grid grid-cols-[20px_1fr] items-start gap-4"><CheckCircle2 class="mt-[5px] h-4 w-4 text-[#ff5a5f]" /><span>AI 视频内容总结</span></li>
                <li class="grid grid-cols-[20px_1fr] items-start gap-4"><CheckCircle2 class="mt-[5px] h-4 w-4 text-[#ff5a5f]" /><span>章节大纲与核心要点</span></li>
                <li class="grid grid-cols-[20px_1fr] items-start gap-4"><CheckCircle2 class="mt-[5px] h-4 w-4 text-[#ff5a5f]" /><span>字幕整理与 TXT / SRT 导出</span></li>
                <li class="grid grid-cols-[20px_1fr] items-start gap-4"><CheckCircle2 class="mt-[5px] h-4 w-4 text-[#ff5a5f]" /><span>思维导图生成与导出</span></li>
                <li class="grid grid-cols-[20px_1fr] items-start gap-4"><CheckCircle2 class="mt-[5px] h-4 w-4 text-[#ff5a5f]" /><span>基于视频内容的 AI 问答</span></li>
              </ul>
              <div class="relative mt-auto pt-8">
                <button
                  type="button"
                  class="w-full rounded-full px-5 py-3 text-base font-black shadow-lg transition disabled:cursor-not-allowed"
                  :class="authUser?.is_vip ? 'border border-emerald-200 bg-emerald-50 text-emerald-700 shadow-emerald-500/10' : 'bg-[#ff5a5f] text-white shadow-[#ff5a5f]/25 hover:bg-[#ef4444]'"
                  :disabled="billingLoading || Boolean(authUser?.is_vip)"
                  @click="startVipCheckout"
                >
                  {{ authUser?.is_vip ? "已开通 VIP" : billingLoading ? "正在创建支付..." : "立即开通 VIP" }}
                </button>
              </div>
            </article>
          </div>
        </div>
      </section>

      <section id="features" class="mx-auto max-w-7xl px-4 py-14 sm:px-6 lg:px-8">
        <div class="text-center">
          <h2 class="text-3xl font-black text-slate-900 sm:text-4xl">为什么选择影知视频下载器</h2>
          <p class="mt-3 text-sm leading-7 text-slate-500">简单、快速、强大的在线视频下载体验，支持视频内容自动整理</p>
        </div>
        <div class="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <article
            v-for="card in featureCards"
            :key="card.title"
            class="rounded-[18px] border border-[#e5e7eb] bg-white p-6 shadow-sm transition hover:-translate-y-1 hover:border-[#dbeafe] hover:shadow-xl hover:shadow-slate-200/80"
          >
            <div
              class="mb-6 grid h-12 w-12 place-items-center rounded-xl"
              :class="{
                'bg-cyan-100 text-cyan-700': card.tone === 'cyan',
                'bg-rose-100 text-rose-700': card.tone === 'rose',
                'bg-amber-100 text-amber-700': card.tone === 'amber'
              }"
            >
              <component :is="card.icon" class="h-6 w-6" />
            </div>
            <h3 class="text-base font-black text-slate-900">{{ card.title }}</h3>
            <p class="mt-3 text-sm leading-7 text-slate-500">{{ card.text }}</p>
          </article>
        </div>
      </section>

      <section id="how-to-use" class="border-y border-[#f2ded3] bg-white">
        <div class="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
          <div class="text-center">
            <h2 class="text-3xl font-black text-slate-900 sm:text-4xl">如何使用影知下载视频</h2>
            <p class="mt-3 text-sm leading-7 text-slate-500">只需 3 步，即可下载并整理 YouTube、Bilibili、抖音等公开视频</p>
          </div>

          <div class="mt-10 grid gap-8 lg:grid-cols-3">
            <article v-for="(step, index) in useSteps" :key="step.title" class="relative text-center">
              <div class="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-blue-50 text-xl font-black text-blue-600">
                {{ index + 1 }}
              </div>
              <h3 class="mt-5 text-lg font-black text-slate-900">{{ step.title }}</h3>
              <p class="mx-auto mt-3 max-w-sm text-sm leading-7 text-slate-500">{{ step.text }}</p>
              <span v-if="index < useSteps.length - 1" class="absolute right-[-18px] top-6 hidden text-4xl font-light text-slate-200 lg:block">›</span>
            </article>
          </div>

          <p class="mt-10 text-center text-sm text-slate-400">全程无需注册登录，手机浏览器也能操作。请仅下载或整理你有权使用的公开视频内容。</p>
        </div>
      </section>

      <section id="comparison" class="bg-[#f8fafc]">
        <div class="mx-auto max-w-6xl px-4 py-16 sm:px-6 lg:px-8">
          <div class="text-center">
            <h2 class="text-3xl font-black text-slate-900 sm:text-4xl">影知与其他视频下载工具对比</h2>
            <p class="mt-3 text-sm leading-7 text-slate-500">一张表看清核心优势，选择更适合学习整理的视频工具</p>
          </div>

          <div class="mt-10 overflow-hidden rounded-3xl border border-[#e5e7eb] bg-white shadow-sm">
            <div class="overflow-x-auto">
              <table class="w-full min-w-[760px] text-left text-sm">
                <thead class="bg-slate-50 text-slate-900">
                  <tr>
                    <th class="px-6 py-4 font-black">功能对比</th>
                    <th class="px-6 py-4 text-center font-black text-blue-600">影知</th>
                    <th class="px-6 py-4 text-center font-black">其他在线工具</th>
                    <th class="px-6 py-4 text-center font-black">桌面下载软件</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100">
                  <tr v-for="row in comparisonRows" :key="row.label" class="text-slate-600">
                    <td class="px-6 py-4 font-bold text-slate-800">{{ row.label }}</td>
                    <td class="px-6 py-4 text-center font-semibold text-emerald-600">{{ row.ours }}</td>
                    <td class="px-6 py-4 text-center">{{ row.online }}</td>
                    <td class="px-6 py-4 text-center">{{ row.desktop }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div class="mt-10">
            <h2 class="text-2xl font-black text-slate-900">公开视频下载与视频总结常见问题</h2>
            <div class="mt-5 grid gap-4 lg:grid-cols-3">
              <article v-for="item in faqItems" :key="item.question" class="rounded-[20px] border border-[#e5e7eb] bg-white p-5 shadow-sm">
                <h3 class="text-base font-black leading-7 text-slate-900">{{ item.question }}</h3>
                <p class="mt-3 text-sm leading-7 text-slate-500">{{ item.answer }}</p>
              </article>
            </div>
          </div>
        </div>
      </section>
    </main>

    <div v-if="authModalOpen" class="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 px-4 backdrop-blur-sm">
      <section class="w-full max-w-md rounded-3xl bg-white p-6 shadow-2xl">
        <div class="flex items-start justify-between gap-4">
          <div>
            <p class="inline-flex items-center gap-1.5 text-sm font-bold text-[#ff5a5f]">
              <User class="h-4 w-4" />
              {{ authMode === "login" ? "登录账号" : "注册账号" }}
            </p>
            <h2 class="mt-2 text-2xl font-black text-slate-900">
              {{ authMode === "login" ? "欢迎回来" : "创建你的账号" }}
            </h2>
          </div>
          <button type="button" class="grid h-9 w-9 place-items-center rounded-full border border-[#f2ded3] text-slate-500 hover:bg-[#fff1ed]" @click="authModalOpen = false" aria-label="关闭">
            <X class="h-4 w-4" />
          </button>
        </div>

        <form class="mt-6 space-y-4" @submit.prevent="submitAuth">
          <label class="block text-sm font-bold text-slate-700">
            邮箱
            <input
              v-model="authEmail"
              type="email"
              autocomplete="email"
              class="mt-2 w-full rounded-2xl border border-[#f2ded3] bg-white px-4 py-3 text-sm text-slate-800 outline-none focus:border-[#ff9f80] focus:ring-4 focus:ring-[#ff5a5f]/10"
              placeholder="you@example.com"
            />
          </label>

          <!-- 登录方式切换（仅登录模式） -->
          <div v-if="authMode === 'login'" class="flex gap-2">
            <button type="button" class="flex-1 rounded-full px-3 py-1.5 text-xs font-bold transition" :class="!authUseCode ? 'bg-[#ff5a5f] text-white' : 'bg-slate-100 text-slate-500'" @click="authUseCode = false">密码登录</button>
            <button type="button" class="flex-1 rounded-full px-3 py-1.5 text-xs font-bold transition" :class="authUseCode ? 'bg-[#ff5a5f] text-white' : 'bg-slate-100 text-slate-500'" @click="authUseCode = true">验证码登录</button>
          </div>

          <!-- 密码（注册或密码登录时显示） -->
          <label v-if="authMode === 'register' || !authUseCode" class="block text-sm font-bold text-slate-700">
            密码
            <input
              v-model="authPassword"
              type="password"
              :autocomplete="authMode === 'login' ? 'current-password' : 'new-password'"
              class="mt-2 w-full rounded-2xl border border-[#f2ded3] bg-white px-4 py-3 text-sm text-slate-800 outline-none focus:border-[#ff9f80] focus:ring-4 focus:ring-[#ff5a5f]/10"
              placeholder="至少 8 位"
            />
          </label>

          <!-- 验证码（注册或验证码登录） -->
          <label v-if="authMode === 'register' || authUseCode" class="block text-sm font-bold text-slate-700">
            验证码
            <div class="mt-2 flex gap-2">
              <input
                v-model="authCode"
                type="text"
                inputmode="numeric"
                maxlength="6"
                autocomplete="one-time-code"
                class="flex-1 rounded-2xl border border-[#f2ded3] bg-white px-4 py-3 text-sm text-slate-800 outline-none focus:border-[#ff9f80] focus:ring-4 focus:ring-[#ff5a5f]/10"
                placeholder="6 位数字"
              />
              <button
                type="button"
                class="shrink-0 rounded-full bg-blue-500 px-4 py-3 text-xs font-bold text-white hover:bg-blue-600 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
                :disabled="codeSending || codeCountdown > 0 || !authEmail.trim()"
                @click="sendAuthCode"
              >
                {{ codeCountdown > 0 ? `${codeCountdown}s` : codeSending ? "发送中..." : "发送验证码" }}
              </button>
            </div>
          </label>

          <p v-if="authError" class="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-600">{{ authError }}</p>
          <button
            type="submit"
            class="inline-flex w-full items-center justify-center gap-2 rounded-full bg-[#ff5a5f] px-5 py-3 text-sm font-black text-white hover:bg-[#ef4444] disabled:cursor-not-allowed disabled:bg-slate-200"
            :disabled="authSubmitting"
          >
            <User class="h-4 w-4" />
            {{ authSubmitting ? "处理中..." : authMode === "login" ? "登录" : "注册并登录" }}
          </button>
        </form>

        <div class="mt-5 rounded-2xl bg-[#fff1ed] px-4 py-3 text-sm leading-6 text-[#b91c1c]">
          VIP 会绑定到这个邮箱账号。请使用你之后还会继续使用的邮箱注册。
        </div>
        <button
          type="button"
          class="mt-4 w-full text-sm font-bold text-slate-500 hover:text-[#ff5a5f]"
          @click="authMode = authMode === 'login' ? 'register' : 'login'; authError = ''"
        >
          {{ authMode === "login" ? "没有账号？立即注册" : "已有账号？去登录" }}
        </button>
      </section>
    </div>

    <div v-if="profileModalOpen" class="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 px-4 backdrop-blur-sm">
      <section class="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-3xl bg-white p-6 shadow-2xl custom-scroll">
        <div class="flex items-start justify-between gap-4">
          <div>
            <p class="inline-flex items-center gap-1.5 text-sm font-bold text-[#ff5a5f]">
              <Settings class="h-4 w-4" />
              个人中心
            </p>
            <h2 class="mt-2 text-2xl font-black text-slate-900">账号资料与支付流水</h2>
          </div>
          <button type="button" class="grid h-9 w-9 place-items-center rounded-full border border-[#f2ded3] text-slate-500 hover:bg-[#fff1ed]" @click="profileModalOpen = false" aria-label="关闭">
            <X class="h-4 w-4" />
          </button>
        </div>

        <div class="mt-6 grid gap-5 lg:grid-cols-[280px_1fr]">
          <aside class="rounded-2xl border border-[#f2ded3] bg-[#fff8f3] p-5">
            <div class="flex items-center gap-4">
              <span class="grid h-16 w-16 shrink-0 place-items-center overflow-hidden rounded-full bg-white text-[#ff5a5f] shadow-sm">
                <img v-if="profileAvatarSrc" :src="profileAvatarSrc" alt="用户头像预览" class="h-full w-full object-cover" />
                <User v-else class="h-7 w-7" />
              </span>
              <div class="min-w-0">
                <p class="truncate text-lg font-black text-slate-900">{{ profileDisplayName }}</p>
                <p class="truncate text-xs font-semibold text-slate-500">{{ authUser?.email }}</p>
              </div>
            </div>
            <div class="mt-5 rounded-2xl border px-4 py-3 text-sm font-black" :class="authUser?.is_vip ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'">
              <span class="inline-flex items-center gap-2">
                <Sparkles class="h-4 w-4" />
                {{ authUser?.is_vip ? "VIP 已开通" : `免费用户 · 今日剩余 ${authUser?.daily_ai_remaining ?? 0} 次` }}
              </span>
              <p v-if="authUser?.vip_activated_at" class="mt-2 text-xs font-semibold opacity-80">
                开通时间：{{ formatPaymentTime(authUser.vip_activated_at) }}
              </p>
            </div>
          </aside>

          <div class="space-y-5">
            <section class="rounded-2xl border border-[#f2ded3] bg-white p-5">
              <h3 class="text-base font-black text-slate-900">编辑主页资料</h3>
              <div class="mt-4 grid gap-4">
                <label class="block text-sm font-bold text-slate-700">
                  昵称
                  <input
                    v-model="profileName"
                    type="text"
                    maxlength="32"
                    class="mt-2 w-full rounded-2xl border border-[#f2ded3] bg-white px-4 py-3 text-sm text-slate-800 outline-none focus:border-[#ff9f80] focus:ring-4 focus:ring-[#ff5a5f]/10"
                    placeholder="给自己起个名字"
                  />
                </label>
                <label class="block text-sm font-bold text-slate-700">
                  头像
                  <span class="mt-2 flex flex-col gap-3 rounded-2xl border border-dashed border-[#ffc9bd] bg-[#fff8f3] p-4 sm:flex-row sm:items-center sm:justify-between">
                    <span class="text-xs font-semibold leading-5 text-slate-500">上传 JPG、PNG 或 WEBP，最大 2MB。</span>
                    <span class="inline-flex w-fit cursor-pointer items-center justify-center gap-2 rounded-full bg-white px-4 py-2 text-xs font-black text-[#ff5a5f] shadow-sm hover:bg-[#fff1ed]">
                      <User class="h-4 w-4" />
                      选择图片
                      <input type="file" accept="image/png,image/jpeg,image/webp" class="sr-only" @change="onAvatarFileChange" />
                    </span>
                  </span>
                </label>
              </div>
              <p v-if="profileError" class="mt-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-600">{{ profileError }}</p>
              <div class="mt-5 flex flex-col gap-3 sm:flex-row sm:justify-end">
                <button type="button" class="rounded-full border border-[#f2ded3] px-5 py-3 text-sm font-bold text-slate-600 hover:bg-[#fff1ed]" @click="profileModalOpen = false">关闭</button>
                <button type="button" class="inline-flex items-center justify-center gap-2 rounded-full bg-[#ff5a5f] px-5 py-3 text-sm font-black text-white hover:bg-[#ef4444] disabled:cursor-not-allowed disabled:bg-slate-200" :disabled="profileSaving" @click="saveProfile">
                  <Settings class="h-4 w-4" />
                  {{ profileSaving ? "保存中..." : "保存资料" }}
                </button>
              </div>
            </section>

            <section class="rounded-2xl border border-[#f2ded3] bg-white p-5">
              <div class="flex items-center justify-between gap-3">
                <h3 class="inline-flex items-center gap-2 text-base font-black text-slate-900">
                  <CreditCard class="h-4 w-4 text-[#ff5a5f]" />
                  支付流水
                </h3>
                <button type="button" class="rounded-full px-3 py-1.5 text-xs font-black text-[#ff5a5f] hover:bg-[#fff1ed]" @click="loadPaymentHistory">
                  刷新
                </button>
              </div>
              <div v-if="paymentsLoading" class="mt-4 rounded-2xl bg-[#fff8f3] px-4 py-6 text-center text-sm font-bold text-slate-500">
                正在加载支付流水...
              </div>
              <div v-else-if="!paymentHistory.length" class="mt-4 rounded-2xl bg-[#fff8f3] px-4 py-6 text-center text-sm font-bold text-slate-500">
                暂无支付流水
              </div>
              <div v-else class="mt-4 space-y-3">
                <article v-for="payment in paymentHistory" :key="payment.id" class="rounded-2xl border border-[#f2ded3] bg-[#fff8f3] p-4">
                  <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div class="min-w-0">
                      <p class="text-base font-black text-slate-900">{{ formatPaymentAmount(payment) }}</p>
                      <p class="mt-1 truncate text-xs font-semibold text-slate-500">流水号：{{ shortPaymentId(payment) }}</p>
                    </div>
                    <div class="flex shrink-0 flex-wrap items-center gap-2">
                      <span class="w-fit rounded-full border px-3 py-1 text-xs font-black" :class="paymentStatusClass(payment.status)">
                        {{ paymentStatusLabel(payment.status) }}
                      </span>
                      <button
                        v-if="canRefundPayment(payment)"
                        type="button"
                        class="rounded-full border border-rose-200 bg-white px-3 py-1 text-xs font-black text-rose-600 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
                        :disabled="refundingPayments[payment.id]"
                        @click="requestRefund(payment)"
                      >
                        {{ refundingPayments[payment.id] ? "退款中..." : "申请退款" }}
                      </button>
                    </div>
                  </div>
                  <div class="mt-3 flex flex-wrap gap-2 text-xs font-semibold text-slate-500">
                    <span>创建：{{ formatPaymentTime(payment.created_at) }}</span>
                    <span>更新：{{ formatPaymentTime(payment.updated_at) }}</span>
                    <span v-if="payment.refund_requested_at">退款申请：{{ formatPaymentTime(payment.refund_requested_at) }}</span>
                    <span v-if="payment.refunded_at">退款完成：{{ formatPaymentTime(payment.refunded_at) }}</span>
                  </div>
                  <p v-if="payment.refund_error" class="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-600">
                    {{ payment.refund_error }}
                  </p>
                </article>
              </div>
            </section>
          </div>
        </div>
      </section>
    </div>

    <div v-if="showComplianceModal" class="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 px-4 backdrop-blur-sm">
      <section class="w-full max-w-lg rounded-3xl bg-white p-6 shadow-2xl">
        <p class="text-sm font-bold text-red-600">合规使用确认</p>
        <h2 class="mt-2 text-2xl font-black text-slate-900">请确认内容使用权</h2>
        <p class="mt-4 text-sm leading-7 text-slate-600">
          请仅解析、下载或导出你有权使用的视频内容。本平台面向授权内容分析、学习整理和内部资料归档场景，不支持处理私密、受版权保护或需要绕过访问控制的内容。
        </p>
        <label class="mt-5 flex items-start gap-3 rounded-2xl border border-[#f2ded3] bg-[#fff8f3] p-4 text-sm leading-6 text-slate-700">
          <input v-model="complianceChecked" type="checkbox" class="mt-1 h-4 w-4 rounded border-slate-300 text-[#ff5a5f]" />
          <span>我已阅读并确认拥有相关内容的合法使用权，愿意遵守平台和版权方规则。</span>
        </label>
        <div class="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-end">
          <button type="button" class="rounded-full border border-[#f2ded3] px-5 py-3 text-sm font-bold text-slate-600 hover:bg-[#fff1ed]" @click="showComplianceModal = false">取消</button>
          <button type="button" class="rounded-full bg-[#ff5a5f] px-5 py-3 text-sm font-black text-white hover:bg-[#ef4444] disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500" :disabled="!complianceChecked" @click="confirmCompliance">确认并开始解析</button>
        </div>
      </section>
    </div>

    <div v-if="infoDrawerOpen" class="fixed inset-0 z-40">
      <div class="absolute inset-0 bg-slate-950/30" @click="infoDrawerOpen = false"></div>
      <aside class="absolute right-0 top-0 h-full w-full max-w-xl overflow-y-auto bg-white p-6 shadow-2xl">
        <div class="flex items-start justify-between gap-4">
          <div>
            <p class="inline-flex items-center gap-1.5 text-sm font-bold text-[#ff5a5f]">
              <HelpCircle class="h-4 w-4" />
              帮助与合规
            </p>
            <h2 class="mt-1 text-2xl font-black text-slate-900">平台与下载说明</h2>
          </div>
          <button type="button" class="grid h-9 w-9 place-items-center rounded-full border border-[#f2ded3] text-slate-500 hover:bg-[#fff1ed]" @click="infoDrawerOpen = false" aria-label="关闭">
            <X class="h-4 w-4" />
          </button>
        </div>

        <div class="mt-6 flex flex-wrap gap-2 rounded-2xl border border-[#f2ded3] bg-[#fff8f3] p-1">
          <button type="button" class="inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-bold" :class="activeDrawerTab === 'platforms' ? 'bg-white text-[#ff5a5f] shadow-sm' : 'text-slate-500'" @click="activeDrawerTab = 'platforms'">
            <Globe2 class="h-4 w-4" />
            支持平台
          </button>
          <button type="button" class="inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-bold" :class="activeDrawerTab === 'download' ? 'bg-white text-[#ff5a5f] shadow-sm' : 'text-slate-500'" @click="activeDrawerTab = 'download'">
            <Download class="h-4 w-4" />
            下载模式
          </button>
          <button type="button" class="inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-bold" :class="activeDrawerTab === 'compliance' ? 'bg-white text-[#ff5a5f] shadow-sm' : 'text-slate-500'" @click="activeDrawerTab = 'compliance'">
            <ShieldCheck class="h-4 w-4" />
            合规边界
          </button>
        </div>

        <section v-if="activeDrawerTab === 'platforms'" class="mt-6 space-y-5">
          <div>
            <h3 class="text-sm font-black text-slate-900">国内平台</h3>
            <div class="mt-3 grid grid-cols-2 gap-3">
              <div v-for="platform in domesticPlatforms" :key="platform" class="rounded-2xl border border-[#f2ded3] bg-[#fff8f3] px-4 py-3 text-sm font-bold text-slate-700">{{ platform }}</div>
            </div>
          </div>
          <div>
            <h3 class="text-sm font-black text-slate-900">海外平台</h3>
            <div class="mt-3 grid grid-cols-2 gap-3">
              <div v-for="platform in overseasPlatforms" :key="platform" class="rounded-2xl border border-[#f2ded3] bg-[#fff8f3] px-4 py-3 text-sm font-bold text-slate-700">{{ platform }}</div>
            </div>
          </div>
          <p class="rounded-2xl bg-cyan-50 p-4 text-sm leading-7 text-cyan-800">平台能力以公开视频可访问策略为准。部分长视频或受限链接可能需要更长处理时间，也可能无法解析。</p>
        </section>

        <section v-else-if="activeDrawerTab === 'download'" class="mt-6 space-y-4">
          <div class="rounded-2xl border border-amber-100 bg-amber-50 p-4">
            <h3 class="inline-flex items-center gap-2 font-black text-amber-900">
              <Zap class="h-5 w-5" />
              极速下载
            </h3>
            <p class="mt-2 text-sm leading-7 text-amber-800">适合可直接获取的公开视频资源，由浏览器处理下载，速度快，不占用云端存储。</p>
          </div>
          <div class="rounded-2xl border border-[#f2ded3] bg-[#fff8f3] p-4">
            <h3 class="inline-flex items-center gap-2 font-black text-slate-900">
              <Cloud class="h-5 w-5" />
              云端处理下载
            </h3>
            <p class="mt-2 text-sm leading-7 text-slate-600">适合复杂链接，后台处理后提供文件入口，可查看任务进度和失败原因。</p>
          </div>
        </section>

        <section v-else class="mt-6 space-y-3 text-sm leading-7 text-slate-600">
          <p class="flex items-start gap-2 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-amber-800">
            <ShieldCheck class="mt-1 h-4 w-4 shrink-0" />
            <span>请仅处理你拥有授权或合法使用权的视频内容。</span>
          </p>
          <p>平台不支持解析私密内容，不支持绕过版权保护、登录限制、验证码或访问控制。</p>
          <p>下载与导出能力仅用于授权内容分析、学习整理、内部资料归档等合规场景。</p>
        </section>
      </aside>
    </div>
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
  background: #cbd5e1;
  border-radius: 4px;
}
.custom-scroll::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}
.custom-scroll {
  scrollbar-width: thin;
  scrollbar-color: #cbd5e1 transparent;
}
</style>
