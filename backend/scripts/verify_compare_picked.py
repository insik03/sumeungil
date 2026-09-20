# -*- coding: utf-8 -*-
"""비교 리포트 — "내가 고른 곳" 라벨이 **실제로 고른 스팟**에만 붙는지 (2026-09-20, qa-reviewer F-3).

#169 가 고친 좌우 역전에는 남아 있던 경로가 하나 있었다. `hotspot_id` 로 스팟을 잡으면
`hotspot_source = "local_store"` 가 되는데, 그 스팟이 곧바로 숨은길로도 뽑혀 자기비교가 되면
`hotspot` 만 None 으로 비우고 **source 는 그대로 뒀다.** 그 뒤 auto 경로가 board 에서 전혀
다른 핫플을 잡아왔는데도 `picked = (hotspot_source == "local_store")` 가 True 로 남아,
왼쪽 "내가 고른 곳" 자리에 고르지도 않은 스팟이 들어가고 실제로 누른 스팟이 오른쪽
"AI 가 찾은 더 한적한 대안"으로 밀렸다.

**서버를 띄우지 않는다.** 스팟 스토어와 혼잡도 board 를 최소 스텁으로 만들어 그 경로를 정확히
재현한다(원천 호출 0, DB 0).

재현 조건(셋 다 필요하다):
  1. 같은 카테고리 두 곳 A·B 가 있는데 태그 유사도가 SIMILARITY_MIN 미만 → `_similar_candidates`
     가 비어 숨은길이 유사도 경로로 안 뽑히고 폴백(_rank_spots 최상위)으로 떨어진다.
  2. 그 폴백 최상위가 **hotspot_id 로 고른 A 자신** → 자기비교 성립.
  3. board 에 같은 카테고리 B 가 있어 auto 가 B 를 핫플로 잡아온다.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PUBLIC_DATA_API_KEY", "stub")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.regions.seed import REGIONS  # noqa: E402
from app.repositories.congestion_repo import (  # noqa: E402
    CongestionRecord,
    CongestionRepository,
    RepoResult,
)
from app.repositories.spot_repo import SpotRecord, SpotRepository  # noqa: E402
from app.services import compare_service  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail and not ok else ""))


# area_cd 가 있는 지역이어야 board 를 조회한다(없으면 혼잡도 경로 자체를 건너뛴다).
REGION = next(r.region_id for r in REGIONS if r.area_cd)

PICKED_ID = 900_001   # 사용자가 "이 곳과 비교"를 누른 스팟
OTHER_ID = 900_002    # board 최상위 — auto 가 잡아올 전혀 다른 곳

# 36차원 이진 태그. 겹치는 축이 없어야 코사인 유사도 0 → SIMILARITY_MIN(0.30) 미달.
_VEC_A = [1.0] + [0.0] * 35
_VEC_B = [0.0] * 18 + [1.0] + [0.0] * 17


def _spot(spot_id: int, name: str, vec: list[float]) -> SpotRecord:
    return SpotRecord(
        id=spot_id,
        name=name,
        category="attraction",  # 둘 다 같은 카테고리여야 auto 가 짝을 찾는다
        region_code=REGION,
        address=None,
        lat=37.0,
        lng=127.0,
        themes={},
        is_hidden_gem=False,
        tag_vector=vec,
    )


SPOTS = [_spot(PICKED_ID, "가나다한적한곳", _VEC_A), _spot(OTHER_ID, "라마바붐비는곳", _VEC_B)]


class StubSpotRepo(SpotRepository):
    def by_region(self, region_code: str, category: str | None = None) -> list[SpotRecord]:
        if region_code != REGION:
            return []
        return [s for s in SPOTS if category is None or s.category == category]

    def by_id(self, content_id: int) -> SpotRecord | None:
        return next((s for s in SPOTS if s.id == content_id), None)

    def all_spots(self) -> list[SpotRecord]:
        return list(SPOTS)

    def region_counts(self) -> dict[str, int]:
        return {REGION: len(SPOTS)}

    def total(self) -> int:
        return len(SPOTS)


class StubCongestionRepo(CongestionRepository):
    async def get_board(self, area_cd: str, sigungu_cd: str) -> RepoResult:
        # 고른 곳이 **덜 붐벼야** 폴백 랭킹(_rank_spots)에서 1등이 되어 숨은길로도 뽑힌다.
        return RepoResult(
            records=[
                CongestionRecord(spot_name="라마바붐비는곳", congestion_rate=90.0, base_date="2026-09-20"),
                CongestionRecord(spot_name="가나다한적한곳", congestion_rate=10.0, base_date="2026-09-20"),
            ],
            area_name="stub",
            fetched_at=datetime.now(timezone.utc),
        )

    async def get_forecast(self, area_cd: str, sigungu_cd: str):  # pragma: no cover - 미사용
        raise NotImplementedError

    def last_upstream_status(self):  # pragma: no cover - 미사용
        return None


async def main() -> None:
    print(f"== 비교 리포트 picked 라벨 검증 (region={REGION}) ==")
    resp = await compare_service.build_compare_response(
        region_code=REGION,
        profile=None,
        hidden_id=None,
        hotspot_id=PICKED_ID,
        category=None,
        spot_repo=StubSpotRepo(),
        congestion_repo=StubCongestionRepo(),
    )

    # 전제 확인 — 이 경로를 실제로 탔는가(자기비교 → auto 로 다른 핫플).
    took_path = resp.hotspot.spot_id == OTHER_ID and resp.hidden.spot_id == PICKED_ID
    check("전제: 자기비교로 빠져 auto 가 다른 핫플을 잡았다", took_path,
          f"hotspot={resp.hotspot.spot_id} hidden={resp.hidden.spot_id}")

    # 본 검증 — 그 핫플은 사용자가 고른 곳이 아니므로 local_store 라고 말하면 안 된다.
    check("고르지 않은 핫플은 hotspot_source=m2_board", resp.meta.hotspot_source == "m2_board",
          f"hotspot_source={resp.meta.hotspot_source}")
    # picked 는 응답에 그대로 실리지 않고 headline 문구로만 나타난다(build_verdict 의 `left`).
    check("헤드라인이 '고른 곳'이라 말하지 않는다", "고른 곳" not in resp.verdict.headline,
          resp.verdict.headline)

    # 정상 경로 무회귀 — 자기비교가 아니면 고른 스팟이 그대로 핫플이고 picked=True 다.
    resp2 = await compare_service.build_compare_response(
        region_code=REGION,
        profile=None,
        hidden_id=PICKED_ID,      # 숨은길을 명시하면 hotspot_id 는 자기비교가 아니다
        hotspot_id=OTHER_ID,
        category=None,
        spot_repo=StubSpotRepo(),
        congestion_repo=StubCongestionRepo(),
    )
    check("무회귀: 고른 핫플이 살아 있으면 local_store + '고른 곳' 문구",
          resp2.hotspot.spot_id == OTHER_ID
          and resp2.meta.hotspot_source == "local_store"
          and "고른 곳" in resp2.verdict.headline,
          f"src={resp2.meta.hotspot_source} headline={resp2.verdict.headline}")

    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n총 {len(RESULTS)}건 중 실패 {len(failed)}건")
    if failed:
        for label in failed:
            print(f"  FAIL: {label}")
        sys.exit(1)
    print("모두 통과")


if __name__ == "__main__":
    asyncio.run(main())
