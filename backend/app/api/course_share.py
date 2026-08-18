"""/api/v1/courses/share · /shared · /mine — 코스 공유·저장(사용자 데이터). 계약 부록 R.

기존 `api/courses.py`(recommend/arrange)와 **같은 prefix 를 쓰는 별도 라우터**다. 파일을
나눈 이유: 코스 조립(무상태·공공데이터)과 코스 공유·저장(사용자 데이터·저장소)은 실패 모드도
보안 성격도 다르다. 한 파일에 섞으면 조회 경로가 저장소 장애에 끌려 들어간다.

라우트 7개:
  POST   /api/v1/courses/share               공유 생성 → share_code(device_id 기준, 공개)
  GET    /api/v1/courses/shared              최근 공유 피드(payload 미포함)
  GET    /api/v1/courses/shared/{code}       상세(+조회수 증가)
  DELETE /api/v1/courses/shared/{code}       삭제(본인 기기만)
  POST   /api/v1/courses/mine                내 코스 저장(2026-08-17 신설, 로그인 필수)
  GET    /api/v1/courses/mine                내가 저장한 코스 목록(로그인 필수)
  DELETE /api/v1/courses/mine/{id}           내 코스 삭제(본인 계정만, 로그인 필수)

경로 우선순위 주의: `/shared` 와 `/shared/{code}` 는 세그먼트 수가 달라 충돌하지 않는다.
`share`(생성)와 `shared`(조회)를 다른 단어로 둔 것도 의도적이다. `/mine`은 device_id가
아니라 **로그인 계정(user_id)** 기준 — `/share`·`/shared`(익명 공개 공유)와는 완전히 다른
신원 모델이다(대표 지시 — AI 코스짜기는 로그인 필수, 저장한 코스는 계정에 묶인다).
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Query, Request

from ..config import settings
from ..db.postgres import Database
from ..deps import get_database
from ..repositories import ai_course_repo, shared_course_repo
from ..schemas.community import (
    ShareCreateRequest,
    ShareCreateResponse,
    SharedCourseDetail,
    SharedCourseListResponse,
)
from ..schemas.courses import (
    MyCourseDetail,
    MyCourseListResponse,
    MyCourseSummaryResponse,
    SaveCourseRequest,
)
from ..security.user_auth import UserIdentity
from ..services import community_errors as errors
from ..services import share_service
from ..util.time import now_kst, to_iso_kst
from .auth_deps import require_login
from .community_common import (
    check_write_quota,
    ensure_enabled,
    error_response,
    read_device_id,
    require_device_id,
    session_display_name,
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
        # QA M-1(2026-08-17) — 로그인 중이면 클라이언트 nickname을 서버 확인값으로 덮어쓴다
        # (community_common.session_display_name — reviews.py와 동일 원칙).
        logged_in_name = await session_display_name(request)
        if logged_in_name is not None:
            req = req.model_copy(update={"nickname": logged_in_name})
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


# --- 2026-08-17 신설: 내가 저장한 AI 코스 (Phase C, 대표 지시) ----------------------
#
# 위 /share·/shared(device_id 기준, 공개 공유 링크)와 신원 모델이 다르다 — 여기는
# 로그인 계정(user_id) 전용 개인 보관함이라 셋 다 require_login이 걸린다. 별도 서비스
# 레이어를 두지 않았다 — 로직이 소유권 확인 정도로 단순해 auth.py/community_common.py
# 처럼 라우터가 리포지토리를 직접 호출하는 기존 패턴을 그대로 따랐다.


@router.post("/mine", response_model=MyCourseSummaryResponse, status_code=201)
async def save_my_course(
    req: SaveCourseRequest,
    db: Database = Depends(get_database),
    identity: UserIdentity = Depends(require_login),
):
    """AI 코스짜기 결과를 계정에 저장한다. 자동 저장이 아니라 사용자가 명시적으로
    "저장하기"를 눌렀을 때만 호출된다(CourseContent.tsx)."""
    row = await db.awrite(
        lambda conn: ai_course_repo.create(
            conn,
            user_id=identity.user_id,
            region_code=req.region_code,
            mode=req.mode,
            payload_json=json.dumps(req.course),
            now_iso=to_iso_kst(now_kst()),
        )
    )
    return row


@router.get("/mine", response_model=MyCourseListResponse)
async def list_my_courses(
    db: Database = Depends(get_database),
    identity: UserIdentity = Depends(require_login),
):
    rows = await db.aread(lambda conn: ai_course_repo.list_by_user(conn, user_id=identity.user_id))
    return MyCourseListResponse(items=rows)


@router.get("/mine/{course_id}", response_model=MyCourseDetail)
async def get_my_course(
    course_id: int,
    db: Database = Depends(get_database),
    identity: UserIdentity = Depends(require_login),
):
    try:
        row = await db.aread(lambda conn: ai_course_repo.get(conn, course_id=course_id))
        if row is None or row["user_id"] != identity.user_id:
            # 남의 코스 id를 넣어도 "존재하지 않음"으로만 응답한다(다른 사람이 몇 건
            # 저장했는지 유추할 단서를 주지 않는다 — community_common의 device_id 비노출과
            # 같은 원칙).
            raise errors.not_found("저장한 코스를 찾을 수 없습니다.")
        return {**row, "course": json.loads(row["payload"])}
    except Exception as exc:  # noqa: BLE001
        return to_response(exc, context="courses/mine/get")


@router.delete("/mine/{course_id}")
async def delete_my_course(
    course_id: int,
    db: Database = Depends(get_database),
    identity: UserIdentity = Depends(require_login),
):
    deleted = await db.awrite(
        lambda conn: ai_course_repo.delete(conn, course_id=course_id, user_id=identity.user_id)
    )
    if not deleted:
        return error_response(404, "NOT_FOUND", "저장한 코스를 찾을 수 없습니다.")
    return {"deleted": True}
