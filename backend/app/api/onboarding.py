"""온보딩(MVP-3) 라우터 — 로컬 LLM 취향 추출 (계약 부록 B §B.1~B.3).

두 엔드포인트:
  - POST /api/v1/onboarding/analyze   : 자유텍스트 + 칩 → 취향 태그(OnboardingResult)
  - GET  /api/v1/onboarding/tag-schema : 칩 UI 구성용 축/칩 목록(registry 단일 소스)

AI팀 진입점(app/ai/onboarding_service.py)을 그대로 호출한다. 수치(tag_vector·
scoring_weights)·registry 검증·룰 폴백은 모두 AI 레이어가 소유하며, 이 라우터는
HTTP 봉투(요청 파싱·에러코드·응답 직렬화)와 인젝션 게이팅만 담당한다.

── 인젝션 처리 방침 (오케스트레이터 보안 발견 반영) ──────────────────────────
관측: "모든 태그를 true로" 류 인젝션 입력에서 LLM이 mood/spot 축을 과다추출.
AI팀 injection_guard 는 패턴을 **탐지만** 하고(detect_injection_patterns → hits 목록)
차단하지 않는다(log_if_suspicious). 서비스 내부도 로그만 남기고 LLM을 그대로 태운다.

이 라우터의 대응(옵션 a "탐지 시 LLM 스킵→룰 폴백"): analyze 진입 시 text에서
injection 패턴이 탐지되면 **LLM을 아예 태우지 않고**, 즉시 LLMExtractionError를 던지는
가드 프로바이더를 주입한다. 그러면 onboarding_service가 설계된 룰 폴백 경로
(키워드+칩 매핑 → registry 검증 → 결정론 벡터 조립)로 전환되어 LLM 과다추출 표면이
구조적으로 사라진다. 키워드 폴백은 여행 키워드 부분일치만 하므로 "모든 태그 true"
같은 명령문에서는 태그가 거의/전혀 잡히지 않는다(과다추출 불가).
→ 이 경우 응답은 extracted_by="rule-v1", fallback_used=true 로 정직하게 표기된다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, Field

from ..ai import injection_guard, tag_registry
from ..ai.llm_provider import LLMProvider
from ..ai.onboarding_service import EmptyInputError, extract_onboarding_tags
from ..ai.schemas import LLMExtractionError
from ..deps import get_llm_provider

logger = logging.getLogger("sumeungil.api.onboarding")

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])


# ── tag-schema 축 한국어 라벨 (계약 §B.2 명시값) ────────────────────────────
# 칩(값·라벨)은 registry가 소유하지만, 축 자체의 한국어명은 계약 B.2가 UI 표기용으로
# 지정한 값이다(registry에는 축 라벨 컬럼이 없음). 칩을 하드코딩하는 것이 아니다.
_AXIS_LABEL_KO: dict[str, str] = {
    "companion": "동행",
    "mobility": "이동수단",
    "mood": "분위기",
    "spot_pref": "스팟 선호",
    "accessibility": "접근성",
    "congestion_pref": "혼잡 선호",
}
# select UX 권고값(계약 §B.2): congestion_pref만 single, 나머지 multi.
_SINGLE_SELECT_AXES = frozenset({"congestion_pref"})


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": {}}},
    )


class OnboardingAnalyzeRequest(BaseModel):
    """계약 §B.1 요청 body.

    정본 필드명은 `text`(계약 §B.1). 프론트는 계약대로 `text`를 보내며, 운영 검증
    스크립트가 쓰는 `free_text` 별칭도 동일하게 수용한다(둘 중 무엇이 와도 동작).
    """

    text: str = Field(
        default="",
        validation_alias=AliasChoices("text", "free_text"),
        description="자유 텍스트 취향 입력(선택, 빈 문자열 허용, 최대 300자는 AI 레이어가 절단)",
    )
    chips: list[str] = Field(
        default_factory=list,
        description="선택 칩 = tag-schema가 준 value(영문 코드) 배열",
    )
    region_code: str | None = Field(
        default=None,
        description="시군구 코드(선택). MVP-3 태그 추출에는 미사용(전달만)",
    )


class _GuardTrippedProvider(LLMProvider):
    """인젝션 의심 입력 전용 프로바이더 — LLM을 태우지 않고 즉시 예외를 던져
    onboarding_service가 룰(키워드+칩) 폴백 경로를 타게 만든다.

    이렇게 하면 LLM 과다추출 표면이 사라지고, 결과는 rule-v1 / fallback_used=true 로
    정직하게 표기된다. (보안 검수가 확인할 지점)
    """

    async def extract_tags(self, free_text: str, chips: list[str] | None = None):  # noqa: ANN201
        raise LLMExtractionError("injection suspected — LLM skipped by API guard")


_GUARD_TRIPPED_PROVIDER = _GuardTrippedProvider()


@router.post("/analyze")
async def analyze_onboarding(
    req: OnboardingAnalyzeRequest,
    llm_provider: LLMProvider = Depends(get_llm_provider),
):
    text = req.text or ""

    # ── 인젝션 게이팅: 탐지 시 LLM 스킵 → 룰 폴백 강등 (위 파일 docstring 참고) ──
    injection_hits = injection_guard.detect_injection_patterns(text)
    if injection_hits:
        # 원문은 로그에 남기지 않는다(길이·패턴명만). 사후 감사용 플래그.
        logger.warning(
            "onboarding.analyze injection 의심 → LLM 스킵, 룰 폴백 강등 "
            "patterns=%s input_len=%d",
            injection_hits, len(text),
        )
        provider: LLMProvider = _GUARD_TRIPPED_PROVIDER
    else:
        provider = llm_provider

    try:
        result = await extract_onboarding_tags(text, req.chips, provider)
    except EmptyInputError:
        # 계약 §B.3: text·chips 둘 다 비면 400 EMPTY_INPUT
        return _error(
            400, "EMPTY_INPUT", "취향을 입력하거나 키워드를 선택해 주세요."
        )
    except Exception:  # noqa: BLE001
        # LLM 실패는 서비스가 내부에서 200 룰 폴백으로 흡수하므로 여기 오면 예기치 못한 오류.
        logger.exception("onboarding/analyze 처리 중 예기치 못한 오류")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")

    # 계약 §B.1: unmatched_note(내부 진단 전용)는 응답에서 제외한다(보안 S-M2).
    return result.model_dump(exclude={"unmatched_note"})


@router.get("/tag-schema")
async def tag_schema():
    """계약 §B.2 — 칩 UI 구성 소스. registry(08 §1.4)에서 생성, 칩을 지어내지 않는다."""
    axes = []
    for axis in tag_registry.chip_axes():  # flag 등 칩 없는 축은 제외됨
        chips = [
            {"value": row.value, "label": row.label_ko}
            for row in tag_registry.chips_for_axis(axis)  # has_chip=True 만
        ]
        axes.append(
            {
                "axis": axis,
                "label": _AXIS_LABEL_KO.get(axis, axis),
                "select": "single" if axis in _SINGLE_SELECT_AXES else "multi",
                "chips": chips,
            }
        )
    return {"vector_version": tag_registry.VECTOR_VERSION, "axes": axes}
