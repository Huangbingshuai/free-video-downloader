# 影知

基于 FastAPI、yt-dlp、Vue3、Vite 和 Tailwind CSS 的公开视频下载与 AI 总结网站 MVP。当前已完成阶段 1 到阶段 3：后端核心 API、前端页面、解析到下载任务的联调闭环。

## 功能范围

- 批量 URL 解析。
- 抖音、爱奇艺、TikTok、Bilibili 等公开视频链接解析。
- 视频信息和格式列表展示。
- 直链下载优先。
- 服务端下载任务兜底。
- 下载进度轮询。
- 完成文件下载。
- AI 视频学习分析：基于平台字幕 / 自动字幕生成摘要、转录文本、思维导图和视频问答。
- VIP 能力、平台能力和风险提示展示。

首版仅支持 yt-dlp 可解析的公开内容，不支持 DRM 绕过、验证码绕过、cookies 上传或反风控能力。

AI 总结第一版仅支持可提取平台字幕或自动字幕的视频。用户在页面填写自己的 DeepSeek API Key，服务端只在本次请求中临时使用，不保存到任务结果。

抖音和爱奇艺使用内置解析器（无需 Cookie），直接通过公开接口获取视频信息和下载链接，无需用户登录。

抖音使用说明：可以直接粘贴抖音分享文本，前端会自动提取其中的链接。若内容需要登录态或平台验证，服务端会拒绝处理，不会要求用户提供 Cookie。

可选抖音外部解析 provider：

```bash
set DOUYIN_RESOLVER_API_BASE=http://127.0.0.1:8001
set DOUYIN_RESOLVER_VIDEO_DATA_PATH=/api/hybrid/video_data
```

可选爱奇艺外部解析 provider：

```bash
set IQIYI_RESOLVER_API_BASE=http://127.0.0.1:8002
set IQIYI_RESOLVER_API_PATH=/api/parse
```

该 provider 只会收到用户粘贴的公开视频 URL，不会收到用户 Cookie。适合接入自部署、合规的公开链接解析服务；不要把用户登录态交给公共网站服务端。

## 启动后端

```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

## 启动前端

```bash
cd frontend
npm install
npm run dev
```

打开：

```text
http://127.0.0.1:5173
```

## 测试

后端：

```bash
cd backend
set PYTHONDONTWRITEBYTECODE=1
python -B -m pytest -q -o cache_dir=%TEMP%\pytest-cache-fvd
```

前端：

```bash
cd frontend
npm run build
```

## 文档

- `docs/requirements-analysis.md`：需求分析、边界和阶段规划。
- `docs/solution-design.md`：架构、API、下载策略和测试策略。
- `docs/implementation-summary.md`：实现总结、内置解析器原理、API 汇总。
