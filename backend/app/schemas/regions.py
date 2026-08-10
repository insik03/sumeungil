"""GET /api/v1/regions/search 응답 모델 = 계약 부록 A.1 코드화.

프론트는 items[].area_cd / sigungu_cd 를 그대로 board 요청에 넘긴다
(프론트가 코드를 지어내지 않는다 — 코드 소유는 backend).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RegionSearchItem(BaseModel):
    region_id: str   # 내부 식별자(= sigungu_cd 문자열, 안정적)
    label: str       # 화면 표시용 full name
    area_cd: str     # board 호출에 넘길 시도코드
    sigungu_cd: str  # board 호출에 넘길 시군구코드


class RegionSearchResponse(BaseModel):
    query: str
    items: list[RegionSearchItem]


# ---------- 부록 Y — 시도 → 시군구 목록 (GET /api/v1/regions/children) ----------
# 지역 허브가 "시도를 고르면 그 시도 전체"로 바뀌면서, 프론트가 **시군구 드롭다운**을 그리려면
# 그 시도에 실제로 조회 가능한 시군구가 무엇인지 알아야 한다. 프론트가 코드를 지어내지 않는다는
# 원칙(A.1)은 그대로다 — region_code 는 여기서 받은 값을 그대로 featured/festivals 에 넘긴다.

class RegionChildItem(BaseModel):
    region_code: str   # = sigungu_cd(법정동 5자리). 그대로 region_code 파라미터로 쓴다
    label: str         # seed 표기 그대로(예: "경기도 가평군") — 지어내지 않는다
    spot_count: int    # 로컬 스토어 스팟 수. **1 이상인 시군구만** 내려간다


class RegionChildrenResponse(BaseModel):
    area_cd: str
    # 시도 짧은 표기(예: "경기"). 사전에 없는 시도코드면 null — 라벨을 지어내지 않는다.
    label: str | None = None
    items: list[RegionChildItem] = Field(default_factory=list)  # 0건이면 [] + 200(에러 아님)
