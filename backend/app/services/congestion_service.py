"""전광판 서비스 — 정규화된 레코드를 계약 응답으로 조립.

책임:
  - congestion_level 판정(백엔드 단독 소유, 계약 §1.4)
  - 혼잡도 내림차순 정렬 + rank 부여 + TOP N 절삭
  - RepoResult 메타 → BoardMeta 매핑
프론트는 레벨을 재판정하지 않는다(판정 단일 소유).
"""

from __future__ import annotations

from datetime import timedelta

from ..repositories.congestion_repo import (
    CongestionRecord,
    ForecastResult,
    RepoResult,
    SpotForecastRecord,
)
from ..schemas.congestion import (
    BoardItem,
    BoardMeta,
    BoardResponse,
    CongestionLevel,
    ForecastDay,
    ForecastMeta,
    ForecastRegion,
    ForecastResponse,
    RegionInfo,
    SpotForecast,
)
from ..util.names import name_matches, norm_name
from ..util.time import now_kst, to_iso_kst

# 계약 §1.4 기본 임계
LEVEL_HIGH = 70.0
LEVEL_MID = 40.0

LIMIT_MIN = 1
LIMIT_MAX = 50

# --- 부록 M: 한적한 날 예보 ---
FORECAST_DAYS_DEFAULT = 14
FORECAST_DAYS_MIN = 1
FORECAST_DAYS_MAX = 35   # 계약 상한. 원천 실측 커버리지는 17일이라 실제로는 그만큼만 온다.
FORECAST_SPOT_LIMIT = 10  # spot_name 미지정 시 전광판 상위 N곳

# 정직 고지: 원천은 '예측' 데이터다(실측 방문자 수가 아니다). 원천 응답·데이터셋 설명에서
# 산출 기반 통신사를 확인하지 못했으므로 특정 사업자명은 쓰지 않는다(추측 금지).
FORECAST_NOTICE = (
    "한국관광공사 관광지별 방문자 집중률 '예측치'입니다. 실측 방문자 수가 아니며 참고용입니다."
)


def classify_level(rate: float | None) -> CongestionLevel:
    if rate is None:
        return "unknown"
    if rate >= LEVEL_HIGH:
        return "high"
    if rate >= LEVEL_MID:
        return "mid"
    return "low"


def clamp_limit(limit: int) -> int:
    if limit < LIMIT_MIN:
        return LIMIT_MIN
    if limit > LIMIT_MAX:
        return LIMIT_MAX
    return limit


def _sort_key(rec: CongestionRecord) -> float:
    # rate 없는 항목은 맨 뒤로
    return rec.congestion_rate if rec.congestion_rate is not None else -1.0


def build_board_response(
    area_cd: str,
    sigungu_cd: str | None,
    limit: int,
    result: RepoResult,
) -> BoardResponse:
    limit = clamp_limit(limit)

    ordered = sorted(result.records, key=_sort_key, reverse=True)[:limit]
    items: list[BoardItem] = [
        BoardItem(
            rank=idx + 1,
            spot_name=rec.spot_name,
            congestion_rate=rec.congestion_rate,
            congestion_level=classify_level(rec.congestion_rate),
            base_date=rec.base_date,
        )
        for idx, rec in enumerate(ordered)
    ]

    region = RegionInfo(
        area_cd=area_cd,
        sigungu_cd=sigungu_cd,
        area_name=result.area_name,
    )

    meta = BoardMeta(
        source="kto_tats_cnctr_rate",
        fetched_at=to_iso_kst(result.fetched_at),
        cache=result.cache,  # type: ignore[arg-type]
        is_stale=result.is_stale,
        degraded=result.degraded,
        notice=result.notice,
    )

    return BoardResponse(region=region, items=items, meta=meta)


# ---------------------------------------------------------------------------
# 부록 M — 한적한 날 예보 (forecast)
# 원천이 관광지마다 주는 미래 날짜(baseYmd) 행들을 시계열로 노출하고, 그중 가장 한산한 날/
# 붐비는 날을 뽑아준다. 레벨 판정은 위 classify_level 재사용(재정의 금지).
# ---------------------------------------------------------------------------


def clamp_days(days: int) -> int:
    if days < FORECAST_DAYS_MIN:
        return FORECAST_DAYS_MIN
    if days > FORECAST_DAYS_MAX:
        return FORECAST_DAYS_MAX
    return days


def forecast_window(days: int) -> tuple[str, str]:
    """오늘(KST) 포함 days 일 윈도우의 [시작, 끝] ISO 날짜. (spot_detail 의 visit_tip 도 재사용)"""
    today = now_kst().date()
    return today.isoformat(), (today + timedelta(days=days - 1)).isoformat()


def _daily_in_window(rec: SpotForecastRecord, start: str, end: str) -> list[ForecastDay]:
    """윈도우 안에 있는 원천 날짜만 ForecastDay 로. 없는 날짜를 채워 넣지 않는다."""
    return [
        ForecastDay(date=p.date, index=p.rate, level=classify_level(p.rate))
        for p in rec.points
        if start <= p.date <= end
    ]


def pick_best_worst(
    daily: list[ForecastDay],
) -> tuple[ForecastDay | None, ForecastDay | None]:
    """가장 한산한 날 / 가장 붐비는 날. 비교할 날이 2일 미만이면 (None, None).

    동률이면 **빠른 날짜**를 택한다(daily 는 날짜 오름차순이므로 min/max 의 first-wins 성질 이용).
    """
    if len(daily) < 2:
        return None, None
    best = min(daily, key=lambda d: d.index)
    worst = max(daily, key=lambda d: d.index)
    return best, worst


def build_spot_forecast(
    rec: SpotForecastRecord, start: str, end: str
) -> SpotForecast:
    daily = _daily_in_window(rec, start, end)
    best, worst = pick_best_worst(daily)
    return SpotForecast(spot_name=rec.spot_name, daily=daily, best_day=best, worst_day=worst)


def select_spots(
    result: ForecastResult,
    spot_name: str | None,
    start: str,
    limit: int,
) -> list[SpotForecastRecord]:
    """응답에 담을 관광지 선택.

    - spot_name 지정: 이름매칭(정확일치 우선 → 부분일치). 매치 없으면 빈 리스트(억지 매칭 금지).
    - 미지정: 윈도우 첫날(=전광판 기준일) 집중률 내림차순 상위 limit — 전광판 정렬과 같은 규칙.
    """
    if spot_name:
        q = norm_name(spot_name)
        exact = [s for s in result.spots if norm_name(s.spot_name) == q]
        if exact:
            return exact[:limit]
        return [s for s in result.spots if name_matches(q, norm_name(s.spot_name))][:limit]

    def first_day_rate(s: SpotForecastRecord) -> float:
        for p in s.points:
            if p.date >= start:
                return p.rate
        return -1.0  # 윈도우 내 데이터가 없으면 뒤로

    return sorted(result.spots, key=first_day_rate, reverse=True)[:limit]


def build_forecast_response(
    region_code: str,
    region_name: str | None,
    spot_name: str | None,
    days: int,
    result: ForecastResult,
    limit: int = FORECAST_SPOT_LIMIT,
) -> ForecastResponse:
    days = clamp_days(days)
    start, end = forecast_window(days)

    selected = select_spots(result, spot_name, start, limit)
    spots = [build_spot_forecast(rec, start, end) for rec in selected]
    # 윈도우 안에 원천 날짜가 하나도 없는 관광지는 담지 않는다(빈 daily 카드 방지).
    spots = [s for s in spots if s.daily]

    notice = FORECAST_NOTICE if not result.notice else f"{result.notice} {FORECAST_NOTICE}"
    meta = ForecastMeta(
        source="kto_tats_cnctr_rate",
        fetched_at=to_iso_kst(result.fetched_at),
        cache=result.cache,  # type: ignore[arg-type]
        is_stale=result.is_stale,
        degraded=result.degraded,
        days=days,
        notice=notice,
    )
    region = ForecastRegion(
        region_code=region_code,
        region_name=region_name or result.area_name,
    )
    return ForecastResponse(region=region, spots=spots, meta=meta)
