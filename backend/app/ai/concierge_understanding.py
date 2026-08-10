"""컨시어지 전용 통합 이해 (부록 N.10, 2026-07-30) — `POST /api/v1/concierge/ask`의
① 조건 해석을 LLM-first로 대체한다. **기존 `extract_onboarding_tags`(부록 B)·`prompts.py`는
한 글자도 건드리지 않는다** — 이 모듈은 그 옆에 추가되는 새 진입점이다.

배경(대표 지시, 2026-07-30): 사전 밖 표현("불꽃놀이 보러 갈 데")·사전 밖 지역명이 섞인
질문에서 기존 키워드 규칙(`is_festival_question`/`detect_region`)이 손을 놓고 엉뚱한 기본
지역(예: 부산)으로 떨어졌다("천안 물었는데 부산 추천"류 오답, 대표 실사용 보고). 태그·의도
(intent)·지역 힌트(region_text)·요청방식(wants_multiple/wants_alternative)을 **LLM 호출
1회**로 함께 받아 사전 밖 표현을 구제하되, 서버가 반드시 지어냄을 재검증한다
(`concierge_service`가 `region_text`를 `detect_region()`으로 재검증 — 이 모듈은 힌트만 준다).

LLM 호출 수는 늘지 않는다 — 기존 ①(`extract_onboarding_tags`의 LLM 호출)을 **대체**할 뿐,
④(답변 생성) 호출은 그대로 별도 1회다. 실패(인젝션 의심·타임아웃·파싱 실패·registry 포화
강등)는 전부 **온보딩과 동일한 키워드 룰 폴백**(`tags_from_keywords`)으로 떨어지고,
intent/region_text/wants_*는 중립값(호출부가 자신의 기존 정규식 규칙으로 그대로 최종
판단하도록 비워 둠)으로 반환한다 — 그래서 이 모듈이 실패해도 N.9(1차) 동작으로 완전히
회귀한다(무회귀 보장).

재사용(승계): `onboarding_service`의 registry 재검증·AXIS_CAP 캡·전축 포화 강등·룰 폴백
헬퍼(모두 `_` 접두 사설 함수)를 그대로 가져다 쓴다. 모듈 간 사설 헬퍼 재사용은 이
코드베이스의 기존 관례다(`course_service.py`가 `recommend_service._Scored`/`_score_spot`
등을 그대로 재사용하는 것과 동일 패턴) — `onboarding_service.py` 자체는 수정하지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from . import onboarding_service
from .assembler import build_tags_dict
from .llm_provider import LLMProvider
from .schemas import LLMExtractionError, OnboardingResult, RawConciergeExtraction

logger = logging.getLogger("sumeungil.ai.concierge_understanding")


@dataclass
class ConciergeUnderstanding:
    """`extract_concierge_understanding()` 반환값.

    `result`는 기존 `OnboardingResult` 그대로라 `build_answer_data` 등 기존 소비 코드가
    한 글자도 안 바뀐다(additive). 나머지 4개 필드가 N.10 신규 힌트다 — **전부 서버가
    자신의 기존 규칙과 OR/재검증으로 최종 판단**하며, 이 값을 그대로 신뢰하지 않는다.
    """

    result: OnboardingResult
    intent: str              # "spots" | "festivals" — LLM 힌트. 호출부가 자신의 규칙과 OR 결합.
    region_text: str | None  # LLM이 옮겨적은 지역 표현 원문. 호출부가 detect_region()으로 재검증.
    wants_multiple: bool
    wants_alternative: bool
    fallback_used: bool


def _neutral_fallback(text_value: str, unmatched_note: str | None = None) -> ConciergeUnderstanding:
    """LLM 미사용/실패 시 반환값. 태그는 기존 온보딩 키워드 룰 폴백과 완전히 동일한 경로
    (`onboarding_service._fallback_result`)를 재사용하고, 나머지(intent/region_text/wants_*)는
    중립값으로 비워 호출부(`concierge_service`)의 기존 정규식 규칙이 그대로 최종 판단하게
    한다 — 결과적으로 N.9(1차) 동작과 100% 동일해진다(무회귀).
    """
    result = onboarding_service._fallback_result(  # noqa: SLF001 — 모듈 간 사설 헬퍼 재사용(기존 관례)
        text_value, {}, unmatched_note=unmatched_note or onboarding_service.FALLBACK_UNMATCHED_NOTE
    )
    return ConciergeUnderstanding(
        result=result,
        intent="spots",
        region_text=None,
        wants_multiple=False,
        wants_alternative=False,
        fallback_used=True,
    )


# 2026-08-01(실측) — 같은 질문이라도 지역어가 붙으면 LLM 이 동행자를 뒤집는 변동이 있다:
#   "실내 데이트 추천해줘"        → companion=couple  (정답)
#   "충청도 실내 데이트 추천해줘"  → companion=solo    (오답)
# "데이트"는 동행자를 명시하는 단어라 solo 와 **정면으로 모순**된다. 규칙 표
# (rule_fallback.py: "데이트" → couple)는 LLM **실패 시에만** 쓰여 이 경우를 못 잡았다.
#
# 범위를 좁게 잡는다 — LLM 을 통째로 덮어쓰지 않고 **명백한 모순(solo)** 일 때만 교정한다.
# "가족 데이트"처럼 다른 동행자가 잡힌 경우는 건드리지 않는다(그쪽이 더 구체적인 정보다).
_CONTRADICTS_SOLO: tuple[str, ...] = ("데이트", "연인", "커플")


def _fix_contradicted_companion(text: str, additions: dict[str, set[str]]) -> None:
    """질문이 동행자를 명시하는데 LLM 이 solo 를 낸 경우만 제자리 교정한다."""
    if not any(k in text for k in _CONTRADICTS_SOLO):
        return
    companion = additions.get("companion")
    if not companion or "solo" not in companion:
        return
    companion.discard("solo")
    if not companion:
        companion.add("couple")
    logger.info("동행자 모순 교정: '데이트/연인/커플' 언급 + solo → %s", sorted(companion))


async def extract_concierge_understanding(
    question: str,
    provider: LLMProvider,
) -> ConciergeUnderstanding:
    """부록 N.10 진입점.

    `provider`는 라우터/서비스가 주입한 것을 그대로 받는다 — 인젝션 의심 시 호출부
    (`concierge_service.build_concierge_answer`)가 이미 가드용 Provider로 바꿔치기한 것을
    받으므로, 이 함수는 인젝션 판단을 직접 하지 않는다(기존 게이팅 패턴과 동일한 위치에서
    한 번만 판단 — 이중 판단으로 인한 불일치를 피한다).
    """
    text_value = (question or "").strip()
    if not text_value:
        # 방어적 안전망 — 호출부(API 레이어)가 이미 빈 질문을 걸러낸다(pragma: no cover에 준함).
        return _neutral_fallback(text_value)

    try:
        raw: RawConciergeExtraction = await provider.extract_concierge_understanding(text_value)
    except LLMExtractionError as exc:
        logger.info("concierge 통합 이해 LLM 미사용/실패 — 룰 폴백: %s", exc)
        return _neutral_fallback(text_value)

    # --- registry 재검증 + AXIS_CAP + 전축 포화 강등 (onboarding_service 로직 그대로 승계) ---
    llm_additions = onboarding_service._sanitize_llm_additions(raw)  # noqa: SLF001
    saturated = onboarding_service._saturated_axis_count(llm_additions)  # noqa: SLF001
    if saturated >= onboarding_service.SATURATION_MIN_AXES:
        logger.warning(
            "concierge-understanding-saturation-suspected saturated_axes=%d/%d text_len=%d — 룰 폴백",
            saturated, len(onboarding_service.AXIS_CAP), len(text_value),
        )
        return _neutral_fallback(text_value, unmatched_note=onboarding_service.SATURATION_UNMATCHED_NOTE)

    _fix_contradicted_companion(text_value, llm_additions)

    confidence_of = onboarding_service._confidence_from_value_confidence(raw)  # noqa: SLF001
    llm_additions = onboarding_service._cap_additions(  # noqa: SLF001
        llm_additions, confidence_of, raw.extraction_confidence
    )
    tags = build_tags_dict(llm_additions, confidence_of, default_confidence=raw.extraction_confidence)
    result = onboarding_service._finalize(  # noqa: SLF001
        tags,
        extraction_confidence=raw.extraction_confidence,
        unmatched_note=raw.unmatched_note,
        extracted_by="llm-v1",
        fallback_used=False,
    )

    return ConciergeUnderstanding(
        result=result,
        # RawConciergeExtraction 필드 검증기(schemas.py)가 이미 enum/타입을 강제하지만,
        # "한 레이어만 믿지 않는다" 원칙에 따라 서비스 경계에서 한 번 더 확인한다.
        intent=raw.intent if raw.intent in ("spots", "festivals") else "spots",
        region_text=raw.region_text,
        wants_multiple=bool(raw.wants_multiple),
        wants_alternative=bool(raw.wants_alternative),
        fallback_used=False,
    )
