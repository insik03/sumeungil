"""지역 검색 서비스 — 리포지토리 결과를 계약 A.1 응답으로 조립."""

from __future__ import annotations

from ..regions.seed import RegionSeed, sido_label
from ..repositories.region_repo import RegionRepository
from ..repositories.spot_repo import SpotRepository
from ..schemas.regions import (
    RegionChildItem,
    RegionChildrenResponse,
    RegionSearchItem,
    RegionSearchResponse,
)

LIMIT_MIN = 1
LIMIT_MAX = 20
LIMIT_DEFAULT = 8


def clamp_limit(limit: int) -> int:
    if limit < LIMIT_MIN:
        return LIMIT_MIN
    if limit > LIMIT_MAX:
        return LIMIT_MAX
    return limit


def _to_item(r: RegionSeed) -> RegionSearchItem:
    return RegionSearchItem(
        region_id=r.region_id,
        label=r.label,
        area_cd=r.area_cd,
        sigungu_cd=r.sigungu_cd,
    )


def build_search_response(
    q: str,
    limit: int,
    repo: RegionRepository,
) -> RegionSearchResponse:
    query = q.strip()
    limit = clamp_limit(limit)
    matches = repo.search(query, limit)
    return RegionSearchResponse(query=query, items=[_to_item(r) for r in matches])


def build_children_response(
    area_cd: str,
    repo: RegionRepository,
    spot_repo: SpotRepository,
) -> RegionChildrenResponse:
    """시도코드 → 그 시도의 시군구 목록 (부록 Y.1).

    **스팟이 1곳 이상 실재하는 시군구만** 내려간다. 이유: 이 목록은 드롭다운으로 그대로
    노출돼 곧바로 featured/festivals 조회로 이어지는데, 스팟 0곳인 지역을 넣으면 고른 순간
    빈 화면이 된다(사전에는 있으나 수집분이 없는 시군구가 실제로 존재한다 — 인천 1곳).

    정렬은 label 가나다순. 한글 음절은 유니코드 코드포인트 순서가 곧 가나다순이라 별도
    로캘 없이 안정적이다(같은 입력 = 같은 순서).
    """
    area = (area_cd or "").strip()
    counts = spot_repo.region_counts()
    items = [
        RegionChildItem(
            region_code=r.region_id,
            label=r.label,
            spot_count=counts.get(r.region_id, 0),
        )
        for r in repo.by_area(area)
        if counts.get(r.region_id, 0) > 0
    ]
    items.sort(key=lambda i: i.label)
    return RegionChildrenResponse(area_cd=area, label=sido_label(area), items=items)
