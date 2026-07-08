# 用户注册登录与 Stripe VIP 支付指南

本文档面向第一次接 Stripe 的开发者。先照着本地测试跑通，再切换到正式环境。

## 功能范围

- 用户用邮箱和密码注册登录。
- VIP 是一次性买断，不是订阅，不接 Stripe Customer Portal。
- 前端展示 `¥9.9 永久`，真实扣款金额以 Stripe Dashboard 里 `STRIPE_VIP_PRICE_ID` 对应的 Price 为准。
- 视频解析、直链下载、云端下载保持免费。
- 只有 AI 总结、总结流、视频问答和 AI 产物导出相关能力要求登录且已开通 VIP。

## Stripe 实现依据

当前实现按 Stripe 最新文档和最佳实践设计：

- 一次性付款使用 Checkout Sessions，`mode="payment"`。
- 使用 Dashboard 里创建好的 `price_...`，后端传 `line_items=[{"price": STRIPE_VIP_PRICE_ID, "quantity": 1}]`。
- 不自建银行卡表单，前端不接触 Stripe 密钥。
- 不传 `payment_method_types`，支付方式交给 Stripe Dashboard 动态配置。
- 创建 Checkout Session 时使用 `idempotency_key`，并复用未过期的 pending payment，避免重复付款入口。
- Webhook 必须校验 `Stripe-Signature`。
- `stripe_events` 记录已处理的 event id，重复投递直接跳过。

## 后端环境变量

复制 `backend/.env.example` 为 `backend/.env`，重点填写这些值：

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

说明：

- `AUTH_SECRET_KEY`：登录 cookie 签名密钥。生产环境必须换成随机长字符串。
- `AUTH_COOKIE_SECURE`：本地 HTTP 用 `false`；生产 HTTPS 用 `true`。
- `PUBLIC_APP_URL`：前端地址，Stripe 支付后会跳回这里。
- `STRIPE_API_KEY`：优先用 `rk_` 开头的 Restricted Key；测试阶段也可先用 `sk_test_`。
- `STRIPE_WEBHOOK_SECRET`：运行 Stripe CLI listen 后终端输出的 `whsec_...`。
- `STRIPE_VIP_PRICE_ID`：推荐填写 Stripe Dashboard 中一次性价格的 `price_...`。注意：如果这个 Price 是美元，Checkout 就会显示美元或按汇率换算成人民币。也可以填写 `CNY 9.90`，让后端用人民币 9.90 动态创建 `price_data`。
- `STRIPE_MOCK_MODE`：完全无外网时设为 `true`，只做本地业务闭环。

## Stripe Dashboard 要做什么

1. 登录 Stripe，切到测试模式。
2. 创建产品：例如 `影知 VIP 永久版`。
3. 给产品创建一次性价格：
   - Pricing model：Standard pricing
   - Price：`9.90`
   - Currency：`CNY`
   - Payment type：One time
4. 复制生成的 `price_...`，填到 `STRIPE_VIP_PRICE_ID`。
5. 复制测试密钥，填到 `STRIPE_API_KEY`。

如果 Checkout 页面显示 `US$9.90` 或 `¥70.05`，说明你当前使用的 Price 是美元 9.90，或用户之前已有一个未支付的美元 Checkout Session。处理方式：

1. 在 Stripe Dashboard 里新建一个 `CNY 9.90` 的一次性 Price，复制新的 `price_...` 到 `STRIPE_VIP_PRICE_ID`。
2. 重启后端。
3. 重新点击开通 VIP。系统会按当前 `STRIPE_VIP_PRICE_ID` 区分 pending payment，不会复用旧 Price 的 Checkout URL。

## 有外网但没有公网回调时怎么测

打开三个终端：

```bash
cd backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm run dev
```

```bash
stripe listen --forward-to http://127.0.0.1:8000/api/billing/webhook
```

Stripe CLI 会输出类似：

```text
Your webhook signing secret is whsec_xxx
```

把这个 `whsec_xxx` 填入 `backend/.env` 的 `STRIPE_WEBHOOK_SECRET`，重启后端。

然后在前端：

1. 注册并登录。
2. 点击开通 VIP。
3. 跳到 Stripe Checkout。
4. 用测试卡完成付款：

```text
卡号：4242 4242 4242 4242
有效期：任意未来日期
CVC：任意 3 位数字
邮编：任意
```

付款成功后，Stripe CLI 会把 `checkout.session.completed` 转发到本地后端。后端验签通过后才会把用户标记为 VIP。

## 完全无外网时怎么测

完全无外网时不能打开真实 Stripe Checkout，也不能完成真实 Stripe 支付测试。

这时只能验证本地业务闭环：

```bash
STRIPE_MOCK_MODE=true
```

mock 模式下，登录用户点击开通 VIP 后，后端会创建一条 mock payment、标记支付成功并开通 VIP。

注意：mock 模式只证明你的网站注册、登录、VIP 解锁、AI 权限控制能跑通，不证明 Stripe 真实支付可用。真实支付必须等能访问 Stripe 后，用 Checkout + webhook 再测一次。

## 上线前检查

- `STRIPE_MOCK_MODE=false`
- `AUTH_COOKIE_SECURE=true`
- 使用正式 Stripe key 和正式 `price_...`
- 在 Stripe Dashboard 配置正式 webhook endpoint：`https://你的域名/api/billing/webhook`
- 只把后端 webhook endpoint 暴露给 Stripe，不在前端暴露任何 Stripe 私钥
- 确认 webhook 至少监听：
  - `checkout.session.completed`
  - `checkout.session.async_payment_succeeded`
  - `checkout.session.async_payment_failed`
  - `checkout.session.expired`
