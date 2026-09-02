"""부록 Q.3 — 계절 추천(그 계절에 붐비는 곳 / 한적한 숨은 명소).

근거 데이터에 대한 정직 고지(2026-07-31 실측):
  당초 계획은 "작년 같은 계절 실측 혼잡도"였으나, 접근 가능한 원천에 **과거 데이터가 없다**
  (KTO tatsCnctrRatedList = 미래 30일 예측만, 과거 날짜 파라미터 거부 / 데이터랩 API 403).
  그래서 **예측이 닿는 앞으로 30일 중 해당 계절에 속하는 날짜들의 평균 집중률**을 근거로 쓴다.
  → meta.basis="forecast", meta.notice 에 그 사실을 그대로 적는다.
  요청한 계절이 예측 창과 겹치지 않으면(예: 한여름에 winter 요청) **빈 목록 + basis="none"**
  으로 돌려준다. 계절 분위기만 보고 아무 스팟이나 채우지 않는다(지어내기 금지).

지역 다양성: region_code 미지정이면 9권역 대표 시군구를 훑고 **시군구당 최대 1곳**만 담는다
(홈 "부산만 많다" 불만과 같은 규칙 — featured diverse 와 동일한 원칙).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from ..cache.base import Cache
from ..regions.nationwide import BLOCK_BY_KEY, REGION_BLOCKS
from ..regions.seed import REGIONS
from ..repositories.congestion_repo import CongestionRepository
from ..repositories.spot_repo import SpotRecord, SpotRepository
from ..schemas.outlook import SeasonalMeta, SeasonalResponse
from ..schemas.places import FeaturedSpot, SpotCongestion
from ..spots.region_map import get_tourapi_region
from ..util.time import now_kst
from . import recommend_service, sampling, spot_detail_service
from .congestion_service import classify_level

logger = logging.getLogger("sumeungil.services.seasonal")

SEASONS: tuple[str, ...] = ("spring", "summer", "autumn", "winter")
SEASON_MONTHS: dict[str, tuple[int, ...]] = {
    "spring": (3, 4, 5),
    "summer": (6, 7, 8),
    "autumn": (9, 10, 11),
    "winter": (12, 1, 2),
}
SEASON_LABELS: dict[str, str] = {
    "spring": "봄", "summer": "여름", "autumn": "가을", "winter": "겨울",
}

LIMIT_MIN, LIMIT_MAX, LIMIT_DEFAULT = 1, 20, 8
SEASONAL_CACHE_TTL_SEC = 12 * 60 * 60
# 2026-08-01: 캐시 대상이 "응답"에서 "후보 풀"로 바뀌었다. 응답을 캐시하면 hidden 무작위가
# 무의미해지기 때문이다(같은 응답이 12시간 재생). 원천(get_forecast) 호출은 여전히 이
# 풀 캐시가 막아준다 → **원천 호출 증가 0**. 풀은 limit 과 무관하므로 키에서 limit 을 뺐다
# (종전엔 limit 마다 별도 캐시라 limit 이 다르면 원천을 다시 불렀다 — 오히려 줄어든다).
SEASONAL_POOL_CACHE_TTL_SEC = SEASONAL_CACHE_TTL_SEC

NOTICE_FORECAST = (
    "앞으로 한 달간의 방문자 집중률 예측 중 {label} 날짜만 모아 골랐어요."
)
NOTICE_NONE = (
    "{label} 예측 데이터는 아직 없어요. 그 시기가 가까워지면 알려드릴게요."
)


def clamp_limit(limit: int) -> int:
    return max(LIMIT_MIN, min(LIMIT_MAX, limit))


def current_season(today: date | None = None) -> str:
    month = (today or now_kst().date()).month
    for season, months in SEASON_MONTHS.items():
        if month in months:
            return season
    return "spring"  # 도달 불가(12개월 전부 매핑됨)


def _region_name(region_code: str) -> str | None:
    tr = get_tourapi_region(region_code)
    if tr:
        return tr.region_name
    return next((r.label for r in REGIONS if r.region_id == region_code), None)


def _area_cd(region_code: str) -> str | None:
    return next((r.area_cd for r in REGIONS if r.region_id == region_code), None)


async def _region_scores(
    region_code: str,
    season: str,
    spot_repo: SpotRepository,
    congestion_repo: CongestionRepository,
) -> list[tuple[SpotRecord, float]]:
    """지역 1곳: (스토어 스팟, 해당 계절 날짜 평균 집중률) 목록. 매칭·데이터 없으면 빈 리스트."""
    area_cd = _area_cd(region_code)
    if not area_cd:
        return []
    try:
        result = await congestion_repo.get_forecast(area_cd, region_code)
    except Exception as exc:  # noqa: BLE001 — 한 지역 실패가 전체를 막지 않는다
        logger.info("seasonal 혼잡도 조회 실패 region=%s: %s", region_code, exc)
        return []

    months = SEASON_MONTHS[season]
    spots = spot_repo.by_region(region_code, None)
    if not spots:
        return []

    out: list[tuple[SpotRecord, float]] = []
    seen_ids: set[int] = set()
    for rec in result.spots:
        rates = [p.rate for p in rec.points if int(p.date[5:7]) in months]
        if not rates:
            continue  # 이 관광지는 해당 계절 예측이 없다 → 제외(보간 금지)
        match = _match_store(rec.spot_name, spots)
        if match is None or match.id in seen_ids:
            continue
        seen_ids.add(match.id)
        out.append((match, sum(rates) / len(rates)))
    return out


def _match_store(board_name: str, spots: list[SpotRecord]) -> SpotRecord | None:
    """원천 관광지명 → 스토어 스팟(정확일치 우선). featured 와 같은 규칙(억지 매칭 금지)."""
    nn = recommend_service._norm(board_name)
    for s in spots:
        if recommend_service._norm(s.name) == nn:
            return s
    for s in spots:
        sn = recommend_service._norm(s.name)
        if sn and (sn in nn or nn in sn):
            return s
    return None


def region_cap_for(limit: int, target_count: int) -> int:
    """시군구당 몇 곳까지 담을지. 훑는 시군구가 적으면 상한을 올려 목록이 비지 않게 한다.

    전국(시군구 9곳, limit 8)은 1 그대로다 — 한 도시 독점을 막는 게 목적이니까.
    권역(시군구 최대 4곳)에서 1 로 두면 8칸짜리 목록에 4장만 차서 전국보다 빈약해진다
    (2026-08-01 실측: 강원 popular 4/8). 필요한 만큼만 올린다.
    """
    if target_count <= 0:
        return 1
    return max(1, -(-limit // target_count))  # ceil


def _pick(
    scored: list[tuple[str, SpotRecord, float]],
    limit: int,
    reverse: bool,
    region_cap: int | None,
) -> list[tuple[str, SpotRecord, float]]:
    """정렬 후 (필요 시) 시군구당 `region_cap` 곳 제한을 걸어 limit 개를 고른다.

    `region_cap=None` 이면 제한 없음(시군구를 콕 집어 조회한 경우).
    """
    ordered = sorted(scored, key=lambda t: (t[2], t[1].name), reverse=reverse)
    picked: list[tuple[str, SpotRecord, float]] = []
    counts: dict[str, int] = {}
    for item in ordered:
        if region_cap is not None and counts.get(item[0], 0) >= region_cap:
            continue
        counts[item[0]] = counts.get(item[0], 0) + 1
        picked.append(item)
        if len(picked) >= limit:
            break
    return picked


async def _to_cards(
    picked: list[tuple[str, SpotRecord, float]], cache: Cache, take: int | None = None
) -> list[FeaturedSpot]:
    """FeaturedSpot(부록 H) 조립 — 홈 카드와 같은 모델. 사진은 기존 캐시 경로 재사용.

    `take` 를 주면 사진 있는 카드를 우선해 그 개수만 남긴다(부록 H.3 과 같은 정책).
    hidden 이 여유분(1.5배)을 뽑아오기 때문에 필요한 절차다. popular 는 순위성이라 take 없음.
    """
    if not picked:
        return []
    photos = await spot_detail_service.get_photos([s for _, s, _ in picked], cache)
    pairs = list(zip(picked, photos))
    if take is not None:
        with_photo = [p for p in pairs if p[1].url]
        without = [p for p in pairs if not p[1].url]
        pairs = (with_photo + without)[:take]
    cards: list[FeaturedSpot] = []
    for (region_code, spot, rate), photo in pairs:
        cards.append(
            FeaturedSpot(
                id=spot.id,
                name=spot.name,
                category=spot.category,  # type: ignore[arg-type]
                region_name=_region_name(region_code),
                address=spot.address,
                location={"lat": spot.lat, "lng": spot.lng},
                congestion=SpotCongestion(
                    index=round(rate, 2), level=classify_level(rate), tier="B",
                ),
                is_hidden_gem=spot.is_hidden_gem,
                image_url=photo.url,
                photo_credit=photo.credit,
            )
        )
    return cards


# --- 부록 Q.3.2 권역 선택(2026-08-01, 대표 지시 "계절여행에 지역 선택 전국부터 9도까지") ---
# 한 권역은 시군구를 최대 44곳(경기)까지 품는다. 전부 훑으면 `get_forecast` 원천 호출이
# 권역당 수십 건이 되어 쿼터를 태운다(2026-07-29 실사고와 같은 경로). 그래서 권역당 훑는
# 시군구를 **상한 4곳**으로 묶는다. 어느 4곳인가는 무작위가 아니라 **스팟이 많은 순**이다 —
# 관광 데이터가 실제로 쌓인 시군구여야 예측 매칭이 나오기 때문이고, 결정적이라 캐시가 듣는다.
# 호출량: 권역 선택 1회 = 최대 4콜, 12시간 풀 캐시. 전국(9권역 대표 1곳씩 = 9콜)과 같은 급이다.
BLOCK_SWEEP_MAX = 4


def block_targets(block_key: str, spot_repo: SpotRepository) -> list[str]:
    """권역 key → 훑을 시군구 코드 목록(대표 시군구 우선, 이후 스팟 많은 순, 최대 4곳).

    알 수 없는 key 면 빈 목록 — 호출부가 전국으로 폴백한다(지어내지 않는다).
    """
    block = BLOCK_BY_KEY.get((block_key or "").strip())
    if block is None:
        return []
    area_cds = set(block.area_cds or (block.area_cd,))
    cands = [r.region_id for r in REGIONS if r.area_cd in area_cds]
    # 대표 시군구는 항상 첫 번째(권역 정의의 기준점이라 결과에서 빠지면 혼란스럽다).
    rest = sorted(
        (rc for rc in cands if rc != block.region_code),
        key=lambda rc: (-len(spot_repo.by_region(rc, None)), rc),
    )
    return ([block.region_code] if block.region_code in cands else []) + rest[
        : BLOCK_SWEEP_MAX - 1
    ]


async def build_seasonal_response(
    season: str | None,
    region_code: str | None,
    limit: int,
    spot_repo: SpotRepository,
    congestion_repo: CongestionRepository,
    cache: Cache,
    seed: int | None = None,
    region_block: str | None = None,
) -> SeasonalResponse:
    """seed(부록 Q.3, 2026-08-01): `hidden` 표본의 난수 시드. None 이면 요청마다 다르다.
    **`popular` 는 시드와 무관하게 항상 고정**(그 계절에 붐비는 순위 자체가 정보다).

    region_block(부록 Q.3.2, 2026-08-01): 9권역 key(`gyeonggi`…`jeju`). 주면 그 권역 안의
    시군구 최대 4곳을 훑는다. `region_code` 가 함께 오면 그쪽이 이긴다(더 좁은 지정).
    """
    season = season if season in SEASONS else current_season()
    limit = clamp_limit(limit)
    region_code = (region_code or "").strip() or None
    label = SEASON_LABELS[season]

    # 우선순위: region_code(시군구 직접 지정) > region_block(권역) > 전국 9권역 대표.
    block_key = (region_block or "").strip() or None
    block_sweep = block_targets(block_key, spot_repo) if block_key else []
    if block_key and not block_sweep:
        # 모르는 권역 key → 전국으로 폴백한다(빈 화면을 주거나 지어내지 않는다).
        logger.info("seasonal 알 수 없는 region_block=%r → 전국 폴백", block_key)
        block_key = None

    if region_code:
        targets = [region_code]
    elif block_sweep:
        targets = block_sweep
    else:
        targets = [b.region_code for b in REGION_BLOCKS]
    # 시군구를 콕 집은 경우만 "한 지역 안"이라 지역 상한이 무의미하다(None). 전국·권역은 둘 다
    # 여러 시군구를 훑으므로 상한을 걸어 한 도시가 목록을 독점하지 않게 한다.
    region_cap = None if region_code else region_cap_for(limit, len(targets))

    # --- 후보 풀 캐시(원천 호출 절약) — 응답이 아니라 **풀**을 캐시한다 ---
    scope = region_code or (f"block:{block_key}" if block_key else "all")
    pool_key = f"seasonal:pool:{season}:{scope}"
    raw: list[tuple[str, int, float]] | None = await cache.get(pool_key)
    if raw is None:
        results = await asyncio.gather(
            *[_region_scores(rc, season, spot_repo, congestion_repo) for rc in targets],
            return_exceptions=True,
        )
        raw = []
        for rc, res in zip(targets, results):
            if isinstance(res, BaseException):
                logger.warning("seasonal 지역 %s 예외: %s", rc, res)
                continue
            raw.extend((rc, spot.id, rate) for spot, rate in res)
        if raw:
            # 데이터 없음은 캐시하지 않는다(원천 복구 시 즉시 반영) — 기존 정책 유지.
            await cache.set(pool_key, raw, SEASONAL_POOL_CACHE_TTL_SEC)

    scored: list[tuple[str, SpotRecord, float]] = []
    for rc, spot_id, rate in raw:
        spot = spot_repo.by_id(spot_id)
        if spot is not None:
            scored.append((rc, spot, rate))

    if not scored:
        # 그 계절 예측 데이터가 하나도 없음 → 빈 목록 + 정직 고지(채우지 않는다)
        response = SeasonalResponse(
            season=season,  # type: ignore[arg-type]
            label=label,
            popular=[],
            hidden=[],
            meta=SeasonalMeta(notice=NOTICE_NONE.format(label=label), basis="none"),
        )
        return response  # 데이터 없음은 캐시하지 않는다(원천 복구 시 즉시 반영)

    # popular: 순위성 섹션 — 정렬 상위 그대로(무작위 금지, 2026-08-01 대표 지시).
    popular_pool = _pick(scored, limit, reverse=True, region_cap=region_cap)
    # hidden: "한적한 숨은 명소" — 순위가 정보가 아니므로 자격 통과 후보 풀에서 무작위 표본.
    # 자격(예측 데이터 보유 + is_hidden_gem + popular 비중복)과 저혼잡 선호는 그대로다.
    taken = {p[1].id for p in popular_pool}
    hidden_ranked = sorted(
        [t for t in scored if t[1].is_hidden_gem and t[1].id not in taken],
        key=lambda t: (t[2], t[1].name),
    )
    # 부록 H.7(2026-08-01, 대표 지시 "빈 사진이 너무 많다")을 계절 화면에도 적용한다.
    # is_hidden_gem 자격에 "대표이미지 없음"이 포함돼 있어(category_map.py:97) 이 풀은 구조적으로
    # 사진 없는 스팟이 많다 — 실측 채움률 56~93%. 사진 있는 숨은 후보를 1등급으로 두고, 모자라면
    # **사진 없는 숨은 곳 대신 사진 있는 저혼잡 후보**로 메운다(예측 데이터 보유·popular 비중복
    # 이라는 자격은 동일하게 요구한다 — 자격 미달을 끌어올리는 게 아니다).
    hidden_tier1 = [t for t in hidden_ranked if t[1].image_url]
    hidden_tier3 = [t for t in hidden_ranked if not t[1].image_url]
    hidden_tier2 = sorted(
        [
            t
            for t in scored
            if t[1].image_url and not t[1].is_hidden_gem and t[1].id not in taken
        ],
        key=lambda t: (t[2], t[1].name),
    )
    # 2026-08-01 결정 2(오케스트레이터): 종전 `sample_preferred(take=photo_budget)` +
    # `trim_photo_candidates` 조합은 **후보 풀이 사진 예산(=ceil(1.5×limit)) 이하이면 표본이
    # 결정적으로 퇴화**했다(풀 전체를 뽑아 선호순 복원 후 앞 limit 개 절삭 → 매 요청 같은 결과).
    # 그 계절 예측 데이터를 가진 숨은 스팟이 적은 지역에서 성립한다. 확정 후보를 먼저 뽑는다.
    hidden_primary, hidden_spares = sampling.sample_with_spares(
        [hidden_tier1, hidden_tier2, hidden_tier3],
        limit,
        sampling.make_rng(seed, f"seasonal:{season}:hidden"),
        has_seed_photo=lambda t: bool(t[1].image_url),
        group_key=(lambda t: t[0]) if region_cap is not None else None,
        group_cap=region_cap or 1,
    )
    hidden_pool = hidden_primary + hidden_spares

    popular, hidden = await asyncio.gather(
        _to_cards(popular_pool, cache),
        # 노출 개수는 확정 후보 수 기준(여유분은 사진 없는 자리를 대신할 때만 들어간다).
        _to_cards(hidden_pool, cache, take=len(hidden_primary)),
    )

    response = SeasonalResponse(
        season=season,  # type: ignore[arg-type]
        label=label,
        popular=popular,
        hidden=hidden,
        meta=SeasonalMeta(notice=NOTICE_FORECAST.format(label=label), basis="forecast"),
    )
    # 응답은 캐시하지 않는다 — hidden 이 매 요청 다른 표본이어야 하기 때문이다.
    # 비용은 위의 후보 풀 캐시가 막는다(원천 호출 횟수 불변).
    return response
