"""새 고객문의 알림 — 슬랙 + 메일 동시 (2026-09-20, 대표 결정 "3번: 슬랙과 메일 같이").

**알림에는 문의 내용·문의자 이메일·계정 정보를 넣지 않는다.** 슬랙·메일은 외부 서비스라 그곳에 내용이 남지 않게,
번호와 접수 시각만 보내고 내용은 관리자 콘솔의 문의 메뉴에서 읽게 한다(처리방침에도 그렇게 안내).

두 채널은 서로 독립이다: 하나가 실패하거나 꺼져 있어도 다른 하나는 나가고, 문의 접수(DB 저장)에는 영향이 없다.
"""

from __future__ import annotations

import asyncio
import logging

from ..config import settings as default_settings
from . import email_notify, slack_notify

logger = logging.getLogger("sumeungil.inquiry_notify")


def build_notice(inquiry_id: int, created_at: str) -> tuple[str, str]:
    """(제목, 본문). 개인정보·문의 내용 없음."""
    subject = f"[숨은길] 새 고객문의 #{inquiry_id} 도착"
    body = (
        f"새 고객문의가 접수됐습니다.\n\n"
        f"문의 번호: #{inquiry_id}\n"
        f"접수 시각: {created_at}\n\n"
        "내용은 관리자 콘솔의 문의 메뉴에서 확인하고 답변해 주세요.\n"
        "(이 알림에는 문의 내용과 문의자 정보를 넣지 않습니다.)\n"
    )
    return subject, body


async def notify_new_inquiry(inquiry_id: int, created_at: str, settings=default_settings) -> dict[str, bool]:  # noqa: ANN001
    subject, body = build_notice(inquiry_id, created_at)
    slack_text = f":envelope_with_arrow: {subject} — 접수 {created_at} (내용은 관리자 콘솔에서 확인)"
    results = await asyncio.gather(
        slack_notify.post(slack_text, webhook_url=settings.slack_webhook_url),
        email_notify.send_text(settings, settings.inquiry_notify_to, subject, body),
        return_exceptions=True,
    )
    out = {
        "slack": results[0] is True,
        "email": results[1] is True,
    }
    logger.info("문의 알림 id=%s slack=%s email=%s", inquiry_id, out["slack"], out["email"])
    return out
