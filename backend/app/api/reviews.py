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

from ..config import settings
from ..db.sqlite import Database
from ..deps import get_database
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
from .community_common import (
    check_write_quota,
    ensure_enabled,
    read_device_id,
    require_device_id,
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
        return await review_service.list_reviews(
            db,
            target_type=target_type,
            target_id=target_id,
            limit=limit,
            offset=offset,
            device_id=read_device_id(request),
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
        device_id = require_device_id(request)
        # 쿼터 초과 시 JSONResponse(429)를 그대로 반환한다 — 데코레이터의 201 은 무시된다.
        limited = check_write_quota(device_id, "review")
        if limited is not None:
            return limited
        return await review_service.create_review(db, req=req, device_id=device_id)
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
        device_id = require_device_id(request)
        limited = check_write_quota(device_id, "review")
        if limited is not None:
            return limited
        return await review_service.update_review(
            db, review_id=review_id, req=req, device_id=device_id
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
        device_id = require_device_id(request)
        await review_service.delete_review(db, review_id=review_id, device_id=device_id)
        return {"deleted": True}
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="reviews/delete")


@router.post("/{review_id}/report", status_code=202)
async def report_review(
    request: Request,
    review_id: int,
    req: ReviewReportRequest,
    db: Database = Depends(get_database),
):
    """신고 접수(202). 서로 다른 기기 N 건이 쌓이면 자동으로 숨김 처리된다."""
    try:
        ensure_enabled()
        device_id = require_device_id(request)
        limited = check_write_quota(device_id, "review")
        if limited is not None:
            return limited
        result = await review_service.report_review(
            db,
            review_id=review_id,
            reason=req.reason,
            device_id=device_id,
            hide_threshold=settings.review_hide_report_threshold,
        )
        return JSONResponse(status_code=202, content=result)
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="reviews/report")
