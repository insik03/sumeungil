"""부록 Q.1 — 전국 9권역 날씨 보드.

"오늘 어느 지역이 나들이 좋은가"를 한 화면에 보여주는 보드. 권역마다 대표 관광코스(D18)를
1회 호출해 강수확률(POP)·기온을 얻고, **서버가 판정**해 verdict/tip 을 고정 문구로 내린다
(프론트는 재판정하지 않는다 — 판정 단일 소유, congestion_service 와 같은 원칙).

예산 고정: 9권역 = 원천 9회 / 30분. 보드 전체를 30분 캐시하고, 권역 하나가 실패해도
그 권역만 available=false 로 두고 나머지는 정상 표시한다(부분 실패 허용).
"""

from __future__ import annotations

import asyncio
import logging

from ..cache.base import Cache
from ..clients import kma_weather_client
from ..clients.kma_weather_client import KmaWeatherError
from ..config import settings
from ..regions.nationwide import REGION_BLOCKS, RegionBlock
from ..schemas.outlook import (
    NationwideRegionWeather,
    NationwideWeatherResponse,
    WeatherVerdict,
)
from ..util.time import now_kst
from .rerank_service import THRESHOLD_ADVISE, THRESHOLD_SOFT

logger = logging.getLogger("sumeungil.services.nationwide_weather")

# verdict 임계는 rerank(F.4-4)의 POP 밴드를 그대로 재사용한다 — 같은 서비스에서 같은 비 예보에
# 다른 판정이 나오면 안 된다(임계 재정의 금지).
#   POP < 30       → good          (clear)
#   30 ≤ POP < 60  → fair          (soft)
#   POP ≥ 60       → poor          (advise_indoor)
_TIPS: dict[str, str] = {
    "good": "야외 나들이 좋아요",
    "fair": "우산을 챙기면 좋아요",
    "poor": "실내 위주로 계획해 보세요",
}

NOTICE_UNAVAILABLE = "이 권역 날씨를 불러오지 못했어요."

# 권역당 시도할 대표 코스 수(응답 시간 상한 관리).
MAX_COURSE_ATTEMPTS = 2


def verdict_for(pop: int) -> WeatherVerdict:
    if pop < THRESHOLD_SOFT:
        return "good"
    if pop < THRESHOLD_ADVISE:
        return "fair"
    return "poor"


def tip_for(verdict: str) -> str:
    return _TIPS[verdict]


async def _one_block(block: RegionBlock) -> NationwideRegionWeather:
    """권역 1개 조회. 어떤 실패도 available=false 로 흡수한다(보드 전체를 죽이지 않는다)."""
    base = NationwideRegionWeather(
        key=block.key, label=block.label, region_code=block.region_code,
    )
    # 후보를 다 돌면 최악의 경우 (후보 수 × 타임아웃)이라 보드가 느려진다 → 2곳까지만 시도하고,
    # 그래도 안 되면 그 권역만 unavailable(나머지 권역은 이미 병렬로 끝나 있다).
    for cid in block.course_ids[:MAX_COURSE_ATTEMPTS]:
        try:
            weather = await kma_weather_client.fetch_course_weather(
                cid, timeout_sec=settings.weather_slow_timeout_sec,
            )
        except KmaWeatherError as exc:
            logger.info("D18 코스 %s 실패(권역 %s), 다음 후보: %s", cid, block.key, exc)
            continue
        except Exception as exc:  # noqa: BLE001 — 예상 밖 예외도 보드를 막지 않는다
            logger.warning("D18 코스 %s 예외(권역 %s): %s", cid, block.key, exc)
            continue
        if weather is None or weather.pop is None:
            continue
        verdict = verdict_for(weather.pop)
        return NationwideRegionWeather(
            key=block.key,
            label=block.label,
            region_code=block.region_code,
            available=True,
            pop=weather.pop,
            temp_c=weather.temp_c,   # 원천에 기온이 없으면 null 그대로(지어내지 않음)
            verdict=verdict,
            tip=tip_for(verdict),
            notice=None,
        )
    base.notice = NOTICE_UNAVAILABLE
    return base


async def build_nationwide_weather(cache: Cache) -> NationwideWeatherResponse:
    as_of = now_kst().date().isoformat()
    key = f"weather_nationwide:{as_of}"

    cached: NationwideWeatherResponse | None = await cache.get(key)
    if cached is not None:
        return cached

    # 권역별 예산(기본 20초)으로 감싼다 — 한 권역이 늘어져도 보드 전체가 그만큼 늦어지지 않는다.
    budget = settings.weather_board_block_budget_sec
    results = await asyncio.gather(
        *[asyncio.wait_for(_one_block(b), timeout=budget) for b in REGION_BLOCKS],
        return_exceptions=True,
    )
    regions: list[NationwideRegionWeather] = []
    for block, res in zip(REGION_BLOCKS, results):
        if isinstance(res, BaseException):
            logger.warning("권역 %s 조회 예외: %s", block.key, res)
            regions.append(
                NationwideRegionWeather(
                    key=block.key, label=block.label, region_code=block.region_code,
                    notice=NOTICE_UNAVAILABLE,
                )
            )
        else:
            regions.append(res)

    response = NationwideWeatherResponse(as_of=as_of, regions=regions)
    # 전부 실패한 보드는 캐시하지 않는다 — 30분간 빈 보드가 고정되면 복구가 늦어진다.
    if any(r.available for r in regions):
        await cache.set(key, response, settings.weather_cache_ttl_sec)
    return response
