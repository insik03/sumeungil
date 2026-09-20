"""/api/v1/admin — 관리자(운영) 콘솔 API. 계약 부록 T.

## 존재 조건 (가장 중요)
`ADMIN_PASSWORD_HASH` 가 없거나 형식이 틀리면 **main.py 가 이 라우터를 등록하지 않는다.**
즉 관리자 기능이 꺼진 서버에서 `/api/v1/admin/*` 은 정의된 적 없는 경로(404)이고 OpenAPI
문서에도 나타나지 않는다. 기본 비밀번호·백도어·"개발용 우회"는 어디에도 없다.

## 인증 모델 (사용자 로그인과 완전히 분리)
사용자 쪽 "로그인"은 닉네임 + localStorage 이고 서버 계정이 없다(부록 R.0). 관리자는 그것과
값 하나도 공유하지 않는다 — 닉네임을 무엇으로 정하든, `X-Device-Id` 를 무엇으로 보내든
관리자가 될 수 없다. 관리자 판정의 유일한 근거는 **HttpOnly 세션 쿠키의 HMAC 서명**이다.

    POST /login  → 비밀번호 검증(scrypt) → 서명 토큰을 HttpOnly 쿠키로 발급(4시간, Mn-1)
    이후 요청    → 쿠키 서명·만료·비밀번호 지문 검증 → 통과해야만 운영 API 실행

## 실패 응답을 하나로 모으는 이유
비밀번호 오류·쿠키 없음·쿠키 변조·만료가 전부 **동일한 401 봉투**다. "비밀번호는 맞고
세션만 만료됐다" 같은 힌트를 주면 공격자에게 탐색 신호가 된다.

## 로그 규칙
비밀번호·해시·세션 토큰은 어떤 로그에도 남기지 않는다. 실패는 `ip_hash`(원본 IP 아님)와
시각만 남긴다.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from ..config import settings
from ..db.postgres import Database
from ..cache.base import Cache
from ..deps import get_admin_auth, get_admin_login_limiter, get_cache, get_database, get_spot_repository
from ..repositories.spot_repo import SpotRepository
from ..middleware.rate_limit import extract_client_ip, rate_limited_response
from ..repositories import admin_repo
from ..schemas.admin import (
    AdminOperatorsResponse,
    AdminTrafficResponse,
    AdminCourseListResponse,
    AdminInquiryItem,
    AdminInquiryListResponse,
    AdminInquiryReplyRequest,
    AdminLoginRequest,
    AdminModerationResponse,
    AdminOkResponse,
    AdminReviewListResponse,
    AdminAiStatusResponse,
    AdminServerStatusResponse,
    AdminSessionResponse,
    AdminStatsResponse,
    AdminUserListResponse,
    CourseStatusFilter,
    InquiryStatusFilter,
    ReviewSortOption,
    ReviewStatusFilter,
)
from ..security.admin_auth import AdminAuth
from ..services import admin_service
from ..services.community_errors import CommunityError
from ..services.share_service import normalize_share_code
from ..util.time import KST, to_iso_kst
from .community_common import to_response

logger = logging.getLogger("sumeungil.api.admin")

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

LOGIN_BUCKET = "admin_login"


def _unauthorized() -> CommunityError:
    """모든 인증 실패가 여기로 수렴한다(사유를 구분해 알려주지 않는다)."""
    return CommunityError(401, "UNAUTHORIZED", "관리자 인증이 필요합니다.")


def _require_session(request: Request) -> AdminAuth:
    """세션 쿠키 검증. 통과하지 못하면 401 을 던진다.

    라우터의 **모든** 운영 엔드포인트가 첫 줄에서 이 함수를 부른다. 미들웨어가 아니라
    명시 호출로 둔 이유: 새 엔드포인트를 추가할 때 "인증을 빠뜨리면 컴파일은 되지만
    공개된다"가 아니라, 이 파일의 패턴을 보고 반드시 복사하게 만들기 위해서다.
    (검증 스크립트가 라우터의 모든 경로에 대해 무인증 401 을 실제로 확인한다.)
    """
    auth = get_admin_auth()
    if not auth.enabled:  # 도달 불가(라우터 미등록) — 이중 안전장치
        raise _unauthorized()
    if auth.verify_token(request.cookies.get(auth.cookie_name)) is None:
        raise _unauthorized()
    return auth


def _client_ip(request: Request) -> str:
    """레이트리밋 미들웨어와 **같은 규칙**으로 클라이언트 IP 를 뽑는다(nginx 뒤 XFF 첫 값)."""
    return extract_client_ip(
        request,
        trust_proxy=settings.rate_limit_trust_proxy,
        trusted_networks=settings.rate_limit_trusted_proxy_networks or None,
    )


def _expires_iso(exp_epoch: int) -> str:
    return to_iso_kst(datetime.fromtimestamp(exp_epoch, tz=KST))


def _ip_hash(request: Request) -> str:
    return get_admin_auth().ip_hash(_client_ip(request))


def _operator(request: Request) -> str:
    """이번 요청을 수행하는 관리자 표시 이름(부록 V).

    **요청 바디가 아니라 세션 쿠키에서** 꺼낸다. 로그인 때 서명해 넣은 값이라 클라이언트가
    바꾸면 서명이 깨져 세션 자체가 무효가 된다 — 즉 남의 이름으로 로그를 남길 수 없다.
    """
    auth = get_admin_auth()
    return auth.token_operator(request.cookies.get(auth.cookie_name))


# --- 인증 ---------------------------------------------------------------------


@router.post("/login", response_model=AdminSessionResponse)
def admin_login(request: Request, req: AdminLoginRequest):
    """비밀번호 → 세션 쿠키.

    **`async def` 가 아니라 `def` 인 것은 의도다** (보안 점검 Mn-4, 2026-08-09).
    이 함수 안에서 도는 `verify_password` 는 scrypt(n=16384, 16MB)라 0.1~0.3초가 걸리는데,
    `async def` 로 두면 그 시간 동안 **이벤트 루프 전체가 멈춘다**(워커 1개 구성이다).
    서로 다른 IP 가 각자 한도(분당 5회) 안에서만 두드려도 블로킹이 누적돼 일반 조회 API 가
    함께 밀린다. `def` 로 두면 FastAPI 가 threadpool 로 보내 루프가 계속 돈다.
    이 파일의 다른 핸들러는 HMAC·쿠키 설정 수준(마이크로초)이라 `async def` 가 맞다 —
    사소한 작업을 threadpool 로 보내면 왕복 비용만 는다.

    쿠키 속성: HttpOnly(JS 접근 차단) · SameSite=Lax(교차 사이트 요청에 실려 나가지 않음) ·
    Secure(ADMIN_COOKIE_SECURE, 기본 true) · 4시간 만료(Mn-1).
    **토큰은 응답 바디에 넣지 않는다** — 넣는 순간 HttpOnly 가 무의미해진다.
    """
    auth = get_admin_auth()
    ip = _client_ip(request)

    # 브루트포스 방어 — 성공/실패와 무관하게 시도 1건을 소모한다(추측 속도 자체를 묶는다).
    decision = get_admin_login_limiter().check(ip, LOGIN_BUCKET)
    if not decision.allowed:
        logger.warning("429 admin 로그인 시도 과다 ip_hash=%s limit=%d", auth.ip_hash(ip), decision.limit)
        return rate_limited_response(decision, window_sec=60)

    if not auth.verify_password(req.password):
        # 비밀번호·길이·해시 어느 것도 로그에 남기지 않는다.
        logger.warning("admin 로그인 실패 ip_hash=%s", auth.ip_hash(ip))
        err = _unauthorized()
        return JSONResponse(
            status_code=err.status,
            content={"error": {"code": err.code, "message": err.message, "detail": {}}},
        )

    # 표시 이름 확인. 목록이 설정돼 있으면 그 안의 값이어야 한다.
    # 실패를 비밀번호 오류와 **같은 401** 로 수렴시키는 이유: 정상 사용자는 드롭다운에서
    # 고르므로 여기 걸릴 일이 없고, 걸렸다면 요청을 손으로 조작했다는 뜻이다.
    operator = (req.operator or "").strip()
    allowed = settings.admin_operators
    if allowed and operator not in allowed:
        logger.warning("admin 로그인 실패(이름 불일치) ip_hash=%s", auth.ip_hash(ip))
        err = _unauthorized()
        return JSONResponse(
            status_code=err.status,
            content={"error": {"code": err.code, "message": err.message, "detail": {}}},
        )

    token, exp = auth.issue_token(operator=operator)
    logger.info("admin 로그인 성공 by=%s ip_hash=%s", operator or "?", auth.ip_hash(ip))
    response = JSONResponse(
        status_code=200, content={"authenticated": True, "expires_at": _expires_iso(exp)}
    )
    response.set_cookie(
        key=auth.cookie_name,
        value=token,
        max_age=auth.session_ttl_sec,
        httponly=True,
        secure=auth.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/operators", response_model=AdminOperatorsResponse)
async def admin_operators():
    """로그인 화면이 "이름 입력칸이 필요한가"만 확인한다. **인증 없이** 조회된다.

    2026-08-18(외부 보안감사 3차): 운영자 표시 이름을 인증 없이 나열하던 응답을 **불리언
    하나로 줄였다**. 화면은 드롭다운 대신 입력칸을 그리고, 이름 대조는 종전대로 서버가
    ADMIN_OPERATORS 와 한다(틀리면 비밀번호 오류와 **같은 401**).
    관리자 기능이 꺼져 있으면 라우터가 등록되지 않아 이 경로도 존재하지 않는다(404).
    """
    return AdminOperatorsResponse(operators=[], required=bool(settings.admin_operators))

@router.post("/logout", response_model=AdminOkResponse)
async def admin_logout():
    """쿠키 만료. 서버에 세션 저장소가 없으므로(무상태 서명 토큰) 클라이언트 쿠키 삭제가
    곧 로그아웃이다. 토큰이 유출된 상황의 강제 무효화는 **비밀번호 해시 교체 + 재시작**이다
    (지문이 바뀌어 기존 토큰이 전부 무효가 된다 — DEPLOY.md 재설정 절차)."""
    auth = get_admin_auth()
    response = JSONResponse(status_code=200, content={"ok": True})
    response.delete_cookie(
        key=auth.cookie_name,
        path="/",
        httponly=True,
        secure=auth.cookie_secure,
        samesite="lax",
    )
    return response


@router.get("/me", response_model=AdminSessionResponse)
async def admin_me(request: Request):
    """프론트 가드용. 유효한 세션이면 200 + 만료시각, 아니면 401(같은 봉투)."""
    try:
        auth = _require_session(request)
        exp = auth.verify_token(request.cookies.get(auth.cookie_name))
        assert exp is not None  # _require_session 을 통과했으므로 항상 참
        return AdminSessionResponse(authenticated=True, expires_at=_expires_iso(exp))
    except Exception as exc:  # noqa: BLE001 — to_response 가 종류별로 분기한다
        return to_response(exc, context="admin/me")


# --- 리뷰 운영 -----------------------------------------------------------------


@router.get("/reviews", response_model=AdminReviewListResponse)
async def admin_list_reviews(
    request: Request,
    status: ReviewStatusFilter = Query(default="reported"),
    sort: ReviewSortOption = Query(default="reported"),
    limit: int = Query(default=admin_repo.DEFAULT_LIMIT, ge=1, le=admin_repo.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_database),
):
    """공개 목록과 달리 **숨김(hidden=1) 도 함께** 조회된다(그게 운영 화면의 목적이다)."""
    try:
        auth = _require_session(request)
        return await admin_service.list_reviews(
            db, auth=auth, status=status, sort=sort, limit=limit, offset=offset
        )
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="admin/reviews/list")


@router.post("/reviews/{review_id}/hide", response_model=AdminModerationResponse)
async def admin_hide_review(request: Request, review_id: int, db: Database = Depends(get_database)):
    try:
        _require_session(request)
        return await admin_service.set_review_hidden(
            db, review_id=review_id, hidden=True, ip_hash=_ip_hash(request), operator=_operator(request)
        )
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="admin/reviews/hide")


@router.post("/reviews/{review_id}/unhide", response_model=AdminModerationResponse)
async def admin_unhide_review(
    request: Request, review_id: int, db: Database = Depends(get_database)
):
    """신고 누적 자동 숨김(부록 R.6)의 오탐을 되돌리는 경로. 삭제가 아니라 플래그라 복구된다."""
    try:
        _require_session(request)
        return await admin_service.set_review_hidden(
            db, review_id=review_id, hidden=False, ip_hash=_ip_hash(request), operator=_operator(request)
        )
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="admin/reviews/unhide")


@router.delete("/reviews/{review_id}", response_model=AdminModerationResponse)
async def admin_delete_review(
    request: Request, review_id: int, db: Database = Depends(get_database)
):
    """**되돌릴 수 없다.** 신고 기록도 FK CASCADE 로 함께 사라진다.
    가릴 목적이라면 hide 를 쓰고, delete 는 불법·명백한 스팸에만 쓴다."""
    try:
        _require_session(request)
        return await admin_service.delete_review(
            db, review_id=review_id, ip_hash=_ip_hash(request), operator=_operator(request)
        )
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="admin/reviews/delete")


# --- 공유 코스 운영 --------------------------------------------------------------


@router.get("/courses", response_model=AdminCourseListResponse)
async def admin_list_courses(
    request: Request,
    status: CourseStatusFilter = Query(default="all"),
    limit: int = Query(default=admin_repo.DEFAULT_LIMIT, ge=1, le=admin_repo.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_database),
):
    try:
        auth = _require_session(request)
        return await admin_service.list_courses(
            db, auth=auth, status=status, limit=limit, offset=offset
        )
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="admin/courses/list")


@router.post("/courses/{share_code}/hide", response_model=AdminModerationResponse)
async def admin_hide_course(
    request: Request, share_code: str, db: Database = Depends(get_database)
):
    try:
        _require_session(request)
        # 공개 경로와 같은 정규화(대소문자·공백 관용, 형식 위반은 404)를 그대로 쓴다.
        code = normalize_share_code(share_code)
        return await admin_service.set_course_hidden(
            db, share_code=code, hidden=True, ip_hash=_ip_hash(request), operator=_operator(request)
        )
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="admin/courses/hide")


@router.post("/courses/{share_code}/unhide", response_model=AdminModerationResponse)
async def admin_unhide_course(
    request: Request, share_code: str, db: Database = Depends(get_database)
):
    try:
        _require_session(request)
        code = normalize_share_code(share_code)
        return await admin_service.set_course_hidden(
            db, share_code=code, hidden=False, ip_hash=_ip_hash(request), operator=_operator(request)
        )
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="admin/courses/unhide")


@router.delete("/courses/{share_code}", response_model=AdminModerationResponse)
async def admin_delete_course(
    request: Request, share_code: str, db: Database = Depends(get_database)
):
    try:
        _require_session(request)
        code = normalize_share_code(share_code)
        return await admin_service.delete_course(
            db, share_code=code, ip_hash=_ip_hash(request), operator=_operator(request)
        )
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="admin/courses/delete")


# --- 고객문의 운영 --------------------------------------------------------------


@router.get("/inquiries", response_model=AdminInquiryListResponse)
async def admin_list_inquiries(
    request: Request,
    status: InquiryStatusFilter = Query(default="new"),
    limit: int = Query(default=admin_repo.DEFAULT_LIMIT, ge=1, le=admin_repo.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_database),
):
    try:
        _require_session(request)
        return await admin_service.list_inquiries(db, status=status, limit=limit, offset=offset,
                                                  operator=_operator(request), ip_hash=_ip_hash(request))
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="admin/inquiries/list")


@router.post("/inquiries/{inquiry_id}/reply", response_model=AdminInquiryItem)
async def admin_reply_inquiry(
    request: Request,
    inquiry_id: int,
    req: AdminInquiryReplyRequest = AdminInquiryReplyRequest(),
    db: Database = Depends(get_database),
):
    """답변 등록. 문의 1건당 답변은 1개뿐이라(스레드형 대화 아님) 재호출 시 기존 답변을
    덮어쓴다 — 오탈자 정정 등 재작성 시나리오를 위해 의도적으로 막지 않는다.

    `req`에 기본값을 준 이유: body 파라미터가 required면 **본문 자체가 아예 없는 요청**은
    FastAPI가 "Field required"(loc=body) 422를 내부 필드 검사보다도 먼저 던진다 — 인증
    여부와 무관하게 이 라우트만 401 대신 422가 나가 위의 "모든 실패가 동일한 401" 원칙이
    깨진다. 기본값을 주면 본문이 아예 없어도 빈 모델로 통과해 `_require_session`까지
    도달하고, 그 뒤에야 401 또는(인증 통과 후) 빈 reply 422로 갈린다."""
    try:
        _require_session(request)
        trimmed = req.reply.strip()
        if not trimmed:
            raise CommunityError(422, "VALIDATION_ERROR", "답변 내용을 입력해주세요.")
        return await admin_service.reply_inquiry(
            db,
            inquiry_id=inquiry_id,
            reply=trimmed,
            ip_hash=_ip_hash(request),
            operator=_operator(request),
        )
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="admin/inquiries/reply")


# --- 회원 (2026-08-23, 대표 지시 "닉네임 정도는 보고 싶은데") -------------------------


@router.get("/users", response_model=AdminUserListResponse)
async def admin_list_users(
    request: Request,
    limit: int = Query(default=admin_repo.DEFAULT_LIMIT, ge=1, le=admin_repo.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_database),
):
    """닉네임·가입일·마지막 로그인·로그인수단만. email·외부 provider ID는 응답에 없다."""
    try:
        _require_session(request)
        return await admin_service.list_users(db, limit=limit, offset=offset,
                                              operator=_operator(request), ip_hash=_ip_hash(request))
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="admin/users/list")


# --- 대시보드 ------------------------------------------------------------------


@router.get("/traffic", response_model=AdminTrafficResponse)
async def admin_traffic(request: Request, days: int = 14, db: Database = Depends(get_database)):
    """방문 집계(부록 X). 대표 지시로 추가한 운영 대시보드용 데이터.

    **원본 IP 는 저장하지 않으므로 여기서도 나오지 않는다.** `heavy_clients` 의 `ip_hash` 는
    키 붙은 HMAC 앞 16자이며, "한 명이 몇 번 두드렸나"만 알 수 있다(신원·국가 판별 불가).
    """
    try:
        _require_session(request)
        return await admin_service.traffic(db, days=max(1, min(days, 90)))
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="admin/traffic")

@router.get("/stats", response_model=AdminStatsResponse)
async def admin_stats(request: Request, db: Database = Depends(get_database)):
    """가벼운 COUNT 7개. 첫 화면이 무거우면 관리자가 쓰지 않게 된다."""
    try:
        _require_session(request)
        return await admin_service.stats(db)
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="admin/stats")


@router.get("/ai-status", response_model=AdminAiStatusResponse)
async def admin_ai_status(
    request: Request,
    cache: Cache = Depends(get_cache),
    spot_repo: SpotRepository = Depends(get_spot_repository),
):
    """AI 사용량(2026-09-20). Gemini 한도·코스 LLM 일일 상한·사전 생성 요약·CSP 보고 집계."""
    try:
        _require_session(request)
        return await admin_service.ai_status(cache, spot_repo)
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="admin/ai-status")


@router.get("/server-status", response_model=AdminServerStatusResponse)
async def admin_server_status(request: Request):
    """서버 상태(2026-08-23, 대표 지시 "그라파나랑 운영대시보드랑 붙여야 한다").

    DB를 안 본다 — Prometheus만 조회하므로 `db` 의존성이 없다. 조회 실패해도
    500이 아니라 `reachable=false`로 정상 응답한다(프론트가 "확인 불가"를
    보여줄 수 있게).
    """
    try:
        _require_session(request)
        return await admin_service.server_status()
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="admin/server-status")
