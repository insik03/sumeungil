"""응답 Pydantic 모델 = 01-interface-contract.md §1.2 / §2.1 의 코드화.

계약이 정본이다. 필드 추가는 additive(계약 버전 minor), 삭제/타입변경은 breaking.
enum 값은 항상 영문 소문자. 한국어 라벨/% 표기는 프론트가 처리.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CongestionLevel = Literal["high", "mid", "low", "unknown"]


class RegionInfo(BaseModel):
    area_cd: str
    sigungu_cd: str | None = None
    area_name: str | None = None


class BoardItem(BaseModel):
    rank: int
    spot_name: str
    congestion_rate: float | None = None
    congestion_level: CongestionLevel
    base_date: str | None = None


class BoardMeta(BaseModel):
    source: str = "kto_tats_cnctr_rate"
    fetched_at: str
    cache: Literal["hit", "miss"]
    is_stale: bool = False
    degraded: bool = False
    notice: str | None = None


class BoardResponse(BaseModel):
    region: RegionInfo
    items: list[BoardItem]
    meta: BoardMeta


# --- 한적한 날 예보 (부록 M) ---
# GET /api/v1/congestion/forecast. board(§1)와 **별도 계약**이며 board 스키마는 불변이다.
# 원천이 주는 미래 날짜(baseYmd)별 행을 그대로 시계열로 노출한다 — 없는 날짜는 응답에 없다.


class ForecastDay(BaseModel):
    date: str                     # "YYYY-MM-DD" (원천 baseYmd 정규화)
    index: float                  # 0~100 원천 집중률(레벨 판정 전 원값)
    level: CongestionLevel        # §1.4 classify_level 재사용(프론트 재판정 금지)


class SpotForecast(BaseModel):
    spot_name: str
    daily: list[ForecastDay] = Field(default_factory=list)  # 날짜 오름차순, 원천에 있는 날만
    best_day: ForecastDay | None = None    # daily 중 index 최저(동률이면 빠른 날짜). daily<2 면 null
    worst_day: ForecastDay | None = None   # daily 중 index 최고(동률이면 빠른 날짜). daily<2 면 null


class ForecastRegion(BaseModel):
    region_code: str
    region_name: str | None = None


class ForecastMeta(BaseModel):
    source: str = "kto_tats_cnctr_rate"
    fetched_at: str
    cache: Literal["hit", "miss"] = "miss"
    is_stale: bool = False
    degraded: bool = False
    days: int = 14                # 실제 적용된 조회 윈도우(clamp 후)
    notice: str | None = None     # 예측치 고지(항상 존재). stale 이면 앞에 폴백 문구가 붙는다


class ForecastResponse(BaseModel):
    region: ForecastRegion
    spots: list[SpotForecast] = Field(default_factory=list)  # 데이터 없으면 [] (에러 아님)
    meta: ForecastMeta


# --- 헬스 ---


class HealthChecks(BaseModel):
    config: Literal["ok", "fail"] = "ok"
    upstream_kto: Literal["ok", "unknown", "fail"] = "unknown"
    cache: Literal["ok", "fail"] = "ok"


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str = "mvp-1"
    checks: HealthChecks
    time: str


# --- 에러 봉투 (§3) ---


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
