"""저장한 스팟(계정 보관함) API — 2026-09-16 대표 지시
"저장한 스팟도 브라우저나 기기가 아닌 그 계정의 데이터로서 저장".

  GET    /api/v1/saved-spots            내 저장 목록(로그인 필수). 스팟 본문은 스토어에서 재구성
  PUT    /api/v1/saved-spots/{spot_id}  저장(멱등 upsert). 본문은 혼잡도 스냅샷뿐 — 나머지는 id 만 신뢰
  DELETE /api/v1/saved-spots/{spot_id}  해제(멱등, 없어도 204)

프론트(savedSpotsStorage.ts)는 localStorage 를 캐시로만 쓰고, 로그인 상태면 이 API 가 정본이다.
비로그인 저장은 종전대로 기기 로컬에만 남고, 로그인 시 한 번 여기로 합쳐진다.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Response

from ..db.postgres import Database
from ..deps import get_database, get_spot_repository
from ..repositories import saved_spot_repo
from ..repositories.spot_repo import SpotRecord, SpotRepository
from ..schemas.saved_spots import (
    SavedCongestionSnapshot,
    SavedSpotItem,
    SavedSpotListResponse,
    SaveSpotRequest,
)
from ..security.user_auth import UserIdentity
from ..util.time import now_kst, to_iso_kst
from .auth_deps import require_login
from .community_common import error_response

router = APIRouter(prefix="/api/v1/saved-spots", tags=["saved-spots"])


def _to_item(spot: SpotRecord, row: dict) -> SavedSpotItem:
    snapshot = None
    if row.get("congestion"):
        try:
            snapshot = SavedCongestionSnapshot.model_validate(json.loads(row["congestion"]))
        except Exception:  # noqa: BLE001 — 손상 스냅샷은 없는 것으로(지어내지 않음)
            snapshot = None
    return SavedSpotItem(
        id=spot.id,
        name=spot.name,
        category=spot.category,
        region_code=spot.region_code,
        location={"lat": spot.lat, "lng": spot.lng},
        congestion=snapshot,
        is_hidden_gem=spot.is_hidden_gem,
        saved_at=row["saved_at"],
    )


@router.get("", response_model=SavedSpotListResponse)
async def list_saved_spots(
    db: Database = Depends(get_database),
    identity: UserIdentity = Depends(require_login),
    spot_repo: SpotRepository = Depends(get_spot_repository),
):
    rows = await db.aread(lambda conn: saved_spot_repo.list_by_user(conn, user_id=identity.user_id))
    items: list[SavedSpotItem] = []
    for row in rows:
        spot = spot_repo.by_id(int(row["spot_id"]))
        if spot is None:
            continue  # 시드에서 사라진 스팟은 조용히 제외(재수집 뒤 되살아날 수 있어 행은 남긴다)
        items.append(_to_item(spot, row))
    return SavedSpotListResponse(items=items)


@router.put("/{spot_id}", response_model=SavedSpotItem)
async def save_spot(
    spot_id: int,
    req: SaveSpotRequest,
    db: Database = Depends(get_database),
    identity: UserIdentity = Depends(require_login),
    spot_repo: SpotRepository = Depends(get_spot_repository),
):
    spot = spot_repo.by_id(spot_id)
    if spot is None:
        return error_response(404, "SPOT_NOT_FOUND", "해당 스팟을 찾을 수 없습니다.")
    count = await db.aread(lambda conn: saved_spot_repo.count_by_user(conn, user_id=identity.user_id))
    if count >= saved_spot_repo.MAX_PER_USER:
        return error_response(409, "SAVED_LIMIT", f"저장은 계정당 {saved_spot_repo.MAX_PER_USER}곳까지예요.")
    congestion_json = req.congestion.model_dump_json() if req.congestion else None
    row = await db.awrite(
        lambda conn: saved_spot_repo.upsert(
            conn,
            user_id=identity.user_id,
            spot_id=spot_id,
            congestion_json=congestion_json,
            now_iso=to_iso_kst(now_kst()),
        )
    )
    return _to_item(spot, row)


@router.delete("/{spot_id}", status_code=204)
async def unsave_spot(
    spot_id: int,
    db: Database = Depends(get_database),
    identity: UserIdentity = Depends(require_login),
):
    await db.awrite(lambda conn: saved_spot_repo.delete(conn, user_id=identity.user_id, spot_id=spot_id))
    return Response(status_code=204)
