"""서버 룰 조립기 — `tags` → `tag_vector` / `scoring_weights`.

08-interface-contract.md D1 핵심 원칙: **LLM은 축별 태그 값만 반환하고,
tag_vector(36차원 이진)·scoring_weights(5축)는 서버 결정론 규칙이 조립한다.**
LLM이 수치를 주입할 경로가 없어야 한다(보안) — 이 파일이 그 경계선이다.
어떤 함수도 LLM 응답에서 직접 숫자를 읽어 tag_vector/scoring_weights에 넣지 않는다
(TagValue.confidence는 표시·진단 전용이며 여기 입력으로 쓰지 않는다 — 08 §1.6).
"""

from __future__ import annotations

from . import tag_registry
from .rule_fallback import TagAdditions
from .schemas import TagValue

# 02-ai-strategy.md §2.1 기본 가중치
_BASE_WEIGHTS: dict[str, float] = {
    "congestion": 0.30,
    "profile_fit": 0.25,
    "distance": 0.20,
    "local_exposure": 0.15,
    "trust": 0.10,
}

_LOCAL_SPOT_VALUES = {"local_cafe", "craft_shop", "traditional_market"}
_PROFILE_FIT_MOODS = {"healing", "contemplative"}


def resolve_congestion_pref(additions: TagAdditions) -> str:
    """congestion_pref는 항상 정확히 1개(08 §1.5). 우선순위: avoid_priority > indifferent > unspecified.

    (칩·LLM·키워드에서 서로 다른 값이 동시에 들어온 경우, 서비스 핵심가치인
    "혼잡 회피"를 우선한다 — 과탐지의 비용이 과소탐지보다 작다는 판단.)
    """
    values = additions.get("congestion_pref", set())
    if "avoid_priority" in values:
        return "avoid_priority"
    if "indifferent" in values:
        return "indifferent"
    return "unspecified"


def build_tags_dict(
    additions: TagAdditions,
    confidence_of: dict[tuple[str, str], float],
    default_confidence: float,
) -> dict[str, list[TagValue]]:
    """축별 태그 값 집합 → `OnboardingResult.tags` (registry 순서로 정렬, label은 registry에서 조회).

    `additions`에 들어있는 (axis,value)는 이미 registry 검증을 통과한 값이라고
    가정한다(호출부가 tag_registry.is_valid로 걸러야 함) — 이 함수는 재검증하지 않는다.
    """
    tags: dict[str, list[TagValue]] = {axis: [] for axis in tag_registry.AXES}

    for axis in tag_registry.AXES:
        values = additions.get(axis, set())
        if axis == "congestion_pref":
            resolved = resolve_congestion_pref(additions)
            label = tag_registry.label_for(axis, resolved) or resolved
            conf = confidence_of.get((axis, resolved), default_confidence)
            tags[axis] = [TagValue(value=resolved, label=label, confidence=conf)]
            continue

        # registry 인덱스 순서로 정렬해 결정론적 출력 순서를 보장
        ordered = sorted(values, key=lambda v: tag_registry.vector_index(axis, v) or 0)
        row_tags: list[TagValue] = []
        for v in ordered:
            if not tag_registry.is_valid(axis, v):
                continue  # 방어계층 5: registry 밖 값은 여기서도 다시 한 번 폐기
            label = tag_registry.label_for(axis, v) or v
            conf = confidence_of.get((axis, v), default_confidence)
            row_tags.append(TagValue(value=v, label=label, confidence=conf))
        tags[axis] = row_tags

    return tags


def assemble_tag_vector(tags: dict[str, list[TagValue]]) -> list[float]:
    """36차원 이진 벡터. 원소는 오직 0.0/1.0 — confidence를 가중치로 쓰지 않는다(D1 폐기안)."""
    vector = [0.0] * tag_registry.VECTOR_DIM
    for axis, values in tags.items():
        for tv in values:
            idx = tag_registry.vector_index(axis, tv.value)
            if idx is not None:
                vector[idx] = 1.0
    return vector


def assemble_scoring_weights(tags: dict[str, list[TagValue]]) -> dict[str, float]:
    """02-ai-strategy.md §2.2 가산표 + 정규화. LLM이 아니라 서버가 산출한다."""
    delta = {k: 0.0 for k in _BASE_WEIGHTS}

    congestion_values = {tv.value for tv in tags.get("congestion_pref", [])}
    if "avoid_priority" in congestion_values:
        delta["congestion"] += 0.10

    flag_values = {tv.value for tv in tags.get("flag", [])}
    if "child_present" in flag_values or "pet_present" in flag_values:
        delta["distance"] += 0.05

    spot_values = {tv.value for tv in tags.get("spot_pref", [])}
    if spot_values & _LOCAL_SPOT_VALUES:
        delta["local_exposure"] += 0.10

    mood_values = {tv.value for tv in tags.get("mood", [])}
    if mood_values & _PROFILE_FIT_MOODS:
        delta["profile_fit"] += 0.05

    # accessibility는 하드 필터 전용 — 가중치 조정하지 않음(§2.2 표 마지막 행)

    raw = {k: _BASE_WEIGHTS[k] + delta[k] for k in _BASE_WEIGHTS}
    total = sum(raw.values())
    if total <= 0:
        # 이론상 발생 불가(base 합=1.0, delta>=0)하지만 방어적으로 base 그대로 반환
        return dict(_BASE_WEIGHTS)
    return {k: v / total for k, v in raw.items()}
