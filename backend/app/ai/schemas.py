"""온보딩 취향 추출 데이터 모델.

정본:
  - RawLLMExtraction = 02-ai-strategy.md §1.3.1 "LLM 직접 출력 스키마"의 파이썬 표현.
    LLM(Ollama)이 반환해야 하는 형태. **여기서 값은 아직 신뢰하지 않는다** — 필드는
    존재해도 enum 밖 값이 섞여 들어올 수 있으므로(로컬 모델은 OpenAI strict schema급
    강제가 없다), 별도 sanitize 단계(assembler 이전)에서 registry로 재검증한다.
  - TagValue / OnboardingResult = 08-interface-contract.md §1.5 정본
    (`ai_contract.py` 교체본)을 그대로 코드화한 것. backend가 API 응답을 만들 때
    이 구조를 그대로 쓰거나 1:1 매핑하면 된다.

주의(§B.1): OnboardingResult.unmatched_note는 **내부 진단 전용**이다.
backend는 HTTP 응답을 만들 때 이 필드를 제외해야 한다(DB 저장·화면 노출 금지, 보안 S-M2).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from . import tag_registry

ExtractedBy = Literal["llm-v1", "rule-v1", "hybrid-v1"]


class RawLLMExtraction(BaseModel):
    """LLM(Ollama) 응답 JSON을 1차 파싱한 형태 (아직 registry 재검증 전, 신뢰하지 않음).

    필드가 누락되면 빈 배열/기본값으로 관대하게 채운다 — 로컬 소형모델이 스키마를
    완벽히 지키지 않는 경우가 있으므로, "필드 하나 어긋남 = 전체 폐기"는 과도하다.
    반면 **JSON 자체를 파싱할 수 없는 경우**(문법 오류)는 이 모델 생성 이전 단계에서
    예외로 처리되어 전체 룰 폴백(§B.3)으로 승격된다 — 그 경계가 방어의 핵심이다.
    """

    companion: list[str] = Field(default_factory=list)
    flag: list[str] = Field(default_factory=list)
    mobility: list[str] = Field(default_factory=list)
    mood: list[str] = Field(default_factory=list)
    spot_pref: list[str] = Field(default_factory=list)
    accessibility: list[str] = Field(default_factory=list)
    congestion_pref: list[str] = Field(default_factory=list)
    value_confidence: dict[str, float] = Field(default_factory=dict)
    extraction_confidence: float = 0.5
    unmatched_note: str | None = None

    @field_validator(
        "companion", "flag", "mobility", "mood", "spot_pref", "accessibility", "congestion_pref",
        mode="before",
    )
    @classmethod
    def _coerce_list_of_str(cls, v: object) -> list[str]:
        # 모델이 문자열 하나만 반환하거나 null을 반환해도 방어적으로 리스트화한다.
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return [str(x) for x in v if isinstance(x, (str, int, float))]
        return []

    @field_validator("extraction_confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, v: object) -> float:
        try:
            f = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.5
        return min(max(f, 0.0), 1.0)


class TagValue(BaseModel):
    value: str
    label: str
    confidence: float = Field(ge=0.0, le=1.0)


class OnboardingResult(BaseModel):
    tags: dict[str, list[TagValue]]
    tag_vector: list[float]
    vector_version: int = tag_registry.VECTOR_VERSION
    scoring_weights: dict[str, float]
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    unmatched_note: str | None = None  # 내부 진단 전용 — API 응답 직렬화 시 backend가 제외
    extracted_by: ExtractedBy
    fallback_used: bool = False


class LLMExtractionError(Exception):
    """Ollama 호출/파싱 실패 (타임아웃·5xx·연결 오류·JSON 디코드 실패 포함).

    onboarding_service가 이 예외를 잡아 §B.3 룰 폴백(200 응답, fallback_used=true)으로
    전환한다. 이 예외가 상위(API 레이어)까지 전파되면 안 된다 — 계약상 LLM 실패는
    사용자에게 에러로 보이지 않아야 한다.
    """
