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
from .rate_limit import extract_client_ip, scope_path

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


# 키 미설정 경고는 **딱 한 번만** 찍는다 — 요청마다 찍으면 로그가 경고로 뒤덮여
# 정작 봐야 할 오류가 묻힌다.
_key_warned = False


def _secret_key() -> bytes | None:
    """IP 해싱 키. 서버 `.env` 안의 값이며 응답·로그 어디에도 나가지 않는다.

    우선순위 (2026-08-18 보안 감사 A-3 — 하드코딩 폴백 제거):
      ① `ADMIN_SESSION_SECRET`  ② `JWT_SECRET_KEY`
      ③ `ADMIN_PASSWORD_HASH` 에서 파생(`security.admin_auth.derive_signing_key` 재사용)
      ④ 셋 다 없으면 **None → 방문 집계를 끈다(fail-closed)**

    ④가 핵심이다. 예전에는 `"sumeungil-visit-fallback"` 이라는 **저장소에 적힌 문자열**을
    폴백 키로 썼는데, 그러면 ip_hash 가 공개 상수로 계산되는 값이 되어 "서버 시크릿 없이는
    역산 불가"라는 전제(파일 상단 원칙 2)가 그냥 거짓이 된다 — 후보 IP 를 대입해 누가 언제
    무엇을 봤는지 되맞출 수 있다. 가명화가 성립하지 않으면 집계 자체를 하지 않는 편이 맞다.
    """
    from ..config import settings

    raw = (settings.admin_session_secret or "").strip() or (settings.jwt_secret_key or "").strip()
    if raw:
        return raw.encode("utf-8")

    # ③ 관리자 세션 서명키와 **같은 파생 방식**을 쓴다(키를 새로 만들지 않는다).
    #    HMAC 안쪽에 _IP_LABEL 이 붙어 있어 세션 서명과 용도 분리는 유지된다.
    password_hash = (getattr(settings, "admin_password_hash", "") or "").strip()
    if password_hash:
        from ..security.admin_auth import derive_signing_key

        return derive_signing_key(password_hash=password_hash, session_secret=None)

    return None


def _warn_no_key_once() -> None:
    global _key_warned
    if _key_warned:
        return
    _key_warned = True
    logger.warning(
        "방문 집계 비활성화 — IP 가명화 키가 없습니다. "
        "ADMIN_SESSION_SECRET(권장) 또는 JWT_SECRET_KEY 를 .env 에 설정하세요."
    )


def visit_ip_hash(ip: str | None) -> str:
    """IP → 되돌릴 수 없는 16자 지문. **키가 없으면 빈 문자열**(= 집계하지 말라는 신호).

    **미들웨어와 페이지 비콘(`api/visit.py`)이 반드시 같은 함수를 써야 한다.**
    해시가 갈리면 같은 사람이 두 명으로 세어져 방문자 수가 부풀어 오른다.
    """
    key = _secret_key()
    if key is None:
        _warn_no_key_once()
        return ""
    raw = (ip or "unknown").encode("utf-8")
    return hmac.new(key, _IP_LABEL + raw, hashlib.sha256).hexdigest()[:16]


class VisitLogMiddleware(BaseHTTPMiddleware):
    """요청 1건을 (날짜, ip_hash) 단위 집계에 더한다.

    `db` 만 앱 기동 시 주입한다. **해싱 키는 주입받지 않는다** — 실제 해싱은 모듈 함수
    `visit_ip_hash` 가 하고, 페이지 비콘(`api/visit.py`)도 같은 함수를 부른다. 키를 여기로
    주입하면 두 경로가 다른 키를 쓸 여지가 생기고, 그러면 같은 사람이 두 명으로 세어진다.

    2026-08-18(QA Minor-4): 쓰이지 않던 `secret=` 인자를 제거했다. 남겨 두면 "이 값이 해싱에
    쓰인다"고 오해를 부른다(실제로 main.py 주석이 그 오해를 그대로 적고 있었다).
    """

    def __init__(self, app, *, db, trust_proxy: bool = True, trusted_networks=None) -> None:
        super().__init__(app)
        self._db = db
        self._trust_proxy = trust_proxy
        self._trusted_networks = trusted_networks

    def _ip_hash(self, ip: str | None) -> str:
        return visit_ip_hash(ip)

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # 스킵 판정도 **ASGI 원본 경로**로 한다(2026-08-18 보안 감사 A-1과 같은 이유) —
        # Host 헤더로 재구성되는 url.path 를 쓰면 제외 목록(/api/v1/admin 등)이 흔들릴 수 있다.
        path = scope_path(request)
        if path in _SKIP_EXACT or any(path.startswith(p) for p in _SKIP_PREFIXES):
            return response
        # 4xx/5xx 는 세지 않는다 — 없는 경로를 긁는 봇이 "인기 페이지"를 만들어버린다.
        if response.status_code >= 400:
            return response

        try:
            now = now_kst()
            ip = extract_client_ip(
                request, trust_proxy=self._trust_proxy, trusted_networks=self._trusted_networks
            )
            ip_hash = self._ip_hash(ip)
            if not ip_hash:
                # 가명화 키 미설정 → 집계 자체를 건너뛴다(fail-closed, 경고는 1회만).
                return response
            await self._db.awrite(
                lambda conn: visit_repo.record(
                    conn,
                    day=now.strftime("%Y-%m-%d"),
                    hour=now.hour,
                    ip_hash=ip_hash,
                    path=fold_path(path),
                    now_iso=now.isoformat(timespec="seconds"),
                )
            )
        except Exception as exc:  # noqa: BLE001
            # 통계는 부가 기능이다 — 절대 요청을 죽이지 않는다.
            logger.warning("방문 집계 실패(무시하고 계속): %s", exc)

        return response


__all__ = ("VisitLogMiddleware", "fold_path", "visit_ip_hash")
