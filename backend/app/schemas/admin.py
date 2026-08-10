"""관리자(운영) 콘솔 요청/응답 모델 = 01-interface-contract.md 부록 T 코드화.

## 이 스키마에 **없는** 것 (의도적)
- `device_id`: 부록 R.0 불변식(응답 비노출)은 관리자에게도 그대로 적용된다. 대신 서버가
  키 붙은 HMAC 으로 만든 8자 `author_hash` 만 내려준다 — 같은 사람이 쓴 글을 묶어 볼 수는
  있지만 원본 식별자는 복원할 수 없다.
- 관리자 계정/이메일/역할: 운영자는 1명이고 계정 테이블이 없다(부록 T.1).
- 세션 토큰: 토큰은 **HttpOnly 쿠키로만** 오간다. 응답 바디에 절대 싣지 않는다
  (바디에 실으면 JS 가 읽을 수 있게 되어 HttpOnly 의 의미가 사라진다).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..security.admin_auth import PASSWORD_MAX_LEN

ReviewStatusFilter = Literal["reported", "hidden", "all"]
ReviewSortOption = Literal["reported", "recent"]
CourseStatusFilter = Literal["all", "hidden"]


class AdminLoginRequest(BaseModel):
    """`min_length` 를 두지 않은 이유: 빈 비밀번호가 422 로 떨어지면 "형식은 맞았다"는
    정보를 주게 된다. 길이와 무관하게 **모든 실패가 동일한 401** 로 수렴해야 한다.
    상한만 두어 무제한 바디가 KDF 로 들어가는 것을 막는다."""

    password: str = Field(default="", max_length=PASSWORD_MAX_LEN)

    # 관리자 표시 이름(부록 V). 서버가 ADMIN_OPERATORS 목록과 대조해 확인한 뒤
    # **세션 토큰 안에 서명해 넣는다** — 이후 요청은 이 값을 다시 받지 않는다.
    # 상한만 두는 이유는 password 와 같다(무제한 바디 차단).
    operator: str = Field(default="", max_length=32)


class AdminOperatorsResponse(BaseModel):
    """로그인 화면 드롭다운용 표시 이름 목록.

    인증 없이 조회된다 — /admin 로그인 화면이 이름을 그려야 하기 때문이다. 노출되는
    것은 성 없는 표시 이름뿐이고, 이 값을 안다고 로그인에 가까워지지 않는다(비밀번호가
    유일한 관문). 그래도 노출이 싫으면 .env 의 ADMIN_OPERATORS 를 라벨(A/B/C)로 바꾸면 된다.
    관리자 기능 자체가 꺼져 있으면(ADMIN_PASSWORD_HASH 미설정) 라우터가 등록되지 않아 404 다.
    """

    operators: list[str] = Field(default_factory=list)

class AdminSessionResponse(BaseModel):
    authenticated: bool = True
    # ISO8601 + KST. 프론트가 "n분 후 만료" 를 표시하거나 자동 로그아웃 타이머를 걸 수 있게.
    expires_at: str


class AdminOkResponse(BaseModel):
    ok: bool = True


class AdminReviewItem(BaseModel):
    id: int
    target_type: str
    target_id: str
    nickname: str
    rating: int
    comment: str | None = None
    created_at: str
    updated_at: str
    hidden: bool = False
    report_count: int = 0
    # device_id 원본이 아니라 8자 HMAC 지문(역산 불가). 도배 계정 판별용.
    author_hash: str = ""


class AdminReviewListResponse(BaseModel):
    items: list[AdminReviewItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 0
    offset: int = 0


class AdminCourseItem(BaseModel):
    share_code: str
    nickname: str
    title: str
    spot_count: int = 0
    created_at: str
    view_count: int = 0
    hidden: bool = False
    author_hash: str = ""


class AdminCourseListResponse(BaseModel):
    items: list[AdminCourseItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 0
    offset: int = 0


class AdminStatsResponse(BaseModel):
    reviews_total: int = 0
    reviews_hidden: int = 0
    reviews_today: int = 0
    reports_pending: int = 0
    reports_total: int = 0
    courses_total: int = 0
    courses_hidden: int = 0
    # 신고가 몇 건 쌓이면 자동 숨김되는지(REVIEW_HIDE_REPORT_THRESHOLD, 기본 3).
    # 관리자 화면이 "자동 숨김"과 "운영자가 숨김"을 구분하는 데 쓴다:
    #   hidden && report_count >= 이 값  →  자동 숨김 (임계 도달로만 hidden 이 되고,
    #                                      숨겨진 글에는 신고가 더 쌓이지 않는다)
    #   hidden && report_count <  이 값  →  운영자가 직접 숨김
    # **프론트에 숫자를 박지 않기 위해** 서버가 내려준다 — env 로 바뀌어도 화면이 따라온다.
    review_hide_report_threshold: int = 0
    generated_at: str


class AdminTrafficDay(BaseModel):
    day: str
    visitors: int = 0
    hits: int = 0


class AdminTrafficPath(BaseModel):
    path: str
    hits: int = 0


class AdminTrafficHour(BaseModel):
    hour: int
    hits: int = 0


class AdminHeavyClient(BaseModel):
    """오늘 가장 많이 요청한 클라이언트. **신원은 알 수 없다** — 원본 IP 를 저장하지
    않기 때문이다(대표 결정 2026-08-10). `ip_hash` 는 키 붙은 HMAC 앞 16자이고,
    이 목록의 유일한 목적은 "한 명이 비정상적으로 많이 두드리는가"를 보는 것이다."""

    ip_hash: str
    hits: int = 0
    first_seen: str
    last_seen: str


class AdminTrafficResponse(BaseModel):
    """운영 트래픽 집계(부록 X).

    `today_visitors` 는 고유 `ip_hash` 수다. 이동통신 IP 는 바뀌고 사무실·학교는 공유되므로
    **정확한 사람 수가 아니라 추정치**다 — 화면에도 그렇게 표기해야 한다.
    """

    today_visitors: int = 0
    today_hits: int = 0
    today_top_hits: int = 0
    daily: list[AdminTrafficDay] = Field(default_factory=list)
    top_paths: list[AdminTrafficPath] = Field(default_factory=list)
    hourly: list[AdminTrafficHour] = Field(default_factory=list)
    heavy_clients: list[AdminHeavyClient] = Field(default_factory=list)
    retention_days: int = 0
    generated_at: str

class AdminModerationResponse(BaseModel):
    """hide / unhide / delete 공통 응답. 프론트가 목록을 낙관적으로 갱신할 수 있게
    변경 후 상태를 그대로 돌려준다."""

    ok: bool = True
    action: str
    target_type: str
    target_id: str
    hidden: bool | None = None
    deleted: bool = False


__all__ = (
    "AdminCourseItem",
    "AdminCourseListResponse",
    "AdminLoginRequest",
    "AdminModerationResponse",
    "AdminOkResponse",
    "AdminReviewItem",
    "AdminReviewListResponse",
    "AdminSessionResponse",
    "AdminStatsResponse",
    "CourseStatusFilter",
    "ReviewSortOption",
    "ReviewStatusFilter",
)
