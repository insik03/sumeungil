"""backend가 호출할 단일 진입점 — `POST /onboarding/analyze` 뒤에서 쓰인다.

    from app.ai.onboarding_service import extract_onboarding_tags, EmptyInputError
    from app.ai.llm_provider import create_provider_from_settings

    provider = create_provider_from_settings(settings)   # deps.py에서 싱글턴화 권장
    try:
        result = await extract_onboarding_tags(text, chips, provider)
    except EmptyInputError:
        raise HTTPException(400, ...)  # EMPTY_INPUT (01-interface-contract.md 부록B §B.3)
    return result  # OnboardingResult — 단 unmatched_note는 API 응답에서 제외할 것(§B.1)

경로 선택 규칙 (01-interface-contract.md 부록B §B.1~B.4, 02-ai-strategy.md §1.7):
  - text·chips 둘 다 없음        → EmptyInputError (호출부가 400 처리)
  - text 없음, chips만 있음      → 칩→태그 직접 매핑. extracted_by="rule-v1", fallback_used=False
                                    (이건 장애 폴백이 아니라 설계상 정상 경로 — LLM을 아예 부르지 않는다)
  - text 있음, LLM 성공          → LLM 태그 + 칩 태그 합집합.
                                    extracted_by = "hybrid-v1"(칩도 있었으면) | "llm-v1"
  - text 있음, LLM 실패/타임아웃/파싱실패 → 키워드 폴백 + 칩 태그 합집합.
                                    extracted_by="rule-v1", fallback_used=True (200 응답, 에러 아님)
"""

from __future__ import annotations

import logging

from . import injection_guard, tag_registry
from .assembler import assemble_scoring_weights, assemble_tag_vector, build_tags_dict
from .llm_provider import LLMProvider
from .rule_fallback import merge_additions, tags_from_chips, tags_from_keywords
from .schemas import LLMExtractionError, OnboardingResult, RawLLMExtraction

logger = logging.getLogger("sumeungil.ai.onboarding_service")

FALLBACK_UNMATCHED_NOTE = "LLM 미사용 — 키워드 기반 폴백 추출"
SATURATION_UNMATCHED_NOTE = "인젝션 의심(전축 동시 과다추출 패턴) — 룰 폴백으로 강등"
FALLBACK_EXTRACTION_CONFIDENCE = 0.3
FALLBACK_KEYWORD_CONFIDENCE = 0.3
CHIP_CONFIDENCE = 1.0

# --- 방어계층 7: 서버측 태그 수 상한 캡 (allowlist형, denylist 우회와 무관하게 작동) ---
# 02-qa-report.md M-3 / 03-security-report.md M-1 대응: injection_guard가 우회되어
# LLM까지 가더라도, "정상 사용자는 한 문장에서 한 축에 몇 개 정도만 고르지 축을
# 죄다 가득 채우지는 않는다"는 관찰을 판별 기준으로 삼아 과다추출을 여기서 무력화한다.
#
# congestion_pref는 대상에서 뺀다 — assembler.resolve_congestion_pref가 항상 정확히
# 1개로 결정론적으로 접기 때문에 캡이 필요 없다(08 §1.5). flag도 뺀다 — registry상
# 가능한 값이 2개뿐이라(child_present/pet_present) 캡을 걸어도 절대 초과할 수 없는
# 축이라 실질 방어 효과가 없고, 오탐만 만들 수 있다.
AXIS_CAP: dict[str, int] = {
    "companion": 3,       # registry 7종 중 최대 3 (예: 가족+아이+반려동물 동시 언급까지는 정상)
    "mobility": 2,        # registry 5종 중 최대 2 (예: "걷거나 자전거로")
    "mood": 3,            # registry 7종 중 최대 3
    "spot_pref": 4,       # registry 8종 중 최대 4
    "accessibility": 3,   # registry 4종 중 최대 3
}
# AXIS_CAP 대상 축 중 이 개수 이상이 "동시에" 상한(이상)에 도달하면 전체 추출을 의심해
# 룰 폴백으로 강등한다. 정상 사용자가 우연히 축 하나둘을 상한까지 채우는 것은 허용하되,
# 여러 축을 동시에 가득 채우는 것은 "모든 태그를 켜라"류 인젝션의 특징적 신호로 본다.
SATURATION_MIN_AXES = 3


class EmptyInputError(Exception):
    """text·chips 둘 다 비었을 때. 호출부(backend API 레이어)가 400 EMPTY_INPUT으로 매핑."""


def _sanitize_llm_additions(raw: RawLLMExtraction) -> dict[str, set[str]]:
    """방어계층 1+5: LLM이 반환한 값 중 registry에 없는 enum은 조용히 폐기한다."""
    additions: dict[str, set[str]] = {axis: set() for axis in tag_registry.AXES}
    raw_by_axis = {
        "companion": raw.companion,
        "flag": raw.flag,
        "mobility": raw.mobility,
        "mood": raw.mood,
        "spot_pref": raw.spot_pref,
        "accessibility": raw.accessibility,
        "congestion_pref": raw.congestion_pref,
    }
    for axis, values in raw_by_axis.items():
        for v in values:
            if tag_registry.is_valid(axis, v):
                additions[axis].add(v)
            else:
                logger.info("registry 밖 LLM 값 폐기: axis=%s value=%r", axis, v)
    return additions


def _saturated_axis_count(additions: dict[str, set[str]]) -> int:
    """AXIS_CAP 대상 축 중 개수가 상한 이상(=포화)인 축이 몇 개인지 센다."""
    return sum(1 for axis, cap in AXIS_CAP.items() if len(additions.get(axis, ())) >= cap)


def _cap_additions(
    additions: dict[str, set[str]],
    confidence_of: dict[tuple[str, str], float],
    default_confidence: float,
) -> dict[str, set[str]]:
    """축당 상한을 "초과"하는 분만 신뢰도 낮은 순으로 잘라낸다.

    상한에 "딱 맞는" 정상 다중선택(예: companion 3개)은 건드리지 않는다 — 자르는
    것은 상한을 넘어선 초과분뿐이다. value_confidence가 없는 값은 default_confidence로
    동률 취급되며, 동률일 때는 registry 순서(vector_index)로 결정론적으로 자른다.
    """
    capped: dict[str, set[str]] = {axis: set(values) for axis, values in additions.items()}
    for axis, cap in AXIS_CAP.items():
        values = capped.get(axis, set())
        if len(values) <= cap:
            continue
        ranked = sorted(
            values,
            key=lambda v: (
                -confidence_of.get((axis, v), default_confidence),
                tag_registry.vector_index(axis, v) or 0,
            ),
        )
        kept, dropped = ranked[:cap], ranked[cap:]
        logger.warning(
            "axis-cap-exceeded axis=%s cap=%d kept=%d dropped=%d dropped_values=%s",
            axis, cap, len(kept), len(dropped), dropped,
        )
        capped[axis] = set(kept)
    return capped


def _confidence_from_value_confidence(
    raw: RawLLMExtraction,
) -> dict[tuple[str, str], float]:
    confidence_of: dict[tuple[str, str], float] = {}
    for key, conf in raw.value_confidence.items():
        axis, sep, value = key.partition(":")
        if not sep:
            continue
        if tag_registry.is_valid(axis, value):
            try:
                confidence_of[(axis, value)] = min(max(float(conf), 0.0), 1.0)
            except (TypeError, ValueError):
                continue
    return confidence_of


async def extract_onboarding_tags(
    text: str | None,
    chips: list[str] | None,
    provider: LLMProvider,
) -> OnboardingResult:
    text_value = (text or "").strip()
    chips_list = list(chips or [])

    if not text_value and not chips_list:
        raise EmptyInputError("text and chips are both empty")

    chip_additions = tags_from_chips(chips_list)

    # --- 경로 A: 칩만 있음 → LLM 호출 안 함 (§1.7 "칩만 선택한 입력은 애초에 LLM을 호출하지 않는다") ---
    if not text_value:
        confidence_of = {
            (axis, v): CHIP_CONFIDENCE for axis, values in chip_additions.items() for v in values
        }
        tags = build_tags_dict(chip_additions, confidence_of, default_confidence=CHIP_CONFIDENCE)
        return _finalize(
            tags,
            extraction_confidence=CHIP_CONFIDENCE,
            unmatched_note=None,
            extracted_by="rule-v1",
            fallback_used=False,
        )

    # 방어계층 6: 인젝션 의심 패턴은 로그만 남기고 차단하지 않는다
    injection_guard.log_if_suspicious(text_value)

    # --- 경로 B: 자유 텍스트 있음 → LLM 시도 ---
    try:
        raw = await provider.extract_tags(text_value, chips_list)
    except LLMExtractionError as exc:
        logger.warning("LLM 추출 실패 — 룰 폴백으로 전환: %s", exc)
        return _fallback_result(text_value, chip_additions)

    llm_additions = _sanitize_llm_additions(raw)

    # 방어계층 7(핵심): injection_guard(계층 6)를 우회해 LLM까지 도달했더라도,
    # 여러 축이 동시에 상한까지 차 있으면(="모든 태그 켜라"류 과다추출 패턴) 이
    # LLM 응답 자체를 신뢰하지 않고 룰 폴백으로 강등한다(칩 선택분은 그대로 반영).
    saturated = _saturated_axis_count(llm_additions)
    if saturated >= SATURATION_MIN_AXES:
        logger.warning(
            "extraction-saturation-suspected saturated_axes=%d/%d text_len=%d — 룰 폴백으로 강등",
            saturated, len(AXIS_CAP), len(text_value),
        )
        return _fallback_result(text_value, chip_additions, unmatched_note=SATURATION_UNMATCHED_NOTE)

    confidence_of = _confidence_from_value_confidence(raw)
    llm_additions = _cap_additions(llm_additions, confidence_of, raw.extraction_confidence)
    merged = merge_additions(llm_additions, chip_additions)

    for axis, values in chip_additions.items():
        for v in values:
            confidence_of[(axis, v)] = CHIP_CONFIDENCE  # 칩 직접 선택이 LLM 추론보다 항상 우선

    tags = build_tags_dict(merged, confidence_of, default_confidence=raw.extraction_confidence)
    extracted_by = "hybrid-v1" if chips_list else "llm-v1"

    return _finalize(
        tags,
        extraction_confidence=raw.extraction_confidence,
        unmatched_note=raw.unmatched_note,
        extracted_by=extracted_by,
        fallback_used=False,
    )


def _fallback_result(
    text_value: str,
    chip_additions: dict[str, set[str]],
    *,
    unmatched_note: str = FALLBACK_UNMATCHED_NOTE,
) -> OnboardingResult:
    keyword_additions = tags_from_keywords(text_value)
    merged = merge_additions(keyword_additions, chip_additions)

    confidence_of: dict[tuple[str, str], float] = {
        (axis, v): FALLBACK_KEYWORD_CONFIDENCE
        for axis, values in keyword_additions.items()
        for v in values
    }
    for axis, values in chip_additions.items():
        for v in values:
            confidence_of[(axis, v)] = CHIP_CONFIDENCE  # 칩은 폴백 중에도 항상 confidence=1.0

    tags = build_tags_dict(merged, confidence_of, default_confidence=FALLBACK_KEYWORD_CONFIDENCE)
    return _finalize(
        tags,
        extraction_confidence=FALLBACK_EXTRACTION_CONFIDENCE,
        unmatched_note=unmatched_note,
        extracted_by="rule-v1",
        fallback_used=True,
    )


def _finalize(
    tags,
    *,
    extraction_confidence: float,
    unmatched_note: str | None,
    extracted_by: str,
    fallback_used: bool,
) -> OnboardingResult:
    tag_vector = assemble_tag_vector(tags)
    scoring_weights = assemble_scoring_weights(tags)
    return OnboardingResult(
        tags=tags,
        tag_vector=tag_vector,
        vector_version=tag_registry.VECTOR_VERSION,
        scoring_weights=scoring_weights,
        extraction_confidence=extraction_confidence,
        unmatched_note=unmatched_note,
        extracted_by=extracted_by,  # type: ignore[arg-type]
        fallback_used=fallback_used,
    )
