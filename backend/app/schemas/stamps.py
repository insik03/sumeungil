"""방문 스탬프 스키마 — 2026-09-20. 프론트 Stamp(stampStorage.ts)와 같은 모양."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StampRequest(BaseModel):
    """브라우저 Geolocation 값. **저장하지 않고** 그 스팟과의 거리 대조에만 쓴다."""

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=1_000_000)


class StampItem(BaseModel):
    spot_id: int
    name: str
    region_code: str
    region_name: str | None
    category: str
    stamped_at: str


class StampListResponse(BaseModel):
    items: list[StampItem] = Field(default_factory=list)
