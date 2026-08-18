"""슬랙 웹훅 전송 공통 모듈 (2026-08-18, 대표 지시 — #알림-봇).

## 이 파일이 존재하는 이유
슬랙으로 보내는 곳이 세 군데(5xx 알림 미들웨어 · 아침 요약 루프 · 배포 알림)로 늘어났다.
전송·실패처리·시크릿 세탁 규칙이 갈라지면 어느 한 곳만 조용히 시크릿을 흘릴 수 있어
**보내는 문은 하나로 둔다.**

## 절대 규칙
**전송 실패가 호출자를 죽이지 않는다.** 알림은 전부 부가 기능이다. 슬랙이 죽든 웹훅이
만료되든, 사용자 응답과 백그라운드 루프는 멀쩡해야 한다. 그래서 이 모듈의 함수는
예외를 밖으로 내지 않고 bool 만 돌려준다.

로그에 웹훅 URL 을 남기지 않는다 — 그 URL 자체가 비밀번호다(아는 사람은 우리 채널에
아무 글이나 쓸 수 있다).
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("sumeungil.services.slack_notify")

_TIMEOUT_SEC = 5.0


async def post(text: str, *, webhook_url: str) -> bool:
    """슬랙에 한 건 보낸다. 성공 여부만 돌려주고 예외는 내지 않는다.

    `unfurl_links=False` — 알림에 링크가 들어갈 때 슬랙이 미리보기 카드를 붙이면
    채널이 길어지고, 우리 링크 미리보기는 정보가 없다(로그인 화면 등).
    """
    if not webhook_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.post(
                webhook_url, json={"text": text, "unfurl_links": False}
            )
    except Exception:  # noqa: BLE001 — 전송 실패는 무해해야 한다
        logger.warning("슬랙 전송 실패(예외) — 무시하고 계속", exc_info=True)
        return False
    if resp.status_code != 200:
        # 응답 본문에 URL 이 들어갈 수 있어 상태코드만 남긴다.
        logger.warning("슬랙 전송 실패 — HTTP %s", resp.status_code)
        return False
    return True
