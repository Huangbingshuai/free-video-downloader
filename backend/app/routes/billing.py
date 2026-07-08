from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import get_current_user, get_optional_user
from app.routes.auth import _public_user
from app.schemas import (
    CheckoutSessionResponse,
    ConfirmCheckoutSessionRequest,
    MembershipStatus,
    PaymentHistoryResponse,
    PaymentRecord,
)
from app.services.auth_service import UserRecord
from app.services.billing_service import (
    BillingError,
    StripeConfigurationError,
    WebhookSignatureError,
    billing_service,
)

router = APIRouter(prefix="/api", tags=["billing"])


@router.get("/membership/status", response_model=MembershipStatus)
def membership_status(user: UserRecord | None = Depends(get_optional_user)) -> MembershipStatus:
    return MembershipStatus(
        is_authenticated=user is not None,
        is_vip=bool(user and user.is_vip),
        vip_activated_at=user.vip_activated_at if user else None,
        user=_public_user(user) if user else None,
    )


@router.post("/billing/create-checkout-session", response_model=CheckoutSessionResponse)
def create_checkout_session(user: UserRecord = Depends(get_current_user)) -> CheckoutSessionResponse:
    try:
        return billing_service.create_checkout_session(user)
    except StripeConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except BillingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/billing/confirm-checkout-session", response_model=CheckoutSessionResponse)
def confirm_checkout_session(
    payload: ConfirmCheckoutSessionRequest,
    user: UserRecord = Depends(get_current_user),
) -> CheckoutSessionResponse:
    try:
        return billing_service.confirm_checkout_session(user, payload.session_id)
    except StripeConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except BillingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/billing/payments", response_model=PaymentHistoryResponse)
def payment_history(user: UserRecord = Depends(get_current_user)) -> PaymentHistoryResponse:
    rows = billing_service.list_user_payments(user.id)
    return PaymentHistoryResponse(payments=[PaymentRecord(**row) for row in rows])


@router.post("/billing/webhook")
async def stripe_webhook(request: Request) -> dict[str, object]:
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    try:
        return billing_service.handle_webhook(payload, signature)
    except StripeConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except (WebhookSignatureError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
