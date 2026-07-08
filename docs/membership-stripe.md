# 会员购买与 Stripe 测试指南

## 功能口径

- VIP 是一次性买断，前端展示 `¥9.9 永久`。
- VIP 只限制 AI 模块：AI 总结、章节大纲、字幕整理、思维导图和视频问答。
- 视频解析、直链下载和云端处理下载保持免费。

## 后端环境变量

在 `backend/.env` 中配置：

```bash
AUTH_SECRET_KEY=change-me-to-a-long-random-string
AUTH_COOKIE_SECURE=false
PUBLIC_APP_URL=http://127.0.0.1:5173
FVD_DB_PATH=./downloads/app.sqlite3

STRIPE_API_KEY=rk_test_or_sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
STRIPE_VIP_PRICE_ID=price_xxx
STRIPE_MOCK_MODE=false
```

生产环境请把 `AUTH_COOKIE_SECURE=true`，并优先使用 Stripe Restricted API Key。

## Stripe 真实本地测试

适用于：本机能访问 Stripe，但没有公网 webhook 地址。

1. 后端启动：

```bash
cd backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

2. 前端启动：

```bash
cd frontend
npm run dev
```

3. Stripe CLI 转发 webhook：

```bash
stripe listen --forward-to http://127.0.0.1:8000/api/billing/webhook
```

把命令输出的 `whsec_...` 填入 `backend/.env` 的 `STRIPE_WEBHOOK_SECRET`。

4. 在前端注册登录，点击“开通 VIP”，使用 Stripe 测试卡：

```text
4242 4242 4242 4242
任意未来有效期
任意 CVC
```

支付成功后，Stripe CLI 会把 `checkout.session.completed` 转发给本地后端，后端验签并把用户标记为 VIP。

## 完全无外网测试

如果电脑完全不能访问 Stripe，无法打开真实 Stripe Checkout，也无法完成真实支付测试。

这时可以只验证本地业务闭环：

```bash
STRIPE_MOCK_MODE=true
```

mock 模式下，点击“开通 VIP”会在本地直接模拟支付成功并解锁 VIP。这个模式仅用于离线开发，不能代表 Stripe 真实支付成功。

## 安全与幂等

- 前端不接触 Stripe 密钥。
- 后端 webhook 必须验证 `Stripe-Signature`。
- `stripe_events` 表记录已处理的 event id，重复 webhook 不会重复开通。
- 创建 Checkout Session 前会复用未过期 pending payment，避免用户重复点击造成多个付款入口。
