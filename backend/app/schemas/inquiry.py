"""고객문의(inquiries) 요청/응답 모델 (2026-08-18 신설 — 대표 지시 "고객문의창도 있어야
할 거 같은데?"). schemas/courses.py의 MyCourseSummary 계열과 동일한 규약."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MESSAGE_MAX = 2000
CONTACT_EMAIL_MAX = 254  # RFC 5321 이메일 최대 길이 관례값 — 엄격한 형식 검증은 하지 않는다.


class CreateInquiryRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MESSAGE_MAX)
    contact_email: str | None = Field(default=None, max_length=CONTACT_EMAIL_MAX)


class InquirySummary(BaseModel):
    """목록 1건(본인 문의 내역용). message 전문은 상세에서만.

    reply/replied_at은 관리자가 답변을 등록해야만 값이 있다(2026-08-18 추가) — 답변이
    어딘가엔 보여야 "답변 작성" 기능이 완결되므로, 본인 문의 목록에서 바로 보여준다.
    """

    id: int
    status: Literal["new", "resolved"]
    created_at: str
    reply: str | None = None
    replied_at: str | None = None


class InquiryDetail(InquirySummary):
    message: str
    contact_email: str | None = None


class InquiryListResponse(BaseModel):
    items: list[InquirySummary] = Field(default_factory=list)


__all__ = (
    "CONTACT_EMAIL_MAX",
    "MESSAGE_MAX",
    "CreateInquiryRequest",
    "InquiryDetail",
    "InquiryListResponse",
    "InquirySummary",
)
