# -*- coding: utf-8 -*-
"""부록 S.8.6 검증 — **per_theme(페이지 크기)를 도중에 바꿔도** 중복 0 · 누락 0.

왜 이 스크립트가 따로 있나(2026-08-01, 운영 실측):
  프론트는 첫 화면을 `per_theme=8` 로 받고 더보기는 `per_theme=50&offset=8` 로 부른다 —
  **한 페이지 열 안에서 페이지 크기가 바뀐다.** 종전 구현은 offset 을 "페이지 번호"처럼 다뤄
  요청의 page_size 로 페이지를 이어서 계산했기 때문에, 크기가 바뀌면 경계가 달라져 앞서 보여준
  스팟이 다음 페이지에 다시 실렸다(운영 재현: "조용히 힐링" 58장 중 경주다방 2회).
  기존 verify_collections_paging.py 는 **크기를 고정한 채**로만 페이징해서 이 결함을 못 잡았다.

    py scripts/verify_collections_mixed_paging.py [시드개수]

**서버를 띄우지 않는다.** 실제 시드 스팟 데이터 + 인메모리 캐시로 서비스 함수를 직접 호출하고,
혼잡도 repo 와 사진 조회는 스텁으로 대체한다(원천 API 호출 0, 네트워크 0).

검증 항목
  (A) 운영에서 실제로 터진 조합·시드 고정(회귀 방지)
  (B) 조합 × 시드 대량 스윕 → 중복 0
  (C) 혼합 크기로 끝까지 페이징 → 회수율 100%(중복 0 · 누락 0)
  (D) 순열 불변식: 크기를 어떻게 나눠 받아도 앞 N개 집합이 동일
  (E) 사진 채움률(참고 수치 — 여유분 폐지의 영향 확인용)
"""
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PUBLIC_DATA_API_KEY", "stub")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.cache.memory import MemoryCache  # noqa: E402
from app.repositories.spot_repo import JsonSpotRepository  # noqa: E402
from app.services import collections_service, spot_detail_service  # noqa: E402
from app.services.photo_service import NO_PHOTO, Photo  # noqa: E402
from app.util.images import kto_credit  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


@dataclass
class _Board:
    records: list


class _StubCongestionRepo:
    async def get_board(self, area_cd, region_code):  # noqa: ANN001
        return _Board(records=[])


async def _stub_get_photos(spots, cache):  # noqa: ANN001
    """사진 조회 스텁 — 시드 image_url 만 본다(원천 콜 0)."""
    return [
        Photo(url=s.image_url, credit=kto_credit(), source="seed") if s.image_url else NO_PHOTO
        for s in spots
    ]


spot_detail_service.get_photos = _stub_get_photos

REPO = JsonSpotRepository()
CACHE = MemoryCache()
CONG = _StubCongestionRepo()
THEMES = collections_service.theme_keys()


async def call(**kw):
    kw.setdefault("region_code", None)
    resp = await collections_service.build_collections_response(
        spot_repo=REPO, congestion_repo=CONG, cache=CACHE, **kw
    )
    return resp.model_dump()


def col(resp, key) -> dict | None:
    return next((c for c in resp["collections"] if c["theme_key"] == key), None)


def check(ok: bool, msg: str) -> None:
    RESULTS.append((ok, msg))
    print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")


async def flow(seed: int, sizes: list[int], theme: str, **base):
    """프론트 실제 호출 순서 재현.

    ① 첫 요청은 전체 조회(`per_theme=sizes[0]`, theme 없음) — 홈/테마 목록 진입.
    ② 이후 더보기는 `theme=<key>&offset=지금까지 받은 개수&per_theme=sizes[i]`.
    반환: (받은 id 순서대로, total, 마지막 has_more)
    """
    r = await call(seed=seed, per_theme=sizes[0], **base)
    c = col(r, theme)
    if not c:
        return [], 0, False
    got = [s["id"] for s in c["spots"]]
    total, more = c["total"], c["has_more"]
    for n in sizes[1:]:
        c = col(await call(seed=seed, per_theme=n, theme=theme, offset=len(got), **base), theme)
        if not c or not c["spots"]:
            return got, total, False
        got += [s["id"] for s in c["spots"]]
        total, more = c["total"], c["has_more"]
    return got, total, more


async def paging_to_end(seed: int, sizes: list[int], theme: str, **base):
    """sizes 를 돌려 가며 has_more 가 꺼질 때까지 더보기를 누른다(혼합 크기 페이징)."""
    r = await call(seed=seed, per_theme=sizes[0], **base)
    c = col(r, theme)
    if not c:
        return [], 0
    got = [s["id"] for s in c["spots"]]
    total = c["total"]
    i = 0
    while c and c["has_more"] and i < 500:
        i += 1
        c = col(
            await call(seed=seed, per_theme=sizes[i % len(sizes)], theme=theme, offset=len(got), **base),
            theme,
        )
        if not c or not c["spots"]:
            break
        got += [s["id"] for s in c["spots"]]
    return got, total


async def main() -> int:
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 60

    print("=== (A) 운영 재현 케이스 고정(8 → 50, diverse) ===")
    # 2026-08-01 운영 실측: /themes 에서 "조용히 힐링" 더보기 1회 → 58장 중 1건 중복.
    # 아래 (테마, 시드)는 수정 전 코드에서 실제로 중복이 재현되던 조합이다(회귀 방지 고정).
    known_bad = [
        ("healing", 15), ("healing", 32), ("healing", 43), ("healing", 65),
        ("photo", 15), ("photo", 40),
        ("nature", 1), ("nature", 5), ("nature", 9), ("nature", 13),
        ("quiet_cafe", 0), ("quiet_cafe", 2), ("quiet_cafe", 3), ("quiet_cafe", 4),
    ]
    bad = []
    for theme, seed in known_bad:
        got, _, _ = await flow(seed, [8, 50], theme, diverse=True)
        if len(got) != len(set(got)):
            bad.append(f"{theme}/seed={seed}")
    check(not bad, f"수정 전 중복 재현 조합 {len(known_bad)}건 → 지금 중복 0" + (f" (실패: {bad})" if bad else ""))

    print(f"=== (B) 조합 × 시드 스윕(시드 0..{n_seeds - 1}) ===")
    combos = [[8, 50], [50, 8], [8, 8], [8, 20, 50], [8, 8, 50], [12, 5, 30], [50, 50]]
    for combo in combos:
        dup = runs = 0
        for theme in THEMES:
            for s in range(n_seeds):
                got, _, _ = await flow(s, combo, theme, diverse=True)
                if not got:
                    continue
                runs += 1
                dup += len(got) != len(set(got))
        check(dup == 0, f"diverse per_theme={combo}: {runs}회 중 중복 {dup}회")
    for combo in [[8, 50], [12, 5, 30]]:
        dup = runs = 0
        for theme in THEMES:
            for s in range(max(10, n_seeds // 3)):
                got, _, _ = await flow(s, combo, theme, region_code="26350")
                if not got:
                    continue
                runs += 1
                dup += len(got) != len(set(got))
        check(dup == 0, f"단일 26350 per_theme={combo}: {runs}회 중 중복 {dup}회")

    print("=== (C) 혼합 크기로 끝까지 페이징 → 회수율 100% ===")
    for label, sizes in [("고정 8", [8]), ("혼합 8/50", [8, 50]), ("혼합 12/5/30", [12, 5, 30])]:
        for theme in ["craft", "market", "nature", "healing"]:
            worst, bad_case = 1.0, ""
            for s in range(5):
                got, total = await paging_to_end(s, sizes, theme, diverse=True)
                if not got:
                    continue
                rate = len(set(got)) / max(total, 1)
                if len(got) != len(set(got)):
                    check(False, f"{label} {theme} seed={s}: 중복 {len(got) - len(set(got))}건")
                    return 1
                if rate < worst:
                    worst, bad_case = rate, f"seed={s} {len(set(got))}/{total}"
            check(worst >= 1.0, f"{label} {theme}: 최저 회수율 {100 * worst:.1f}% {bad_case}")

    print("=== (D) 순열 불변식(크기를 어떻게 나눠 받아도 앞 N개 집합 동일) ===")
    for theme in THEMES:
        ok = True
        for s in range(10):
            one, _, _ = await flow(s, [48], theme, diverse=True)
            many, _, _ = await flow(s, [8, 8, 8, 8, 8, 8], theme, diverse=True)
            mixed, _, _ = await flow(s, [8, 20, 20], theme, diverse=True)
            if not one:
                continue
            if set(one) != set(many) or set(one) != set(mixed):
                ok = False
                break
        check(ok, f"{theme}: 48 = 8×6 = 8+20+20 앞 48개 집합 동일")

    print("=== (E) 사진 채움률(참고 — 여유분 폐지 영향) ===")
    for label, kw in [
        ("diverse per8 offset0", dict(diverse=True, seed=3, per_theme=8)),
        ("diverse per50 offset8", dict(diverse=True, seed=3, per_theme=50, offset=8)),
        ("단일 26350 per8", dict(region_code="26350", seed=3, per_theme=8)),
        ("단일 26350 per20", dict(region_code="26350", seed=3, per_theme=20)),
    ]:
        r = await call(**kw)
        spots = [s for c in r["collections"] for s in c["spots"]]
        with_photo = sum(1 for s in spots if s["image_url"])
        print(f"  [INFO] {label}: 사진 {with_photo}/{len(spots)} ({100 * with_photo / max(len(spots), 1):.0f}%)")

    failed = [m for ok, m in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} PASS")
    for m in failed:
        print("  FAIL:", m)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
