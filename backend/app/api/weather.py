"""GET /api/v1/weather/nationwide — 전국 9권역 날씨 보드 (부록 Q.1).

원천 호출 예산은 서비스가 고정한다(9권역 × 30분 캐시). 부분 실패는 200 안에서
available=false 로 표현하므로, 이 레이어에서 5xx 로 승격시키지 않는다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..cache.base import Cache
from ..deps import get_cache
from ..schemas.outlook import NationwideWeatherResponse
from ..services import nationwide_weather_service

logger = logging.getLogger("sumeungil.api.weather")

router = APIRouter(prefix="/api/v1/weather", tags=["weather"])


@router.get("/nationwide", response_model=NationwideWeatherResponse)
async def get_nationwide_weather(cache: Cache = Depends(get_cache)):
    try:
        return await nationwide_weather_service.build_nationwide_weather(cache)
    except Exception:  # noqa: BLE001
        logger.exception("weather/nationwide 처리 중 예기치 못한 오류")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL", "message": "서버 오류가 발생했습니다.", "detail": {}}},
        )
