# -*- coding: utf-8 -*-
"""부록 H.6 검증 — `GET /places/featured` 의 `limit` 이 실제로 동작하는가 (2026-08-01).

**서버를 띄우지 않는다.** 실제 시드 스팟 데이터 + 인메모리 캐시로 서비스 함수를 직접 호출하고,
혼잡도 board 와 사진 조회는 스텁으로 대체한다(원천 API 호출 0, 네트워크 0).

    py scripts/verify_featured_limit.py
    py scripts/verify_featured_limit.py --dump-diverse out.json   # 무회귀 비교용 스냅샷

검증 항목(오케스트레이터 지시서 수용 기준)
  (a) region_code 지정 + limit 8/24/48 에서 hidden_picks 가 실제로 증가(후보 부족 시 수치 보고)
  (b) trending 이 board 상한(이름매칭 성공 개수)까지 채워진다
  (c) trending_total / hidden_total 이 정확하다
  (d) 사진 조회 ≤ 노출 개수 × 1.5 (부록 H.3 비용 정책)
  (e) diverse 경로 무회귀(응답 스냅샷 동일, totals 는 null)
  (f) limit 미지정 요청은 종전과 동일(trending 8 / hidden 6 상한)
  (g) limit 상한 클램프(>50 → 50)
  (h) 랜덤성 유지(같은 요청 2회 → 다른 조합) / seed 고정 시 재현
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PUBLIC_DATA_API_KEY", "stub")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.cache.memory import MemoryCache  # noqa: E402
from app.regions.seed import REGIONS  # noqa: E402
from app.repositories.congestion_repo import CongestionRecord  # noqa: E402
from app.repositories.spot_repo import JsonSpotRepository  # noqa: E402
from app.services import featured_service, spot_detail_service  # noqa: E402
from app.services.photo_service import NO_PHOTO, Photo  # noqa: E402
from app.util.images import kto_credit  # noqa: E402

PHOTO_LOOKUPS = {"n": 0}
RESULTS: list[tuple[bool, str]] = []

REGION = "26350"  # 부산 해운대구(기본 지역, 실측 기준 지역)
# 스텁 board 가 그 지역 스토어에서 몇 개의 관광지를 "이름매칭 가능"하게 줄 것인가.
# 실측(운영 board)은 해운대 10건 중 8건 매칭이었다 — 여기서는 그 상한 구조를 재현한다.
BOARD_MATCHED = 10
BOARD_UNMATCHED = 2  # 스토어에 없는 이름(억지매칭 금지 확인용)


@dataclass
class _Board:
    records: list
    area_name: str | None = None


class _StubCongestionRepo:
    """지역 스토어의 앞쪽 스팟 이름으로 board 를 만든다(원천 호출 0, 결정적)."""

    async def get_board(self, area_cd, region_code):  # noqa: ANN001
        spots = REPO.by_region(region_code, None)
        recs = [
            CongestionRecord(spot_name=s.name, congestion_rate=90.0 - i, base_date="2026-08-01")
            for i, s in enumerate(spots[:BOARD_MATCHED])
        ]
        recs += [
            CongestionRecord(
                spot_name=f"존재하지않는관광지{i}", congestion_rate=99.0, base_date="2026-08-01"
            )
            for i in range(BOARD_UNMATCHED)
        ]
        return _Board(records=recs)

    async def get_forecast(self, area_cd, region_code):  # noqa: ANN001
        raise NotImplementedError

    def last_upstream_status(self) -> str:
        return "ok"


async def _stub_get_photos(spots, cache):  # noqa: ANN001
    """사진 조회 스텁 — 시드 image_url 만 본다(원천 콜 0). 조회 건수를 센다."""
    PHOTO_LOOKUPS["n"] += len(spots)
    return [
        Photo(url=s.image_url, credit=kto_credit(), source="seed") if s.image_url else NO_PHOTO
        for s in spots
    ]


spot_detail_service.get_photos = _stub_get_photos

REPO = JsonSpotRepository()
CACHE = MemoryCache()
CONG = _StubCongestionRepo()


async def call(**kw):
    PHOTO_LOOKUPS["n"] = 0
    kw.setdefault("region_code", REGION)
    kw.setdefault("limit", None)
    resp = await featured_service.build_featured_response(
        spot_repo=REPO, congestion_repo=CONG, cache=CACHE, **kw
    )
    return resp, PHOTO_LOOKUPS["n"]


def check(ok: bool, label: str) -> None:
    RESULTS.append((bool(ok), label))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")


def _dump(resp) -> dict:
    d = resp.model_dump()
    # 무회귀 비교에서는 신규 필드를 제외하고 **기존 필드만** 비교한다(additive 확인은 별도).
    d.pop("trending_total", None)
    d.pop("hidden_total", None)
    return d


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump-diverse", default=None)
    ap.add_argument("--dump-single", default=None)
    args = ap.parse_args()

    if args.dump_single:
        # 기존 호출부(CoursePromo limit=4, Hero limit=6, /regions 1단계 limit=8)의 응답이
        # 이번 변경 전후로 **완전히 동일**한지 비교하기 위한 스냅샷(seed 고정).
        out = {}
        for lim in (4, 6, 8):
            resp, photos = await call(limit=lim, seed=42)
            out[str(lim)] = {"resp": _dump(resp), "photos": photos}
        Path(args.dump_single).write_text(
            json.dumps(out, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8"
        )
        print(f"single-region 스냅샷 기록: {args.dump_single}")
        return 0

    if args.dump_diverse:
        resp, _ = await call(region_code=None, limit=None, diverse=True, seed=42)
        Path(args.dump_diverse).write_text(
            json.dumps(_dump(resp), ensure_ascii=False, sort_keys=True, indent=1),
            encoding="utf-8",
        )
        print(f"diverse 스냅샷 기록: {args.dump_diverse}")
        return 0

    all_spots = REPO.by_region(REGION, None)
    hidden_all = [s for s in all_spots if s.is_hidden_gem]
    # 부록 H.7 — 사진 백필 후보(숨은 자격은 없지만 사진이 있는 저혼잡 스팟).
    backfill_all = [s for s in all_spots if s.image_url and not s.is_hidden_gem]
    area_cd = next((r.area_cd for r in REGIONS if r.region_id == REGION), None)
    print(f"[데이터] region={REGION} area_cd={area_cd} 스팟 {len(all_spots)}곳 "
          f"(is_hidden_gem {len(hidden_all)}곳 / 그중 사진보유 "
          f"{len([s for s in hidden_all if s.image_url])}곳, 사진 백필 {len(backfill_all)}곳)"
          f" / 스텁 board {BOARD_MATCHED + BOARD_UNMATCHED}건(매칭가능 {BOARD_MATCHED})")

    # --- (f) limit 미지정 = 종전 동작 ---
    print("\n(f) limit 미지정(기본) — 종전 동작 유지")
    resp, photos = await call(limit=None, seed=1)
    print(f"  trending {len(resp.trending)}/{resp.trending_total} · hidden {len(resp.hidden_picks)}"
          f"/{resp.hidden_total} · 사진 조회 {photos}")
    check(len(resp.trending) == 8, f"trending = {len(resp.trending)} (기대 8 = 기본 limit)")
    check(len(resp.hidden_picks) == 6, f"hidden_picks = {len(resp.hidden_picks)} (기대 6 = 기본 상한)")

    # --- (a)(b)(c)(d) limit 별 실측 ---
    print("\n(a)(b)(c)(d) limit 별 실제 개수")
    print(f"  {'limit':>6} | {'trending':>8} {'t_total':>7} | {'hidden':>6} {'h_total':>7} | "
          f"{'photo':>5} {'≤노출×1.5':>9}")
    rows = []
    for lim in (8, 24, 48, 50):
        resp, photos = await call(limit=lim, seed=7)
        shown = len(resp.trending) + len(resp.hidden_picks)
        budget = len(resp.trending) + (len(resp.hidden_picks) * 3 + 1) // 2  # ceil(1.5*hidden)
        rows.append((lim, resp, photos, budget))
        print(f"  {lim:>6} | {len(resp.trending):>8} {resp.trending_total:>7} | "
              f"{len(resp.hidden_picks):>6} {resp.hidden_total:>7} | {photos:>5} {budget:>9}")

    r8, r24, r48 = rows[0][1], rows[1][1], rows[2][1]
    check(len(r24.hidden_picks) > len(r8.hidden_picks),
          f"hidden_picks 가 limit 8({len(r8.hidden_picks)}) → 24({len(r24.hidden_picks)}) 로 증가")
    check(len(r48.hidden_picks) >= len(r24.hidden_picks),
          f"hidden_picks 가 limit 24({len(r24.hidden_picks)}) → 48({len(r48.hidden_picks)}) 로 증가/유지")
    # hidden 은 후보 총 수를 넘을 수 없다(정직) — 넘으면 지어낸 것이다.
    for lim, resp, _, _ in rows:
        check(len(resp.hidden_picks) <= min(lim, resp.hidden_total),
              f"limit={lim}: hidden_picks({len(resp.hidden_picks)}) ≤ min(limit, hidden_total={resp.hidden_total})")

    # (b) trending 은 board 매칭 상한까지
    check(len(r8.trending) == 8, f"limit=8 → trending 8 (limit 이 상한)")
    check(len(r24.trending) == BOARD_MATCHED,
          f"limit=24 → trending {len(r24.trending)} (board 매칭 상한 {BOARD_MATCHED} 까지 채움)")
    check(len(r48.trending) == BOARD_MATCHED,
          f"limit=48 → trending {len(r48.trending)} (board 상한 = 더 늘지 않음, 정직)")

    # (c) totals 정확성
    check(r24.trending_total == BOARD_MATCHED,
          f"trending_total = {r24.trending_total} (매칭 성공 {BOARD_MATCHED}, 미매칭 {BOARD_UNMATCHED} 제외)")
    for lim, resp, _, _ in rows:
        shown_ids = {s.id for s in resp.trending}
        # 부록 H.7(2026-08-01): hidden_total 은 "숨은 자격 후보 수"가 아니라 **노출 가능 수**다
        # (숨은 후보 + 사진 백필). 프론트가 이 값으로 더보기를 감추므로 실제 공급량이어야 한다.
        expect_hidden_total = len(
            [s for s in hidden_all if s.id not in shown_ids]
        ) + len([s for s in backfill_all if s.id not in shown_ids])
        check(resp.hidden_total == expect_hidden_total,
              f"limit={lim}: hidden_total {resp.hidden_total} == 노출가능 후보수 {expect_hidden_total}")
        overlap = shown_ids & {s.id for s in resp.hidden_picks}
        check(not overlap, f"limit={lim}: trending ∩ hidden_picks = {len(overlap)}건")

        # 품질 하한(부록 H.7 개정) — 종전 단언 "전원 is_hidden_gem" 은 폐기했다. 그 규칙 아래서는
        # 사진 있는 숨은 후보가 바닥나면 **사진 없는 숨은 후보**가 자리를 메워, 더보기를 누를수록
        # 플레이스홀더만 쌓였다(실측 limit=24 에서 채움률 42~54%). 대신 두 가지를 강제한다:
        #   H.7-1 등급 순서: 사진 있는 숨은 후보가 남아 있는 한 백필/무사진이 들어오지 않는다.
        #   H.7-2 백필의 자격: 백필로 들어온 스팟은 반드시 사진이 있다(빈 카드를 늘리지 않는다).
        picks = resp.hidden_picks
        hidden_photo_supply = len(
            [s for s in hidden_all if s.image_url and s.id not in shown_ids]
        )
        n_tier1 = len([s for s in picks if s.is_hidden_gem and s.image_url])
        check(n_tier1 == min(len(picks), hidden_photo_supply),
              f"limit={lim}: 1등급(숨은+사진) {n_tier1} == min(노출 {len(picks)}, 공급 {hidden_photo_supply}) — 등급 순서 준수")
        no_photo_backfill = [s for s in picks if not s.is_hidden_gem and not s.image_url]
        check(not no_photo_backfill,
              f"limit={lim}: 사진 없는 백필 {len(no_photo_backfill)}건 (0이어야 함 — 백필은 사진 있는 것만)")

    # (i) 사진 채움률 — 부록 H.7 의 존재 이유. 공급이 충분하면 빈 카드가 0 이어야 한다.
    #     대표 지시(2026-08-01) "군데군데 빈 사진이 너무 많다"의 회귀 방지선.
    print("\n(i) 사진 채움률(부록 H.7)")
    for lim, resp, _, _ in rows:
        picks = resp.hidden_picks
        if not picks:
            continue
        shown_ids = {s.id for s in resp.trending}
        photo_supply = len(
            [s for s in all_spots if s.image_url and s.id not in shown_ids]
        )
        filled = len([s for s in picks if s.image_url])
        expect = min(len(picks), photo_supply)  # 공급이 모자랄 때만 빈 카드 허용
        check(filled == expect,
              f"limit={lim}: 사진 {filled}/{len(picks)} (기대 {expect} = min(노출, 공급 {photo_supply}))")

    # (d) 사진 조회 상한
    for lim, resp, photos, budget in rows:
        check(photos <= budget,
              f"limit={lim}: 사진 조회 {photos} ≤ 노출기준 예산 {budget}(trending + ceil(1.5×hidden))")

    # --- (g) 클램프 ---
    print("\n(g) limit 클램프")
    resp_over, _ = await call(limit=999, seed=7)
    check(len(resp_over.hidden_picks) <= featured_service.LIMIT_MAX,
          f"limit=999 → hidden_picks {len(resp_over.hidden_picks)} ≤ LIMIT_MAX {featured_service.LIMIT_MAX}")
    check(len(resp_over.hidden_picks) == len(rows[3][1].hidden_picks),
          "limit=999 결과 = limit=50 결과(상한 클램프 동작)")
    resp_zero, _ = await call(limit=0, seed=7)
    check(len(resp_zero.trending) == 1 and len(resp_zero.hidden_picks) <= 1,
          f"limit=0 → 하한 1 클램프(trending {len(resp_zero.trending)}, hidden {len(resp_zero.hidden_picks)})")

    # --- (h) 랜덤성 / 재현성 ---
    print("\n(h) 랜덤성(부록 S) 유지")
    for lim in (8, 24, 48):
        a, _ = await call(limit=lim)
        b, _ = await call(limit=lim)
        ids_a = [s.id for s in a.hidden_picks]
        ids_b = [s.id for s in b.hidden_picks]
        if len(ids_a) < (a.hidden_total or 0):
            # 후보가 남아 있을 때만 "섞인다"가 성립한다.
            check(ids_a != ids_b,
                  f"limit={lim}: seed 없이 2회 → hidden 조합 상이({len(set(ids_a) ^ set(ids_b))}곳 차이)")
        else:
            # 후보를 **전부** 노출하는 구간(limit ≥ hidden_total)은 표본이 곧 모집단이라
            # 같은 결과가 정상이다. 여기서 다르면 오히려 후보를 빠뜨린 것이다.
            shown = {t.id for t in a.trending}
            full_pool = {s.id for s in hidden_all + backfill_all if s.id not in shown}
            check(set(ids_a) == set(ids_b) == full_pool,
                  f"limit={lim}: 후보 전량 노출 구간({len(ids_a)}/{a.hidden_total}) → 2회 동일 + 누락 0(정상)")
        check([s.id for s in a.trending] == [s.id for s in b.trending],
              f"limit={lim}: trending 은 2회 동일(고정 섹션, 부록 S.1)")
    s1, _ = await call(limit=24, seed=42)
    s2, _ = await call(limit=24, seed=42)
    check([s.id for s in s1.hidden_picks] == [s.id for s in s2.hidden_picks],
          "seed=42 2회 → hidden 완전 동일(재현성)")

    # --- (e) diverse 무회귀 ---
    print("\n(e) diverse 경로 무회귀")
    d_none, _ = await call(region_code=None, limit=None, diverse=True, seed=42)
    d_8, _ = await call(region_code=None, limit=8, diverse=True, seed=42)
    d_48, _ = await call(region_code=None, limit=48, diverse=True, seed=42)
    check(_dump(d_none) == _dump(d_8), "diverse: limit 미지정 == limit=8 명시(종전 라우트 기본값과 동치)")
    check(len(d_48.hidden_picks) <= featured_service.HIDDEN_PICKS_MAX,
          f"diverse: limit=48 이어도 hidden {len(d_48.hidden_picks)} ≤ {featured_service.HIDDEN_PICKS_MAX}(홈 무회귀)")
    check(d_none.trending_total is None and d_none.hidden_total is None,
          "diverse: totals 는 null(집계 안 함 → 프론트가 더보기를 띄우지 않음)")
    check(d_none.region is None, "diverse: region null 유지")

    # (i) 2026-09-15 — 숨은 명소 픽 카테고리 다양성: 인천 연수구(28185)는 사진 있는 숨은 후보가
    # 카페 12·시장 1이라 종전엔 카페만 나왔다. 카테고리당 상한(6곳이면 2)으로 백필(관광지·식당)이 섞인다.
    print("\n[i] 숨은 명소 픽 카테고리 상한(28185 인천 연수구)")
    for seed in (1, 2, 3):
        r_ys, _ = await call(region_code="28185", limit=None, seed=seed)
        cats = [s.category for s in r_ys.hidden_picks]
        cap = featured_service._category_cap_for(len(cats))
        check(len(cats) == 6 and max(cats.count(c) for c in set(cats)) <= cap,
              f"seed={seed}: hidden_picks 6곳, 카테고리당 ≤{cap} → {cats}")
    check(featured_service._category_cap_for(24) == 8 and featured_service._category_cap_for(4) == 2,
          "상한 = max(2, ceil(n/3))")

    ok = sum(1 for r, _ in RESULTS if r)
    print(f"\n== {ok}/{len(RESULTS)} PASS ==")
    for r, label in RESULTS:
        if not r:
            print(f"  FAIL: {label}")
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
