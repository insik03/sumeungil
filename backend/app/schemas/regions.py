"""GET /api/v1/regions/search 응답 모델 = 계약 부록 A.1 코드화.

프론트는 items[].area_cd / sigungu_cd 를 그대로 board 요청에 넘긴다
(프론트가 코드를 지어내지 않는다 — 코드 소유는 backend).
"""

from __future__ import annotations

from pydantic import BaseModel


class RegionSearchItem(BaseModel):
    region_id: str   # 내부 식별자(= sigungu_cd 문자열, 안정적)
    label: str       # 화면 표시용 full name
    area_cd: str     # board 호출에 넘길 시도코드
    sigungu_cd: str  # board 호출에 넘길 시군구코드


class RegionSearchResponse(BaseModel):
    query: str
    items: list[RegionSearchItem]
