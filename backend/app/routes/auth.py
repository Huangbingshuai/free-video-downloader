from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.dependencies import get_optional_user
from app.schemas import AuthResponse, AuthUser, LoginRequest, RegisterRequest
from app.services import auth_service
from app.services.auth_service import AUTH_COOKIE_NAME, DuplicateEmail, UserRecord

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _cookie_secure() -> bool:
    return os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes"}


def _public_user(user: UserRecord) -> AuthUser:
    return AuthUser(
        id=user.id,
        email=user.email,
        is_vip=user.is_vip,
        vip_activated_at=user.vip_activated_at,
    )


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=auth_service.SESSION_TTL_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest, response: Response) -> AuthResponse:
    try:
        user = auth_service.create_user(payload.email, payload.password)
    except DuplicateEmail as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    token = auth_service.create_session_token(user.id)
    _set_auth_cookie(response, token)
    return AuthResponse(user=_public_user(user))


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, response: Response) -> AuthResponse:
    user = auth_service.authenticate_user(payload.email, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")
    token = auth_service.create_session_token(user.id)
    _set_auth_cookie(response, token)
    return AuthResponse(user=_public_user(user))


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    session_id = auth_service.session_id_from_token(request.cookies.get(AUTH_COOKIE_NAME))
    if session_id:
        auth_service.revoke_session(session_id)
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", response_model=AuthResponse)
def me(user: UserRecord | None = Depends(get_optional_user)) -> AuthResponse:
    return AuthResponse(user=_public_user(user) if user else None)
