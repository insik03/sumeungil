"""스팟명 정규화·매칭 단일 소스.

기존에는 `recommend_service._norm` 이 사실상 공용 함수로 쓰여 왔다(featured/compare/collections/
search 가 전부 import). 예보(forecast) 서비스도 같은 규칙이 필요한데 congestion_service →
recommend_service 는 **순환 import**(recommend_service 가 congestion_service.classify_level 을
쓴다)라 참조할 수 없다. 그래서 규칙을 이 모듈로 내리고 recommend_service._norm 은 이 함수를
그대로 가리키게 한다 — **정의는 한 곳**(재정의 금지), 호출부는 전부 불변.
"""

from __future__ import annotations


def norm_name(s: str) -> str:
    """공백 제거 + 소문자화. (기존 recommend_service._norm 과 동일 규칙)"""
    return s.replace(" ", "").lower().strip()


def name_matches(a_norm: str, b_norm: str) -> bool:
    """정규화된 두 이름이 같거나 한쪽이 다른 쪽을 포함하면 매치.

    `recommend_service._match_congestion` 의 매칭 규칙과 동일하다(억지 매칭을 늘리지 않기 위해
    새 규칙을 만들지 않는다). 짧은 이름이 넓게 걸릴 수 있는 한계도 동일하게 승계한다.
    """
    if not a_norm or not b_norm:
        return False
    return a_norm == b_norm or a_norm in b_norm or b_norm in a_norm
