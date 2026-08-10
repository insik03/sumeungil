"""AI 여행 문답(컨시어지) 요청/응답 모델 = 01-interface-contract.md 부록 N 코드화.

`POST /api/v1/concierge/ask` 전용. 신규 외부 API 0 — 기존 온보딩 추출·지역 seed·
추천 파이프라인·로컬 LLM 을 그대로 재사용한다(부록 B/C/F).

정직 원칙:
  - `extracted` 는 서버가 질문을 **어떻게 이해했는지**를 그대로 노출한다(프론트가
    "이렇게 이해했어요" 로 보여줌). 지어낸 값이 아니라 registry enum 재검증을 통과한 값만 담긴다.
  - `answer` 는 절대 null 이 아니다(문답 기능). LLM 실패 시 enum 라벨 기반 템플릿으로 채우고
    `meta.answer_source="template"` 로 정직하게 표기한다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..ai.schemas import TagValue
from .places import Festival, SpotCard

# 질문 길이 계약(부록 N.1). 하한 2자는 "카페" 같은 최소 질의를 허용하되 빈 입력을 거절하고,
# 상한 200자는 LLM 비용 폭주·DoS 방어(온보딩 sanitize 상한 300자보다 짧게 잡는다).
QUESTION_MIN_CHARS = 2
QUESTION_MAX_CHARS = 200


class ConciergeAskRequest(BaseModel):
    """길이 위반은 FastAPI/pydantic 기본 422(부록 N.4). 그 외 값 검증은 서버가 수행."""

    question: str = Field(..., min_length=QUESTION_MIN_CHARS, max_length=QUESTION_MAX_CHARS)
    region_code: str | None = Field(default=None, max_length=20)


class ConciergeRegion(BaseModel):
    region_code: str
    region_name: str | None = None


class ConciergeExtracted(BaseModel):
    """해석 결과(정직 노출). tags 는 OnboardingResult.tags 와 **동일 형태**(축→TagValue 배열)."""

    tags: dict[str, list[TagValue]] = Field(default_factory=dict)
    region: ConciergeRegion | None = None


class ConciergeMeta(BaseModel):
    notice: str | None = None
    # additive(정직 표기): 답변을 로컬 LLM 이 썼는지, 템플릿 폴백인지. 프론트 렌더에는 영향 없음.
    answer_source: Literal["llm", "template"] = "template"
    # additive(2026-07-30): 이 질문을 어떤 의도로 처리했는지. "festivals" 면 spots 는 항상 비어 있고
    # festivals 에 결과가 담긴다. 기본값 "spots" 라 기존 클라이언트 동작은 그대로다.
    intent: Literal["spots", "festivals"] = "spots"


class ConciergeAskResponse(BaseModel):
    answer: str                      # 항상 비어있지 않다(템플릿 폴백 보장)
    extracted: ConciergeExtracted
    spots: list[SpotCard] = Field(default_factory=list)
    # additive(2026-07-30): 축제 질문("~축제 있어?")일 때만 채워진다. 스팟 모드에서는 항상 [].
    festivals: list[Festival] = Field(default_factory=list)
    meta: ConciergeMeta
