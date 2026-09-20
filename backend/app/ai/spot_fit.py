"""spot_fit — 프로필 tag_vector vs 스팟 태그벡터 **코사인 유사도** (AI 소관).

정본: 08-interface-contract.md §스코어링 코사인 규약 + 부록 C.5.
  - 슬라이스는 registry MOOD_SPOT_SLICE = idx 14~28 (mood 7 + spot_pref 8 = 15차원).
    이 슬라이스만 쓰는 이유: companion/accessibility/congestion_pref 축은 '취향 적합'이
    아니라 하드필터·가중치 조정용이라 유사도 축에서 제외한다(부록 C.5 profile_fit 행).
  - 두 벡터 모두 이진(0/1)이므로 코사인 = |교집합| / sqrt(|user| * |spot|).
  - 어느 한쪽이 슬라이스 내 전부 0이면 유사도 정의 불가 → 0.0(중립) 반환.

AI 소관은 여기까지(spot_fit 수치 + matched_tags)이며, 나머지 축 결합·정렬·signals
조립은 backend(recommend_service)가 한다 — 08 compare(D1) 소관 분리와 동일 패턴.
LLM 무관: tag_vector는 서버가 registry로 조립한 값이고 이 함수는 순수 수치 연산이다.
"""

from __future__ import annotations

from math import sqrt

from . import tag_registry

_SLICE_LO, _SLICE_HI = tag_registry.MOOD_SPOT_SLICE  # (14, 29)


def _slice(vec: list[float]) -> list[float]:
    return vec[_SLICE_LO:_SLICE_HI]


def cosine_spot_fit(
    user_vector: list[float], spot_vector: list[float], weights: list[float] | None = None
) -> float:
    """mood+spot_pref 슬라이스의 코사인 유사도 [0.0, 1.0]. 한쪽이 0벡터면 0.0.

    weights(36차원, 선택)를 주면 **희소한 태그가 맞을수록 더 높게** 친다(가중 코사인, IDF). 스팟 태그가
    1~2개뿐이면 이진 코사인은 몇 가지 값에만 몰리는데("맛집" 545곳 = "산책로" 27곳과 같은 점수),
    드문 태그를 더 쳐주면 실제 분포에서 점수가 갈린다. weights=None 이면 종전 이진 코사인과 같다.
    """
    u = _slice(user_vector)
    s = _slice(spot_vector)
    if len(u) != len(s):
        return 0.0
    w = _slice(weights) if weights is not None and len(weights) == len(user_vector) else [1.0] * len(u)
    dot = sum(x * a * b for x, a, b in zip(w, u, s))
    nu = sqrt(sum(x * a * a for x, a in zip(w, u)))
    ns = sqrt(sum(x * b * b for x, b in zip(w, s)))
    if nu == 0.0 or ns == 0.0:
        return 0.0
    return dot / (nu * ns)


def matched_tags(user_vector: list[float], spot_vector: list[float]) -> list[str]:
    """유사도에 기여한 태그(교집합)의 registry value 목록. 프론트가 label로 변환한다.

    슬라이스(mood+spot_pref)에서 user·spot 둘 다 1인 인덱스의 registry value.
    registry 순서를 보존해 결정론적으로 반환.
    """
    out: list[str] = []
    for idx in range(_SLICE_LO, _SLICE_HI):
        if idx < len(user_vector) and idx < len(spot_vector):
            if user_vector[idx] == 1.0 and spot_vector[idx] == 1.0:
                row = tag_registry.REGISTRY[idx]
                out.append(row.value)
    return out
