"""/api/v1/visit — 페이지 조회 비콘 (부록 X, 2026-08-10).

## 왜 별도 엔드포인트가 필요한가
집계 미들웨어는 **백엔드 컨테이너**에만 있다. 그런데 화면 페이지(`/congestion`, `/regions` …)는
**프론트 컨테이너**(Next.js)가 처리하고 nginx 가 `/api/` 만 백엔드로 보낸다. 그래서 미들웨어는
API 호출만 보고 **사람이 어느 페이지를 봤는지는 영원히 알 수 없다**(2026-08-10 실측으로 확인).

브라우저가 페이지를 열 때 이 엔드포인트를 한 번 부르면 그 공백이 메워진다.

## 신뢰 수준
경로를 **클라이언트가 보낸다** — 즉 조작할 수 있다. 그래서:
  - 형식을 강하게 검증하고(슬래시로 시작, 길이 제한, 제어문자 금지)
  - 미들웨어와 **같은 접기 함수**로 정규화해 저장한다(경로 폭발·오염 방지)
  - 레이트리밋 기본 버킷이 그대로 걸린다
이 수치는 **운영 참고용**이지 과금·정산 근거가 아니다. 그 전제에서 이 정도 검증이면 충분하다.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..config import settings
from ..db.postgres import Database
from ..deps import get_database
from ..middleware.rate_limit import extract_client_ip
from ..middleware.visit_log import fold_path, visit_ip_hash
from ..repositories import visit_repo
from ..util.time import now_kst

logger = logging.getLogger("sumeungil.api.visit")

router = APIRouter(prefix="/api/v1", tags=["visit"])

# 화면 경로만 받는다. 스킴·호스트·제어문자·과도한 길이를 전부 거른다.
_PATH_RE = re.compile(r"^/[A-Za-z0-9/_\-.:%]{0,120}$")


class VisitBeacon(BaseModel):
    path: str = Field(default="/", max_length=200)


@router.post("/visit", status_code=204)
async def record_visit(
    request: Request, body: VisitBeacon, db: Database = Depends(get_database)
):
    """페이지 조회 1건 기록. 응답 본문이 없다(204) — 클라이언트가 기다릴 이유가 없다.

    **실패해도 조용히 넘어간다.** 집계는 부가 기능이라 사용자 화면에 영향을 주면 안 된다.
    """
    raw = (body.path or "/").strip()
    # 경로 순회 문자열은 거른다. 보안 구멍은 아니지만(그냥 통계 문자열이다) 통계에
    # '/../etc/passwd' 같은 쓰레기 행이 쌓이면 화면이 지저분해지고 오해를 부른다.
    if ".." in raw or not _PATH_RE.match(raw):
        # 형식이 틀리면 조용히 무시한다. 400 을 주면 "무엇이 통과하는지" 를 알려주는 셈이다.
        return None
    # 관리자 화면 경로는 /admin이 아니라 무작위 문자열이다(2026-08-18, frontend/app/
    # ops-37878f1b71/page.tsx 상단 주석 참고) — 프론트가 이미 이 경로를 아예 안 보내지만
    # (VisitBeacon.tsx), 서버 쪽에서도 한 번 더 막아둔다(방어 심층화, 프론트만 믿지 않는다).
    if raw.startswith("/api/") or raw.startswith("/ops-37878f1b71"):
        # API 는 미들웨어가 이미 세고, 관리자 화면은 통계에서 제외하기로 했다.
        return None

    try:
        now = now_kst()
        ip = extract_client_ip(request, trust_proxy=settings.rate_limit_trust_proxy)
        await db.awrite(
            lambda conn: visit_repo.record(
                conn,
                day=now.strftime("%Y-%m-%d"),
                hour=now.hour,
                ip_hash=visit_ip_hash(ip),
                path=fold_path(raw),
                now_iso=now.isoformat(timespec="seconds"),
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("페이지 비콘 집계 실패(무시): %s", exc)
    return None
