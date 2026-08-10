"""region_code(법정동 5자리) → 원천 파라미터/표시명 해석 헬퍼.

혼잡도 원천(KTO tatsCnctrRatedList)은 areaCd(시도 2자리)+signguCd(시군구 5자리)를 받는다.
추천/상세 경로는 이미 REGIONS seed 에서 area_cd 를 찾고 있었는데, 예보(forecast)·visit_tip 도
같은 해석이 필요해 한 곳으로 모은다(규칙 재정의 없음 — seed 조회 + 표시명 폴백 그대로).
"""

from __future__ import annotations

from ..regions.seed import REGIONS
from ..spots.region_map import get_tourapi_region


def resolve_area_cd(region_code: str) -> str | None:
    """region_code → 원천 areaCd. seed 에 없으면 앞 2자리로 폴백(원천이 빈 응답을 주면 graceful).

    형식이 아예 아니면(숫자 아님/2자리 미만) None → 호출부가 400 으로 거절한다.
    """
    code = (region_code or "").strip()
    if not code.isdigit() or len(code) < 2:
        return None
    seed = next((r for r in REGIONS if r.region_id == code), None)
    if seed:
        return seed.area_cd
    return code[:2]


def resolve_region_name(region_code: str) -> str | None:
    """표시용 지역명. TourAPI 매핑 → REGIONS seed 라벨 순(spot_detail 과 동일 폴백). 없으면 None."""
    code = (region_code or "").strip()
    tr = get_tourapi_region(code)
    if tr:
        return tr.region_name
    return next((r.label for r in REGIONS if r.region_id == code), None)
