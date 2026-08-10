"""방문 집계 미들웨어 (부록 X, 2026-08-10).

## 설계 원칙 세 가지

**1. 집계 실패가 요청을 죽이지 않는다.**
통계는 부가 기능이다. 디스크가 차든 DB 가 잠기든, 사용자가 보는 화면은 멀쩡해야 한다.
그래서 기록은 전부 try/except 로 감싸고 실패는 로그 한 줄로 끝낸다.

**2. 원본 IP 를 저장하지 않는다.**
`ip_hash`(키 붙은 HMAC 앞 16자)만 남긴다 — 대표 결정(2026-08-10). 서버 시크릿 없이는
후보 IP 를 대입해도 역산할 수 없다.

**3. 경로를 접어서 저장한다.**
`/spot/126508` 을 그대로 쌓으면 스팟 수만큼 행이 생겨 집계가 무의미해진다.
동적 구간을 `:id` 로 접어 `/spot/:id` 한 줄로 모은다.

## 무엇을 세지 않는가
정적 자산(`/_next/`, 이미지), 헬스체크, 관리자 경로는 제외한다. 셋 다 "사람이 서비스를
쓴 흔적"이 아니다. 특히 관리자 경로를 넣으면 운영자가 콘솔을 볼 때마다 방문자 수가
올라가 자기 통계를 자기가 오염시킨다.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from ..repositories import visit_repo
from ..util.time import now_kst
from .rate_limit import extract_client_ip

logger = logging.getLogger("sumeungil.middleware.visit_log")

_IP_LABEL = b"sumeungil.visit.ip.v1"

# 세지 않을 경로. startswith 로 판정한다.
_SKIP_PREFIXES: tuple[str, ...] = (
    "/_next/",
    "/static/",
    "/landmarks/",
    "/favicon",
    "/api/v1/admin",   # 운영자가 자기 통계를 오염시키지 않게
    # 페이지 비콘 자신. 비콘은 "보고 있는 페이지"를 이미 기록하므로, 그 호출까지 세면
    # 페이지 하나당 2건이 되어 이중 계산이 된다(2026-08-10 실측으로 잡음).
    "/api/v1/visit",
    # 헬스체크는 도커·LB 가 주기적으로 두드린다. 세면 "방문"이 기계 트래픽으로 뒤덮인다.
    # `/health` 만 적었더니 실제 경로인 `/api/v1/health` 가 안 걸러졌다(2026-08-10 실측).
    "/health",
    "/api/v1/health",
    "/nginx-health",
    "/.well-known/",
)
_SKIP_EXACT: frozenset[str] = frozenset({"/robots.txt", "/sitemap.xml"})

# 동적 구간 접기. 값이 매번 다른 조각만 :id 로 바꾼다.
#
# **대소문자를 무시하면 안 된다.** 처음에 `[A-Z0-9]{6,12}` 에 re.I 를 걸었더니
# `regions`·`congestion`·`places` 같은 **평범한 경로 이름까지 전부 :id 로 접혔다**
# (인기 경로 목록이 `/api/v1/:id` 뿐이 되어 쓸모가 없어졌다 — 2026-08-10 실측으로 잡음).
#
#   \d+                     : 스팟/축제 id (126508)
#   대문자+숫자 6~12자       : 공유 코드 (56AFBTB6) — **숫자를 최소 1개 요구**해
#                             `REGIONS` 같은 순수 대문자 단어를 걸러낸다
#   16자 이상 hex            : 해시성 식별자. 8자로 두면 `deadbeef` 류 단어와 겹친다
_DYNAMIC_SEGMENT = re.compile(
    r"^(?:\d+|(?=[A-Z0-9]{6,12}$)(?=.*\d)[A-Z0-9]+|[0-9a-f]{16,})$"
)

PATH_MAX = 80


def fold_path(path: str) -> str:
    """`/spot/126508` → `/spot/:id`. 경로 폭발을 막는 유일한 장치다."""
    if not path or path == "/":
        return "/"
    parts = [p for p in path.split("/") if p]
    folded = ["/" + (":id" if _DYNAMIC_SEGMENT.match(p) else p) for p in parts]
    out = "".join(folded)
    return out[:PATH_MAX]


def _secret_key() -> bytes:
    """IP 해싱 키. 서버 `.env` 안의 값이며 응답·로그 어디에도 나가지 않는다."""
    from ..config import settings

    raw = settings.admin_session_secret or settings.jwt_secret_key or "sumeungil-visit-fallback"
    return raw.encode("utf-8")


def visit_ip_hash(ip: str | None) -> str:
    """IP → 되돌릴 수 없는 16자 지문.

    **미들웨어와 페이지 비콘(`api/visit.py`)이 반드시 같은 함수를 써야 한다.**
    해시가 갈리면 같은 사람이 두 명으로 세어져 방문자 수가 부풀어 오른다.
    """
    key = _secret_key()
    raw = (ip or "unknown").encode("utf-8")
    return hmac.new(key, _IP_LABEL + raw, hashlib.sha256).hexdigest()[:16]


class VisitLogMiddleware(BaseHTTPMiddleware):
    """요청 1건을 (날짜, ip_hash) 단위 집계에 더한다.

    `db` 는 앱 기동 시 주입한다. `secret` 인자는 하위호환으로 남겨두되, 실제 해싱은
    모듈 함수 `visit_ip_hash` 를 쓴다 — 비콘과 키가 갈리지 않게 하기 위해서다.
    """

    def __init__(self, app, *, db, secret: str = "", trust_proxy: bool = True) -> None:
        super().__init__(app)
        self._db = db
        self._trust_proxy = trust_proxy

    def _ip_hash(self, ip: str | None) -> str:
        return visit_ip_hash(ip)

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        path = request.url.path
        if path in _SKIP_EXACT or any(path.startswith(p) for p in _SKIP_PREFIXES):
            return response
        # 4xx/5xx 는 세지 않는다 — 없는 경로를 긁는 봇이 "인기 페이지"를 만들어버린다.
        if response.status_code >= 400:
            return response

        try:
            now = now_kst()
            ip = extract_client_ip(request, trust_proxy=self._trust_proxy)
            await self._db.awrite(
                lambda conn: visit_repo.record(
                    conn,
                    day=now.strftime("%Y-%m-%d"),
                    hour=now.hour,
                    ip_hash=self._ip_hash(ip),
                    path=fold_path(path),
                    now_iso=now.isoformat(timespec="seconds"),
                )
            )
        except Exception as exc:  # noqa: BLE001
            # 통계는 부가 기능이다 — 절대 요청을 죽이지 않는다.
            logger.warning("방문 집계 실패(무시하고 계속): %s", exc)

        return response


__all__ = ("VisitLogMiddleware", "fold_path", "visit_ip_hash")
