"""/api/v1/courses/share · /shared — 코스 공유(데모). 계약 부록 R.

기존 `api/courses.py`(recommend/arrange)와 **같은 prefix 를 쓰는 별도 라우터**다. 파일을
나눈 이유: 코스 조립(무상태·공공데이터)과 코스 공유(사용자 데이터·저장소)는 실패 모드도
보안 성격도 다르다. 한 파일에 섞으면 조회 경로가 저장소 장애에 끌려 들어간다.

라우트 4개:
  POST   /api/v1/courses/share               공유 생성 → share_code
  GET    /api/v1/courses/shared              최근 공유 피드(payload 미포함)
  GET    /api/v1/courses/shared/{code}       상세(+조회수 증가)
  DELETE /api/v1/courses/shared/{code}       삭제(본인 기기만)

경로 우선순위 주의: `/shared` 와 `/shared/{code}` 는 세그먼트 수가 달라 충돌하지 않는다.
`share`(생성)와 `shared`(조회)를 다른 단어로 둔 것도 의도적이다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request

from ..config import settings
from ..db.sqlite import Database
from ..deps import get_database
from ..repositories import shared_course_repo
from ..schemas.community import (
    ShareCreateRequest,
    ShareCreateResponse,
    SharedCourseDetail,
    SharedCourseListResponse,
)
from ..services import share_service
from .community_common import (
    check_write_quota,
    ensure_enabled,
    read_device_id,
    require_device_id,
    to_response,
)

logger = logging.getLogger("sumeungil.api.course_share")

router = APIRouter(prefix="/api/v1/courses", tags=["course-share"])


@router.post("/share", response_model=ShareCreateResponse, status_code=201)
async def create_shared_course(
    request: Request,
    req: ShareCreateRequest,
    db: Database = Depends(get_database),
):
    try:
        ensure_enabled()
        device_id = require_device_id(request)
        limited = check_write_quota(device_id, "share")
        if limited is not None:
            return limited
        return await share_service.create_share(
            db,
            req=req,
            device_id=device_id,
            max_bytes=settings.share_payload_max_bytes,
        )
    except Exception as exc:  # noqa: BLE001 — to_response 가 종류별로 분기한다
        return to_response(exc, context="courses/share")


@router.get("/shared", response_model=SharedCourseListResponse)
async def list_shared_courses(
    limit: int = Query(default=share_service.DEFAULT_LIMIT, ge=1, le=shared_course_repo.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_database),
):
    """다른 사람이 공유한 코스 피드(최신순). 항목에 payload 를 싣지 않는다(목록 경량화)."""
    try:
        ensure_enabled()
        return await share_service.list_shares(db, limit=limit, offset=offset)
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="courses/shared/list")


@router.get("/shared/{share_code}", response_model=SharedCourseDetail)
async def get_shared_course(
    request: Request,
    share_code: str,
    db: Database = Depends(get_database),
):
    try:
        ensure_enabled()
        return await share_service.get_share(
            db, share_code=share_code, device_id=read_device_id(request)
        )
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="courses/shared/get")


@router.delete("/shared/{share_code}")
async def delete_shared_course(
    request: Request,
    share_code: str,
    db: Database = Depends(get_database),
):
    try:
        ensure_enabled()
        device_id = require_device_id(request)
        await share_service.delete_share(db, share_code=share_code, device_id=device_id)
        return {"deleted": True}
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="courses/shared/delete")
