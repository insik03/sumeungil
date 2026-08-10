"""GET /api/v1/plan/outlook — 출발일(오늘~+180일) 날씨·혼잡도 전망 (부록 Q.2).

검증 계약:
  region_code 누락/형식오류/미등록 → 400 INVALID_REGION
  date 형식오류                    → 400 INVALID_DATE
  오늘~+180일 밖(과거 포함)        → 400 DATE_OUT_OF_RANGE
데이터가 없는 것은 에러가 아니다 → 200 + available:false + notice(정직 표기).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ..cache.base import Cache
from ..deps import get_cache, get_congestion_repository
from ..regions.seed import REGIONS
from ..repositories.congestion_repo import CongestionRepository
from ..schemas.outlook import OutlookResponse
from ..services import outlook_service
from ..services.outlook_service import DateOutOfRange, InvalidDate

logger = logging.getLogger("sumeungil.api.plan")

router = APIRouter(prefix="/api/v1/plan", tags=["plan"])

_KNOWN_REGIONS = {r.region_id for r in REGIONS}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": {}}},
    )


@router.get("/outlook", response_model=OutlookResponse)
async def get_outlook(
    region_code: str = Query("", max_length=20),
    date: str = Query("", max_length=20),
    congestion_repo: CongestionRepository = Depends(get_congestion_repository),
    cache: Cache = Depends(get_cache),
):
    rc = (region_code or "").strip()
    if not rc or not rc.isdigit() or rc not in _KNOWN_REGIONS:
        return _error(400, "INVALID_REGION", "지역을 선택해 주세요.")

    try:
        return await outlook_service.build_outlook(
            region_code=rc, date_str=date, congestion_repo=congestion_repo, cache=cache,
        )
    except InvalidDate:
        return _error(400, "INVALID_DATE", "날짜 형식이 올바르지 않습니다. (YYYY-MM-DD)")
    except DateOutOfRange:
        return _error(
            400, "DATE_OUT_OF_RANGE",
            f"오늘부터 {outlook_service.MAX_DAYS_AHEAD}일 이내의 날짜만 조회할 수 있어요.",
        )
    except Exception:  # noqa: BLE001
        logger.exception("plan/outlook 처리 중 예기치 못한 오류")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")
