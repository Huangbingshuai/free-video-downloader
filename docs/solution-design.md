# 万能视频下载网站方案设计

## 技术架构

项目采用前后端分离：

- 后端：FastAPI + yt-dlp，负责 URL 解析、下载任务、直链探测、文件响应。
- 前端：Vue3 + Vite + Tailwind CSS，负责输入、解析结果、格式选择、任务进度和下载入口。
- 存储：首版只使用本地文件系统和内存任务表，不接数据库。

目录结构：

```text
backend/
  app/
    main.py
    schemas.py
    routes/videos.py
    services/job_store.py
    services/ytdlp_service.py
  tests/
frontend/
  src/
docs/
```

## 后端接口

### POST /api/analyze

请求：

```json
{
  "urls": ["https://example.com/video"]
}
```

响应包含每个 URL 的解析结果。成功项返回标题、封面、平台、时长、格式列表和字幕摘要；失败项返回错误信息。

### POST /api/jobs

创建服务端下载任务。

```json
{
  "url": "https://example.com/video",
  "format_id": "best",
  "download_mode": "proxy"
}
```

响应返回 `job_id`，前端随后轮询任务状态。

### GET /api/jobs/{job_id}

返回任务状态、进度百分比、速度、总大小、错误信息和完成文件。

### GET /api/direct

查询参数包含 `url` 和可选 `format_id`。后端通过 yt-dlp 解析直链并做基础探测。可用时返回 302 重定向；不可用时返回 409，前端提示用户改用服务端下载。

### GET /api/files/{job_id}/{file_id}

返回服务端已下载文件。小文件使用 `FileResponse`，大于 500MB 的文件使用 `StreamingResponse` 分块传输。

## 任务状态模型

任务状态保存在内存中：

- `queued`：任务已创建。
- `running`：yt-dlp 正在下载。
- `success`：任务完成，文件可下载。
- `failed`：任务失败，记录错误信息。

任务数据包含 URL、格式、进度、速度、已下载大小、总大小、输出文件列表和错误。

## 下载服务设计

yt-dlp 使用 Python API 调用，避免解析命令行输出：

- `extract_info(url, download=False)` 用于解析。
- `YoutubeDL(...).download([url])` 用于服务端下载。
- `progress_hooks` 更新内存任务进度。
- 抖音、TikTok 等公开视频优先使用 yt-dlp 官方 extractor，不使用用户 Cookie、公共账号池或服务端扫码登录。
- 对 yt-dlp 返回的登录态、Cookie、验证码类错误进行友好化处理，明确提示“服务端不接收、不代管平台 Cookie”。
- 可选配置 `DOUYIN_RESOLVER_API_BASE` 接入自部署抖音公开链接解析 provider。该 provider 只接收公开视频 URL，默认兼容 `/api/hybrid/video_data?url=...&minimal=false` 形态，返回直链后由本服务端流式下载或直链跳转。

下载文件保存到 `backend/downloads/{job_id}/`。文件名由 yt-dlp 输出模板生成，并在后端做安全处理。文件接口只允许访问任务表中登记的文件，避免路径穿越。

## 前端设计

页面参考 `ai.codefather.cn/painting` 的视觉方向：白底、蓝色主色、居中强标题、圆角输入框、卡片网格、清晰商业化价值表达。

主要区域：

- 顶部导航：品牌、平台能力、VIP、风险提示。
- 首屏工具区：批量 URL 输入、解析按钮、卖点标签。
- 解析结果区：视频卡片、格式选择、直链下载、服务端下载。
- 任务区：进度条、状态、下载速度、错误、完成文件入口。
- 商业引导区：批量增强、字幕翻译、AI 总结、云端历史记录。
- 平台展示区：展示常见平台，并说明以 yt-dlp 实际支持为准。

## 测试策略

后端：

- mock yt-dlp 服务，测试解析、任务创建、状态轮询。
- 测试文件接口不能访问任务外文件。
- 测试大文件分支返回流式响应。

前端：

- 构建验证。
- 桌面和移动端浏览器检查布局、文字和按钮不溢出。

集成：

- 使用公开视频链接验证解析、格式选择和下载流程。
- 当直链不可用时，前端可以回退到服务端下载任务。
