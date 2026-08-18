"""슬랙 슬래시 명령어 (2026-08-18, 대표 지시 — `/서버상태` ·`/문의`).

## 이 엔드포인트는 인터넷에 열려 있다
슬랙이 우리 서버로 POST 해야 하므로 인증 쿠키를 쓸 수 없다. 그래서 **요청 서명 검증이
유일한 방어선**이다. 검증을 빼면 URL 을 아는 누구나 우리 운영 수치(방문자·문의 건수)를
조회할 수 있다. `SLACK_SIGNING_SECRET` 이 없으면 main.py 가 이 라우터를 **등록하지 않는다**
(404) — 관리자 라우터가 `ADMIN_PASSWORD_HASH` 없으면 사라지는 것과 같은 원칙이다.

## 서명 검증 방식 (슬랙 공식 규격)
1. 기준 문자열 = `v0:{X-Slack-Request-Timestamp}:{원본 본문}`
2. `HMAC-SHA256(signing_secret, 기준문자열)` 의 hex 를 `v0=` 접두사와 붙임
3. `X-Slack-Signature` 와 **상수시간 비교**(`hmac.compare_digest`) — `==` 로 비교하면
   응답 시간 차이로 서명을 한 바이트씩 알아낼 수 있다
4. 타임스탬프가 5분보다 오래되면 거부 — 서명이 유효해도 **재전송 공격**을 막는다

> **원본 본문(raw body)으로 검증해야 한다.** 파싱한 폼을 다시 직렬화하면 순서·인코딩이
> 달라져 서명이 깨진다. 그래서 `await request.body()` 를 먼저 읽고 그 바이트로 검증한 뒤
> 직접 파싱한다.

## 응답 규칙
- **3초 안에 응답해야 한다.** 넘기면 슬랙이 `operation_timeout` 을 띄운다. 그래서 여기서는
  가벼운 COUNT 쿼리와 인메모리 헬스체크만 한다. 무거운 작업이 필요해지면 즉시 빈 200 을
  주고 `response_url` 로 나중에 보내는 방식으로 바꿔야 한다.
- `ephemeral` — **명령을 실행한 사람에게만** 보인다. 채널에 남기지 않는 이유는 두 가지다:
  운영 수치가 90일 히스토리에 쌓이지 않게, 그리고 3명 채널이 조회 결과로 도배되지 않게.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..cache.base import Cache
from ..config import settings
from ..db.postgres import Database
from ..deps import get_cache, get_congestion_repository, get_database
from ..repositories.congestion_repo import CongestionRepository
from ..services import slack_report

logger = logging.getLogger("sumeungil.api.slack")

router = APIRouter(tags=["slack"])

# 서명이 유효해도 이보다 오래된 요청은 거부한다(재전송 공격 방어). 슬랙 권장값.
_MAX_SKEW_SEC = 60 * 5

# 한글 명령어가 슬랙 설정에서 불편할 때를 위해 영문 별칭도 받는다.
_STATUS_CMDS = frozenset({"/서버상태", "/status", "/서버"})
_INQUIRY_CMDS = frozenset({"/문의", "/inquiries", "/inquiry"})

_HELP = (
    "쓸 수 있는 명령어\n"
    "· `/서버상태` — 서버 종합 상태와 오늘 방문 집계\n"
    "· `/문의` — 미답변 고객문의 건수"
)


def _verify_signature(raw_body: bytes, timestamp: str, signature: str) -> bool:
    """슬랙 서명 검증. 실패 이유는 로그에만 남기고 응답에는 쓰지 않는다.

    공격자에게 "타임스탬프가 문제였다 / 서명이 문제였다"를 알려주면 탐색을 도와준다.
    """
    secret = settings.slack_signing_secret
    if not secret:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        logger.warning("슬랙 서명 검증 실패 — 타임스탬프 형식 오류")
        return False
    if abs(time.time() - ts) > _MAX_SKEW_SEC:
        logger.warning("슬랙 서명 검증 실패 — 타임스탬프가 허용 범위를 벗어남(재전송 의심)")
        return False

    base = b"v0:" + timestamp.encode("utf-8") + b":" + raw_body
    expected = "v0=" + hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        logger.warning("슬랙 서명 검증 실패 — 서명 불일치")
        return False
    return True


def _ephemeral(text: str) -> JSONResponse:
    return JSONResponse({"response_type": "ephemeral", "text": text})


@router.post("/api/v1/slack/commands")
async def slack_commands(
    request: Request,
    db: Database = Depends(get_database),
    cache: Cache = Depends(get_cache),
    repo: CongestionRepository = Depends(get_congestion_repository),
):
    raw = await request.body()

    if not _verify_signature(
        raw,
        request.headers.get("X-Slack-Request-Timestamp", ""),
        request.headers.get("X-Slack-Signature", ""),
    ):
        # 401 로 통일 — 무엇이 틀렸는지 알려주지 않는다.
        return JSONResponse({"detail": "unauthorized"}, status_code=401)

    form = parse_qs(raw.decode("utf-8", errors="replace"))
    command = (form.get("command") or [""])[0].strip()
    user = (form.get("user_name") or [""])[0]
    logger.info("슬랙 명령어 수신 command=%s user=%s", command, user)

    if command in _STATUS_CMDS:
        return _ephemeral(await slack_report.build_server_status(db, cache, repo))
    if command in _INQUIRY_CMDS:
        return _ephemeral(await slack_report.build_inquiry_status(db))

    return _ephemeral(f"모르는 명령어입니다: `{command}`\n\n{_HELP}")
