# -*- coding: utf-8 -*-
"""부록 S.8 검증 — 테마별 전체 보기(per_theme) + 더보기(theme/offset/seed).

**서버를 띄우지 않는다.** 실제 시드 스팟 데이터 + 인메모리 캐시로 서비스 함수를 직접 호출하고,
혼잡도 repo 와 사진 조회는 스텁으로 대체한다(원천 API 호출 0, 네트워크 0).

    py scripts/verify_collections_paging.py

검증 항목(대표 지시 → 오케스트레이터 수용 기준)
  (a) per_theme 이 커지면 그만큼 나온다(후보 부족 시 있는 만큼 + total 정확)
  (b) 같은 seed 로 offset 을 이어받으면 **중복 0**, 끝까지 페이징하면 회수율 보고
  (c) seed 없이 두 번 호출하면 다른 조합(랜덤 유지) / 응답 seed 재사용 시 재현
  (d) theme 지정 시 그 테마만, 내용은 전체 조회와 동일
  (e) region_code + theme + offset 조합 정상
  (f) 사진 조회 ≤ 노출 개수 × 1.5 (부록 H.3 비용 정책)
  (g) 시군구 쏠림 상한 준수(diverse)
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
from app.services import collections_service, sampling, spot_detail_service  # noqa: E402
from app.services.photo_service import NO_PHOTO, Photo  # noqa: E402
from app.util.images import kto_credit  # noqa: E402

PHOTO_LOOKUPS = {"n": 0}
RESULTS: list[tuple[bool, str]] = []


@dataclass
class _Board:
    records: list


class _StubCongestionRepo:
    async def get_board(self, area_cd, region_code):  # noqa: ANN001
        return _Board(records=[])


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
    kw.setdefault("region_code", None)
    resp = await collections_service.build_collections_response(
        spot_repo=REPO, congestion_repo=CONG, cache=CACHE, **kw
    )
    return resp.model_dump()


def ids(resp) -> dict[str, list[int]]:
    return {c["theme_key"]: [s["id"] for s in c["spots"]] for c in resp["collections"]}


def col(resp, key) -> dict | None:
    return next((c for c in resp["collections"] if c["theme_key"] == key), None)


def check(ok: bool, msg: str) -> None:
    RESULTS.append((ok, msg))
    print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")


async def sweep(label: str, per: int, **base) -> None:
    """더보기를 끝까지 눌러 본다 — 중복 0 이어야 하고 회수율을 출력한다."""
    off, seen, sizes = 0, set(), []
    total = 0
    while len(sizes) <= 150:
        r = await call(seed=77, per_theme=per, offset=off, **base)
        if not r["collections"]:
            break
        c = r["collections"][0]
        got = [s["id"] for s in c["spots"]]
        total = c["total"]
        if seen & set(got):
            check(False, f"{label}: offset={off} 에서 중복 {len(seen & set(got))}건")
            return
        seen |= set(got)
        sizes.append(len(got))
        off += len(got)
        if not c["has_more"]:
            break
    check(
        True,
        f"{label} per={per}: {len(sizes)}페이지 누계 {len(seen)}/{total}"
        f" ({100 * len(seen) / max(total, 1):.0f}%) 중복 0",
    )


async def main() -> int:
    print("=== (a) per_theme 확대 ===")
    r = await call(region_code="26350", seed=7, per_theme=20)
    check(
        all(len(c["spots"]) == min(20, c["total"]) for c in r["collections"]),
        "단일 26350 per_theme=20 → " + ", ".join(f"{c['theme_key']} {len(c['spots'])}/{c['total']}" for c in r["collections"]),
    )
    r = await call(diverse=True, seed=7, per_theme=20)
    check(
        all(len(c["spots"]) == min(20, c["total"]) for c in r["collections"]),
        "diverse per_theme=20 → " + ", ".join(f"{c['theme_key']} {len(c['spots'])}" for c in r["collections"]),
    )

    print("=== (b) 같은 seed + offset 이어받기(중복 0) ===")
    for label, base in [("단일 26350", dict(region_code="26350")), ("diverse", dict(diverse=True))]:
        pages = [ids(await call(seed=99, offset=o, **base)) for o in (0, 8, 16)]
        for k in sorted(pages[0]):
            seq = sum((p.get(k, []) for p in pages), [])
            check(len(seq) == len(set(seq)), f"{label}/{k}: 페이지 {[len(p.get(k, [])) for p in pages]} 중복 {len(seq) - len(set(seq))}")
    await sweep("diverse photo 끝까지", 12, diverse=True, theme="photo")
    await sweep("diverse craft 끝까지", 8, diverse=True, theme="craft")
    await sweep("단일 26350 photo 끝까지", 6, region_code="26350", theme="photo")

    print("=== (c) 랜덤 유지 / seed 재사용 재현 ===")
    check(ids(await call(region_code="26350")) != ids(await call(region_code="26350")), "seed 미지정 2회 → 조합 상이(단일)")
    check(ids(await call(diverse=True)) != ids(await call(diverse=True)), "seed 미지정 2회 → 조합 상이(diverse)")
    first = await call(region_code="26350")
    check(ids(first) == ids(await call(region_code="26350", seed=first["seed"])), "응답 seed 재사용 → 같은 조합 재현")

    print("=== (d) theme 지정 ===")
    for label, base in [("단일", dict(region_code="26350")), ("diverse", dict(diverse=True))]:
        one, full = await call(seed=42, theme="photo", **base), await call(seed=42, **base)
        check(
            list(ids(one)) == ["photo"] and ids(one)["photo"] == ids(full)["photo"],
            f"{label} theme=photo → photo 만, 내용은 전체 조회와 동일",
        )

    print("=== (e) region_code + theme + offset ===")
    p0 = ids(await call(region_code="26350", seed=5, theme="healing"))["healing"]
    p1 = ids(await call(region_code="26350", seed=5, theme="healing", offset=8))["healing"]
    full0 = ids(await call(region_code="26350", seed=5))["healing"]
    check(p0 == full0, "지역+theme 첫 페이지 = 전체 조회 첫 페이지")
    check(not (set(p0) & set(p1)), f"지역+theme+offset=8 중복 0 (len {len(p0)}, {len(p1)})")
    c = col(await call(region_code="26350", seed=5, theme="quiet_cafe"), "quiet_cafe")
    check(c is not None and not c["has_more"], f"후보 소진 테마 has_more=false (total {c['total'] if c else '-'})")

    print("=== (f) 사진 조회 ≤ 노출×1.5 ===")
    for label, kw in [
        ("단일 per20", dict(region_code="26350", seed=3, per_theme=20)),
        ("diverse per20", dict(diverse=True, seed=3, per_theme=20)),
        ("diverse per50 theme=photo", dict(diverse=True, seed=3, per_theme=50, theme="photo")),
        ("diverse offset=16", dict(diverse=True, seed=3, offset=16)),
        ("기본(무파라미터)", dict(diverse=True, seed=3)),
    ]:
        r = await call(**kw)
        shown = sum(len(v) for v in ids(r).values())
        check(PHOTO_LOOKUPS["n"] <= shown * 1.5, f"{label}: 조회 {PHOTO_LOOKUPS['n']} ≤ 노출 {shown}×1.5")

    print("=== (g) diverse 시군구 쏠림 상한 ===")
    # S.8.6(2026-08-01 중복 수정) 이후 상한의 정의가 바뀌었다.
    #   종전: "한 페이지당 시군구 N곳" — 페이지가 곧 표본 추출 단위였기에 가능했지만, 상한에
    #         걸린 후보를 **영구히 버려서** 끝까지 페이징해도 안 나오는 스팟이 생겼다(누락).
    #   현재: 순열 청크(8개)당 2곳. 노출 구간이 걸치는 청크 수 × 2 가 상한이다.
    #         후보를 버리지 않으므로 회수율 100% 를 지키면서 구간 어디를 잘라도 지역이 섞인다.
    # 후보 총 수 ≤ 노출 개수인 테마(전량 노출)는 상한을 적용하지 않는다 — 후보 자체가
    # 한 지역에 몰려 있으면 "전체 보기"를 위해 그대로 다 보여주는 게 맞다.
    for per in (8, 20, 50):
        r = await call(diverse=True, seed=11, per_theme=per)
        for c in r["collections"]:
            shown = len(c["spots"])
            if c["total"] <= shown:
                continue
            cap = 2 * -(-shown // sampling.SEQ_CHUNK)
            counts: dict[str, int] = {}
            for s in c["spots"]:
                counts[s["region_name"]] = counts.get(s["region_name"], 0) + 1
            worst = max(counts.values(), default=0)
            check(worst <= cap, f"per_theme={per} {c['theme_key']}: 한 시군구 최대 {worst} ≤ 상한 {cap}")

    failed = [m for ok, m in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} PASS")
    for m in failed:
        print("  FAIL:", m)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
