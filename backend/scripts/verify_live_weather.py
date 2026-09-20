# -*- coding: utf-8 -*-
"""지점 단위 "지금 날씨" 검증 (2026-09-20 대표 지시 "시 별로 지금 비가 오는지").

**원천을 부르지 않는다.** 격자 변환은 순수 함수라 그대로 검증하고, 서비스 계층은 클라이언트를
스텁으로 갈아 끼워 캐시 동작만 본다(기상청 쿼터 0, 네트워크 0 — CI 에서 결정적으로 돈다).

검증 항목
  (a) 위경도 → 기상청 격자 변환이 공개 검증값과 일치한다. 이게 틀리면 **다른 동네 날씨**를
      보여주게 되는데 화면상으로는 멀쩡해 보여서 못 잡는다.
  (b) 같은 5km 격자 안의 좌표들은 원천 호출을 **1건만** 쓴다(캐시 키가 좌표가 아니라 격자다).
  (c) 다른 격자는 따로 부른다.
  (d) 원천 실패는 None 으로 강등되고, 실패도 짧게 캐시해 매 요청이 타임아웃을 물지 않는다.
  (e) 좌표가 없으면 아예 부르지 않는다.
  (f) 시군구 대표 좌표는 그 지역 스팟 좌표의 중앙값이다(이상치에 끌려가지 않는다).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PUBLIC_DATA_API_KEY", "stub")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.cache.memory import MemoryCache  # noqa: E402
from app.clients import kma_ncst_client  # noqa: E402
from app.clients.kma_ncst_client import LiveWeather as ClientSnapshot  # noqa: E402
from app.clients.kma_ncst_client import to_grid  # noqa: E402
from app.services import live_weather_service  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail and not ok else ""))


def section(title: str) -> None:
    print(f"\n== {title} ==")


async def main() -> None:
    section("(a) 위경도 → 기상청 격자 변환")
    # 기상청이 배포한 지점 목록의 공개 검증값. 변환식을 건드리면 여기서 먼저 깨진다.
    for name, lat, lng, nx, ny in [
        ("서울시청", 37.5665, 126.9780, 60, 127),
        ("부산 해운대구청", 35.1631, 129.1635, 99, 75),
        ("제주시청", 33.4996, 126.5312, 53, 38),
        ("강릉시청", 37.7519, 128.8761, 92, 132),
    ]:
        g = to_grid(lat, lng)
        check(f"{name} → nx={nx}, ny={ny}", (g.nx, g.ny) == (nx, ny), f"got=({g.nx},{g.ny})")

    section("(b)(c) 캐시 키는 좌표가 아니라 격자다")
    calls: list[tuple[float, float]] = []

    async def _stub(lat, lng, **_kw):
        calls.append((lat, lng))
        return ClientSnapshot(
            nx=0, ny=0, condition="맑음", precipitation=False,
            temperature_c=21.5, humidity_pct=40, rain_1h_mm=0.0,
            observed_at="2026-09-20 15:00",
        )

    original = kma_ncst_client.fetch_live_weather
    kma_ncst_client.fetch_live_weather = _stub
    try:
        cache = MemoryCache()
        # 서울시청과 1km 남짓 떨어진 좌표 — 같은 격자여야 한다.
        a = await live_weather_service.for_point(37.5665, 126.9780, cache)
        b = await live_weather_service.for_point(37.5700, 126.9800, cache)
        check("첫 조회가 값을 준다", a is not None and a.condition == "맑음")
        check("같은 격자 두 좌표 → 원천 호출 1회", len(calls) == 1, f"calls={len(calls)}")
        check("두 번째도 같은 값을 받는다", b is not None and b.temperature_c == 21.5)
        check("같은 격자 판정이 실제로 맞다",
              to_grid(37.5665, 126.9780) == to_grid(37.5700, 126.9800))

        await live_weather_service.for_point(33.4996, 126.5312, cache)  # 제주 — 다른 격자
        check("다른 격자는 따로 부른다", len(calls) == 2, f"calls={len(calls)}")

        section("(e) 좌표가 없으면 아예 부르지 않는다")
        before = len(calls)
        check("lat=None → None", await live_weather_service.for_point(None, 126.9, cache) is None)
        check("lng=None → None", await live_weather_service.for_point(37.5, None, cache) is None)
        check("원천 호출 증가 없음", len(calls) == before, f"calls={len(calls)}")

        section("(d) 원천 실패는 None 으로 강등 + 실패도 캐시")
        fail_calls: list[int] = []

        async def _fail(lat, lng, **_kw):
            fail_calls.append(1)
            return None

        kma_ncst_client.fetch_live_weather = _fail
        cache2 = MemoryCache()
        r1 = await live_weather_service.for_point(35.1631, 129.1635, cache2)
        r2 = await live_weather_service.for_point(35.1631, 129.1635, cache2)
        check("실패 → None", r1 is None and r2 is None)
        check("실패도 캐시돼 재호출하지 않는다", len(fail_calls) == 1, f"calls={len(fail_calls)}")
    finally:
        kma_ncst_client.fetch_live_weather = original

    section("(f) 시군구 대표 좌표 = 스팟 좌표 중앙값")

    class _Spot:
        def __init__(self, lat, lng):
            self.lat, self.lng = lat, lng

    class _Repo:
        def by_region(self, region_code, category=None):
            # 마지막 한 곳이 멀리 떨어진 이상치 — 평균이면 끌려가고 중앙값이면 안 끌려간다.
            return [_Spot(35.15, 129.15), _Spot(35.16, 129.16), _Spot(35.17, 129.17),
                    _Spot(38.90, 125.00)]

    point = live_weather_service.region_centroid("26350", _Repo())
    check("중앙값을 쓴다(이상치 미반영)",
          point is not None and abs(point[0] - 35.165) < 0.001, str(point))

    class _EmptyRepo(_Repo):
        def by_region(self, region_code, category=None):
            return []

    check("스팟이 없으면 None", live_weather_service.region_centroid("99999", _EmptyRepo()) is None)

    class _BrokenRepo(_Repo):
        def by_region(self, region_code, category=None):
            raise RuntimeError("store down")

    check("스토어 실패해도 예외를 던지지 않는다",
          live_weather_service.region_centroid("26350", _BrokenRepo()) is None)

    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n총 {len(RESULTS)}건 중 실패 {len(failed)}건")
    if failed:
        for label in failed:
            print(f"  FAIL: {label}")
        sys.exit(1)
    print("모두 통과")


if __name__ == "__main__":
    asyncio.run(main())
