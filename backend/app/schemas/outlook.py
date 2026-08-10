"""부록 Q 응답 모델 — 전국 날씨 보드 / 출발일 조회 / 계절 추천.

계약이 정본이다(01-interface-contract.md 부록 Q). 필드명은 프론트와 합의된 고정값이라
바꾸지 않는다. 모든 문구(tip/summary/notice)는 **서버 고정 템플릿 + 실측 수치**만 쓴다
— 외부 문자열·LLM 문장을 넣지 않는다(인젝션 안전, 부록 F.1-6 규칙 승계).

정직 표기 원칙:
  available=false 면 수치 필드는 전부 null 이고 notice 에 사유가 들어간다. 값을 지어내지 않는다.
  basis 는 "그 숫자가 어디서 왔는지"를 프론트가 그대로 노출할 수 있게 하는 라벨이다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .places import FeaturedSpot, RecommendRegion

# 날씨 근거: forecast=기상청 실예보 / none=미제공(예보 커버 밖 또는 원천 실패)
#   ※ 평년값(normal) 경로는 채택하지 않았다 — 같은 키로 접근 가능한 평년/중기 원천이 없다.
WeatherBasis = Literal["forecast", "none"]
# 혼잡도 근거: forecast=KTO 예측 커버 안 / last_year=작년 같은 시기 실측 / none=미제공
#   ※ last_year 는 **계약상 정의만 존재**한다. 현재 접근 가능한 원천에 과거 데이터가 없어
#     서버는 이 값을 만들어내지 않는다(원천 확보 시 그대로 켜지도록 자리를 비워 둔다).
CongestionBasis = Literal["forecast", "last_year", "none"]
WeatherVerdict = Literal["good", "fair", "poor"]
Season = Literal["spring", "summer", "autumn", "winter"]


# ---------- Q.1 전국 9권역 날씨 보드 ----------

class NationwideRegionWeather(BaseModel):
    key: str                       # 권역 고정 키(regions/nationwide.py)
    label: str                     # 권역 표시명
    region_code: str               # 대표 시군구 법정동 5자리(그 지역 화면으로 이동 가능)
    available: bool = False
    pop: int | None = None         # 강수확률 %. available=false 면 null
    temp_c: float | None = None    # 기온 ℃. 원천에 없으면 available=true 여도 null
    verdict: WeatherVerdict | None = None
    tip: str | None = None         # verdict → 서버 고정 문구
    notice: str | None = None      # 미가용 사유(정형 문구)


class NationwideWeatherResponse(BaseModel):
    as_of: str                     # "YYYY-MM-DD" (KST 오늘)
    regions: list[NationwideRegionWeather] = Field(default_factory=list)  # 항상 9개


# ---------- Q.2 출발일 지정 조회 ----------

class OutlookWeather(BaseModel):
    available: bool = False
    basis: WeatherBasis = "none"
    pop: int | None = None
    temp_c: float | None = None
    summary: str | None = None     # 근거가 드러나는 서버 고정 문구
    notice: str | None = None


class OutlookCongestion(BaseModel):
    available: bool = False
    basis: CongestionBasis = "none"
    level: Literal["low", "mid", "high", "unknown"] = "unknown"
    index: int | None = None       # 0~100 (그 날짜 지역 평균 집중률, 반올림)
    summary: str | None = None
    notice: str | None = None


class OutlookMeta(BaseModel):
    notice: str | None = None


class OutlookResponse(BaseModel):
    region: RecommendRegion
    date: str                      # "YYYY-MM-DD"
    days_ahead: int                # 오늘(KST) 기준 남은 일수(오늘=0)
    weather: OutlookWeather
    congestion: OutlookCongestion
    meta: OutlookMeta


# ---------- Q.3 계절 추천 ----------

class SeasonalMeta(BaseModel):
    notice: str | None = None
    basis: CongestionBasis = "none"


class SeasonalResponse(BaseModel):
    """아이템 모델은 **부록 H 의 FeaturedSpot 을 그대로 재사용**한다(2026-07-31 프론트 합의).

    홈의 FeaturedSpotCard 컴포넌트를 계절 카드에 그대로 쓰기 위해서다 — 사진(image_url·
    photo_credit)·지역명·숨은명소 여부·혼잡도가 모두 필요하다. 신규 카드 모델을 만들지 않는다.
    """

    season: Season
    label: str                     # "봄"|"여름"|"가을"|"겨울"
    popular: list[FeaturedSpot] = Field(default_factory=list)  # 그 계절 혼잡도 상위
    hidden: list[FeaturedSpot] = Field(default_factory=list)   # 그 계절 혼잡도 하위(숨은 명소)
    meta: SeasonalMeta
