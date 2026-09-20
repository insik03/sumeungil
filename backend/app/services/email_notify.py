"""운영자 알림 메일 전송 (2026-09-20, 대표 지시 "고객문의가 오면 메일로 연결").

slack_notify 와 같은 원칙:
- **전송 실패가 호출자를 죽이지 않는다.** 예외를 밖으로 내지 않고 bool 만 돌려준다.
- **로그에 비밀번호·수신자 외 개인정보를 남기지 않는다.**
- 표준 라이브러리 smtplib 만 쓴다(새 의존성 없음). 블로킹 호출이라 스레드로 돌린다.

설정(.env, 값은 대표가 직접 입력 — 이 저장소에 두지 않는다): SMTP_HOST · SMTP_PORT(기본 587, STARTTLS) ·
SMTP_USER · SMTP_PASSWORD · SMTP_FROM(비우면 SMTP_USER). SMTP_HOST 가 비어 있으면 메일은 꺼진 것이다(조용히 건너뜀).
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

logger = logging.getLogger("sumeungil.email_notify")

_TIMEOUT_SEC = 10.0


def is_enabled(settings) -> bool:  # noqa: ANN001 (app.config.Settings)
    return bool(settings.smtp_host and (settings.smtp_from or settings.smtp_user))


def _send_blocking(settings, to: str, subject: str, body: str) -> None:  # noqa: ANN001
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to
    msg.set_content(body)
    port = settings.smtp_port
    if port == 465:  # 암묵적 TLS
        with smtplib.SMTP_SSL(settings.smtp_host, port, timeout=_TIMEOUT_SEC, context=ssl.create_default_context()) as s:
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
        return
    with smtplib.SMTP(settings.smtp_host, port, timeout=_TIMEOUT_SEC) as s:
        s.starttls(context=ssl.create_default_context())
        if settings.smtp_user:
            s.login(settings.smtp_user, settings.smtp_password)
        s.send_message(msg)


async def send_text(settings, to: str, subject: str, body: str) -> bool:  # noqa: ANN001
    """메일 1통. 꺼져 있거나 실패하면 False(예외 없음). 실패 사유는 종류만 로그에 남긴다(자격 증명·본문 제외)."""
    if not is_enabled(settings) or not to:
        return False
    try:
        await asyncio.to_thread(_send_blocking, settings, to, subject, body)
        return True
    except Exception as exc:  # noqa: BLE001 — 알림은 부가 기능, 어떤 실패도 호출자를 죽이지 않는다
        logger.warning("알림 메일 전송 실패(무시): %s", type(exc).__name__)
        return False
