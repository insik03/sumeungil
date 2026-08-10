"""GET /api/v1/congestion/board — 실시간 혼잡 전광판.

계약 §1. 파라미터 생략 시 서버 기본 지역으로 응답한다.
원천 장애는 가능한 한 에러 대신 is_stale/degraded 로 부드럽게 처리하고,
제공할 캐시조차 없을 때만 502 UPSTREAM_UNAVAILABLE.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ..clients.kto_client import KtoUpstreamError
from ..config import settings
from ..deps import get_congestion_repository, get_spot_repository
from ..repositories.congestion_repo import CongestionRepository
from ..repositories.spot_repo import SpotRepository
from ..cache.base import Cache
from ..deps import get_cache
from ..schemas.congestion import BoardResponse, ForecastResponse
from ..schemas.nationwide import NationwideCongestionResponse
from ..services import congestion_service, nationwide_congestion_service
from ..util.regions import resolve_area_cd, resolve_region_name

logger = logging.getLogger("sumeungil.api.congestion")

router = APIRouter(prefix="/api/v1/congestion", tags=["congestion"])


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": {}}},
    )


@router.get("/board", response_model=BoardResponse)
async def get_board(
    area_cd: str | None = Query(default=None, description="시도코드(공공 API areaCd)"),
    sigungu_cd: str | None = Query(default=None, description="시군구코드(공공 API signguCd)"),
    limit: int = Query(default=10, description="반환 최대 개수 (1~50)"),
    repo: CongestionRepository = Depends(get_congestion_repository),
):
    area = (area_cd or settings.default_area_cd).strip()
    sigungu = (sigungu_cd or settings.default_sigungu_cd).strip()

    # 최소 형식 검증 (숫자 코드)
    if not area.isdigit() or not sigungu.isdigit():
        return _error(400, "INVALID_REGION", "지역 코드 형식이 올바르지 않습니다.")

    try:
        result = await repo.get_board(area, sigungu)
    except KtoUpstreamError as exc:
        logger.warning("board 원천 실패 + 폴백 없음: %s", exc)
        return _error(502, "UPSTREAM_UNAVAILABLE", "혼잡도 데이터를 불러오지 못했습니다.")
    except Exception:  # noqa: BLE001
        logger.exception("board 처리 중 예기치 못한 오류")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")

    return congestion_service.build_board_response(area, sigungu, limit, result)


# 부록 M — 한적한 날 예보. board(§1)와 별도 계약이며 board 응답·캐시는 불변이다.
# 원천은 관광지마다 미래 17일치(실측) 예측 행을 주는데 board 는 '오늘' 1행만 쓰고 버린다.
# 이 엔드포인트가 그 버려지던 날짜들을 시계열로 살려 "언제 가면 한적한지"를 답한다.
@router.get("/forecast", response_model=ForecastResponse)
async def get_forecast(
    region_code: str = Query(..., description="법정동 시군구 코드(예: 26350)"),
    spot_name: str | None = Query(default=None, max_length=60, description="특정 관광지만 조회"),
    days: int = Query(default=congestion_service.FORECAST_DAYS_DEFAULT, description="조회 일수(1~35)"),
    limit: int = Query(default=congestion_service.FORECAST_SPOT_LIMIT, description="관광지 수(1~50)"),
    repo: CongestionRepository = Depends(get_congestion_repository),
):
    code = (region_code or "").strip()
    area_cd = resolve_area_cd(code)
    if area_cd is None:
        return _error(400, "INVALID_REGION", "지역 코드 형식이 올바르지 않습니다.")

    try:
        result = await repo.get_forecast(area_cd, code)
    except KtoUpstreamError as exc:
        logger.warning("forecast 원천 실패 + 폴백 없음: %s", exc)
        return _error(502, "UPSTREAM_UNAVAILABLE", "혼잡도 예보를 불러오지 못했습니다.")
    except Exception:  # noqa: BLE001
        logger.exception("forecast 처리 중 예기치 못한 오류")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")

    # 데이터가 없는 지역은 에러가 아니라 spots:[] 로 정직하게(graceful) 응답한다.
    return congestion_service.build_forecast_response(
        region_code=code,
        region_name=resolve_region_name(code),
        spot_name=(spot_name or "").strip() or None,
        days=days,
        result=result,
        limit=congestion_service.clamp_limit(limit),
    )


# --- 부록 U(2026-08-01): 전국 17개 시도 혼잡도 보드 ---
# 시군구 250곳을 다 부르면 쿼터가 죽는다(원천이 signguCd 필수). 시도당 대표 시군구 1곳,
# 12시간 캐시 → 하루 ~34건. 근거 지역명을 응답에 담아 "서울=종로 기준"을 숨기지 않는다.
@router.get("/nationwide", response_model=NationwideCongestionResponse)
async def get_nationwide_congestion(
    congestion_repo: CongestionRepository = Depends(get_congestion_repository),
    spot_repo: SpotRepository = Depends(get_spot_repository),
    cache: Cache = Depends(get_cache),
):
    try:
        return await nationwide_congestion_service.build_nationwide_congestion(
            congestion_repo, cache, spot_repo
        )
    except Exception:  # noqa: BLE001
        logger.exception("congestion/nationwide 처리 중 예기치 못한 오류")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL", "message": "서버 오류가 발생했습니다.", "detail": {}}},
        )
