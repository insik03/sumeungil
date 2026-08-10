"""WeatherProvider (부록 F.4-5) — 지역 단위 날씨 스냅샷 제공, graceful degradation.

get_region_forecast(region_code) -> WeatherSnapshot | None
  - None 반환 = 데이터 없음 → recommend 응답 provider_status="unavailable", rerank 무개입.

구현체:
  - NullWeatherProvider: 항상 None. 전 구간 graceful("날씨 정보 준비중"). 완전 무해한 기본값.
  - KmaCourseWeatherProvider: 기상청 D18(관광코스별 상세날씨) 실호출. region_code→대표 COURSE_ID
    핀 매핑(kma_weather_client.REGION_COURSE_IDS)으로 근시점 POP 확보. 실호출로 4개 데모 지역
    전부 매핑 확인함. 매핑/호출 실패 시 None → 자동 graceful(날씨 없다고 목록/화면이 죽지 않음).

배선(deps.get_weather_provider): settings.weather_provider 로 선택(기본 "kma", 실패 시 자동 None 폴백).
날씨값(POP)은 지어내지 않는다 — 실호출 실패/미매핑이면 None 을 정직하게 반환한다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from ..clients import kma_weather_client
from ..clients.kma_weather_client import KmaWeatherError

logger = logging.getLogger("sumeungil.services.weather")


@dataclass(frozen=True)
class WeatherSnapshot:
    """지역 단위 날씨 스냅샷. precip_probability(POP)만 rerank 에 쓰인다(F.4-4)."""

    region_code: str
    precip_probability: int | None  # POP 0~100. None 이면 밴드 산정 불가
    source: str                      # 데이터 출처 식별자(진단용)


class WeatherProvider:
    """날씨 데이터 소스 추상화(F.4-5). 상용 시 격자 단기예보 구현체로 교체(계약 불변)."""

    async def get_region_forecast(self, region_code: str) -> WeatherSnapshot | None:  # noqa: D401
        raise NotImplementedError


class NullWeatherProvider(WeatherProvider):
    """항상 None — graceful 기본값. 날씨 미확보 상태를 정직하게 표기하게 한다."""

    async def get_region_forecast(self, region_code: str) -> WeatherSnapshot | None:
        return None


class KmaCourseWeatherProvider(WeatherProvider):
    """기상청 D18 실호출 구현체. region_code→대표 COURSE_ID, 근시점 POP. TTL 캐시로 재호출 억제."""

    def __init__(self, ttl_sec: int = 1800) -> None:
        self._ttl = ttl_sec
        self._cache: dict[str, tuple[float, WeatherSnapshot | None]] = {}

    async def get_region_forecast(self, region_code: str) -> WeatherSnapshot | None:
        region_code = (region_code or "").strip()
        now = time.monotonic()
        hit = self._cache.get(region_code)
        if hit and (now - hit[0]) < self._ttl:
            return hit[1]

        snapshot = await self._fetch(region_code)
        self._cache[region_code] = (now, snapshot)
        return snapshot

    async def _fetch(self, region_code: str) -> WeatherSnapshot | None:
        course_ids = kma_weather_client.REGION_COURSE_IDS.get(region_code)
        if not course_ids:
            # 데모 밖 지역 → 대표 코스 미핀 → 정직하게 데이터 없음
            logger.info("D18 대표 코스 미매핑 region=%s → unavailable", region_code)
            return None
        for cid in course_ids:
            try:
                pop = await kma_weather_client.fetch_course_pop(cid)
            except KmaWeatherError as exc:
                logger.info("D18 코스 %s 실패, 다음 후보 시도: %s", cid, exc)
                continue
            if pop is not None:
                return WeatherSnapshot(
                    region_code=region_code,
                    precip_probability=pop,
                    source=f"kma_d18_course_{cid}",
                )
        return None


def create_weather_provider(provider_name: str, ttl_sec: int) -> WeatherProvider:
    name = (provider_name or "").strip().lower()
    if name == "kma":
        return KmaCourseWeatherProvider(ttl_sec=ttl_sec)
    # "null" 또는 알 수 없는 값 → 안전한 Null(무해 graceful)
    if name and name != "null":
        logger.warning("알 수 없는 WEATHER_PROVIDER=%r → NullWeatherProvider 로 폴백", provider_name)
    return NullWeatherProvider()
