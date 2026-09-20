"""스팟 소개글(overview) → 분위기·스팟선호 태그 — 결정론 규칙 추출기 (2026-09-20).

왜 규칙인가
  시드의 스팟은 72% 가 태그 1개(카테고리에서 파생된 spot_pref)뿐이라 매칭도가 계단처럼 몰렸다
  (같은 카테고리 = 같은 점수). 소개글에는 분위기(한적·힐링·로맨틱…)와 특성(산책로·포토스팟…)이
  적혀 있으므로 그 문장에서 태그를 더 뽑는다. 로컬 LLM 은 2코어 서버에서 스팟당 수십 초라 2만 건을
  못 돌리고, 규칙은 즉시·무료·재현 가능하며 소개글에 **없는** 성격을 지어내지 않는다.

  - 소개글에 근거 키워드가 있을 때만 태그를 붙인다(없으면 안 붙인다 — 추측 금지).
  - 결과는 (소개글 해시, RULES_VERSION) 으로 캐시된다. 소개글이 바뀌거나 규칙을 올릴 때만 다시 만든다.
  - LLM 무관: 순수 함수.
"""

from __future__ import annotations

import re

from . import tag_registry

# 규칙을 바꾸면 반드시 올린다 — 캐시된 태그가 이 값과 다르면 다시 만든다.
RULES_VERSION = "2"

# 태그별 (강한 키워드, 약한 키워드). 강한 키워드는 1번만 나와도 근거가 되고, 약한 키워드("가족, 연인,
# 친구와 함께" 같은 나열문에도 나오는 흔한 말)는 2번 이상 겹칠 때만 근거로 인정한다.
_RULES: dict[tuple[str, str], tuple[tuple[str, ...], tuple[str, ...]]] = {
    # --- mood ---
    ("mood", "calm"): (("한적", "고즈넉", "호젓", "붐비지 않", "번잡하지 않"), ("조용", "차분", "여유로")),
    ("mood", "lively"): (("활기", "북적", "시끌", "왁자", "핫플", "인산인해", "젊음의 거리"), ("밤새",)),
    ("mood", "healing"): (("힐링", "치유", "산림욕", "온천", "족욕", "웰니스", "평온"), ("휴식", "편안", "스파", "평화로")),
    ("mood", "romantic"): (("로맨틱", "데이트", "낭만", "야경", "노을", "일몰", "석양", "프러포즈"), ("연인", "커플")),
    ("mood", "contemplative"): (("사색", "명상", "성찰", "템플스테이", "묵상"), ("고요", "산사", "사찰", "암자", "선원")),
    ("mood", "unique"): (("이색", "독특", "이국적", "특별한 체험", "이채"), ()),
    ("mood", "family_friendly"): (("아이와", "아이들", "어린이", "키즈", "체험학습", "아이 동반", "유아"), ("가족",)),
    # --- spot_pref ---
    ("spot_pref", "nature_view"): (("절경", "폭포", "계곡", "해수욕장", "전망대", "일출", "일몰"), ("전망", "해변", "바다", "호수", "숲", "경관", "자연", "수목", "오름", "섬")),
    ("spot_pref", "photo_spot"): (("포토존", "인생샷", "포토스팟", "사진 명소", "사진 촬영", "사진 찍", "사진을 찍", "사진작가", "출사"), ("포토",)),
    ("spot_pref", "walking_trail"): (("산책로", "둘레길", "트레킹", "올레", "탐방로", "등산로", "하이킹", "숲길", "해안길"), ("산책", "걷기", "걷는", "도보")),
    ("spot_pref", "craft_shop"): (("공방", "도예", "공예", "수공예", "목공", "원데이 클래스"), ()),
    ("spot_pref", "traditional_market"): (("전통시장", "재래시장", "오일장", "5일장", "장터"), ("시장",)),
    ("spot_pref", "local_cafe"): (("카페", "디저트", "브런치", "베이커리", "로스터리"), ("커피",)),
    ("spot_pref", "festival"): (("축제", "페스티벌", "불꽃놀이"), ("행사",)),
}

# 소개글에서 뽑아 붙일 수 있는 태그(레지스트리에 실제로 있는 값만).
_VALID = {(r.axis, r.value) for r in tag_registry.REGISTRY}
assert all(k in _VALID for k in _RULES), "규칙에 레지스트리에 없는 태그가 있다"

# 한 스팟에 소개글 파생으로 붙는 상한 — 태그가 많다고 매칭이 좋아지는 게 아니라 뭉개진다.
MAX_MOOD = 2
MAX_SPOT_PREF = 2

_NEGATED_LIVELY = re.compile(r"(활기|북적|시끌|왁자)[^.。]{0,6}(지\s*않|없)")


def _hits(text: str, keywords: tuple[str, ...]) -> int:
    return sum(text.count(k) for k in keywords)


def derive_tags(text: str | None) -> list[tuple[str, str]]:
    """정제된 소개글 → [(axis, value), …]. 근거가 없으면 빈 리스트. 결정론적(같은 입력 = 같은 출력)."""
    if not text or not text.strip():
        return []
    body = _NEGATED_LIVELY.sub(" ", text)  # "북적이지 않는" 같은 부정 표현은 활기 근거가 아니다
    scored: dict[str, list[tuple[int, tuple[str, str]]]] = {"mood": [], "spot_pref": []}
    for (axis, value), (strong, weak) in _RULES.items():
        s_hits, w_hits = _hits(body, strong), _hits(body, weak)
        if s_hits >= 1 or w_hits >= 2:
            scored[axis].append((s_hits * 2 + w_hits, (axis, value)))  # 강한 근거가 많은 태그를 우선
    out: list[tuple[str, str]] = []
    for axis, cap in (("mood", MAX_MOOD), ("spot_pref", MAX_SPOT_PREF)):
        # 적중 많은 순, 동률은 레지스트리 순서 — 재현 가능
        ranked = sorted(scored[axis], key=lambda x: (-x[0], _order(x[1])))
        out.extend(tag for _n, tag in ranked[:cap])
    return out


def _order(tag: tuple[str, str]) -> int:
    for r in tag_registry.REGISTRY:
        if (r.axis, r.value) == tag:
            return r.index
    return 999
