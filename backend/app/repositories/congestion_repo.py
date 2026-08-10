"""혼잡도 데이터 리포지토리.

경계(boundary)의 목적: 읽기 경로가 '데이터를 어디서 얻는지'를 감춘다.
  - MVP-1:  LiveCongestionRepository — 공공 API fetch-on-miss + 인메모리 캐시
  - 상용:   DbCongestionRepository  — 배치가 채운 congestion_snapshots 테이블 read
둘 다 동일한 get_board() 시그니처/RepoResult 를 반환하므로 엔드포인트·응답 계약은 불변.

원천 API는 '예측' 데이터라 관광지별로 여러 미래 날짜(baseYmd) 행을 준다.
전광판은 '오늘에 가장 가까운 날짜' 한 벌만 골라 관광지별 1행으로 정규화한다.
**예보(get_forecast)는 그 버려지던 미래 날짜 행들을 관광지별 시계열로 살려 쓴다**
(실측 17일치 — kto_client 모듈 docstring 참고). board 와 캐시 키·TTL 이 분리돼 있어
전광판 동작은 완전히 불변이다.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from ..cache.base import Cache
from ..clients import kto_client
from ..clients.kto_client import KtoUpstreamError
from ..util.time import KST, today_yyyymmdd

logger = logging.getLogger("sumeungil.repo")


@dataclass
class CongestionRecord:
    """정규화된 관광지 혼잡도 1건 (레벨 판정 전, 정렬 전)."""

    spot_name: str
    congestion_rate: float | None
    base_date: str | None  # ISO date "YYYY-MM-DD" 또는 None


@dataclass
class RepoResult:
    """리포지토리 조회 결과 + 신선도 메타."""

    records: list[CongestionRecord]
    area_name: str | None
    fetched_at: datetime
    cache: str = "miss"          # "hit" | "miss"
    is_stale: bool = False       # 원천 재호출 실패로 옛 데이터 제공 중
    degraded: bool = False       # 원천 장애로 축소/폴백
    notice: str | None = None


@dataclass
class ForecastPoint:
    """관광지 예보 1일치. rate 는 원천 cnctrRate 파싱 성공분만 담는다(없는 날은 아예 제외)."""

    date: str    # ISO date "YYYY-MM-DD"
    rate: float  # 0~100


@dataclass
class SpotForecastRecord:
    """관광지 1곳의 날짜별 예보 시계열(날짜 오름차순)."""

    spot_name: str
    points: list[ForecastPoint] = field(default_factory=list)


@dataclass
class ForecastResult:
    """예보 조회 결과 + 신선도 메타 (RepoResult 와 같은 메타 규약)."""

    spots: list[SpotForecastRecord]
    area_name: str | None
    fetched_at: datetime
    cache: str = "miss"
    is_stale: bool = False
    degraded: bool = False
    notice: str | None = None


class CongestionRepository(ABC):
    @abstractmethod
    async def get_board(self, area_cd: str, sigungu_cd: str) -> RepoResult:
        """지역코드로 정규화된 혼잡도 레코드 묶음을 반환. 실패 시 KtoUpstreamError."""
        raise NotImplementedError

    @abstractmethod
    async def get_forecast(self, area_cd: str, sigungu_cd: str) -> ForecastResult:
        """지역코드로 관광지별 '날짜별' 예보 시계열을 반환. 실패 시 KtoUpstreamError."""
        raise NotImplementedError

    @abstractmethod
    def last_upstream_status(self) -> str:
        """최근 원천 호출 상태: 'ok' | 'unknown' | 'fail' (헬스체크용, 원천 재호출 안 함)."""
        raise NotImplementedError


class LiveCongestionRepository(CongestionRepository):
    """공공 API 실연동 + 캐시. fetch-on-miss."""

    def __init__(self, cache: Cache, ttl_seconds: int, forecast_ttl_seconds: int | None = None) -> None:
        self._cache = cache
        self._ttl = ttl_seconds
        # 예보 TTL 은 board 와 별도(기본은 board 와 동일값으로 하위호환).
        self._forecast_ttl = forecast_ttl_seconds if forecast_ttl_seconds is not None else ttl_seconds
        # 원천 장애 시 stale 폴백용 마지막 성공 결과 (지역별)
        self._last_good: dict[str, RepoResult] = {}
        self._last_good_forecast: dict[str, ForecastResult] = {}
        self._last_upstream: str = "unknown"

    @staticmethod
    def _key(area_cd: str, sigungu_cd: str) -> str:
        return f"congestion:{area_cd}:{sigungu_cd}"

    @staticmethod
    def _forecast_key(area_cd: str, sigungu_cd: str) -> str:
        # board 캐시와 **다른 키**: 페이로드가 다르고 TTL 도 다르다(전광판 무회귀).
        return f"congestion_forecast:{area_cd}:{sigungu_cd}"

    def last_upstream_status(self) -> str:
        return self._last_upstream

    async def get_board(self, area_cd: str, sigungu_cd: str) -> RepoResult:
        key = self._key(area_cd, sigungu_cd)

        # 1) 캐시 히트 (TTL 유효)
        cached: RepoResult | None = await self._cache.get(key)
        if cached is not None:
            # 저장된 결과 복제해 cache 상태만 hit 로
            return _with_cache_flag(cached, "hit")

        # 2) 미스 → 원천 호출
        try:
            raw = await kto_client.fetch_congestion_raw(area_cd, sigungu_cd)
            result = _normalize(raw)
            self._last_upstream = "ok"
            await self._cache.set(key, result, self._ttl)
            self._last_good[key] = result
            return _with_cache_flag(result, "miss")
        except KtoUpstreamError as exc:
            self._last_upstream = "fail"
            logger.warning("원천 실패, stale 폴백 시도: %s", exc)
            # 3) stale 폴백: 마지막 성공 결과가 있으면 그것을 degraded 로 제공
            stale = self._last_good.get(key)
            if stale is not None:
                fallback = RepoResult(
                    records=stale.records,
                    area_name=stale.area_name,
                    fetched_at=stale.fetched_at,
                    cache="hit",
                    is_stale=True,
                    degraded=True,
                    notice="최신 데이터를 불러오지 못해 이전 값을 표시합니다.",
                )
                return fallback
            # 4) 폴백도 없음 → 상위에서 502 로 변환
            raise

    async def get_forecast(self, area_cd: str, sigungu_cd: str) -> ForecastResult:
        """관광지별 날짜별 예보. board 와 동일한 캐시→원천→stale 폴백 3단 정책."""
        key = self._forecast_key(area_cd, sigungu_cd)

        cached: ForecastResult | None = await self._cache.get(key)
        if cached is not None:
            return _with_forecast_cache_flag(cached, "hit")

        try:
            raw = await kto_client.fetch_congestion_forecast_raw(area_cd, sigungu_cd)
            result = _normalize_forecast(raw)
            self._last_upstream = "ok"
            await self._cache.set(key, result, self._forecast_ttl)
            self._last_good_forecast[key] = result
            return _with_forecast_cache_flag(result, "miss")
        except KtoUpstreamError as exc:
            self._last_upstream = "fail"
            logger.warning("예보 원천 실패, stale 폴백 시도: %s", exc)
            stale = self._last_good_forecast.get(key)
            if stale is not None:
                return ForecastResult(
                    spots=stale.spots,
                    area_name=stale.area_name,
                    fetched_at=stale.fetched_at,
                    cache="hit",
                    is_stale=True,
                    degraded=True,
                    notice="최신 데이터를 불러오지 못해 이전 값을 표시합니다.",
                )
            raise


def _with_cache_flag(result: RepoResult, cache_state: str) -> RepoResult:
    return RepoResult(
        records=result.records,
        area_name=result.area_name,
        fetched_at=result.fetched_at,
        cache=cache_state,
        is_stale=result.is_stale,
        degraded=result.degraded,
        notice=result.notice,
    )


def _normalize(raw: list[dict]) -> RepoResult:
    """원천 item 리스트 → '오늘 최근접 날짜' 관광지별 1행 RepoResult.

    빈 데이터(raw=[])도 정상으로 처리 → 빈 records, degraded=False.
    """
    now = datetime.now(KST)
    if not raw:
        return RepoResult(records=[], area_name=None, fetched_at=now, cache="miss")

    area_name = _resolve_area_name(raw)

    # baseYmd 후보 중 오늘에 가장 가까운 날짜 선택
    dates = sorted({str(r.get("baseYmd", "")).strip() for r in raw if r.get("baseYmd")})
    target_date = _nearest_date(dates, today_yyyymmdd())

    records: list[CongestionRecord] = []
    seen: set[str] = set()
    for r in raw:
        if str(r.get("baseYmd", "")).strip() != target_date:
            continue
        spot = str(r.get("tAtsNm", "")).strip()
        if not spot or spot in seen:
            continue
        seen.add(spot)
        records.append(
            CongestionRecord(
                spot_name=spot,
                congestion_rate=_parse_rate(r.get("cnctrRate")),
                base_date=_fmt_date(target_date),
            )
        )

    return RepoResult(records=records, area_name=area_name, fetched_at=now, cache="miss")


def _with_forecast_cache_flag(result: ForecastResult, cache_state: str) -> ForecastResult:
    return ForecastResult(
        spots=result.spots,
        area_name=result.area_name,
        fetched_at=result.fetched_at,
        cache=cache_state,
        is_stale=result.is_stale,
        degraded=result.degraded,
        notice=result.notice,
    )


def _normalize_forecast(raw: list[dict]) -> ForecastResult:
    """원천 item 리스트 → 관광지별 날짜 시계열.

    - 날짜/수치를 **지어내지 않는다**: baseYmd 형식이 아니거나 cnctrRate 파싱 실패면 그 날짜를
      아예 빼고, 빈 날짜를 보간하지 않는다.
    - 같은 (관광지, 날짜)가 중복으로 오면 먼저 온 행을 쓴다.
    - 빈 데이터(raw=[])도 정상 → spots=[], degraded=False.
    """
    now = datetime.now(KST)
    if not raw:
        return ForecastResult(spots=[], area_name=None, fetched_at=now, cache="miss")

    area_name = _resolve_area_name(raw)

    by_spot: dict[str, dict[str, float]] = {}
    for r in raw:
        spot = str(r.get("tAtsNm", "")).strip()
        date = _fmt_date(r.get("baseYmd"))
        rate = _parse_rate(r.get("cnctrRate"))
        if not spot or date is None or rate is None:
            continue
        by_spot.setdefault(spot, {}).setdefault(date, rate)

    spots = [
        SpotForecastRecord(
            spot_name=name,
            points=[ForecastPoint(date=d, rate=points[d]) for d in sorted(points)],
        )
        for name, points in by_spot.items()
    ]
    return ForecastResult(spots=spots, area_name=area_name, fetched_at=now, cache="miss")


def _resolve_area_name(raw: list[dict]) -> str | None:
    for r in raw:
        area = str(r.get("areaNm", "")).strip()
        sigungu = str(r.get("signguNm", "")).strip()
        if area or sigungu:
            return " ".join(p for p in (area, sigungu) if p) or None
    return None


def _nearest_date(dates: list[str], today: str) -> str:
    """YYYYMMDD 문자열 중 today 에 가장 가까운 값. today 이상(미래/당일)을 우선."""
    if not dates:
        return today

    def key(d: str) -> tuple[int, int]:
        try:
            diff = abs(int(d) - int(today))
        except ValueError:
            diff = 10**9
        future = 0 if d >= today else 1  # 미래/당일 우선
        return (diff, future)

    return min(dates, key=key)


def _parse_rate(value) -> float | None:
    if value is None:
        return None
    try:
        rate = float(str(value).strip())
    except (ValueError, TypeError):
        return None
    # 0~100 클램프
    return max(0.0, min(100.0, rate))


def _fmt_date(yyyymmdd: str) -> str | None:
    s = str(yyyymmdd).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return None
