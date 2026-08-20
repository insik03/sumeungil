"""개인화 여행 팁 스키마 — 계약 부록 Z.

**자유 텍스트 필드를 추가하지 말 것.** 요청에 사용자 문자열이 하나도 없다는 사실이
이 엔드포인트의 프롬프트 인젝션 표면을 0으로 만드는 근거다(부록 Z.0-1). 필드를 하나라도
늘리는 순간 그 전제가 깨지고, 온보딩과 같은 injection_guard·길이 상한 방어가 필요해진다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 정적 5건과 동일한 축(부록 Z.2). LLM 이 이 밖의 값을 내면 서버가 그 팁을 **버린다**.
TipCategory = Literal["혼잡", "교통", "날씨", "반려동물", "안전"]

TITLE_MAX = 40
BODY_MAX = 200

# `notice` 는 서버 상수다 — LLM 이 만들지 않는다(부록 Z.6-3).
AI_NOTICE = "AI가 만든 참고용 안내예요. 방문 전 공식 정보를 확인해 주세요."


class TipsRequest(BaseModel):
    # 2026-08-20 보안검수 L-4 — 모듈 docstring 의 "자유 텍스트 필드를 추가하지 말 것"을
    # 스키마가 **강제**한다. 기본값(extra="ignore")이면 클라이언트가 보낸 잉여 필드가
    # 조용히 버려져서, 프론트가 실수로 자유 텍스트를 붙여도 아무도 눈치채지 못한 채
    # "인젝션 표면 0" 전제가 조용히 흔들린다. forbid 면 그 순간 422 로 드러난다.
    model_config = ConfigDict(extra="forbid")

    # 등록되지 않은 코드는 **무시**한다(오류가 아니다 — 지역 피처만 빠진다).
    # 형식(길이·문자 종류)만 스키마에서 막는다 → 형식 위반은 422.
    region_code: str | None = Field(default=None, pattern=r"^[0-9A-Za-z_-]{1,10}$")


class TipItem(BaseModel):
    id: str
    category: TipCategory
    title: str
    body: str
    source: Literal["ai", "static"]


class TipsResponse(BaseModel):
    """`tips` 는 **항상 3~5건**이다(0건이 되는 경우가 없다 — 부족하면 정적 폴백)."""

    tips: list[TipItem] = Field(default_factory=list)
    generated_by: Literal["ai-v1", "static-v2"]
    notice: str | None = None


__all__ = (
    "AI_NOTICE",
    "BODY_MAX",
    "TITLE_MAX",
    "TipCategory",
    "TipItem",
    "TipsRequest",
    "TipsResponse",
)
