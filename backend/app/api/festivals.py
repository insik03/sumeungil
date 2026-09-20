"""GET /api/v1/festivals — 홈 축제 배너 실연동 (부록 K).

지역별 진행중/예정 축제를 **2원 소스**(TourAPI searchFestival2 + 행안부 전국문화축제표준데이터)
실호출로 내려준다. 라우트 계약·응답 스키마는 신설 때와 동일 — 소스만 2원화(2026-07-29).
additive: 기존 places/collections/compare/courses 엔드포인트·스키마·동작 불변.
원천 실패/데이터없음/축제없는 지역은 festivals=[] + region 으로 graceful(홈 정적 폴백 유지 가능).
region_code 를 생략하면 전국 목록을 준다.

2026-07-29 확장(전용 페이지용, **additive**): `limit` 상한 30→200, `month=YYYY-MM`, `window_days`(≤365),
응답 `total`. 파라미터를 안 주면 홈 동작은 이전과 같다(기본 limit 10 / 90일 윈도우).
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..cache.base import Cache
from ..deps import get_cache, get_spot_repository, get_weather_provider
from ..regions.nationwide import BLOCK_BY_KEY
from ..repositories.spot_repo import SpotRepository
from ..regions.seed import is_area_cd
from ..schemas.places import FestivalDetailResponse, FestivalsResponse
from ..services import festival_detail_service, festival_service
from ..services.festival_detail_service import FestivalNotFound
from ..services.weather_provider import WeatherProvider

logger = logging.getLogger("sumeungil.api.festivals")

router = APIRouter(prefix="/api/v1/festivals", tags=["festivals"])


def _parse_as_of(as_of: str | None) -> date | None:
    """as_of(YYYYMMDD) → date. 없거나 형식오류면 None(서비스가 실제 오늘로 폴백).

    조회 기준일 knob(기본=오늘). 진행중/예정 판정도 이 날짜 기준으로 일관 계산된다.
    프론트는 이 파라미터를 생략(=오늘)해 항상 진행중/예정 축제만 받는다.
    원천 스윕은 항상 실제 오늘 기준이고 as_of 는 캐시된 목록의 메모리 필터로만 쓰인다
    (as_of 를 바꿔 부르는 요청이 원천 호출/캐시 키를 증식시키지 못하게 하는 방어 — 부록 K.1).
    """
    if not as_of:
        return None
    s = as_of.strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        return None


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": {}}},
    )


@router.get("", response_model=FestivalsResponse)
async def get_festivals(
    region_code: str | None = None,
    limit: int = 10,
    as_of: str | None = None,
    month: str | None = None,
    window_days: int | None = None,
    # 부록 Y additive(2026-08-11): 시도 전체 축제. region_code 가 오면 무시된다(더 좁은 지정 우선).
    # 형식 위반은 400 — 조용히 전국으로 떨어지면 사용자가 "경기 축제"를 본다고 착각한다.
    area_cd: str | None = None,
    # 2026-09-20 additive: 9권역 key(gyeonggi…jeju). region_code·area_cd 가 오면 무시된다.
    # 알 수 없는 key 는 area_cd 와 같은 이유로 400 — 조용히 전국으로 떨어지면 사용자가
    # "이 권역 축제만 보고 있다"고 오인한다.
    region_block: str | None = None,
    cache: Cache = Depends(get_cache),
):
    """축제 목록. 홈 배너(파라미터 없음)와 축제 전용 페이지가 같은 엔드포인트를 쓴다.

    - `limit`: 기본 10, **1~200 클램프**(전용 페이지용으로 30→200 확대. 기본값은 그대로).
    - `month=YYYY-MM`: 그 달에 기간이 걸치는 축제만. 형식 오류면 **400**(조용히 무시하지 않는다).
      month 를 주면 window_days 는 무시된다.
    - `window_days`: 시작 예정 윈도우(기본 90, 1~365 클램프). 가을 축제까지 보려면 365.
    - 셋 다 생략하면 개정 전과 동일한 홈 동작(진행중 + 90일 내 예정, 10건).
    """
    if month is not None:
        try:
            festival_service.month_bounds(month)
        except ValueError:
            return _error(400, "INVALID_MONTH", "month 는 YYYY-MM 형식이어야 합니다.")
    if area_cd is not None and not is_area_cd(area_cd):
        return _error(400, "INVALID_AREA", "시도코드(area_cd)는 2자리 숫자여야 합니다.")
    if region_block is not None and region_block.strip() not in BLOCK_BY_KEY:
        return _error(400, "INVALID_REGION_BLOCK", "알 수 없는 권역입니다.")

    try:
        return await festival_service.build_festivals_response(
            region_code=region_code,
            limit=limit,
            cache=cache,
            today=_parse_as_of(as_of),
            month=month,
            window_days=window_days,
            area_cd=area_cd,
            region_block=region_block,
        )
    except Exception:  # noqa: BLE001
        logger.exception("festivals 처리 중 예기치 못한 오류")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL", "message": "서버 오류가 발생했습니다.", "detail": {}}},
        )


# 부록 P.2 — 축제 상세(사진 슬라이드·방문 타이밍·날씨). additive: 위 목록 라우트는 불변.
# 원천을 새로 부르지 않는다(목록과 같은 전국 스윕 캐시 + detailImage2 7일 캐시만).
@router.get("/{festival_id}", response_model=FestivalDetailResponse)
async def get_festival_detail(
    festival_id: int,
    as_of: str | None = None,
    cache: Cache = Depends(get_cache),
    weather_provider: WeatherProvider = Depends(get_weather_provider),
    spot_repo: SpotRepository = Depends(get_spot_repository),
):
    """축제 1건 상세. 전국 캐시에 없는 id 는 404 FESTIVAL_NOT_FOUND.

    `as_of`(YYYYMMDD)는 목록과 동일한 테스트/데모용 knob — 생략하면 오늘 기준이다.
    """
    try:
        return await festival_detail_service.build_festival_detail(
            festival_id=festival_id,
            cache=cache,
            weather_provider=weather_provider,
            today=_parse_as_of(as_of),
            # 축제는 좌표가 없어 그 시군구 스팟 좌표로 "지금 날씨" 지점을 잡는다.
            spot_repo=spot_repo,
        )
    except FestivalNotFound:
        return _error(404, "FESTIVAL_NOT_FOUND", "해당 축제를 찾을 수 없습니다.")
    except Exception:  # noqa: BLE001
        logger.exception("festivals/{festival_id} 처리 중 예기치 못한 오류")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")
