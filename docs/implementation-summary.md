# 万能视频下载助手 — 实现总结

## 项目概述

万能视频下载助手是一个轻量级公开视频下载网站，基于 FastAPI + yt-dlp 后端和 Vue3 + Vite + Tailwind CSS 前端。用户粘贴公开视频链接后，系统完成解析、格式选择和下载，移动端和桌面端均可使用。

首版定位为学习和技术验证用途，基于 yt-dlp 封装通用平台解析能力，并针对抖音、爱奇艺等 yt-dlp 无法可靠解析的平台实现了**内置解析器**，无需用户提供 Cookie 或登录态。

## 技术架构

```
backend/                          frontend/
  app/                              src/
    main.py          ← FastAPI        App.vue         ← 主页面（单页应用）
    schemas.py       ← Pydantic       main.ts         ← 入口
    routes/videos.py ← API 路由       styles.css      ← Tailwind
    services/
      ytdlp_service.py    ← yt-dlp 封装，解析/下载/进度
      douyin_resolver.py  ← 抖音内置解析器（无 Cookie）
      iqiyi_resolver.py   ← 爱奇艺内置解析器（无 Cookie）
      job_store.py        ← 内存任务表
  tests/
    test_videos.py
    test_douyin_resolver.py
docs/
  requirements-analysis.md  ← 需求分析
  solution-design.md        ← 方案设计
  implementation-summary.md ← 本文档
```

- **后端**: FastAPI + uvicorn，端口 8000
- **前端**: Vue3 + Vite + TypeScript + Tailwind CSS，端口 5173
- **存储**: 首版使用内存任务表 + 本地文件系统，不接数据库

## 核心功能

### 1. URL 解析

`POST /api/analyze` 接收批量 URL（最多 20 个），返回视频标题、封面、时长、平台、可用格式列表和字幕摘要。

解析链路优先级：
1. 抖音内置解析器（`douyin_resolver.py`）
2. 爱奇艺内置解析器（`iqiyi_resolver.py`）
3. yt-dlp 通用解析器（兜底）

### 2. 下载策略

| 策略 | 条件 | 实现 |
|------|------|------|
| 直链 302 重定向 | 直链可用且未过期 | `GET /api/direct` → 302 |
| 服务端代理下载 | 直链不可用或防盗链 | `POST /api/jobs` → 后台下载 |
| m3u8 流下载 | 爱奇艺等 m3u8 流 | ffmpeg 子进程下载 + 进度解析 |
| 大文件流式响应 | > 500MB | `StreamingResponse` 分块传输 |

### 3. 下载进度

- yt-dlp: 通过 `progress_hooks` 回调更新内存任务进度
- m3u8/ffmpeg: 解析 stderr 中的 `Duration` 和 `time` 字段计算进度
- 直链下载: 基于 `Content-Length` 和已下载字节数计算
- 前端轮询 `GET /api/jobs/{job_id}` 每 1.5 秒更新进度条

### 4. AI 视频学习分析

新增字幕驱动的 AI 学习分析模块，第一版仅支持可提取平台字幕或自动字幕的视频，不做无字幕音频转写。用户在前端填写自己的 DeepSeek API Key，服务端只在本次请求/后台任务中临时使用，不写入任务结果。

能力包括：

- 视频总结摘要：一句话概览、章节大纲、核心知识点、行动建议和术语解释。
- 字幕 / 转录文本展示：统一解析 `vtt`、`srt`、`json3` 为带时间戳片段。
- 思维导图可视化：后端生成树形结构，前端以层级图展示。
- AI 问答：基于已生成的摘要和字幕上下文回答问题，并返回引用字幕片段。

新增模块：

```text
backend/app/routes/summaries.py
backend/app/services/summary_store.py
backend/app/services/transcript_service.py
backend/app/services/deepseek_service.py
```

## 内置平台解析器

### 抖音 (DouyinBuiltinParser)

**解决的问题**: yt-dlp 解析抖音公开视频需要 Cookie 或登录态，本解析器完全无需 Cookie。

**技术原理**:
1. 解析 URL 提取 `aweme_id`（支持 `/video/{id}`、`/share/video/{id}`、`?modal_id=xxx`、`v.douyin.com` 短链接）
2. 使用移动端 UA 请求 `iesdouyin.com/share/video/{id}/` 公开分享页
3. 从 HTML 中提取 `window._ROUTER_DATA` JSON（SSR 渲染数据）
4. 递归遍历 JSON 树找到包含 `aweme_id` + `video` 的对象
5. 提取 `play_addr` 并将 `playwm` 替换为 `play`（去水印）
6. 检测 `filter_list` 中的封禁原因，抛出明确错误（私密/删除/违规）

**支持特性**:
- 去水印直链
- 图片集（图集）解析
- 私密/删除视频的友好错误提示
- 可选外部解析器（`DOUYIN_RESOLVER_API_BASE` 环境变量）

### 爱奇艺 (IqiyiBuiltinParser)

**解决的问题**: yt-dlp 无法解析爱奇艺的 JS 渲染页面（找不到 tvid）。

**技术原理**:
1. **tvid 解码**: 逆向 iQiyi JavaScript 中的 XOR + base36 编码算法，从 URL 路径（如 `v_2f1sx772wzo`）解码出数字 tvid
2. **API 签名**: 计算 `video_id = md5(tvid)`，生成 `sc = md5(timestamp + API_KEY + tvid)` 签名
3. **流获取**: 调用 `cache.m.iqiyi.com/jp/tmts/{tvid}/{video_id}/` API 获取 vidl 流列表
4. **DRM 试看检测**: 下载 m3u8 播放列表，对比 `EXTINF` 总时长与 API 声明的时长，若差 50% 以上则标记为 [试看] 并警告用户
5. **元数据获取**: 编码 tvid 回 video_code，用 Googlebot UA 请求 `v_{code}.html` 页面提取标题和 og:image 封面

**支持特性**:
- 多 URL 格式: `v_XXX.html`、`w_XXX.html`、`?tvid=xxx`、`qy.net` 短链接
- 质量映射: 96→流畅240P, 1→标清360P, 4→超清720P, 5→蓝光1080P 等
- VIP/DRM 试看检测和警告
- m3u8 流 ffmpeg 下载，实时进度上报
- 封面图和标题提取（SSR 页面抓取）
- 可选外部解析器（`IQIYI_RESOLVER_API_BASE` 环境变量）

### 关键算法

**tvid 编解码**（XOR + base36）:

```
解码: video_code → base36 decode → binary → XOR with MAGIC → tvid
编码: tvid → XOR with MAGIC → binary → base36 encode → video_code
```

MAGIC = `0x75706971676c`，用于 XOR 混淆。tvid < 900000 时会执行 `100 * (n + 900000)` 调整。

`_encode_tvid()` 是新增的逆向函数，用于从 tvid 恢复 video_code，从而构造正确的爱奇艺视频页面 URL 获取标题和封面。

## API 接口汇总

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/analyze` | 批量解析视频 URL |
| POST | `/api/jobs` | 创建服务端下载任务 |
| GET | `/api/jobs/{job_id}` | 查询任务状态和进度 |
| GET | `/api/direct?url=&format_id=` | 直链探测和 302 重定向 |
| GET | `/api/files/{job_id}/{file_id}` | 下载已完成文件 |
| POST | `/api/summaries` | 创建 AI 视频学习分析任务 |
| GET | `/api/summaries/{summary_id}` | 查询 AI 分析任务和结果 |
| POST | `/api/summaries/{summary_id}/questions` | 针对视频内容提问 |

## 前端设计

单页应用（`App.vue`），主要区域：

- **顶部导航**: 品牌、平台能力、VIP 增强、风险提示锚点
- **首屏工具区**: 多行文本输入（支持粘贴带文字的分享内容，自动提取 URL）、解析按钮
- **解析结果区**: 视频卡片网格（封面、标题、时长），格式下拉选择，直链/服务端下载切换
- **任务进度区**: 进度条、速度、大小，完成文件下载入口
- **平台展示区**: 抖音、爱奇艺、TikTok、YouTube、Bilibili 等 9 个平台标签
- **风险提示区**: 版权和合规提示

**URL 智能提取**: 前端正则 `/https?:\/\/[^\s，。；、"'<>]+/g` 自动从混合文本中提取 URL，支持直接粘贴抖音/B 站分享文案。

## 错误处理

- **Cookie/登录错误**: 正则匹配 `cookie|cookies-from-browser|login|登录|验证码` 等关键词，重写为友好提示："服务端不接收、不代管平台 Cookie"
- **ANSI 颜色码**: 清理 yt-dlp 错误信息中的 ANSI 转义序列
- **抖音不可用视频**: 解析 `filter_list` 返回具体原因（私密、删除、违规等）
- **爱奇艺 VIP/DRM**: 在格式标签中标注 `[试看X分钟]` 警告
- **超时保护**: 解析超时 25 秒，下载超时继承各模块设置

## 测试

后端 10 个测试全部通过：

```
tests/test_douyin_resolver.py: 2 tests (URL 识别、外部解析器映射)
tests/test_videos.py:           8 tests (mock 解析、任务生命周期、
                                 文件安全、大文件流式、回退目录、
                                 格式规范化、ANSI 清理、Cookie 错误重写)
```

## 风险边界

- 仅支持 yt-dlp 可解析的公开视频链接
- 不提供 DRM 绕过、验证码绕过、Cookie 上传或反风控能力
- 用户自行承担平台规则、版权合规和账号风险
- 本项目定位为学习和技术研究用途

## 快速启动

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 前端
cd frontend
npm install
npm run dev
```

访问 `http://127.0.0.1:5173`
