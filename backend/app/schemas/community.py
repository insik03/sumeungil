"""리뷰 · 코스 공유(데모) 요청/응답 모델 = 01-interface-contract.md 부록 R 코드화.

## 신원 모델 (읽고 시작할 것)
이 스키마 어디에도 `device_id` 필드가 없다. 기기 식별자는 **요청 헤더 `X-Device-Id`** 로만
오가며 **응답에는 절대 나가지 않는다**. 대신 서버가 대조해 `is_mine` 불리언만 내려준다.
device_id 를 내려주면 다른 사용자의 식별자를 수집해 그 사람인 척 수정·삭제할 수 있다 —
인증이 없는 데모라 이 노출 금지가 유일한 소유권 보호선이다.

## 검증 위치
길이·범위 검증은 pydantic(→ 422)이 담당하고, 정제(HTML 태그·제어문자 제거)와 업무 규칙
(중복 리뷰·소유권)은 서비스 레이어(→ 400/403/409)가 담당한다. 두 곳으로 나눈 이유는
"형식 오류"와 "규칙 위반"을 프론트가 구분해 다르게 안내할 수 있게 하기 위해서다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

TargetType = Literal["spot", "festival"]

NICKNAME_MAX = 20
COMMENT_MAX = 300
TITLE_MAX = 40
REASON_MAX = 200
TARGET_ID_MAX = 40


def _coerce_target_id(v: Any) -> Any:
    """프론트가 스팟 id 를 숫자로 보내도 받아준다(pydantic v2 는 int→str 자동 변환을 안 한다).

    실수로 float/bool 이 오면 그대로 422 로 떨어뜨린다 — 조용히 문자열로 만들면
    `123.0` 같은 값이 별개의 target_id 로 저장돼 리뷰가 두 갈래로 쪼개진다.
    """
    if isinstance(v, bool):
        return v  # bool 은 int 서브클래스라 먼저 걸러 422 로 보낸다
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return v.strip()
    return v


# --- 리뷰 ---------------------------------------------------------------------


class ReviewCreateRequest(BaseModel):
    target_type: TargetType
    target_id: str = Field(min_length=1, max_length=TARGET_ID_MAX)
    nickname: str = Field(min_length=1, max_length=NICKNAME_MAX)
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=COMMENT_MAX)

    @field_validator("target_id", mode="before")
    @classmethod
    def _target_id(cls, v: Any) -> Any:
        return _coerce_target_id(v)


class ReviewUpdateRequest(BaseModel):
    """PATCH — 보낸 필드만 바꾼다. 셋 다 없으면 400 NOTHING_TO_UPDATE."""

    nickname: str | None = Field(default=None, min_length=1, max_length=NICKNAME_MAX)
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=COMMENT_MAX)


class ReviewReportRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=REASON_MAX)


class ReviewItem(BaseModel):
    id: int
    nickname: str
    rating: int
    comment: str | None = None
    created_at: str
    updated_at: str
    # 서버가 헤더 device_id 와 대조해 계산한 값. 프론트는 이 값으로만 수정/삭제 버튼을 노출한다
    # (원본 device_id 는 응답에 없다).
    is_mine: bool = False
    # QA M-3(2026-08-01): 신고 누적으로 가려진 글. **본인 응답에서만 true 가 될 수 있다** —
    # 타인 목록에는 숨김 글이 애초에 실리지 않으므로 남의 글에서 true 를 보는 경우는 없다.
    # 프론트는 true 면 "신고가 누적돼 가려진 상태" 배지를 달고 수정·삭제 버튼은 유지한다.
    hidden: bool = False


class ReviewSummary(BaseModel):
    """average 는 리뷰가 0건이면 null — 0.0 으로 내리면 "별 0점"으로 오독된다."""

    average: float | None = None
    count: int = 0
    # 키는 "1"~"5" 문자열(JSON 객체 키는 문자열이어야 한다). 값이 0인 등급도 항상 포함한다.
    distribution: dict[str, int] = Field(default_factory=dict)


class ReviewListResponse(BaseModel):
    summary: ReviewSummary
    items: list[ReviewItem] = Field(default_factory=list)
    total: int = 0


class ReviewCreateResponse(BaseModel):
    review: ReviewItem
    summary: ReviewSummary


class ReviewSummaryMapResponse(BaseModel):
    """카드 목록용 일괄 요약. 키는 target_id 문자열.

    카드 N 개가 각자 `/reviews` 를 부르는 N+1 을 막기 위한 엔드포인트다. 요청한 id 중
    리뷰가 하나도 없는 것은 `{average: null, count: 0}` 으로 **반드시 포함**한다 —
    프론트가 키 존재 여부로 분기하지 않게 하기 위해서다.
    """

    summaries: dict[str, ReviewSummary] = Field(default_factory=dict)


# --- 코스 공유 -----------------------------------------------------------------


class ShareCreateRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=NICKNAME_MAX)
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    # 기존 코스 응답 구조를 그대로 보관한다(서버는 내용을 해석하지 않는다).
    # 크기·중첩 깊이 상한은 서비스 레이어에서 검사한다(413 / 400).
    course: dict[str, Any]


class ShareCreateResponse(BaseModel):
    share_code: str
    created_at: str


class SharedCourseItem(BaseModel):
    """피드 목록 1건. payload 전체를 싣지 않는다(목록 응답이 수 MB 가 되는 것을 방지)."""

    share_code: str
    nickname: str
    title: str
    spot_count: int
    created_at: str
    view_count: int


class SharedCourseListResponse(BaseModel):
    items: list[SharedCourseItem] = Field(default_factory=list)
    total: int = 0


class SharedCourseDetail(SharedCourseItem):
    course: dict[str, Any] = Field(default_factory=dict)
    is_mine: bool = False


__all__ = (
    "COMMENT_MAX",
    "NICKNAME_MAX",
    "REASON_MAX",
    "ReviewCreateRequest",
    "ReviewCreateResponse",
    "ReviewItem",
    "ReviewListResponse",
    "ReviewReportRequest",
    "ReviewSummary",
    "ReviewSummaryMapResponse",
    "ReviewUpdateRequest",
    "ShareCreateRequest",
    "ShareCreateResponse",
    "SharedCourseDetail",
    "SharedCourseItem",
    "SharedCourseListResponse",
    "TITLE_MAX",
    "TargetType",
)
