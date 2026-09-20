"""/api/v1/reviews — 스팟·축제 후기(별점 + 한줄평). 계약 부록 R.

데모 수준 신원 모델: 헤더 `X-Device-Id`(클라이언트 생성 UUID) = 작성자 키. **인증이 아니다.**
자세한 경고는 `api/community_common.py` 상단 주석 참고.

라우트 6개:
  GET    /api/v1/reviews                 목록 + 요약
  GET    /api/v1/reviews/summary         여러 대상 요약 일괄(N+1 방지)
  POST   /api/v1/reviews                 작성(같은 기기 + 같은 대상 1건)
  PATCH  /api/v1/reviews/{id}            수정(본인만)
  DELETE /api/v1/reviews/{id}            삭제(본인만)
  POST   /api/v1/reviews/{id}/report     신고(누적 시 자동 숨김)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from ..cache.base import Cache
from ..config import settings
from ..db.postgres import Database
from ..deps import get_cache, get_database
from ..middleware.rate_limit import extract_client_ip
from ..middleware.visit_log import visit_ip_hash
from ..repositories import review_repo
from ..schemas.community import (
    ReviewCreateRequest,
    ReviewCreateResponse,
    ReviewItem,
    ReviewListResponse,
    ReviewReportRequest,
    ReviewSummaryMapResponse,
    ReviewUpdateRequest,
    TargetType,
)
from ..services import review_service
from .auth_deps import optional_identity, require_login
from .community_common import (
    check_write_quota,
    ensure_enabled,
    require_device_id,
    session_display_name,
    to_response,
)

logger = logging.getLogger("sumeungil.api.reviews")

router = APIRouter(prefix="/api/v1/reviews", tags=["reviews"])


@router.get("", response_model=ReviewListResponse)
async def get_reviews(
    request: Request,
    target_type: TargetType,
    target_id: str,
    limit: int = Query(default=review_service.DEFAULT_LIMIT, ge=1, le=review_repo.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_database),
):
    try:
        ensure_enabled()
        # 읽기는 비로그인도 된다. 로그인 중이면 is_mine 판정과 "내 숨김글 보기"에만 쓴다.
        # optional_identity 는 세션 검증 + DB 조회라 **한 번만** 부른다.
        viewer = await optional_identity(request)
        return await review_service.list_reviews(
            db,
            target_type=target_type,
            target_id=target_id,
            limit=limit,
            offset=offset,
            viewer_user_id=viewer.user_id if viewer else None,
        )
    except Exception as exc:  # noqa: BLE001 — to_response 가 종류별로 분기한다
        return to_response(exc, context="reviews/list")


@router.get("/summary", response_model=ReviewSummaryMapResponse)
async def get_review_summaries(
    target_type: TargetType,
    ids: str = Query(description="콤마로 구분한 target_id 목록 (최대 100개)"),
    db: Database = Depends(get_database),
):
    """카드 목록이 후기 요약을 **한 번에** 받아가는 엔드포인트.

    카드마다 `/reviews` 를 부르면 화면 하나에 수십 번의 요청이 나간다(N+1). 프론트는
    목록을 그릴 때 이 엔드포인트를 1회만 호출한다.
    """
    try:
        ensure_enabled()
        target_ids = [t for t in (ids or "").split(",") if t.strip()]
        return await review_service.summary_map(
            db, target_type=target_type, target_ids=target_ids
        )
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="reviews/summary")


@router.post("", response_model=ReviewCreateResponse, status_code=201)
async def create_review(
    request: Request,
    req: ReviewCreateRequest,
    db: Database = Depends(get_database),
):
    try:
        ensure_enabled()
        # 2026-09-20 — 후기는 **로그인 필수**다. 종전엔 이 검사가 프론트에만 있어서
        # X-Device-Id 헤더만 있으면 닉네임을 직접 지정해 비로그인으로 남길 수 있었다.
        identity = await require_login(request)
        device_id = require_device_id(request)
        # 쿼터 초과 시 JSONResponse(429)를 그대로 반환한다 — 데코레이터의 201 은 무시된다.
        limited = check_write_quota(device_id, "review")
        if limited is not None:
            return limited
        # 닉네임은 **항상** 서버가 확인한 계정 표시 이름이다(클라이언트 값은 무시).
        # 로그인이 필수가 된 이상 "비로그인은 기존 그대로" 분기는 더 이상 존재하지 않는다.
        logged_in_name = await session_display_name(request)
        if logged_in_name is not None:
            req = req.model_copy(update={"nickname": logged_in_name})
        return await review_service.create_review(
            db, req=req, user_id=identity.user_id, device_id=device_id
        )
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="reviews/create")


@router.patch("/{review_id}", response_model=ReviewItem)
async def update_review(
    request: Request,
    review_id: int,
    req: ReviewUpdateRequest,
    db: Database = Depends(get_database),
):
    try:
        ensure_enabled()
        identity = await require_login(request)
        device_id = require_device_id(request)
        limited = check_write_quota(device_id, "review")
        if limited is not None:
            return limited
        # QA M-1 — 이번 요청이 실제로 nickname 을 건드릴 때만 서버 확인값으로 덮어쓴다
        # (model_fields_set 유지 — 건드리지 않은 필드는 여전히 "변경 없음"으로 남는다).
        if "nickname" in req.model_fields_set:
            logged_in_name = await session_display_name(request)
            if logged_in_name is not None:
                req = req.model_copy(update={"nickname": logged_in_name})
        return await review_service.update_review(
            db, review_id=review_id, req=req, user_id=identity.user_id
        )
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="reviews/update")


@router.delete("/{review_id}")
async def delete_review(
    request: Request,
    review_id: int,
    db: Database = Depends(get_database),
):
    try:
        ensure_enabled()
        identity = await require_login(request)
        await review_service.delete_review(db, review_id=review_id, user_id=identity.user_id)
        return {"deleted": True}
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="reviews/delete")


@router.post("/{review_id}/report", status_code=202)
async def report_review(
    request: Request,
    review_id: int,
    req: ReviewReportRequest,
    db: Database = Depends(get_database),
    cache: Cache = Depends(get_cache),
):
    """신고 접수(202). 서로 다른 기기 N 건이 쌓이면 자동으로 숨김 처리된다.

    보안감사 F-03(2026-09): 기기 ID 는 클라이언트가 바꿀 수 있어 같은 IP 가 ID 만 바꿔 3회 신고하면
    남의 리뷰를 숨길 수 있었다. IP 가명 지문(방문 통계와 같은 함수) 기준으로 같은 리뷰엔 24시간
    1회만 집계한다 — 응답은 똑같이 202 라 우회 여부를 알 수 없다.
    """
    try:
        ensure_enabled()
        # 신고도 로그인 필수 — 익명 대량 신고로 남의 후기를 숨길 수 있으면 안 된다.
        # 중복 방지 기준(기기 + IP 가명 지문)은 F-03 그대로 둔다(스키마 무변경).
        await require_login(request)
        device_id = require_device_id(request)
        limited = check_write_quota(device_id, "review")
        if limited is not None:
            return limited
        ip_hash = visit_ip_hash(
            extract_client_ip(
                request,
                trust_proxy=settings.rate_limit_trust_proxy,
                trusted_networks=settings.rate_limit_trusted_proxy_networks or None,
            )
        )
        result = await review_service.report_review(
            db,
            review_id=review_id,
            reason=req.reason,
            device_id=device_id,
            hide_threshold=settings.review_hide_report_threshold,
            ip_hash=ip_hash or None,
            cache=cache,
        )
        return JSONResponse(status_code=202, content=result)
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="reviews/report")
