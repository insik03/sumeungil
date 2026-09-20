# -*- coding: utf-8 -*-
"""지점 단위 "지금 날씨" 서비스 (2026-09-20) — 스팟 상세·축제 상세 공용.

`clients/kma_ncst_client` 실호출을 **격자 단위로 캐시**해 감싼다. 캐시 키가 좌표가 아니라
격자(nx, ny)인 것이 핵심이다 — 같은 5km 칸 안의 스팟 수십 곳이 원천 호출 1건을 나눠 쓴다
(해운대 스팟 87곳이 전부 같은 칸이다).

TTL 은 원천 발표 주기에 맞춘다: 초단기실황은 매시 정시 관측이 40분경 공개되므로 30분을 넘겨
캐시할 이유가 없고, 그보다 짧게 잡으면 같은 값을 다시 받아오느라 쿼터만 쓴다.

실패는 전부 None 이다. 날씨가 없다고 상세 화면이 죽지 않는다(호출부는 필드를 null 로 둔다).
"""

from __future__ import annotations

import logging
import statistics

from ..cache.base import Cache
from ..clients import kma_ncst_client
from ..repositories.spot_repo import SpotRepository
from ..schemas.places import LiveWeather

logger = logging.getLogger("sumeungil.services.live_weather")

# 초단기실황 발표 주기(1시간)의 절반. 화면이 "몇 시 기준"을 함께 표기하므로 30분 지연은 정직하다.
CACHE_TTL_SEC = 30 * 60
# 원천 실패를 짧게 캐시해 장애 시 매 요청이 6초 타임아웃을 무는 걸 막는다.
FAIL_TTL_SEC = 3 * 60


def _key(nx: int, ny: int) -> str:
    return f"live_weather:v1:{nx}:{ny}"


async def for_point(lat: float | None, lng: float | None, cache: Cache) -> LiveWeather | None:
    """좌표의 "지금 날씨". 좌표가 없거나 원천이 실패하면 None."""
    if lat is None or lng is None:
        return None
    try:
        grid = kma_ncst_client.to_grid(float(lat), float(lng))
    except (TypeError, ValueError):
        return None

    key = _key(grid.nx, grid.ny)
    cached = await cache.get(key)
    if cached is not None:
        # 실패도 캐시한다(빈 dict). 그 경우 None 으로 되돌린다.
        return LiveWeather(**cached) if cached else None

    snapshot = await kma_ncst_client.fetch_live_weather(float(lat), float(lng))
    if snapshot is None:
        await cache.set(key, {}, FAIL_TTL_SEC)
        return None

    result = LiveWeather(
        condition=snapshot.condition,
        precipitation=snapshot.precipitation,
        temperature_c=snapshot.temperature_c,
        humidity_pct=snapshot.humidity_pct,
        rain_1h_mm=snapshot.rain_1h_mm,
        observed_at=snapshot.observed_at,
    )
    await cache.set(key, result.model_dump(), CACHE_TTL_SEC)
    return result


def region_centroid(region_code: str, spot_repo: SpotRepository) -> tuple[float, float] | None:
    """시군구 대표 좌표 = 그 지역 스팟들의 좌표 **중앙값**.

    축제는 원천이 좌표를 주지 않고 주소만 준다(festival_region_match 참고). 주소를 지오코딩하는
    새 원천을 붙이는 대신, 이미 있는 스팟 시드의 좌표로 그 시군구의 중심을 잡는다.
    평균이 아니라 중앙값인 이유는 섬·외곽 스팟 한두 곳이 중심을 끌고 가지 않게 하기 위해서다.
    5km 격자 기준이라 시군구 안에서의 오차는 대개 같은 칸 또는 이웃 칸에 머문다.
    """
    try:
        spots = spot_repo.by_region(region_code, None)
    except Exception:  # noqa: BLE001 — 날씨는 부가정보다. 스토어 조회 실패로 상세를 막지 않는다.
        return None
    lats = [s.lat for s in spots if s.lat is not None]
    lngs = [s.lng for s in spots if s.lng is not None]
    if not lats or not lngs:
        return None
    return statistics.median(lats), statistics.median(lngs)


__all__ = ("for_point", "region_centroid", "CACHE_TTL_SEC")
