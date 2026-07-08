from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.schemas import CheckoutSessionResponse
from app.services.auth_service import UserRecord, activate_vip
from app.services.database import get_connection


class BillingError(RuntimeError):
    pass


class StripeConfigurationError(BillingError):
    pass


class WebhookSignatureError(BillingError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> int:
    return int(time.time())


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _app_url() -> str:
    return os.getenv("PUBLIC_APP_URL", "http://127.0.0.1:5173").rstrip("/")


def _stripe_value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class BillingService:
    def create_checkout_session(self, user: UserRecord) -> CheckoutSessionResponse:
        if user.is_vip:
            return CheckoutSessionResponse(status="already_vip", is_vip=True)

        pending = self._find_active_pending_payment(user.id)
        if pending is not None:
            return CheckoutSessionResponse(
                status="pending",
                checkout_url=pending["checkout_url"],
                session_id=pending["stripe_checkout_session_id"],
                is_vip=False,
            )

        payment_id = uuid4().hex
        self._insert_payment(payment_id, user.id, "pending")

        if _env_bool("STRIPE_MOCK_MODE", False):
            session_id = f"cs_mock_{payment_id}"
            self._update_payment_after_session(
                payment_id=payment_id,
                session_id=session_id,
                checkout_url=f"{_app_url()}/?checkout=success&mock=1&session_id={session_id}#pricing",
                expires_at=_now_ts() + 30 * 60,
            )
            self._mark_payment_paid(session_id, f"pi_mock_{payment_id}")
            activate_vip(user.id, stripe_customer_id=f"cus_mock_{user.id[:12]}")
            return CheckoutSessionResponse(
                status="mock_paid",
                checkout_url=f"{_app_url()}/?checkout=success&mock=1&session_id={session_id}#pricing",
                session_id=session_id,
                is_vip=True,
            )

        session = self._create_stripe_checkout_session(payment_id, user)
        session_id = str(_stripe_value(session, "id"))
        checkout_url = str(_stripe_value(session, "url"))
        expires_at = _stripe_value(session, "expires_at")
        self._update_payment_after_session(
            payment_id=payment_id,
            session_id=session_id,
            checkout_url=checkout_url,
            expires_at=int(expires_at) if expires_at else None,
        )
        return CheckoutSessionResponse(
            status="pending",
            checkout_url=checkout_url,
            session_id=session_id,
            is_vip=False,
        )

    def _create_stripe_checkout_session(self, payment_id: str, user: UserRecord) -> Any:
        api_key = os.getenv("STRIPE_API_KEY", "").strip()
        price_id = os.getenv("STRIPE_VIP_PRICE_ID", "").strip()
        if not api_key or not price_id:
            raise StripeConfigurationError("服务端未配置 Stripe 支付参数")
        try:
            import stripe  # type: ignore
        except ModuleNotFoundError as exc:
            raise StripeConfigurationError("stripe 依赖未安装，请先安装 backend/requirements.txt") from exc

        stripe.api_key = api_key
        params: dict[str, Any] = {
            "mode": "payment",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": f"{_app_url()}/?checkout=success&session_id={{CHECKOUT_SESSION_ID}}#pricing",
            "cancel_url": f"{_app_url()}/?checkout=cancel#pricing",
            "client_reference_id": user.id,
            "customer_email": user.email,
            "metadata": {"user_id": user.id, "purchase_type": "vip_lifetime"},
        }
        if user.stripe_customer_id:
            params.pop("customer_email", None)
            params["customer"] = user.stripe_customer_id
        else:
            params["customer_creation"] = "always"
        return stripe.checkout.Session.create(**params, idempotency_key=f"vip:{payment_id}")

    def handle_webhook(self, payload: bytes, signature_header: str | None) -> dict[str, Any]:
        event = self._construct_event(payload, signature_header)
        event_id = str(event.get("id") or "")
        event_type = str(event.get("type") or "")
        if not event_id or not event_type:
            raise WebhookSignatureError("Stripe webhook event 无效")
        if not self._record_event_once(event_id, event_type):
            return {"ok": True, "duplicate": True}

        if event_type == "checkout.session.completed":
            session = event.get("data", {}).get("object", {})
            self._handle_checkout_completed(session)
        elif event_type == "checkout.session.expired":
            session = event.get("data", {}).get("object", {})
            session_id = str(session.get("id") or "")
            if session_id:
                self._mark_payment_status(session_id, "expired")
        return {"ok": True, "duplicate": False}

    def _construct_event(self, payload: bytes, signature_header: str | None) -> dict[str, Any]:
        if _env_bool("STRIPE_MOCK_MODE", False) and not os.getenv("STRIPE_WEBHOOK_SECRET", "").strip():
            return json.loads(payload.decode("utf-8"))
        secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
        if not secret:
            raise StripeConfigurationError("服务端未配置 STRIPE_WEBHOOK_SECRET")
        if not signature_header:
            raise WebhookSignatureError("缺少 Stripe-Signature")
        self._verify_signature(payload, signature_header, secret)
        return json.loads(payload.decode("utf-8"))

    def _verify_signature(self, payload: bytes, header: str, secret: str, tolerance: int = 300) -> None:
        parts: dict[str, list[str]] = {}
        for item in header.split(","):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            parts.setdefault(key, []).append(value)
        timestamp = parts.get("t", [""])[0]
        signatures = parts.get("v1", [])
        if not timestamp or not signatures:
            raise WebhookSignatureError("Stripe webhook 签名格式无效")
        try:
            ts_int = int(timestamp)
        except ValueError as exc:
            raise WebhookSignatureError("Stripe webhook 时间戳无效") from exc
        if abs(_now_ts() - ts_int) > tolerance:
            raise WebhookSignatureError("Stripe webhook 签名已过期")
        signed_payload = timestamp.encode("utf-8") + b"." + payload
        expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
            raise WebhookSignatureError("Stripe webhook 签名校验失败")

    def _handle_checkout_completed(self, session: dict[str, Any]) -> None:
        if session.get("mode") != "payment" or session.get("payment_status") != "paid":
            return
        metadata = session.get("metadata") or {}
        if metadata.get("purchase_type") != "vip_lifetime":
            return
        user_id = metadata.get("user_id") or session.get("client_reference_id")
        if not user_id:
            return
        session_id = str(session.get("id") or "")
        payment_intent = session.get("payment_intent")
        customer = session.get("customer")
        if session_id:
            self._mark_payment_paid(session_id, str(payment_intent) if payment_intent else None)
        activate_vip(str(user_id), stripe_customer_id=str(customer) if customer else None)

    def _find_active_pending_payment(self, user_id: str):
        with get_connection() as conn:
            return conn.execute(
                """
                SELECT * FROM payments
                WHERE user_id = ?
                  AND status = 'pending'
                  AND checkout_url IS NOT NULL
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id, _now_ts()),
            ).fetchone()

    def _insert_payment(self, payment_id: str, user_id: str, status: str) -> None:
        now = _now_iso()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO payments (id, user_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (payment_id, user_id, status, now, now),
            )

    def _update_payment_after_session(
        self,
        payment_id: str,
        session_id: str,
        checkout_url: str,
        expires_at: int | None,
    ) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE payments
                SET stripe_checkout_session_id = ?, checkout_url = ?, expires_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (session_id, checkout_url, expires_at, _now_iso(), payment_id),
            )

    def _mark_payment_paid(self, session_id: str, payment_intent: str | None) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE payments
                SET status = 'paid', stripe_payment_intent_id = COALESCE(?, stripe_payment_intent_id), updated_at = ?
                WHERE stripe_checkout_session_id = ?
                """,
                (payment_intent, _now_iso(), session_id),
            )

    def _mark_payment_status(self, session_id: str, status: str) -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE payments SET status = ?, updated_at = ? WHERE stripe_checkout_session_id = ?",
                (status, _now_iso(), session_id),
            )

    def _record_event_once(self, event_id: str, event_type: str) -> bool:
        try:
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO stripe_events (event_id, event_type, processed_at) VALUES (?, ?, ?)",
                    (event_id, event_type, _now_iso()),
                )
            return True
        except Exception:
            return False


billing_service = BillingService()
