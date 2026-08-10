"""MVP-7 rerank 레이어 (부록 F.1-4 / F.4-4) — 스코어링 **이후** 순서만 조정.

08 §3 불변식: **페널티/재정렬은 이 레이어에서 단 1회**. match_score(스코어링)는 절대
재계산하지 않는다 — 두 함수 모두 items 의 **순서만** 바꾸고 SpotCard 필드는 손대지 않는다.

결합 순서(F.4-4, 08 §15.8.1 승계):
  [1] recommend 스코어링(match_score 내림차순)   ← 순수, 페널티 없음
  [2] apply_balance_rerank      ← 혼잡 분산(단 1회)
  [2.5] apply_weather_rerank    ← 파트1 결과 안에서만 실내 부스트(단 1회, 혼잡 스팟으로 되돌리지 않음)

인젝션 안전(F.1-6/F.4-6): notice 에는 **수치·정형문구만**. 스팟명은 절대 넣지 않는다 —
이름은 congested/boosted_spot_ids 로 구조화 전달, 프론트가 items 에서 찾아 텍스트 노드로 렌더.
"""

from __future__ import annotations

from ..schemas.places import (
    RerankDistribution,
    RerankWeather,
    SpotCard,
    WeatherBand,
)
from .weather_provider import WeatherSnapshot

# 파트1: §1.4 high 임계 재사용(가정값 70)
THRESHOLD_HIGH = 70
# 파트4: 08 §15.8.3 가정 임계(backend 실측 후 보정 여지)
THRESHOLD_SOFT = 30
THRESHOLD_ADVISE = 60

# F.4-4 실내/실외 판별 — SpotCard.category(C.2.1) 기반(스팟 단위엔 course_tag_vector 없음)
OUTDOOR_CATEGORIES = frozenset({"nature", "trail", "attraction"})
INDOOR_CATEGORIES = frozenset({"cafe", "craft", "market", "restaurant"})

# 정형 안내 문구(수치·정형만, 스팟명 없음)
_NOTICE_BALANCE = "붐비는 곳 대신 혼잡도가 낮은 대안을 위로 올렸어요."
# 2026-08-01(대표 지적) — 위로 올린 대안 중에 **혼잡도 미상**이 섞이면 위 문구는 거짓이다.
# 실측(운영 부산 해운대, 비개인화): 상위 2곳이 congestion=null 인데 "혼잡도가 낮은 대안"이라고
# 표기했다. 미상은 낮음이 아니다 — 모르는 걸 안다고 말하지 않는다.
_NOTICE_BALANCE_MIXED = (
    "지금 붐비는 곳을 아래로 내렸어요. 위쪽에는 혼잡도가 낮거나 아직 확인되지 않은 곳이 있어요."
)
_NOTICE_AMBER = "인기 지점이 다소 붐벼 여유로운 대안을 함께 배치했어요."
_NOTICE_NO_ALT = "이 지역은 전반적으로 붐빕니다. 시간대를 여유롭게 잡아보세요."
_NOTICE_WEATHER_PREP = "날씨 정보 준비중"


def _is_high(card: SpotCard) -> bool:
    return card.congestion is not None and card.congestion.level == "high"


def _is_mid(card: SpotCard) -> bool:
    return card.congestion is not None and card.congestion.level == "mid"


# ---------- 파트1: 혼잡 분산 rerank ----------

def apply_balance_rerank(items: list[SpotCard]) -> tuple[list[SpotCard], RerankDistribution]:
    """혼잡(high) 스팟을 아래로, 저혼잡 대안을 위로 **단 1회** 재배치. match_score 불변.

    반환: (재정렬된 items, RerankDistribution). 원본 리스트는 변형하지 않는다.
    """
    dist = RerankDistribution(threshold_high=THRESHOLD_HIGH)
    if not items:
        return items, dist

    high = [c for c in items if _is_high(c)]
    non_high = [c for c in items if not _is_high(c)]

    # 대안 없음 정직 처리(F.1-4): 전부 high → 강등 안 함, 목록 안 비움
    if high and not non_high:
        dist.applied = False
        dist.reason = "no_alternative"
        dist.congested_spot_ids = [c.id for c in high]
        dist.notice = _NOTICE_NO_ALT
        return list(items), dist

    if high:
        # low/mid/unknown 대안이 실재 → 저혼잡 먼저, high 를 뒤로(각 그룹 내부 순서 보존)
        reordered = non_high + high
        moved = _diff_moves(items, reordered)
        if not moved:  # 이미 high 가 전부 하단 → 순서 변화 없음
            dist.applied = False
            return list(items), dist
        old_pos = {c.id: i for i, c in enumerate(items)}
        new_pos = {c.id: i for i, c in enumerate(reordered)}
        dist.applied = True
        dist.reason = "primary_over_threshold"
        dist.congested_spot_ids = [c.id for c in high if new_pos[c.id] > old_pos[c.id]]
        boosted = [c for c in non_high if new_pos[c.id] < old_pos[c.id]]
        dist.boosted_spot_ids = [c.id for c in boosted]
        # 위로 올린 것 중 혼잡도를 **모르는** 스팟이 하나라도 있으면 "낮은 대안"이라고 하지 않는다.
        has_unknown = any(
            c.congestion is None or c.congestion.level is None for c in boosted
        )
        dist.notice = _NOTICE_BALANCE_MIXED if has_unknown else _NOTICE_BALANCE
        return reordered, dist

    # high 없음 — AMBER(mid) 소프트 분산: 상단이 mid 이고 아래에 mid 아닌 여유 대안이 있으면 1회
    if items and _is_mid(items[0]):
        calm = [c for c in items if not _is_mid(c)]
        mids = [c for c in items if _is_mid(c)]
        if calm:  # 여유 대안 실재
            reordered = calm + mids
            moved = _diff_moves(items, reordered)
            if moved:
                old_pos = {c.id: i for i, c in enumerate(items)}
                new_pos = {c.id: i for i, c in enumerate(reordered)}
                dist.applied = True
                dist.reason = "primary_amber_distributed"
                dist.congested_spot_ids = [c.id for c in mids if new_pos[c.id] > old_pos[c.id]]
                dist.boosted_spot_ids = [c.id for c in calm if new_pos[c.id] < old_pos[c.id]]
                dist.notice = _NOTICE_AMBER
                return reordered, dist

    # 분산할 혼잡 없음 → 순서 유지, applied False(reason 없음)
    dist.applied = False
    return list(items), dist


# ---------- 파트4: 날씨 rerank ----------

def _band_for(pop: int | None) -> WeatherBand:
    if pop is None:
        return "unknown"
    if pop < THRESHOLD_SOFT:
        return "clear"
    if pop < THRESHOLD_ADVISE:
        return "soft"
    return "advise_indoor"


def apply_weather_rerank(
    items: list[SpotCard], snapshot: WeatherSnapshot | None,
) -> tuple[list[SpotCard], RerankWeather]:
    """비 예보(POP≥advise)일 때 실내 카테고리를 위로 **단 1회**. 파트1 결과 안에서만.

    혼잡 불변식 보존: high 혼잡 스팟은 절대 위로 올리지 않는다(하단 고정). 실내 부스트는
    high 아닌 풀 안에서만 일어난다 → 날씨 때문에 혼잡한 곳으로 되돌아가지 않는다(F.4-4).
    반환: (재정렬된 items, RerankWeather). match_score 불변.
    """
    wx = RerankWeather(threshold_soft=THRESHOLD_SOFT, threshold_advise=THRESHOLD_ADVISE)

    if snapshot is None:
        # 데이터 없음 → 정직 표기, 재정렬 스킵(기능은 정상)
        wx.provider_status = "unavailable"
        wx.band = "unknown"
        wx.precip_probability = None
        wx.notice = _NOTICE_WEATHER_PREP
        return list(items), wx

    pop = snapshot.precip_probability
    wx.provider_status = "ok"
    wx.precip_probability = pop
    wx.band = _band_for(pop)

    if wx.band in ("clear", "unknown"):
        # 맑음/판정불가 → 재정렬 없음(배지만)
        return list(items), wx

    if wx.band == "soft":
        # 과잉개입 방지: 순위 변경 없음, 우산 안내만(수치만)
        wx.notice = f"강수확률 {pop}% — 우산을 챙기세요."
        return list(items), wx

    # advise_indoor: high 는 하단 고정, high 아닌 풀에서만 실내 우선 안정 정렬
    high = [c for c in items if _is_high(c)]
    pool = [c for c in items if not _is_high(c)]
    has_outdoor = any(c.category in OUTDOOR_CATEGORIES for c in pool)
    indoor = [c for c in pool if c.category in INDOOR_CATEGORIES]

    if not (has_outdoor and indoor):
        # 실내 대안 없음(또는 실외 없음) → 스왑 안 함, 고지만
        wx.applied = False
        wx.notice = f"강수확률 {pop}%로 비 예보지만 실내 대안이 없어 순서를 유지했어요."
        return list(items), wx

    # 실내 먼저(안정), 그 외(실외·중립) 뒤 — pool 내부만. high 는 그대로 뒤에 이어붙임
    non_indoor = [c for c in pool if c.category not in INDOOR_CATEGORIES]
    reordered = indoor + non_indoor + high
    moved = _diff_moves(items, reordered)
    if not moved:
        wx.applied = False
        wx.notice = f"강수확률 {pop}% — 실내 스팟이 이미 상위에 있어요."
        return list(items), wx

    old_pos = {c.id: i for i, c in enumerate(items)}
    new_pos = {c.id: i for i, c in enumerate(reordered)}
    boosted_cats = sorted(
        {c.category for c in indoor if new_pos[c.id] < old_pos[c.id]}
    )
    wx.applied = True
    wx.boosted_categories = boosted_cats
    wx.notice = f"강수확률 {pop}%로 실내 스팟을 먼저 보여드려요."
    return reordered, wx


def _diff_moves(a: list[SpotCard], b: list[SpotCard]) -> bool:
    """두 리스트의 id 순서가 다르면 True(실제 재배치 발생)."""
    return [c.id for c in a] != [c.id for c in b]
