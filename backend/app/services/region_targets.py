"""도(道) → 시군구 상위 N곳 선정 — 여러 서비스가 공유하는 작은 유틸.

원래 `concierge_service` 안에 있던 로직이다(부록 N.12, 2026-08-01). 부록 Y(지역 허브 A안)의
`featured_service` 가 같은 규칙을 재사용하면서 컨시어지에 의존하게 됐는데, 2026-08-20
컨시어지 기능 제거(08-PRD §4-6)로 그 모듈이 사라지므로 **로직을 그대로** 여기로 옮겼다.

옮기면서 규칙은 한 줄도 바꾸지 않았다 — "스팟이 많은 순 상위 PROVINCE_SWEEP_MAX 곳, 동수면
코드순"이라는 결정적 선정이 그대로 유지되어야 홈(`/api/v1/places/featured`)의 응답과 캐시
히트율이 종전과 동일하다.
"""

from __future__ import annotations

from ..regions.seed import REGIONS
from ..repositories.spot_repo import SpotRepository

# 충청도는 시군구 30곳, 경상도는 45곳이다. 전부 훑으면 혼잡도 board 원천 호출이 요청 1건당
# 수십 건이 되어 쿼터를 태운다(2026-07-29 실사고와 같은 경로). 그래서 **스팟이 많은 상위 6곳**만
# 훑는다. 어느 6곳인지는 결정적이라 캐시가 듣는다.
PROVINCE_SWEEP_MAX = 6


def province_targets(area_cds: tuple[str, ...], spot_repo: SpotRepository) -> list[str]:
    """도에 속한 시군구 중 **스팟이 많은 순 상위 PROVINCE_SWEEP_MAX 곳**(결정적).

    스팟이 실제로 쌓인 시군구여야 추천이 나온다. 동수면 코드순으로 고정한다.
    """
    codes = [r.region_id for r in REGIONS if r.area_cd in area_cds]
    codes.sort(key=lambda rc: (-len(spot_repo.by_region(rc, None)), rc))
    return codes[:PROVINCE_SWEEP_MAX]
