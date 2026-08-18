"""/api/v1/inquiries — 고객문의 (2026-08-18 신설, 대표 지시 "고객문의창도 있어야 할 거
같은데?"). 마이페이지 "나의 활동" 5번째 타일에서만 진입한다 — 로그인 필수(auth_deps.
require_login), course_share.py의 /courses/mine과 동일한 구조.

**범위 합의(대표 확인)**: "간단한 문의 폼 + DB 저장"까지만. admin 콘솔에서 목록을 보는
화면은 별도 후속 작업 — 지금은 저장된 문의를 보려면 DB를 직접 조회해야 한다(SELECT *
FROM inquiries ORDER BY created_at DESC).

message는 clean_user_text(util/user_text.py)를 쓰지 않는다 — 그 파이프라인은 짧은 텍스트
(닉네임·리뷰·코스 제목)용으로 설계돼 300자 하드 절단이 걸려 있고("사용자 텍스트 → 저장
가능한 한 줄 평문"), 애초에 목적이 LLM 프롬프트 인젝션·공개 렌더 XSS 방지인데 문의 내용은
둘 다 해당 없다(관리자만 읽고, 어떤 LLM에도 넣지 않는다 — LLM 불변식 유지). Pydantic
max_length(2000)로 길이만 막는다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_database
from ..repositories import inquiry_repo
from ..schemas.inquiry import CreateInquiryRequest, InquiryListResponse, InquirySummary
from ..security.user_auth import UserIdentity
from ..util.time import now_kst, to_iso_kst
from .auth_deps import require_login

logger = logging.getLogger("sumeungil.api.inquiries")
router = APIRouter(prefix="/api/v1/inquiries", tags=["inquiries"])


@router.post("", response_model=InquirySummary, status_code=201)
async def create_inquiry(
    req: CreateInquiryRequest,
    identity: UserIdentity = Depends(require_login),
):
    # 2026-08-18(qa-reviewer K-m1) — Pydantic min_length=1은 공백 하나(" ")도 통과시킨다.
    # strip() 후 빈 문자열이면 여기서 막는다(그대로 두면 빈 문의가 저장된다).
    trimmed_message = req.message.strip()
    if not trimmed_message:
        raise HTTPException(status_code=422, detail="문의 내용을 입력해주세요.")
    db = get_database()
    contact_email = (req.contact_email or "").strip() or None
    row = await db.awrite(
        lambda conn: inquiry_repo.create(
            conn,
            user_id=identity.user_id,
            message=trimmed_message,
            contact_email=contact_email,
            now_iso=to_iso_kst(now_kst()),
        )
    )
    logger.info("문의 접수 id=%s user_id=%s", row["id"], identity.user_id)
    return row


@router.get("/mine", response_model=InquiryListResponse)
async def list_my_inquiries(identity: UserIdentity = Depends(require_login)):
    db = get_database()
    rows = await db.aread(lambda conn: inquiry_repo.list_by_user(conn, user_id=identity.user_id))
    return InquiryListResponse(items=rows)


__all__ = ("router",)
