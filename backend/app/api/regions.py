"""GET /api/v1/regions/search — 지명 → 지역코드 조회 (계약 부록 A.1).

프론트 검색창 타이핑/지역 칩이 이걸로 area_cd/sigungu_cd 를 얻어 board 를 재호출한다.
매칭 0건은 에러가 아니라 items:[] + 200.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ..deps import get_region_repository, get_spot_repository
from ..regions.seed import is_area_cd
from ..repositories.region_repo import RegionRepository
from ..repositories.spot_repo import SpotRepository
from ..schemas.regions import RegionChildrenResponse, RegionSearchResponse
from ..services import region_service

logger = logging.getLogger("sumeungil.api.regions")

router = APIRouter(prefix="/api/v1/regions", tags=["regions"])


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": {}}},
    )


@router.get("/search", response_model=RegionSearchResponse)
async def search_regions(
    q: str = Query(..., description="지명 조각(예: '해운', '경주'). 1자 이상"),
    limit: int = Query(default=region_service.LIMIT_DEFAULT, description="후보 최대 개수 (1~20)"),
    repo: RegionRepository = Depends(get_region_repository),
):
    query = q.strip()
    if not query:
        return _error(400, "INVALID_QUERY", "검색어(q)는 1자 이상이어야 합니다.")

    try:
        return region_service.build_search_response(query, limit, repo)
    except Exception:  # noqa: BLE001
        logger.exception("regions/search 처리 중 예기치 못한 오류")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")


# 부록 Y.1(2026-08-11) — 시도 → 시군구 목록. additive: /search 는 완전 불변.
# 지역 허브가 "경기를 고르면 수원 장안구 한 곳"이던 문제(대표 지적)의 백엔드 절반이다.
# 프론트는 이 목록으로 시군구 드롭다운을 그리고, 고른 region_code 를 기존 엔드포인트에 넘긴다.
@router.get("/children", response_model=RegionChildrenResponse)
async def region_children(
    area_cd: str = Query(..., description="시도코드 2자리(예: 41=경기, 51=강원)"),
    repo: RegionRepository = Depends(get_region_repository),
    spot_repo: SpotRepository = Depends(get_spot_repository),
):
    """스팟이 실재하는 시군구만 label 가나다순으로. 0건은 에러가 아니라 items:[] + 200."""
    if not is_area_cd(area_cd):
        return _error(400, "INVALID_AREA", "시도코드(area_cd)는 2자리 숫자여야 합니다.")

    try:
        return region_service.build_children_response(area_cd, repo, spot_repo)
    except Exception:  # noqa: BLE001
        logger.exception("regions/children 처리 중 예기치 못한 오류")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")
