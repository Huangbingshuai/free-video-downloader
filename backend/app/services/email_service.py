from __future__ import annotations

import os
import random
import smtplib
import time
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from uuid import uuid4

from app.services.database import get_connection


class EmailError(RuntimeError):
    pass


CODE_EXPIRE_MINUTES = 5
SEND_COOLDOWN_SECONDS = 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_code() -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(6))


def _smtp_config():
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587").strip())
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    from_name = os.getenv("SMTP_FROM_NAME", "影知").strip()
    if not host or not user or not password:
        raise EmailError("SMTP 未配置，请在 .env 中设置 SMTP_HOST / SMTP_USER / SMTP_PASSWORD")
    return host, port, user, password, from_name


def _send_email(to_email: str, subject: str, html: str) -> None:
    host, port, user, password, from_name = _smtp_config()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, user))
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        server = smtplib.SMTP(host, port, timeout=15)
        server.starttls()
        server.login(user, password)
        server.sendmail(user, [to_email], msg.as_string())
        server.quit()
    except smtplib.SMTPException as exc:
        raise EmailError(f"邮件发送失败: {exc}") from exc


def store_and_send_code(email: str, purpose: str) -> None:
    email = email.strip().lower()
    _check_cooldown(email, purpose)
    code = _make_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=CODE_EXPIRE_MINUTES)
    code_id = uuid4().hex
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO email_codes (id, email, code, purpose, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (code_id, email, code, purpose, expires_at.isoformat(), now),
        )

    title = "注册" if purpose == "register" else "登录"
    subject = f"影知 {title}验证码: {code}"

    html = f"""\
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f1f5f9;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:40px 0;">
<tr><td align="center">
  <table width="420" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,0.06);">

    <!-- Header -->
    <tr>
      <td style="background:linear-gradient(135deg,#2563eb,#7c3aed);padding:32px 32px 24px;text-align:center;">
        <p style="margin:0;font-size:28px;font-weight:800;color:#ffffff;letter-spacing:2px;">🎬 影知</p>
        <p style="margin:8px 0 0;font-size:14px;color:rgba(255,255,255,0.85);">AI 视频解析 · 学习总结工具</p>
      </td>
    </tr>

    <!-- Body -->
    <tr>
      <td style="padding:32px 32px 24px;">

        <p style="margin:0 0 8px;font-size:18px;font-weight:700;color:#1e293b;">{title}验证码</p>
        <p style="margin:0 0 24px;font-size:14px;color:#64748b;line-height:1.7;">
          你正在使用邮箱 <strong style="color:#334155;">{email}</strong> {title}影知账号，请输入以下验证码完成验证：
        </p>

        <!-- Code box -->
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="background:#f8fafc;border:1px dashed #cbd5e1;border-radius:12px;padding:20px;text-align:center;">
              <p style="margin:0;font-family:'SF Mono','Cascadia Code','Consolas',monospace;font-size:36px;font-weight:800;letter-spacing:10px;color:#0f172a;">{code}</p>
            </td>
          </tr>
        </table>

        <p style="margin:20px 0 0;font-size:12px;color:#94a3b8;text-align:center;">
          验证码 {CODE_EXPIRE_MINUTES} 分钟内有效 · 请勿转发给他人
        </p>

      </td>
    </tr>

    <!-- Footer -->
    <tr>
      <td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:20px 32px;text-align:center;">
        <p style="margin:0;font-size:12px;color:#94a3b8;">
          此邮件由影知系统自动发送，请勿回复。
        </p>
        <p style="margin:4px 0 0;font-size:12px;color:#94a3b8;">
          如果不是你本人操作，请忽略此邮件。
        </p>
      </td>
    </tr>

  </table>
</td></tr>
</table>
</body>
</html>"""

    _send_email(email, subject, html)


def verify_code(email: str, code: str, purpose: str) -> bool:
    email = email.strip().lower()
    code = code.strip()
    now = _now_iso()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, used, expires_at FROM email_codes
            WHERE email = ? AND code = ? AND purpose = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (email, code, purpose),
        ).fetchone()
    if row is None:
        return False
    if bool(row["used"]):
        return False
    if row["expires_at"] < now:
        return False
    with get_connection() as conn:
        conn.execute("UPDATE email_codes SET used = 1 WHERE id = ?", (row["id"],))
    return True


def _check_cooldown(email: str, purpose: str) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=SEND_COOLDOWN_SECONDS)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT created_at FROM email_codes
            WHERE email = ? AND purpose = ? AND created_at > ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (email, purpose, cutoff.isoformat()),
        ).fetchone()
    if row is not None:
        remaining = SEND_COOLDOWN_SECONDS - (time.time() - datetime.fromisoformat(row["created_at"]).timestamp())
        if remaining > 0:
            raise EmailError(f"验证码发送过于频繁，请 {int(remaining)} 秒后再试")
