from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import billing
from app.services.auth_service import activate_vip
from app.services.database import get_connection


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    monkeypatch.setenv("FVD_DB_PATH", str(tmp_path / "app.sqlite3"))
    monkeypatch.setenv("FVD_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-auth-secret-with-at-least-32-bytes")
    yield


def _register(client: TestClient, email: str = "user@example.com"):
    code = "123456"
    now = f"2026-07-09T00:00:00.{time.time_ns()}+00:00"
    expires_at = "2099-01-01T00:00:00+00:00"
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO email_codes (id, email, code, purpose, expires_at, created_at)
            VALUES (?, ?, ?, 'register', ?, ?)
            """,
            (f"test-{uuid4().hex}", email, code, expires_at, now),
        )
    return client.post("/api/auth/register", json={"email": email, "password": "password123", "code": code})


def _stripe_signature(payload: bytes, secret: str) -> str:
    timestamp = str(int(time.time()))
    signed = timestamp.encode("utf-8") + b"." + payload
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def test_register_login_logout_flow():
    with TestClient(app) as client:
        response = _register(client, "flow@example.com")
        assert response.status_code == 200
        assert response.json()["user"]["email"] == "flow@example.com"

        duplicate = _register(client, "flow@example.com")
        assert duplicate.status_code == 409

        client.post("/api/auth/logout")
        assert client.get("/api/auth/me").json()["user"] is None

        bad_login = client.post("/api/auth/login", json={"email": "flow@example.com", "password": "wrong"})
        assert bad_login.status_code == 401

        login = client.post("/api/auth/login", json={"email": "flow@example.com", "password": "password123"})
        assert login.status_code == 200
        assert client.get("/api/auth/me").json()["user"]["email"] == "flow@example.com"


def test_update_profile_flow():
    with TestClient(app) as client:
        _register(client, "profile@example.com")
        response = client.put(
            "/api/auth/profile",
            json={"display_name": "影知用户"},
        )
        me = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["user"]["display_name"] == "影知用户"
    assert me.json()["user"]["display_name"] == "影知用户"


def test_upload_avatar_flow(monkeypatch, tmp_path):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("FVD_UPLOAD_DIR", str(upload_dir))
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    with TestClient(app) as client:
        _register(client, "avatar@example.com")
        response = client.post(
            "/api/auth/avatar",
            files={"file": ("avatar.png", png_bytes, "image/png")},
        )

    assert response.status_code == 200
    avatar_url = response.json()["user"]["avatar_url"]
    assert avatar_url.startswith("/uploads/avatars/")
    assert (Path(upload_dir) / "avatars" / avatar_url.rsplit("/", 1)[-1]).is_file()


def test_create_checkout_session_reuses_pending_payment(monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_mock")
    monkeypatch.setenv("STRIPE_VIP_PRICE_ID", "price_mock")
    monkeypatch.setenv("STRIPE_MOCK_MODE", "false")

    calls: list[str] = []

    def fake_create(payment_id, user):
        calls.append(payment_id)
        return {
            "id": "cs_test_reuse",
            "url": "https://checkout.stripe.test/session",
            "expires_at": int(time.time()) + 3600,
        }

    monkeypatch.setattr(billing.billing_service, "_create_stripe_checkout_session", fake_create)

    with TestClient(app) as client:
        _register(client, "checkout-reuse@example.com")
        first = client.post("/api/billing/create-checkout-session")
        second = client.post("/api/billing/create-checkout-session")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["session_id"] == "cs_test_reuse"
    assert second.json()["session_id"] == "cs_test_reuse"
    assert len(calls) == 1


def test_checkout_session_does_not_reuse_pending_payment_after_price_change(monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_mock")
    monkeypatch.setenv("STRIPE_VIP_PRICE_ID", "price_usd_mock")
    monkeypatch.setenv("STRIPE_MOCK_MODE", "false")

    calls: list[str] = []

    def fake_create(payment_id, user):
        calls.append(payment_id)
        index = len(calls)
        return {
            "id": f"cs_test_price_{index}",
            "url": f"https://checkout.stripe.test/session-{index}",
            "expires_at": int(time.time()) + 3600,
        }

    monkeypatch.setattr(billing.billing_service, "_create_stripe_checkout_session", fake_create)

    with TestClient(app) as client:
        _register(client, "checkout-price-change@example.com")
        first = client.post("/api/billing/create-checkout-session")
        second = client.post("/api/billing/create-checkout-session")
        monkeypatch.setenv("STRIPE_VIP_PRICE_ID", "CNY 9.90")
        third = client.post("/api/billing/create-checkout-session")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200
    assert first.json()["session_id"] == "cs_test_price_1"
    assert second.json()["session_id"] == "cs_test_price_1"
    assert third.json()["session_id"] == "cs_test_price_2"
    assert len(calls) == 2


def test_checkout_returns_existing_vip_without_payment():
    with TestClient(app) as client:
        response = _register(client, "already-vip@example.com")
        activate_vip(response.json()["user"]["id"])
        checkout = client.post("/api/billing/create-checkout-session")

    assert checkout.status_code == 200
    assert checkout.json()["status"] == "already_vip"
    assert checkout.json()["is_vip"] is True


def test_mock_checkout_activates_vip(monkeypatch):
    monkeypatch.setenv("STRIPE_MOCK_MODE", "true")

    with TestClient(app) as client:
        _register(client, "mock-vip@example.com")
        checkout = client.post("/api/billing/create-checkout-session")
        status = client.get("/api/membership/status")

    assert checkout.status_code == 200
    assert checkout.json()["status"] == "mock_paid"
    assert checkout.json()["is_vip"] is True
    assert status.json()["is_vip"] is True


def test_confirm_checkout_session_activates_vip(monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_mock")

    def fake_retrieve(session_id):
        return {
            "id": session_id,
            "mode": "payment",
            "payment_status": "paid",
            "payment_intent": "pi_confirm_paid",
            "customer": "cus_confirm_paid",
            "client_reference_id": None,
            "metadata": {"user_id": user_id, "purchase_type": "vip_lifetime"},
        }

    with TestClient(app) as client:
        auth = _register(client, "confirm-vip@example.com")
        user_id = auth.json()["user"]["id"]
        monkeypatch.setattr(billing.billing_service, "_retrieve_stripe_checkout_session", fake_retrieve)
        confirm = client.post(
            "/api/billing/confirm-checkout-session",
            json={"session_id": "cs_test_confirm_paid"},
        )
        status = client.get("/api/membership/status")

    assert confirm.status_code == 200
    assert confirm.json()["is_vip"] is True
    assert status.json()["is_vip"] is True


def test_payment_history_records_paid_checkout(monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_mock")
    monkeypatch.setenv("STRIPE_VIP_PRICE_ID", "price_mock")
    monkeypatch.setenv("STRIPE_MOCK_MODE", "false")

    def fake_create(payment_id, user):
        return {
            "id": "cs_test_history_paid",
            "url": "https://checkout.stripe.test/history",
            "expires_at": int(time.time()) + 3600,
            "amount_total": 990,
            "currency": "cny",
        }

    def fake_retrieve(session_id):
        return {
            "id": session_id,
            "mode": "payment",
            "payment_status": "paid",
            "payment_intent": "pi_history_paid",
            "customer": "cus_history_paid",
            "client_reference_id": None,
            "amount_total": 990,
            "currency": "cny",
            "metadata": {"user_id": user_id, "purchase_type": "vip_lifetime"},
        }

    monkeypatch.setattr(billing.billing_service, "_create_stripe_checkout_session", fake_create)

    with TestClient(app) as client:
        auth = _register(client, "payment-history@example.com")
        user_id = auth.json()["user"]["id"]
        checkout = client.post("/api/billing/create-checkout-session")
        monkeypatch.setattr(billing.billing_service, "_retrieve_stripe_checkout_session", fake_retrieve)
        confirm = client.post(
            "/api/billing/confirm-checkout-session",
            json={"session_id": checkout.json()["session_id"]},
        )
        history = client.get("/api/billing/payments")

    assert confirm.status_code == 200
    assert history.status_code == 200
    assert history.json()["payments"][0]["status"] == "paid"
    assert history.json()["payments"][0]["amount_total"] == 990
    assert history.json()["payments"][0]["currency"] == "cny"


def test_refund_paid_checkout_deactivates_vip(monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_mock")
    monkeypatch.setenv("STRIPE_VIP_PRICE_ID", "price_mock")
    monkeypatch.setenv("STRIPE_MOCK_MODE", "false")

    def fake_create(payment_id, user):
        return {
            "id": "cs_test_refund_paid",
            "url": "https://checkout.stripe.test/refund",
            "expires_at": int(time.time()) + 3600,
            "amount_total": 990,
            "currency": "cny",
        }

    def fake_retrieve(session_id):
        return {
            "id": session_id,
            "mode": "payment",
            "payment_status": "paid",
            "payment_intent": "pi_refund_paid",
            "customer": "cus_refund_paid",
            "client_reference_id": None,
            "amount_total": 990,
            "currency": "cny",
            "metadata": {"user_id": user_id, "purchase_type": "vip_lifetime"},
        }

    def fake_refund(payment_intent, payment_id):
        assert payment_intent == "pi_refund_paid"
        return {"id": "re_test_refund_paid", "status": "succeeded"}

    monkeypatch.setattr(billing.billing_service, "_create_stripe_checkout_session", fake_create)
    monkeypatch.setattr(billing.billing_service, "_create_stripe_refund", fake_refund)

    with TestClient(app) as client:
        auth = _register(client, "refund@example.com")
        user_id = auth.json()["user"]["id"]
        checkout = client.post("/api/billing/create-checkout-session")
        monkeypatch.setattr(billing.billing_service, "_retrieve_stripe_checkout_session", fake_retrieve)
        client.post(
            "/api/billing/confirm-checkout-session",
            json={"session_id": checkout.json()["session_id"]},
        )
        paid_history = client.get("/api/billing/payments").json()["payments"]
        refund = client.post(f"/api/billing/payments/{paid_history[0]['id']}/refund")
        status = client.get("/api/membership/status")

    assert refund.status_code == 200
    assert refund.json()["payment"]["status"] == "refunded"
    assert refund.json()["payment"]["stripe_refund_id"] == "re_test_refund_paid"
    assert refund.json()["user"]["is_vip"] is False
    assert status.json()["is_vip"] is False


def test_confirm_checkout_session_rejects_wrong_user(monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_mock")

    def fake_retrieve(session_id):
        return {
            "id": session_id,
            "mode": "payment",
            "payment_status": "paid",
            "metadata": {"user_id": "another-user", "purchase_type": "vip_lifetime"},
        }

    monkeypatch.setattr(billing.billing_service, "_retrieve_stripe_checkout_session", fake_retrieve)

    with TestClient(app) as client:
        _register(client, "confirm-wrong-user@example.com")
        confirm = client.post(
            "/api/billing/confirm-checkout-session",
            json={"session_id": "cs_test_confirm_wrong_user"},
        )
        status = client.get("/api/membership/status")

    assert confirm.status_code == 400
    assert status.json()["is_vip"] is False


def test_webhook_rejects_bad_signature(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("STRIPE_MOCK_MODE", "false")
    payload = json.dumps({"id": "evt_bad", "type": "checkout.session.completed"}).encode("utf-8")
    with TestClient(app) as client:
        response = client.post(
            "/api/billing/webhook",
            data=payload,
            headers={"stripe-signature": "t=1,v1=bad"},
        )
    assert response.status_code == 400


def test_checkout_completed_webhook_activates_vip_once(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("STRIPE_MOCK_MODE", "false")
    with TestClient(app) as client:
        auth = _register(client, "webhook-vip@example.com")
        user_id = auth.json()["user"]["id"]
        event = {
            "id": "evt_checkout_completed_once",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_paid",
                    "mode": "payment",
                    "payment_status": "paid",
                    "payment_intent": "pi_test_paid",
                    "customer": "cus_test_paid",
                    "client_reference_id": user_id,
                    "metadata": {"user_id": user_id, "purchase_type": "vip_lifetime"},
                }
            },
        }
        payload = json.dumps(event).encode("utf-8")
        headers = {"stripe-signature": _stripe_signature(payload, "whsec_test")}
        first = client.post("/api/billing/webhook", data=payload, headers=headers)
        second = client.post("/api/billing/webhook", data=payload, headers=headers)
        status = client.get("/api/membership/status")

    assert first.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert status.json()["is_vip"] is True


def test_async_payment_succeeded_webhook_activates_vip(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("STRIPE_MOCK_MODE", "false")
    with TestClient(app) as client:
        auth = _register(client, "async-webhook-vip@example.com")
        user_id = auth.json()["user"]["id"]
        event = {
            "id": "evt_async_checkout_succeeded",
            "type": "checkout.session.async_payment_succeeded",
            "data": {
                "object": {
                    "id": "cs_test_async_paid",
                    "mode": "payment",
                    "payment_status": "paid",
                    "payment_intent": "pi_test_async_paid",
                    "customer": "cus_test_async_paid",
                    "client_reference_id": user_id,
                    "metadata": {"user_id": user_id, "purchase_type": "vip_lifetime"},
                }
            },
        }
        payload = json.dumps(event).encode("utf-8")
        headers = {"stripe-signature": _stripe_signature(payload, "whsec_test")}
        response = client.post("/api/billing/webhook", data=payload, headers=headers)
        status = client.get("/api/membership/status")

    assert response.status_code == 200
    assert status.json()["is_vip"] is True
