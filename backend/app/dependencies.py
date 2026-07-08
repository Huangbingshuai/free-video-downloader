from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.services.auth_service import AUTH_COOKIE_NAME, UserRecord, user_from_token


def get_optional_user(request: Request) -> UserRecord | None:
    return user_from_token(request.cookies.get(AUTH_COOKIE_NAME))


def get_current_user(user: UserRecord | None = Depends(get_optional_user)) -> UserRecord:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    return user


def get_current_vip_user(user: UserRecord = Depends(get_current_user)) -> UserRecord:
    if not user.is_vip:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AI 总结为 VIP 专享功能，请先开通 VIP")
    return user


def get_ai_access_user(user: UserRecord = Depends(get_current_user)) -> UserRecord:
    if user.is_vip:
        return user
    from app.services.auth_service import check_and_increment_daily_ai_usage
    if not check_and_increment_daily_ai_usage(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="今日免费 AI 次数已用完（每日 2 次），请开通 VIP 继续使用",
        )
    return user
