"""축제 상세 조회 서비스 (부록 P.2, 2026-07-31 신설) — 축제 카드 클릭 → 상세 화면.

GET /api/v1/festivals/{festival_id} 소관. **새 원천을 하나도 추가하지 않는다** — 이미 있는
세 가지를 조립할 뿐이다:

  1) 축제 본문     : festival_service 전국 스윕 캐시(6h)에서 id 로 조회. **원천 재호출 금지.**
  2) 사진(images)  : TourAPI 출신(id < 900,000,000) 축제만 detailImage2(7일 캐시, photo_service).
                     표준데이터 출신(synthetic id)은 원천에 이미지 필드 자체가 없다 → 항상 [].
                     **다른 축제/장소 사진으로 채우지 않는다**(프론트 플레이스홀더가 정답).
  3) 타이밍/날씨    : timing 은 날짜 산술 + 서버 고정 템플릿(LLM·추측 없음),
                     weather 는 기존 weather_provider(POP 실측)만. 수치를 지어내지 않는다.

정직 원칙(이 모듈의 핵심):
  - timing.tip 은 **enum/날짜 계산으로만 결정되는 고정 문구**다. 축제명·주소 등 외부 문자열을
    문구에 섞지 않는다(인젝션 표면 0, 프론트는 텍스트 노드로 렌더).
  - weather 는 **예보 범위 안에 축제 기간이 걸릴 때만** available=true. 그 밖은 available=false +
    사유 notice. "아마 맑을 것" 같은 추정 문구는 만들지 않는다.
"""

from __future__ import annotations

import logging
import asyncio
from datetime import date

from ..ai.injection_guard import normalize_unicode
from ..cache.base import Cache
from ..config import settings
from ..repositories.summary_repo import SummaryRepository
from ..clients import tourapi_detail_client
from ..schemas.places import (
    Festival,
    FestivalDetailResponse,
    FestivalTiming,
    FestivalWeather,
    RecommendRegion,
    SpotImage,
)
from ..services import festival_service, live_weather_service, photo_service
from ..services.rerank_service import THRESHOLD_ADVISE, THRESHOLD_SOFT
from ..services.weather_provider import WeatherProvider
from ..util.images import kto_credit
from ..util.text import strip_html_to_plain, truncate_text

logger = logging.getLogger("sumeungil.services.festival_detail")

# 슬라이드 한 벌 상한(대표사진 포함) — 스팟 상세와 같은 값.
IMAGES_MAX = photo_service.DETAIL_IMAGES_MAX

# 장기(상설성) 축제 판정 기준 — 총 기간이 이 일수 이상이면 "장기 진행 중" 문구를 쓴다.
LONG_RUN_DAYS = 30
# "곧 시작" 으로 볼 D-day 상한.
SOON_START_DAYS = 7
# "곧 끝나요" 로 볼 잔여일 상한.
SOON_END_DAYS = 3

# 날씨 예보 범위(오늘 포함 일수). weather_provider(기상청 D18)가 주는 값은 **근시점 1블록의
# 강수확률(POP)** 하나뿐이라, 정직하게 "오늘"까지만 유효하다고 본다. 날짜별 예보를 주는
# 프로바이더로 교체하면 이 상수만 늘리면 된다(응답 계약은 그대로).
WEATHER_WINDOW_DAYS = 1

_NOTICE_OUT_OF_WINDOW = "축제 기간이 예보 범위 밖이에요"
_NOTICE_NO_REGION = "축제 지역을 확인할 수 없어 날씨를 제공하지 않아요"
_NOTICE_NO_DATA = "이 지역 날씨 정보를 불러오지 못했어요"


class FestivalNotFound(Exception):
    """전국 캐시에 없는 festival_id → API 레이어가 404 FESTIVAL_NOT_FOUND."""


# ---------- timing (룰 기반 고정 문구) ----------

def _parse(d: str) -> date | None:
    try:
        return date.fromisoformat(d)
    except (TypeError, ValueError):
        return None


def build_timing(festival: Festival, today: date) -> FestivalTiming:
    """오늘 기준 진행상태 + D-day/잔여일 + 고정 템플릿 tip.

    날짜 파싱이 불가능한 이례적 레코드(스윕 단계에서 걸러지지만 방어)는 ended 로 두지 않고
    status=upcoming 등으로 추측하지 않는다 — d_day/days_left 를 null 로 두고 중립 문구를 준다.
    """
    start, end = _parse(festival.start_date), _parse(festival.end_date)
    if start is None or end is None:
        return FestivalTiming(status="upcoming", tip="축제 일정을 확인해 주세요")

    if today < start:
        d_day = (start - today).days
        if d_day == 1:
            tip = "내일 시작해요"
        elif d_day <= SOON_START_DAYS:
            tip = f"D-{d_day}, 곧 시작해요"
        else:
            tip = f"D-{d_day}, 시작까지 여유가 있어요"
        return FestivalTiming(status="upcoming", d_day=d_day, tip=tip)

    if today > end:
        return FestivalTiming(status="ended", tip="이미 종료된 축제예요")

    days_left = (end - today).days + 1  # 오늘 포함
    duration = (end - start).days + 1
    if today == start and days_left == 1:
        tip = "오늘 하루만 열리는 축제예요"
    elif today == start:
        tip = "오늘 시작한 축제예요"
    elif days_left == 1:
        tip = "오늘이 마지막 날이에요"
    elif end.weekday() >= 5 and end <= date.fromordinal(
        today.toordinal() + (6 - today.weekday())
    ):
        # QA Minor-1(2026-07-31): "일주일 안" 조건은 **다음 주** 토요일 종료까지 이번 주말로
        # 오표기했다(실측: 일요일 기준 6일 뒤 토요일 종료). 종료일이 토/일이면서 **이번 주
        # 일요일 이내**일 때만 이 문구를 쓴다. (오늘이 일요일이면 이번 주 일요일 = 오늘이라
        # days_left==1 분기가 먼저 잡는다 — 이 분기는 사실상 이번 주 토/일 종료 전용이 된다.)
        tip = "이번 주말이 마지막이에요"
    elif days_left <= SOON_END_DAYS:
        tip = f"{days_left}일 뒤 끝나요, 서둘러 보세요"
    elif duration >= LONG_RUN_DAYS:
        tip = "장기 진행 중인 축제예요"
    else:
        tip = f"{days_left}일 남았어요"
    return FestivalTiming(status="ongoing", days_left=days_left, tip=tip)


# ---------- weather (실측 POP 만) ----------

def _in_forecast_window(festival: Festival, today: date) -> bool:
    """예보 범위(오늘 ~ 오늘+WEATHER_WINDOW_DAYS-1)와 축제 기간이 겹치는가."""
    start, end = _parse(festival.start_date), _parse(festival.end_date)
    if start is None or end is None:
        return False
    window_end = date.fromordinal(today.toordinal() + WEATHER_WINDOW_DAYS - 1)
    return start <= window_end and end >= today


def _summary(pop: int) -> str:
    """실측 강수확률만 담은 정형 문구(밴드 임계는 rerank 와 동일 값 재사용)."""
    if pop >= THRESHOLD_ADVISE:
        return f"오늘 강수확률 {pop}% — 우산과 실내 프로그램을 함께 준비하세요"
    if pop >= THRESHOLD_SOFT:
        return f"오늘 강수확률 {pop}% — 우산을 챙기면 좋아요"
    return f"오늘 강수확률 {pop}% — 야외 관람하기 좋아요"


async def build_weather(
    festival: Festival,
    region_code: str | None,
    today: date,
    weather_provider: WeatherProvider | None,
) -> FestivalWeather:
    """축제 지역의 근시점 강수확률. 못 얻으면 available=false + 사유 notice(지어내지 않음)."""
    if not region_code:
        return FestivalWeather(available=False, notice=_NOTICE_NO_REGION)
    if not _in_forecast_window(festival, today):
        return FestivalWeather(available=False, notice=_NOTICE_OUT_OF_WINDOW)
    if weather_provider is None:
        return FestivalWeather(available=False, notice=_NOTICE_NO_DATA)

    try:
        snapshot = await weather_provider.get_region_forecast(region_code)
    except Exception as exc:  # noqa: BLE001 — 날씨 실패가 상세 조회를 막지 않는다
        logger.info("축제 날씨 스킵(원천 실패) region=%s: %s", region_code, exc)
        return FestivalWeather(available=False, notice=_NOTICE_NO_DATA)

    if snapshot is None or snapshot.precip_probability is None:
        return FestivalWeather(available=False, notice=_NOTICE_NO_DATA)
    return FestivalWeather(available=True, summary=_summary(snapshot.precip_probability))


# ---------- images ----------

async def build_images(festival: Festival, cache: Cache) -> list[SpotImage]:
    """대표사진(첫 번째) + detailImage2 추가사진. 표준데이터 출신은 항상 [].

    표준데이터(id >= 900,000,000)는 TourAPI contentid 가 아니라 CRC32 합성 id 라서 그 id 로
    detailImage2 를 부르면 **엉뚱한 스팟 사진**이 오거나 빈 결과가 온다 → 아예 호출하지 않는다.
    """
    if festival_service.is_synthetic_id(festival.id):
        return []
    extra = await photo_service.detail_image_urls(festival.id, cache)
    return [
        SpotImage(url=url, credit=credit)
        for url, credit in photo_service.build_image_list(
            festival.image_url, kto_credit() if festival.image_url else None,
            extra, IMAGES_MAX,
        )
    ]


# ---------- description (축제 소개) ----------

# 상세 화면 본문 상한. 넘으면 문장 경계에서 끊는다(util.text.truncate_text).
DESCRIPTION_MAX_CHARS = 1200
# TourAPI overview 는 거의 불변 → images 와 같은 7일 캐시. 키는 분리한다(사진과 수명·실패가 별개).
DESCRIPTION_TTL_SEC = 7 * 24 * 60 * 60
# 429/타임아웃을 7일간 "설명 없음"으로 굳히지 않되 폭주도 막는 짧은 음성 캐시.
DESCRIPTION_FAIL_TTL_SEC = 10 * 60


def clean_description(raw: str | None) -> str | None:
    """원천 설명문 → 표시용 평문. 없거나 정제 후 비면 None(지어내지 않음).

    유니코드 정규화(NFKC + 제로폭 제거) → HTML 엔티티 복원·태그 제거·공백 정규화 →
    1200자 절단(가능하면 문장 경계). 스팟 개요(course blurb)와 **같은 util.text 규칙**을 쓴다.
    """
    if not raw or not isinstance(raw, str):
        return None
    text = strip_html_to_plain(normalize_unicode(raw))
    if not text:
        return None
    return truncate_text(text, DESCRIPTION_MAX_CHARS) or None


async def _tour_description(content_id: int, cache: Cache) -> str | None:
    """TourAPI 축제의 detailCommon2 overview. 실패/빈값 → None.

    - 캐시 `festival_desc:{id}` 7일(빈 결과도 캐시 — 없는 축제를 매번 다시 묻지 않는다).
    - 429/타임아웃은 **10분만** 음성 캐시해 다음에 재시도(사진과 동일 정책).
    - 어떤 예외도 밖으로 던지지 않는다(소개글 때문에 상세가 깨지지 않게).
    """
    key = f"festival_desc:{content_id}"
    cached = await cache.get(key)
    if cached is not None:
        return cached.get("description")

    try:
        item = await tourapi_detail_client.fetch_detail_common(content_id)
    except Exception as exc:  # noqa: BLE001 — 429 포함
        logger.info("축제 소개 스킵(원천 실패) id=%s: %s", content_id, exc)
        await cache.set(key, {"description": None}, DESCRIPTION_FAIL_TTL_SEC)
        return None

    description = clean_description((item or {}).get("overview"))
    await cache.set(key, {"description": description}, DESCRIPTION_TTL_SEC)
    return description


async def build_description(entry_description: str | None, festival: Festival, cache: Cache) -> str | None:
    """축제 소개 1건. 소스별 규칙(부록 P.2.7).

    - 표준데이터(id >= 900M): 전국 스윕 캐시가 보존한 원천 `fstvlCo`(축제내용)를 정제해서 쓴다.
      원천에 그 필드가 없으면 null — TourAPI 를 대신 부르지 않는다(합성 id 라 엉뚱한 스팟이 나온다).
    - TourAPI(id < 900M): detailCommon2 overview(7일 캐시). 실패/빈값이면 null.
    """
    if festival_service.is_synthetic_id(festival.id):
        return clean_description(entry_description)
    return await _tour_description(festival.id, cache)


# ---------- 조립 ----------

async def build_festival_detail(
    festival_id: int,
    cache: Cache,
    weather_provider: WeatherProvider | None = None,
    today: date | None = None,
    spot_repo=None,
) -> FestivalDetailResponse:
    """festival_id 로 축제 상세를 조립. 전국 캐시에 없으면 FestivalNotFound."""
    as_of = today or date.today()

    entry = await festival_service.find_entry(festival_id, cache)
    if entry is None:
        raise FestivalNotFound(f"festival_id={festival_id}")

    festival = entry.festival
    # 캐시에는 스윕 시점(=실제 오늘) 기준 ongoing 이 들어 있다 → 조회 기준일로 다시 계산.
    ongoing = festival.start_date <= as_of.isoformat() <= festival.end_date
    if festival.ongoing != ongoing:
        festival = festival.model_copy(update={"ongoing": ongoing})

    region: RecommendRegion | None = None
    if entry.region_code:
        region = RecommendRegion(
            region_code=entry.region_code,
            region_name=festival_service._region_name(entry.region_code),
        )

    images = await build_images(festival, cache)
    timing = build_timing(festival, as_of)
    weather = await build_weather(festival, entry.region_code, as_of, weather_provider)
    description = await build_description(entry.description, festival, cache)

    summary, provider = await asyncio.to_thread(
        SummaryRepository(settings.summary_store_dir, settings.ollama_model).display,
        "festival", festival.id, description,
    )
    # 2026-09-20 — 축제 지역의 "지금 날씨". 위 weather 와 다른 질문이다:
    #   weather(D18)      = "축제 **기간에** 비가 올 확률", 시도 해상도, 예보 범위 밖이면 불가
    #   live_weather(격자) = "지금 이 지역에 비가 오는가", 5km 격자, 기간과 무관하게 항상 가능
    # 축제 원천은 좌표를 안 주고 주소만 준다 → 그 시군구 스팟들의 좌표 중앙값을 지역 대표로 쓴다.
    live_weather = None
    if entry.region_code and spot_repo is not None:
        point = live_weather_service.region_centroid(entry.region_code, spot_repo)
        if point is not None:
            live_weather = await live_weather_service.for_point(point[0], point[1], cache)

    return FestivalDetailResponse(
        ai_summary=summary,
        ai_provider=provider,
        festival=festival,
        region=region,
        images=images,
        timing=timing,
        weather=weather,
        live_weather=live_weather,
        description=description,
    )
