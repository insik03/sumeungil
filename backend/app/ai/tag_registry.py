"""`tag_axis_registry` 정본 시드 (vector_version = 1, 36차원).

출처: projects/sumeungil/08-interface-contract.md §1.4 (표 36행 그대로 코드화).
이 파일이 이 프로젝트에서 태그 축·값·라벨·벡터 인덱스의 **유일한 소스**다.
- LLM 프롬프트의 enum (prompts.py)
- LLM 출력 재검증 (schemas.py RawLLMExtraction)
- 칩→태그 룰 폴백 매핑 (rule_fallback.py)
- tag_vector 조립 순서 (assembler.py)
- `GET /onboarding/tag-schema` 응답(backend 소관, 여기서 조회)

모두 이 registry 하나를 참조해야 한다. 값 하드코딩 금지.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegistryRow:
    index: int          # tag_vector 내 고정 위치 (0~35)
    axis: str           # 축 이름 (7종)
    value: str           # 영문 코드 (registry 정본 값)
    label_ko: str        # 한국어 표시명. TagValue.label은 이 값과 항상 일치해야 한다.
    has_chip: bool = True  # False = UI 칩 없음(파생/디폴트 값) → tag-schema에서 제외


VECTOR_VERSION = 1
VECTOR_DIM = 36

# 08 §1.4 표 그대로. index 7·8(flag)·35(congestion_pref:unspecified)의 label_ko는
# 08 부록B §B.1 실제 응답 예시("아이 동반"/"반려동물 동반"/"미언급")를 정본으로 채택했다
# (원 표의 "(칩 없음 — ...)" 괄호 설명은 UI 노출용 라벨이 아니라 각주이므로 그대로 쓰지 않는다).
REGISTRY: tuple[RegistryRow, ...] = (
    RegistryRow(0, "companion", "couple", "연인"),
    RegistryRow(1, "companion", "family", "가족"),
    RegistryRow(2, "companion", "with_child", "아이 동반"),
    RegistryRow(3, "companion", "with_parents", "부모님 동반"),
    RegistryRow(4, "companion", "with_pet", "반려동물 동반"),
    RegistryRow(5, "companion", "solo", "혼자"),
    RegistryRow(6, "companion", "friends", "친구"),
    RegistryRow(7, "flag", "child_present", "아이 동반", has_chip=False),
    RegistryRow(8, "flag", "pet_present", "반려동물 동반", has_chip=False),
    RegistryRow(9, "mobility", "walk", "도보"),
    RegistryRow(10, "mobility", "bike", "자전거"),
    RegistryRow(11, "mobility", "car", "차량/드라이브"),
    RegistryRow(12, "mobility", "transit", "대중교통"),
    RegistryRow(13, "mobility", "any", "무관"),
    RegistryRow(14, "mood", "calm", "한적함"),
    RegistryRow(15, "mood", "lively", "활기참"),
    RegistryRow(16, "mood", "healing", "힐링"),
    RegistryRow(17, "mood", "romantic", "로맨틱"),
    RegistryRow(18, "mood", "contemplative", "사색"),
    RegistryRow(19, "mood", "unique", "이색 체험"),
    RegistryRow(20, "mood", "family_friendly", "가족 친화"),
    RegistryRow(21, "spot_pref", "local_cafe", "로컬 카페"),
    RegistryRow(22, "spot_pref", "craft_shop", "공방"),
    RegistryRow(23, "spot_pref", "traditional_market", "전통시장"),
    RegistryRow(24, "spot_pref", "nature_view", "자연경관"),
    RegistryRow(25, "spot_pref", "photo_spot", "포토스팟"),
    RegistryRow(26, "spot_pref", "restaurant", "맛집"),
    RegistryRow(27, "spot_pref", "walking_trail", "산책로"),
    RegistryRow(28, "spot_pref", "festival", "축제/이벤트"),
    RegistryRow(29, "accessibility", "parking_required", "주차 필요"),
    RegistryRow(30, "accessibility", "stroller_friendly", "유모차 접근"),
    RegistryRow(31, "accessibility", "wheelchair_friendly", "휠체어 접근"),
    RegistryRow(32, "accessibility", "pet_friendly_required", "반려동물 동반 가능"),
    RegistryRow(33, "congestion_pref", "avoid_priority", "혼잡 회피 우선"),
    RegistryRow(34, "congestion_pref", "indifferent", "혼잡도 무관"),
    RegistryRow(35, "congestion_pref", "unspecified", "미언급", has_chip=False),
)

assert len(REGISTRY) == VECTOR_DIM
assert [r.index for r in REGISTRY] == list(range(VECTOR_DIM))

# 축 이름 정본 순서 (OnboardingResult.tags 의 key 7종)
AXES: tuple[str, ...] = (
    "companion", "flag", "mobility", "mood", "spot_pref", "accessibility", "congestion_pref",
)

# --- 조회용 인덱스 (모듈 로드 시 1회 구성) ---
INDEX_OF: dict[tuple[str, str], int] = {(r.axis, r.value): r.index for r in REGISTRY}
LABEL_OF: dict[tuple[str, str], str] = {(r.axis, r.value): r.label_ko for r in REGISTRY}
VALID_VALUES: dict[str, frozenset[str]] = {
    axis: frozenset(r.value for r in REGISTRY if r.axis == axis) for axis in AXES
}


def is_valid(axis: str, value: str) -> bool:
    """registry에 등록된 (축,값) 조합인지 확인. LLM 출력 재검증(방어계층 1·5)의 핵심."""
    return value in VALID_VALUES.get(axis, frozenset())


def label_for(axis: str, value: str) -> str | None:
    return LABEL_OF.get((axis, value))


def vector_index(axis: str, value: str) -> int | None:
    return INDEX_OF.get((axis, value))


def chip_axes() -> tuple[str, ...]:
    """`GET /onboarding/tag-schema`용 — 칩이 있는 축만 (flag 제외)."""
    return tuple(axis for axis in AXES if axis != "flag")


def chips_for_axis(axis: str) -> list[RegistryRow]:
    """`GET /onboarding/tag-schema`용 — 축의 실제 UI 칩(has_chip=True)만."""
    return [r for r in REGISTRY if r.axis == axis and r.has_chip]


# S_fit 코사인 유사도용 슬라이스 (08 §1.4 슬라이스 규약) — backend/AI 스코어링 공용 상수.
# 하드코딩된 매직넘버가 아니라 registry 인덱스에서 파생된 상수임을 명확히 하기 위해 여기 둔다.
MOOD_SPOT_SLICE = (14, 29)   # index 14~28 (mood + spot_pref, 15차원) — range(14, 29)
ACCESSIBILITY_SLICE = (29, 33)  # index 29~32 — 하드 필터
