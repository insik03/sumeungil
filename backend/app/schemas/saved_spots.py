"""저장한 스팟(계정 보관함) 스키마 — 2026-09-16. 프론트 SavedSpot(savedSpotsStorage.ts)과 같은 모양."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SavedCongestionSnapshot(BaseModel):
    """저장 시점의 혼잡도 스냅샷(프론트 SpotCongestion 축약). 값을 재판정하지 않고 그대로 보관한다."""

    index: float | None = None
    level: Literal["high", "mid", "low", "unknown"] = "unknown"
    tier: Literal["A", "B", "C", "none"] = "none"


class SaveSpotRequest(BaseModel):
    congestion: SavedCongestionSnapshot | None = None


class SavedSpotItem(BaseModel):
    id: int
    name: str
    category: str
    region_code: str
    location: dict[str, float] | None
    congestion: SavedCongestionSnapshot | None
    is_hidden_gem: bool
    saved_at: str


class SavedSpotListResponse(BaseModel):
    items: list[SavedSpotItem] = Field(default_factory=list)
