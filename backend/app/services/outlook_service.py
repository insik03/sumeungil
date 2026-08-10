"""부록 Q.2 — 출발일 지정 조회 (오늘 ~ +180일).

"이 날 떠나면 어떨까?"에 답하는 화면용. 두 축을 **각각 다른 커버리지**로 정직하게 답한다:

  weather    : 기상청 D18 예보가 닿는 **오늘~+3일**만 basis="forecast". 그 밖은 미제공(none).
               (같은 키로 중기예보·평년값 원천에 접근할 수 없음을 실호출로 확인 — 2026-07-31)
  congestion : KTO 집중률 예측이 닿는 **오늘~+29일**(원천 실측 30일치)이면 basis="forecast".
               그 밖은 작년 같은 시기 실측(last_year)이 필요하나 **원천이 없다** → none.

핵심은 basis 라벨이다. 프론트는 이 라벨로 "실예보"와 "미제공"을 구분해 표기한다.
값을 지어내지 않는다 — 못 구하면 available=false + 정형 notice.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

from ..cache.base import Cache
from ..clients import kma_weather_client
from ..clients.kma_weather_client import (
    FORECAST_MAX_DAYS_AHEAD,
    REGION_COURSE_IDS,
    KmaWeatherError,
)
from ..config import settings
from ..regions.seed import REGIONS
from ..repositories.congestion_repo import CongestionRepository
from ..schemas.outlook import (
    OutlookCongestion,
    OutlookMeta,
    OutlookResponse,
    OutlookWeather,
)
from ..schemas.places import RecommendRegion
from ..spots.region_map import get_tourapi_region
from ..util.time import now_kst
from .congestion_service import classify_level

logger = logging.getLogger("sumeungil.services.outlook")

# 조회 가능 상한(계약 Q.2). 오늘(0) ~ +180일.
MAX_DAYS_AHEAD = 180
# 혼잡도 예측 커버는 원천 응답에서 **동적으로** 판정한다(오늘 실측 30일치. 원천이 늘리거나
# 줄여도 코드 수정 없이 따라간다). 아래 값은 안내 문구에만 쓰는 참고치다.
CONGESTION_COVER_HINT_DAYS = 30

OUTLOOK_CACHE_TTL_SEC = 6 * 60 * 60  # (region_code, date) 6시간

NOTICE_WEATHER_OUT_OF_RANGE = f"{FORECAST_MAX_DAYS_AHEAD}일 뒤까지만 날씨를 알려드릴 수 있어요."
NOTICE_WEATHER_NO_COURSE = "이 지역은 아직 날씨 예보 지점이 연결되지 않았어요."
NOTICE_WEATHER_UPSTREAM = "날씨 정보를 불러오지 못했어요."
NOTICE_CONGESTION_OUT_OF_RANGE = (
    f"혼잡도 예측은 약 {CONGESTION_COVER_HINT_DAYS}일 뒤까지만 제공돼요. "
    "그 이후는 시기가 가까워지면 알려드릴게요."
)
NOTICE_CONGESTION_UPSTREAM = "혼잡도 정보를 불러오지 못했어요."
NOTICE_META = (
    "날씨는 예보가 닿는 기간까지, 혼잡도는 예측이 닿는 기간까지만 알려드려요. "
    "그 밖의 날짜는 표시하지 않습니다."
)


class InvalidDate(Exception):
    """날짜 형식 오류 — API 가 400 INVALID_DATE 로 매핑."""


class DateOutOfRange(Exception):
    """오늘~+180일 밖 — API 가 400 DATE_OUT_OF_RANGE 로 매핑."""


def parse_date(value: str) -> date:
    """YYYY-MM-DD 파싱 + 범위 검증. 과거 날짜도 DateOutOfRange 다(계약 Q.2)."""
    raw = (value or "").strip()
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise InvalidDate(f"날짜 형식이 올바르지 않습니다: {raw!r}") from exc
    ahead = (parsed - now_kst().date()).days
    if ahead < 0 or ahead > MAX_DAYS_AHEAD:
        raise DateOutOfRange(f"조회 가능 범위(오늘~+{MAX_DAYS_AHEAD}일) 밖: {raw}")
    return parsed


def _region_name(region_code: str) -> str | None:
    tr = get_tourapi_region(region_code)
    if tr:
        return tr.region_name
    return next((r.label for r in REGIONS if r.region_id == region_code), None)


def _area_cd(region_code: str) -> str | None:
    return next((r.area_cd for r in REGIONS if r.region_id == region_code), None)


# ---------- 날씨 ----------

async def _weather_for(region_code: str, target: date, ahead: int) -> OutlookWeather:
    if ahead > FORECAST_MAX_DAYS_AHEAD:
        return OutlookWeather(available=False, basis="none", notice=NOTICE_WEATHER_OUT_OF_RANGE)

    course_ids = REGION_COURSE_IDS.get(region_code) or []
    if not course_ids:
        return OutlookWeather(available=False, basis="none", notice=NOTICE_WEATHER_NO_COURSE)

    date_iso = target.isoformat()
    # 원천은 HOUR(리드타임) 주변 시간 윈도우를 돌려준다 → 목표일에 맞춘 리드타임으로 먼저
    # 시도하고, 비면 상한(72h) 윈도우로 한 번 더 본다(실측: d=3 은 48/72 둘 다에서 잡힌다).
    primary = min(72, max(6, ahead * 24))
    hours = [primary] if primary == 72 else [primary, 72]

    failed = False
    # 후보를 다 돌면 (후보 × 리드타임 × 타임아웃)으로 응답이 길어진다 → 2곳까지만 시도한다.
    for cid in course_ids[:2]:
        for hour in hours:
            try:
                weather = await kma_weather_client.fetch_course_weather_for_date(
                    cid, date_iso, hour, timeout_sec=settings.weather_slow_timeout_sec,
                )
            except KmaWeatherError as exc:
                failed = True
                logger.info("outlook 날씨 실패 course=%s hour=%s: %s", cid, hour, exc)
                continue
            if weather is None or weather.pop is None:
                continue
            return OutlookWeather(
                available=True,
                basis="forecast",
                pop=weather.pop,
                temp_c=weather.temp_c,
                summary=_weather_summary(weather.pop, weather.temp_c),
                notice=None,
            )
    return OutlookWeather(
        available=False,
        basis="none",
        notice=NOTICE_WEATHER_UPSTREAM if failed else NOTICE_WEATHER_OUT_OF_RANGE,
    )


def _weather_summary(pop: int, temp_c: float | None) -> str:
    """서버 고정 템플릿 + 실측 수치. 근거(기상청 예보)를 문장 안에 드러낸다."""
    head = f"기상청 예보 기준 강수확률 {pop}%"
    if temp_c is not None:
        head += f", 기온 {temp_c}도"
    if pop < 30:
        return f"{head}예요. 야외 일정 잡기 좋아요."
    if pop < 60:
        return f"{head}예요. 우산을 챙기면 좋아요."
    return f"{head}예요. 실내 위주로 계획해 보세요."


# ---------- 혼잡도 ----------

async def _last_year_congestion(region_code: str, target: date) -> tuple[float, str] | None:
    """작년 같은 날짜 ±3일 **실측** 평균 — 원천 미확보로 항상 None.

    2026-07-31 실호출 확인(backend-engineer):
      - KTO tatsCnctrRatedList 는 **미래 30일치 예측만** 준다. baseYmd/startYmd/endYmd 를 주면
        INVALID_REQUEST_PARAMETER_ERROR 로 거절돼 과거 날짜 조회 자체가 불가능하다.
      - 한국관광 데이터랩(metcoRegnVisitrDDList / locgoRegnVisitrDDList)은 같은 키로 403.
    → 과거 실측을 만들어낼 방법이 없으므로 basis="last_year" 를 **절대 반환하지 않는다**.
      (숫자를 지어내느니 available=false 로 두는 게 계약이다. 원천이 열리면 이 함수만 채우면
       상위 로직·응답 스키마는 그대로 동작한다.)
    """
    return None


async def _congestion_for(
    region_code: str, target: date, congestion_repo: CongestionRepository
) -> OutlookCongestion:
    area_cd = _area_cd(region_code)
    if not area_cd:
        return OutlookCongestion(available=False, basis="none", notice=NOTICE_CONGESTION_UPSTREAM)

    date_iso = target.isoformat()
    try:
        result = await congestion_repo.get_forecast(area_cd, region_code)
    except Exception as exc:  # noqa: BLE001 — 원천 실패는 화면을 막지 않는다
        logger.info("outlook 혼잡도 조회 실패 region=%s: %s", region_code, exc)
        return OutlookCongestion(available=False, basis="none", notice=NOTICE_CONGESTION_UPSTREAM)

    rates = [p.rate for s in result.spots for p in s.points if p.date == date_iso]
    if rates:
        index = round(sum(rates) / len(rates))
        level = classify_level(float(index))
        return OutlookCongestion(
            available=True,
            basis="forecast",
            level=level,
            index=index,
            summary=_congestion_summary(level, index, len(rates)),
            notice=None,
        )

    # 예측 커버 밖 → 작년 실측 폴백(현재 원천 없음)
    last_year = await _last_year_congestion(region_code, target)
    if last_year is not None:
        rate, _basis_note = last_year
        index = round(rate)
        level = classify_level(float(index))
        return OutlookCongestion(
            available=True,
            basis="last_year",
            level=level,
            index=index,
            summary=f"작년 같은 시기엔 {_level_word(level)} 편이었어요(작년 실측 {index}).",
        )

    return OutlookCongestion(
        available=False, basis="none", notice=NOTICE_CONGESTION_OUT_OF_RANGE,
    )


def _level_word(level: str) -> str:
    return {"low": "한산한", "mid": "보통인", "high": "붐비는"}.get(level, "알 수 없는")


def _congestion_summary(level: str, index: int, spot_count: int) -> str:
    head = {
        "low": "이 날은 비교적 한산할 것으로 예측돼요",
        "mid": "이 날은 보통 수준으로 예측돼요",
        "high": "이 날은 붐빌 것으로 예측돼요",
    }.get(level, "이 날 혼잡도는 판단하기 어려워요")
    return f"{head}(관광지 {spot_count}곳 평균 예측 집중률 {index})."


# ---------- 조립 ----------

async def build_outlook(
    region_code: str,
    date_str: str,
    congestion_repo: CongestionRepository,
    cache: Cache,
) -> OutlookResponse:
    """오늘~+180일 사이 특정 출발일의 날씨·혼잡도 전망. 날짜 검증 실패는 예외로 던진다."""
    target = parse_date(date_str)          # InvalidDate / DateOutOfRange
    ahead = (target - now_kst().date()).days

    key = f"outlook:{region_code}:{target.isoformat()}"
    cached: OutlookResponse | None = await cache.get(key)
    if cached is not None:
        return cached

    # 날씨·혼잡도는 서로 다른 원천이라 동시에 부른다. 날씨는 원천이 늘어질 수 있어 예산으로
    # 감싸고(초과 시 그 축만 미제공), 혼잡도는 내부에서 이미 예외를 흡수한다.
    weather_task = asyncio.wait_for(
        _weather_for(region_code, target, ahead),
        timeout=settings.weather_board_block_budget_sec,
    )
    weather_res, congestion = await asyncio.gather(
        weather_task,
        _congestion_for(region_code, target, congestion_repo),
        return_exceptions=True,
    )
    if isinstance(weather_res, BaseException):
        logger.info("outlook 날씨 예산 초과/실패 region=%s: %r", region_code, weather_res)
        weather = OutlookWeather(available=False, basis="none", notice=NOTICE_WEATHER_UPSTREAM)
    else:
        weather = weather_res
    if isinstance(congestion, BaseException):  # 방어적: _congestion_for 는 예외를 흡수한다
        logger.warning("outlook 혼잡도 예외 region=%s: %r", region_code, congestion)
        congestion = OutlookCongestion(
            available=False, basis="none", notice=NOTICE_CONGESTION_UPSTREAM,
        )

    response = OutlookResponse(
        region=RecommendRegion(region_code=region_code, region_name=_region_name(region_code)),
        date=target.isoformat(),
        days_ahead=ahead,
        weather=weather,
        congestion=congestion,
        meta=OutlookMeta(notice=NOTICE_META),
    )
    # 둘 다 원천 실패면 캐시하지 않는다(6시간 동안 빈 응답이 고정되는 것을 막는다).
    if weather.available or congestion.available:
        await cache.set(key, response, OUTLOOK_CACHE_TTL_SEC)
    return response
