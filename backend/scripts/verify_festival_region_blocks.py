# -*- coding: utf-8 -*-
"""축제 지역 필터 — 9권역(`region_block`) 묶음 검증 (2026-09-20 대표 지시).

축제 "지역 바로가기"가 시도 17칩에서 9권역 칩으로 바뀌면서, 서버가 권역에 속한 **시도 전체**를
훑어야 한다. 권역 대표 시군구 1곳으로 좁히면 "전남·광주"를 눌렀는데 여수 축제만 나온다.

**원천을 부르지 않는다.** 전국 스윕 캐시에 가짜 축제를 미리 넣어두고(같은 캐시 키) 메모리
필터만 확인한다 — TourAPI·표준데이터 호출 0.

검증 항목
  (a) 9권역이 17개 시도를 **빠짐없이, 겹치지 않게** 덮는다 — 한 곳이라도 빠지면 그 지역 축제는
      어떤 칩으로도 볼 수 없고, 겹치면 같은 축제가 두 권역에 뜬다.
  (b) region_block 은 그 권역의 모든 시도 축제를 준다(광역시 흡수 포함).
  (c) 좁은 지정 우선: region_code > area_cd > region_block.
  (d) 알 수 없는 key 는 400 (조용히 전국으로 떨어지지 않는다).
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PUBLIC_DATA_API_KEY", "stub")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient  # noqa: E402

from app.cache.memory import MemoryCache  # noqa: E402
from app.regions.nationwide import BLOCK_BY_KEY, REGION_BLOCKS  # noqa: E402
from app.regions.seed import REGIONS  # noqa: E402
from app.schemas.places import Festival  # noqa: E402
from app.services import festival_service  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail and not ok else ""))


def section(title: str) -> None:
    print(f"\n== {title} ==")


TODAY = date.today()
SOON = (TODAY + timedelta(days=3)).isoformat()
LATER = (TODAY + timedelta(days=20)).isoformat()


def _entry(fid: int, region_code: str):
    return festival_service._Entry(
        Festival(id=fid, title=f"축제{fid}", start_date=SOON, end_date=LATER),
        region_code,
        "stub",
    )


async def _seeded_cache(entries) -> MemoryCache:
    """실제 스윕 대신 전국 캐시를 직접 채운다 — _load_nationwide 가 그대로 읽어간다."""
    cache = MemoryCache()
    key = f"festivals:all:v4:{TODAY.isoformat()}"
    await cache.set(key, [e.to_dict() for e in entries], 3600)
    return cache


async def main() -> None:
    section("(a) 9권역이 17개 시도를 빠짐없이·겹치지 않게 덮는다")
    seen: dict[str, str] = {}
    dup: list[str] = []
    for b in REGION_BLOCKS:
        for ac in (b.area_cds or (b.area_cd,)):
            if ac in seen:
                dup.append(f"{ac}({seen[ac]}↔{b.key})")
            seen[ac] = b.key
    all_area_cds = {r.area_cd for r in REGIONS}
    missing = sorted(all_area_cds - set(seen))
    check("시도 중복 배정 없음", not dup, ", ".join(dup))
    check("어느 권역에도 없는 시도 없음", not missing, ", ".join(missing))
    check("9권역 고정", len(REGION_BLOCKS) == 9, str(len(REGION_BLOCKS)))

    section("(b) region_block 은 권역에 속한 시도 전체를 준다")
    # 경기·서울 권역 = 11(서울) + 41(경기) + 28(인천). 광역시 흡수가 실제로 동작하는지가 핵심.
    block = BLOCK_BY_KEY["gyeonggi"]
    entries = [
        _entry(1, "11110"),   # 서울 종로 — 이 권역
        _entry(2, "41111"),   # 경기 수원 — 이 권역
        _entry(3, "28185"),   # 인천 연수 — 이 권역(흡수된 광역시)
        _entry(4, "26350"),   # 부산 해운대 — 다른 권역
        _entry(5, "50110"),   # 제주 — 다른 권역
    ]
    cache = await _seeded_cache(entries)
    res = await festival_service.build_festivals_response(
        region_code=None, limit=200, cache=cache, region_block="gyeonggi"
    )
    got = sorted(f.id for f in res.festivals)
    check("경기·서울 권역 = 서울+경기+인천 3건", got == [1, 2, 3], f"got={got}")
    check("area_cds 가 실제로 3개 시도", set(block.area_cds) == {"11", "41", "28"}, str(block.area_cds))

    res = await festival_service.build_festivals_response(
        region_code=None, limit=200, cache=cache, region_block="gyeongnam"
    )
    got = sorted(f.id for f in res.festivals)
    check("경남·부산·울산 권역 = 부산 1건", got == [4], f"got={got}")

    # 전국(필터 없음)은 전부
    res = await festival_service.build_festivals_response(region_code=None, limit=200, cache=cache)
    check("전국은 5건 전부", len(res.festivals) == 5, str(len(res.festivals)))

    section("(c) 좁은 지정이 이긴다 — region_code > area_cd > region_block")
    res = await festival_service.build_festivals_response(
        region_code="11110", limit=200, cache=cache, area_cd="26", region_block="jeju"
    )
    got = sorted(f.id for f in res.festivals)
    check("region_code 가 area_cd·region_block 을 이긴다", got == [1], f"got={got}")

    res = await festival_service.build_festivals_response(
        region_code=None, limit=200, cache=cache, area_cd="26", region_block="gyeonggi"
    )
    got = sorted(f.id for f in res.festivals)
    check("area_cd 가 region_block 을 이긴다", got == [4], f"got={got}")

    section("(d) 알 수 없는 권역 key 는 400")
    from app.main import app  # noqa: E402 — 라우터 등록 후에 import

    client = TestClient(app)
    r = client.get("/api/v1/festivals", params={"region_block": "없는권역"})
    check("알 수 없는 region_block → 400", r.status_code == 400, str(r.status_code))
    body = r.json() if r.status_code == 400 else {}
    check("에러 코드 INVALID_REGION_BLOCK",
          body.get("error", {}).get("code") == "INVALID_REGION_BLOCK", r.text[:160])
    r = client.get("/api/v1/festivals", params={"region_block": "jeju", "limit": 1})
    check("유효한 region_block 은 200", r.status_code == 200, str(r.status_code))

    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n총 {len(RESULTS)}건 중 실패 {len(failed)}건")
    if failed:
        for label in failed:
            print(f"  FAIL: {label}")
        sys.exit(1)
    print("모두 통과")


if __name__ == "__main__":
    asyncio.run(main())
