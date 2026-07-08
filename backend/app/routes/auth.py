from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status

from app.dependencies import get_current_user, get_optional_user
from app.schemas import AuthResponse, AuthUser, LoginRequest, RegisterRequest, SendCodeRequest, UpdateProfileRequest
from app.services import auth_service
from app.services.auth_service import AUTH_COOKIE_NAME, DuplicateEmail, UserRecord
from app.services.email_service import EmailError, store_and_send_code, verify_code

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_AVATAR_BYTES = 2 * 1024 * 1024
AVATAR_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _uploads_root() -> Path:
    return Path(os.getenv("FVD_UPLOAD_DIR", Path(__file__).resolve().parents[2] / "uploads"))


def _avatar_dir() -> Path:
    path = _uploads_root() / "avatars"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _remove_old_avatar(avatar_url: str | None) -> None:
    if not avatar_url or not avatar_url.startswith("/uploads/avatars/"):
        return
    filename = avatar_url.rsplit("/", 1)[-1]
    target = (_avatar_dir() / filename).resolve()
    avatar_root = _avatar_dir().resolve()
    if avatar_root not in target.parents:
        return
    try:
        target.unlink(missing_ok=True)
    except OSError:
        pass


def _cookie_secure() -> bool:
    return os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes"}


def _public_user(user: UserRecord) -> AuthUser:
    return AuthUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        is_vip=user.is_vip,
        vip_activated_at=user.vip_activated_at,
        daily_ai_remaining=auth_service.get_daily_ai_remaining(user.id) if not user.is_vip else 999,
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


@router.post("/send-code")
def send_code(payload: SendCodeRequest) -> dict[str, str]:
    if payload.purpose == "login":
        existing = auth_service.get_user_by_email(payload.email)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该邮箱未注册")
    try:
        store_and_send_code(payload.email, payload.purpose)
    except EmailError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return {"ok": "true"}


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest, response: Response) -> AuthResponse:
    if not verify_code(payload.email, payload.code, "register"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误或已过期")
    try:
        user = auth_service.create_user(payload.email, payload.password)
    except DuplicateEmail as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    token = auth_service.create_session_token(user.id)
    _set_auth_cookie(response, token)
    return AuthResponse(user=_public_user(user))


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, response: Response) -> AuthResponse:
    user = None
    if payload.code:
        if not verify_code(payload.email, payload.code, "login"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="验证码错误或已过期")
        user = auth_service.get_user_by_email(payload.email)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="该邮箱未注册")
    elif payload.password:
        user = auth_service.authenticate_user(payload.email, payload.password)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请提供密码或验证码")
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


@router.put("/profile", response_model=AuthResponse)
def update_profile(
    payload: UpdateProfileRequest,
    user: UserRecord = Depends(get_current_user),
) -> AuthResponse:
    updated = auth_service.update_profile(user.id, payload.display_name)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return AuthResponse(user=_public_user(updated))


@router.post("/avatar", response_model=AuthResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    user: UserRecord = Depends(get_current_user),
) -> AuthResponse:
    suffix = AVATAR_CONTENT_TYPES.get(file.content_type or "")
    if suffix is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="头像仅支持 JPG、PNG 或 WEBP")

    content = await file.read(MAX_AVATAR_BYTES + 1)
    if len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="头像不能超过 2MB")
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="头像文件为空")

    filename = f"{user.id}_{uuid4().hex}{suffix}"
    target = _avatar_dir() / filename
    target.write_bytes(content)

    avatar_url = f"/uploads/avatars/{filename}"
    updated = auth_service.update_avatar(user.id, avatar_url)
    if updated is None:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    _remove_old_avatar(user.avatar_url)
    return AuthResponse(user=_public_user(updated))
