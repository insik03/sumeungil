"""칩→태그 룰 매핑(08 A6) + 키워드 폴백(02-ai-strategy.md §1.7).

두 가지 별도 용도로 쓰인다:
  1. `tags_from_chips()` — 사용자가 고른 칩(registry value)을 태그로 직접 변환.
     LLM 성공 여부와 무관하게 **항상** 적용된다(칩은 LLM을 타지 않는다, §1.7).
  2. `tags_from_keywords()` — Ollama 장애/타임아웃/파싱 실패 시에만 쓰는
     자유 텍스트 경량 키워드 매칭. "정교한 NLP가 아니라 화면이 멈추지 않게 하는
     최소 안전망"(§1.7) — 확장하지 않는다.

confidence 규칙(§1.7): 칩 직접 선택분 = 1.0, 키워드 매칭 유추분 = 0.3.
"""

from __future__ import annotations

from . import tag_registry

TagAdditions = dict[str, set[str]]


def _empty_additions() -> TagAdditions:
    return {axis: set() for axis in tag_registry.AXES}


# --- 1) 칩 → 태그 (registry value 기준, 08 A6 / 02 §1.7-1) -----------------

# 칩 자신의 값(예: "with_child")이 속한 축을 역조회. tag-schema에 실제 노출되는
# 칩(has_chip=True)만 대상 — flag/unspecified는 칩이 아니므로 chips 입력으로
# 직접 올 수 없다(들어와도 아래서 무시됨).
VALUE_TO_AXIS: dict[str, str] = {
    r.value: r.axis for r in tag_registry.REGISTRY if r.has_chip
}

# 칩 선택 시 함께 세팅되는 파생 태그 (02-ai-strategy.md §1.7-1 표 그대로).
# 주의: #아이 동반 → stroller_friendly 파생은 표에 "designer 별도 확인 필요"로
# 명시되어 있어 자동 세팅하지 않는다(사용자가 명시적으로 accessibility 칩을 또
# 골라야만 세팅됨).
CHIP_DERIVED: dict[str, tuple[tuple[str, str], ...]] = {
    "couple": (("mood", "romantic"),),                    # "#연인과 데이트" 행
    "with_child": (("flag", "child_present"),),
    "with_pet": (("flag", "pet_present"), ("accessibility", "pet_friendly_required")),
    "calm": (("congestion_pref", "avoid_priority"),),      # "#한적한 곳" 행
    "contemplative": (("congestion_pref", "avoid_priority"),),  # "#사색/생각정리" 행
    "walking_trail": (("mobility", "walk"),),               # 보조
}


def tags_from_chips(chips: list[str]) -> TagAdditions:
    """칩(registry value) 목록을 축별 태그 값 집합으로 변환.

    registry에 없는 값은 조용히 무시한다(에러 아님 — 01-interface-contract.md
    부록B §B.1: "registry에 없는 값은 서버가 무시").
    """
    result = _empty_additions()
    for chip_value in chips:
        axis = VALUE_TO_AXIS.get(chip_value)
        if axis is None:
            continue
        result[axis].add(chip_value)
        for d_axis, d_value in CHIP_DERIVED.get(chip_value, ()):
            result[d_axis].add(d_value)
    return result


# --- 2) 키워드 → 태그 (LLM 장애 시 전체 룰 폴백, §1.7 의사코드 완성본) -------

# (keyword substring, {axis: [values...]}) — 순서대로 검사, 매칭되면 해당 축에 값 추가.
# §1.7 의사코드에 명시된 항목 + "UI 키워드 칩 목록과 1:1 대응"이라는 지침에 따라
# tag-schema 축 전체를 커버하도록 registry 값마다 대표 키워드 하나씩 채움
# (형태소 분석 없는 단순 부분일치 — 오버엔지니어링 금지, §1.7).
KEYWORD_RULES: list[tuple[str, dict[str, list[str]]]] = [
    # companion / flag
    ("아이", {"companion": ["with_child"], "flag": ["child_present"]}),
    ("반려견", {"companion": ["with_pet"], "flag": ["pet_present"], "accessibility": ["pet_friendly_required"]}),
    ("강아지", {"companion": ["with_pet"], "flag": ["pet_present"], "accessibility": ["pet_friendly_required"]}),
    ("고양이", {"companion": ["with_pet"], "flag": ["pet_present"], "accessibility": ["pet_friendly_required"]}),
    ("반려동물", {"companion": ["with_pet"], "flag": ["pet_present"], "accessibility": ["pet_friendly_required"]}),
    ("연인", {"companion": ["couple"], "mood": ["romantic"]}),
    ("데이트", {"companion": ["couple"], "mood": ["romantic"]}),
    ("부모님", {"companion": ["with_parents"]}),
    ("가족", {"companion": ["family"]}),
    ("친구", {"companion": ["friends"]}),
    ("혼자", {"companion": ["solo"]}),
    ("나홀로", {"companion": ["solo"]}),
    # mobility
    ("드라이브", {"mobility": ["car"]}),
    ("차로", {"mobility": ["car"]}),
    ("자전거", {"mobility": ["bike"]}),
    ("대중교통", {"mobility": ["transit"]}),
    ("걷", {"mobility": ["walk"], "spot_pref": ["walking_trail"]}),
    ("산책", {"mobility": ["walk"], "spot_pref": ["walking_trail"]}),
    # mood / congestion_pref
    ("힐링", {"mood": ["healing"], "congestion_pref": ["avoid_priority"]}),
    ("한적", {"mood": ["calm"], "congestion_pref": ["avoid_priority"]}),
    ("조용", {"mood": ["calm"], "congestion_pref": ["avoid_priority"]}),
    ("대기 없이", {"congestion_pref": ["avoid_priority"]}),
    ("활기", {"mood": ["lively"]}),
    ("사색", {"mood": ["contemplative"], "congestion_pref": ["avoid_priority"]}),
    ("이색", {"mood": ["unique"]}),
    ("상관없", {"congestion_pref": ["indifferent"]}),
    ("무관", {"congestion_pref": ["indifferent"]}),
    # spot_pref
    ("공방", {"spot_pref": ["craft_shop"]}),
    ("소상공인", {"spot_pref": ["craft_shop"]}),
    ("카페", {"spot_pref": ["local_cafe"]}),
    ("시장", {"spot_pref": ["traditional_market"]}),
    ("자연", {"spot_pref": ["nature_view"]}),
    ("경치", {"spot_pref": ["nature_view"]}),
    ("포토", {"spot_pref": ["photo_spot"]}),
    ("사진", {"spot_pref": ["photo_spot"]}),
    ("맛집", {"spot_pref": ["restaurant"]}),
    ("축제", {"spot_pref": ["festival"]}),
    # accessibility
    ("주차", {"accessibility": ["parking_required"]}),
    ("유모차", {"accessibility": ["stroller_friendly"]}),
    ("휠체어", {"accessibility": ["wheelchair_friendly"]}),
]


def tags_from_keywords(text: str) -> TagAdditions:
    """자유 텍스트에서 경량 키워드 매칭으로 태그를 유추한다 (LLM 완전 실패 시 전용)."""
    result = _empty_additions()
    if not text:
        return result
    lowered = text  # 한국어 키워드 위주라 대소문자 변환 불필요(영문 키워드 없음)
    for keyword, additions in KEYWORD_RULES:
        if keyword in lowered:
            for axis, values in additions.items():
                for v in values:
                    if tag_registry.is_valid(axis, v):
                        result[axis].add(v)
    return result


def merge_additions(*sources: TagAdditions) -> TagAdditions:
    merged = _empty_additions()
    for src in sources:
        for axis, values in src.items():
            merged[axis].update(values)
    return merged
