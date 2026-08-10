"""부록 U — 전국 시도 혼잡도 보드 응답 스키마 (2026-08-01).

`available=false` 인 항목은 index/level 이 **null 이다**(0 이 아니다) — 데이터가 없다는 뜻과
한산하다는 뜻을 섞지 않는다. 프론트는 이 둘을 다른 색으로 그린다(회색 vs 파랑).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

CongestionLevel = Literal["low", "mid", "high"]


class NationwideCongestionItem(BaseModel):
    sido_code: str                       # 법정동 시도 2자리(= area_cd)
    short_name: str                      # 화면 표기용 짧은 시도명("서울", "경기" …)
    region_code: str                     # 이 값을 낸 **대표 시군구** 코드(클릭 시 이동 대상)
    basis_region_name: str | None = None  # 예: "서울특별시 종로구" — 화면에 반드시 표기
    available: bool = False
    index: float | None = None           # 상위 스팟 집중률 평균(0~100). 없으면 null
    level: CongestionLevel | None = None
    sample_count: int = 0                # 평균에 쓴 스팟 수(근거 투명성)
    # ★ 2026-08-01 additive — 그 지역의 **실제 관광 사진**(한국관광공사 TourAPI firstimage).
    # 사진에 찍힌 곳의 이름을 함께 준다 — 화면이 "무엇을 보여주는지" 정확히 밝히기 위해서다.
    # 없으면 둘 다 null(다른 지역 사진으로 채우지 않는다).
    photo_spot_name: str | None = None
    photo_url: str | None = None


class NationwideCongestionResponse(BaseModel):
    items: list[NationwideCongestionItem]
    fetched_at: str
    notice: str | None = None
