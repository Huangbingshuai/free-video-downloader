from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import billing
from app.services.auth_service import activate_vip


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    monkeypatch.setenv("FVD_DB_PATH", str(tmp_path / "app.sqlite3"))
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-auth-secret-with-at-least-32-bytes")
    yield


def _register(client: TestClient, email: str = "user@example.com"):
    return client.post("/api/auth/register", json={"email": email, "password": "password123"})


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


def test_checkout_returns_existing_vip_without_payment():
    with TestClient(app) as client:
        response = _register(client, "already-vip@example.com")
        activate_vip(response.json()["user"]["id"])
        checkout = client.post("/api/billing/create-checkout-session")

    assert checkout.status_code == 200
    assert checkout.json()["status"] == "already_vip"
    assert checkout.json()["is_vip"] is True


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
