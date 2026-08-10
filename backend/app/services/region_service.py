"""지역 검색 서비스 — 리포지토리 결과를 계약 A.1 응답으로 조립."""

from __future__ import annotations

from ..regions.seed import RegionSeed
from ..repositories.region_repo import RegionRepository
from ..schemas.regions import RegionSearchItem, RegionSearchResponse

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
