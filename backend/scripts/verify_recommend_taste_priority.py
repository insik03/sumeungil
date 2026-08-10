# -*- coding: utf-8 -*-
"""부록 F.1-7 검증 — 맞춤 추천은 **취향이 1순위**, 혼잡도가 순서를 뒤집지 않는다 (2026-08-01).

대표 지시: *"맞춤 추천에서 부산은 붐비는 곳 대신 혼잡도가 낮은 대안을 위로 올렸다 이런 말도
있는데 다른 지역은 없고, 기본적으로 맞춤 추천은 내 취향에 맞춰서 추천을 우선적으로 해줘야지
혼잡도 무관하게."*

**서버를 띄우지 않는다.** 스팟은 실제 시드를 쓰고 혼잡도 board 만 스텁으로 만든다(원천 호출 0).

검증 항목
  (a) 개인화 맞춤 추천: balance 를 켜도 **순수 match_score 순서와 동일** + reason="taste_priority"
  (b) match_score 값 자체는 rerank 전후로 불변(08 §3 불변식)
  (c) 대안이 아예 없는 지역(전부 high)은 순서를 안 바꾸되 경고는 그대로 준다(no_alternative)
  (d) 명시 정렬(popular/calm)은 종전대로 explicit_sort
  (e) 비개인화(프로필 없음)는 종전 동작 유지 — 혼잡도순 + balance 적용(무회귀)
  (f) notice 정직성: 위로 올린 대안에 **혼잡도 미상**이 섞이면 "혼잡도가 낮은"이라고 말하지 않는다
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

from app.ai import tag_registry  # noqa: E402
from app.cache.memory import MemoryCache  # noqa: E402
from app.repositories.congestion_repo import CongestionRecord  # noqa: E402
from app.repositories.spot_repo import JsonSpotRepository  # noqa: E402
from app.schemas.places import ProfileInput, RerankInput  # noqa: E402
from app.services import recommend_service, rerank_service  # noqa: E402
from app.schemas.places import SpotCard, SpotCongestion, SpotLocation, SpotThemes  # noqa: E402

REGION = "26350"  # 부산 해운대구 — 대표가 지적한 그 지역
RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, msg: str) -> None:
    RESULTS.append((ok, msg))
    print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")


REPO = JsonSpotRepository()
CACHE = MemoryCache()


@dataclass
class _Board:
    records: list
    area_name: str | None = None


class _StubCongestionRepo:
    """지역 **전체 스팟**에 혼잡도를 부여하는 board.

    앞쪽 N곳만 덮으면 개인화 top-10 과 겹치지 않아(정렬 기준이 다르므로) high 가 한 곳도
    안 잡힌다 — 그러면 "재정렬을 안 했다"가 아니라 "재정렬할 게 없었다"가 되어 검증이 무의미해진다.
    그래서 전 스팟을 덮되 `mixed=True` 면 짝수번째만 high 로 만들어 **혼잡/여유가 공존**하게 한다.
    """

    def __init__(self, rate: float = 90.0, mixed: bool = False):
        self.rate, self.mixed = rate, mixed

    async def get_board(self, area_cd, region_code):  # noqa: ANN001
        spots = REPO.by_region(region_code, None)
        recs = []
        for i, s in enumerate(spots):
            rate = (self.rate if i % 2 == 0 else 10.0) if self.mixed else self.rate
            recs.append(
                CongestionRecord(spot_name=s.name, congestion_rate=rate, base_date="2026-08-01")
            )
        return _Board(records=recs)

    async def get_forecast(self, area_cd, region_code):  # noqa: ANN001
        raise NotImplementedError

    def last_upstream_status(self) -> str:
        return "ok"


def make_profile(congestion_weight: float = 0.2) -> ProfileInput:
    """유효한 프로필(V1~V4 통과). `congestion_weight` 로 "혼잡도를 얼마나 신경 쓰는지"를 조절한다.

    `0.0` 은 대표가 말한 **"혼잡도 무관하게"** 사용자다. 이 사용자에게 종전 코드는
    "붐비는 곳을 아래로" 하드 재배치를 그대로 걸었다 — 신경 안 쓴다고 한 축으로 순서를 뒤집은 셈.
    (반대로 가중치를 키우면 붐비는 곳은 **점수 자체가 낮아져** 자연히 밀린다. 혼잡도를 버린 게
    아니라 사용자가 정한 만큼만 반영한다는 뜻이다 — 아래 (g) 에서 그걸 확인한다.)
    """
    vec = [0.0] * tag_registry.VECTOR_DIM
    for i in (2, 5, 9, 14):
        vec[i] = 1.0
    keys = [k for k in recommend_service.WEIGHT_KEYS if k != "congestion"]
    rest = (1.0 - congestion_weight) / len(keys)
    weights = {k: rest for k in keys}
    weights["congestion"] = congestion_weight
    return ProfileInput(
        tag_vector=vec,
        vector_version=tag_registry.VECTOR_VERSION,
        scoring_weights=weights,
        tags={},
    )


async def call(profile, sort: str, balance: bool, cong: _StubCongestionRepo):
    return await recommend_service.build_recommend_response(
        region_code=REGION,
        profile=profile,
        category=None,
        sort=sort,
        limit=10,
        spot_repo=REPO,
        congestion_repo=cong,
        rerank=RerankInput(balance=balance, weather=False),
    )


def ids(resp) -> list[int]:
    return [c.id for c in resp.items]


def scores(resp) -> list[float | None]:
    return [c.match_score for c in resp.items]


def dist_of(resp):
    return getattr(getattr(resp, "rerank", None), "distribution", None)


async def main() -> int:
    prof = make_profile(congestion_weight=0.0)  # "혼잡도 무관" 사용자(대표 지시의 그 경우)
    cong = _StubCongestionRepo(rate=90.0, mixed=True)  # 혼잡·여유가 섞인 지역

    print("\n(a)(b) 개인화 맞춤 추천 — 취향 1순위, match_score 불변")
    pure = await call(prof, "recommended", False, cong)
    with_bal = await call(prof, "recommended", True, cong)
    check(ids(with_bal) == ids(pure),
          f"balance=on 순서 == 순수 match_score 순서(상위 {len(ids(pure))}곳 전부 일치)")
    check(scores(with_bal) == scores(pure), "match_score 값 불변(재계산·페널티 없음)")
    d = dist_of(with_bal)
    check(d is not None and d.applied is False and d.reason == "taste_priority",
          f"distribution: applied={getattr(d,'applied',None)} reason={getattr(d,'reason',None)}")
    highs = [c for c in with_bal.items if c.congestion and c.congestion.level == "high"]
    check(len(highs) > 0,
          f"이 시나리오에 high 스팟이 실재({len(highs)}곳) — 재정렬을 '안 한' 것이지 '할 게 없던' 게 아님")
    # 종전 규칙(비-high 전부를 high 전부보다 위로)이라면 실제로 순서가 뒤집혔을 것 —
    # 이게 성립해야 "고쳐서 달라졌다"가 증명된다(고치나 마나인 시나리오면 검증이 헛돈다).
    would_be, _ = rerank_service.apply_balance_rerank(list(pure.items))
    check([c.id for c in would_be] != ids(pure),
          "종전 규칙이었다면 순서가 뒤집혔을 시나리오임(수정 효과가 실재)")

    print("\n(c) 대안이 없는 지역(전부 high) — 순서는 그대로, 경고는 유지")
    all_high = _StubCongestionRepo(rate=95.0)
    r = await call(prof, "recommended", True, all_high)
    pure_all = await call(prof, "recommended", False, all_high)
    d = dist_of(r)
    check(ids(r) == ids(pure_all), "전부 high 여도 취향 순서 그대로")
    check(getattr(d, "reason", None) == "no_alternative",
          f"reason={getattr(d,'reason',None)} (경고는 살아 있음)")
    check(bool(getattr(d, "notice", None)), f"notice: {getattr(d,'notice',None)}")

    print("\n(d) 명시 정렬은 종전대로")
    for s in ("popular", "calm"):
        r = await call(prof, s, True, cong)
        check(getattr(dist_of(r), "reason", None) == "explicit_sort", f"sort={s} → explicit_sort")

    print("\n(e) 비개인화(프로필 없음) — 종전 동작 유지(무회귀)")
    r = await call(None, "recommended", True, cong)
    check(r.personalized is False, "personalized=False (혼잡도순으로 강등, 종전 그대로)")
    check(getattr(dist_of(r), "reason", None) != "taste_priority",
          "비개인화에는 taste_priority 를 쓰지 않는다(취향 자체가 없으므로)")

    print("\n(f) notice 정직성 — '미상'을 '낮음'이라고 말하지 않는다")
    lo = SpotCongestion(index=10.0, level="low", tier="B")
    hi = SpotCongestion(index=90.0, level="high", tier="B")

    def card(i: int, c) -> SpotCard:
        return SpotCard(
            id=i,
            name=f"스팟{i}",
            category="attraction",
            region_code=REGION,
            address="주소",
            location=SpotLocation(lat=35.16, lng=129.16),
            themes=SpotThemes(),
            congestion=c,
        )

    _, d_pure = rerank_service.apply_balance_rerank([card(1, hi), card(2, lo)])
    check("혼잡도가 낮은" in (d_pure.notice or ""),
          f"올린 대안이 전부 low/mid → 종전 문구 유지: {d_pure.notice}")
    _, d_mixed = rerank_service.apply_balance_rerank([card(1, hi), card(2, None)])
    check("혼잡도가 낮은 대안" not in (d_mixed.notice or ""),
          f"올린 대안에 미상 포함 → '낮은 대안'이라 말하지 않음: {d_mixed.notice}")
    check("확인되지 않은" in (d_mixed.notice or ""), "미상임을 문구에 명시")

    print("\n(g) 혼잡도를 버린 게 아니다 — 가중치를 키우면 붐비는 곳이 점수로 밀린다")
    care = await call(make_profile(congestion_weight=0.6), "recommended", True, cong)
    dont = await call(make_profile(congestion_weight=0.0), "recommended", True, cong)
    n_high = lambda r: len(  # noqa: E731
        [c for c in r.items if c.congestion and c.congestion.level == "high"]
    )
    check(n_high(care) < n_high(dont),
          f"혼잡도 중시(0.6) 상위 high {n_high(care)}곳 < 무관(0.0) {n_high(dont)}곳 — 점수로 반영됨")
    check(ids(care) != ids(dont), "가중치가 다르면 순서도 실제로 다르다(사용자 설정이 살아 있음)")

    passed = sum(1 for ok, _ in RESULTS if ok)
    print(f"\n== {passed}/{len(RESULTS)} PASS ==")
    for ok, msg in RESULTS:
        if not ok:
            print(f"  FAIL: {msg}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
