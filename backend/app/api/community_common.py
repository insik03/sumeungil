"""부록 R 라우터 공통부 — 신원 헤더 · 에러 봉투 · 쓰기 쿼터.

리뷰 라우터와 코스 공유 라우터가 **완전히 같은 규칙**을 쓰도록 한 곳에 모았다.
두 라우터가 각자 헤더를 파싱하면 한쪽만 검증이 느슨해지는 사고가 난다.
"""

from __future__ import annotations

import logging
import psycopg

from fastapi import Request
from fastapi.responses import JSONResponse

from ..config import settings
from ..deps import get_community_write_limiter, get_database, get_user_auth
from ..middleware.rate_limit import rate_limited_response
from ..repositories import user_repo
from ..services import community_errors as errors
from ..services.community_errors import CommunityError
from ..util.user_text import is_valid_device_id

logger = logging.getLogger("sumeungil.api.community")

# 클라이언트가 localStorage 에 영구 보관하는 UUID v4 를 실어 보내는 헤더.
#
# !!! 이것은 인증이 아니다 !!!
# 서버는 이 값을 검증할 방법이 없다(누구든 임의의 값을 보낼 수 있다). 남의 device_id 를
# 알아내면 그 사람의 글을 수정·삭제할 수 있다는 뜻이다. 그래서 서버는 device_id 를
# **어떤 응답에도 싣지 않는다** — 유출 경로를 만들지 않는 것이 유일한 보호선이다.
# 정식 회원제로 갈 때 이 헤더는 Authorization 토큰으로 대체된다(계약 부록 R.9).
DEVICE_ID_HEADER = "X-Device-Id"


def error_response(
    status: int, code: str, message: str, detail: dict | None = None
) -> JSONResponse:
    """계약 §3 에러 봉투 — 기존 라우터와 동일 형식.

    `detail` 은 기본 `{}`(기존 동작 그대로). 값을 채우는 곳은 프론트가 분기해야 하는
    경우뿐이다(예: 409 REVIEW_EXISTS 의 `{"hidden": true}` — QA M-3).
    """
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": detail or {}}},
    )


def to_response(exc: BaseException, *, context: str) -> JSONResponse:
    """서비스 예외 → HTTP 응답. 라우터의 except 블록은 전부 이 함수만 부른다."""
    if isinstance(exc, CommunityError):
        # 업무 규칙 위반은 정상 흐름이다 — 스택트레이스를 남기지 않는다(로그 노이즈 방지).
        return error_response(exc.status, exc.code, exc.message, exc.detail)
    if isinstance(exc, psycopg.Error):
        # 디스크 가득참·권한·파일 손상 등. 사용자에게는 "잠시 후" 로만 알린다.
        logger.exception("%s 저장소 오류", context)
        err = errors.storage_unavailable()
        return error_response(err.status, err.code, err.message)
    logger.exception("%s 처리 중 예기치 못한 오류", context)
    return error_response(500, "INTERNAL", "서버 오류가 발생했습니다.")


def ensure_enabled() -> None:
    """킬스위치(COMMUNITY_ENABLED=false) — 읽기·쓰기 모두 닫는다."""
    if not settings.community_enabled:
        raise errors.feature_disabled()


def read_device_id(request: Request) -> str | None:
    """조회 경로용. 없거나 형식이 틀리면 None → `is_mine` 이 전부 false 가 될 뿐이다."""
    raw = request.headers.get(DEVICE_ID_HEADER)
    if raw is None:
        return None
    value = raw.strip()
    return value if is_valid_device_id(value) else None


def require_device_id(request: Request) -> str:
    """쓰기 경로용. 없으면 400 — 소유권을 기록할 수 없는 글을 만들지 않는다."""
    raw = request.headers.get(DEVICE_ID_HEADER)
    if raw is None or not raw.strip():
        raise errors.device_id_required()
    value = raw.strip()
    if not is_valid_device_id(value):
        raise errors.invalid_input(
            "INVALID_DEVICE_ID", "기기 식별자 형식이 올바르지 않습니다."
        )
    return value


async def session_display_name(request: Request) -> str | None:
    """유효한 구글 로그인 세션이면 **DB의 현재 표시 이름**을, 아니면 None을 돌려준다.

    2026-08-17 QA M-1 대응 — 로그인은 원래 "화면 게이트"일 뿐 리뷰·코스공유 같은 쓰기
    API는 여전히 device_id(익명, §DEVICE_ID_HEADER 주석 참고) 기준이라 클라이언트가 보낸
    nickname을 그대로 믿었다. 그래서 로그인 직후 "표시 이름 확인" 단계(LoginModal.tsx)를
    거치고도, 같은 브라우저가 API를 직접 호출하면 그 확인을 우회한 임의 nickname으로
    글을 쓸 수 있었다(clean_user_text/is_impersonating_staff는 여전히 걸려 사칭까지
    뚫리진 않지만, "로그인 시 확인한 이름만 쓴다"는 처리방침 3항과 실제 동작이 달랐다).

    로그인하지 않은 사용자의 **익명 작성 자체는 그대로 허용한다** — device_id 기반
    비로그인 리뷰·공유는 이 서비스가 처음부터 의도한 기능이고(community_common.py 상단
    주석, verify_community.py 회귀 스위트) 이번 변경의 대상이 아니다. 로그인한 사용자에
    한해서만 클라이언트가 보낸 nickname을 서버가 무시하고 세션의 display_name으로
    덮어쓴다 — 그래야 로그인의 "표시 이름 확인" 단계가 실제로 의미를 가진다."""
    auth = get_user_auth()
    if not auth.enabled:
        return None
    identity = auth.verify_token(request.cookies.get(auth.cookie_name))
    if identity is None:
        return None
    db = get_database()
    user = await db.aread(lambda conn: user_repo.get_by_id(conn, identity.user_id))
    return user["display_name"] if user else None


def check_write_quota(device_id: str, bucket: str) -> JSONResponse | None:
    """device_id 기준 분당 쓰기 한도. 초과면 미들웨어와 **같은 429 봉투**를 돌려준다.

    반환값이 None 이 아니면 라우터는 그 응답을 그대로 반환해야 한다(계속 진행 금지).
    """
    decision = get_community_write_limiter().check(device_id, bucket)
    if decision.allowed:
        return None
    # device_id 는 로그에도 남기지 않는다(버킷·한도만).
    logger.warning("429 device 쓰기 한도 초과 bucket=%s limit=%d", bucket, decision.limit)
    return rate_limited_response(decision, window_sec=60)


__all__ = (
    "DEVICE_ID_HEADER",
    "check_write_quota",
    "ensure_enabled",
    "error_response",
    "read_device_id",
    "require_device_id",
    "session_display_name",
    "to_response",
)
