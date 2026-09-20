"""방문 스탬프(계정 보관함) API — 2026-09-20 대표 지시
"방문 스탬프는 브라우저 위치로 찍고, 기기가 아니라 계정에 저장".

  GET    /api/v1/stamps            내 스탬프(로그인 필수). 스팟 본문은 스토어에서 재구성
  POST   /api/v1/stamps/{spot_id}  현장 인증 후 스탬프(멱등). 본문 lat/lng 는 그 스팟과 거리 대조에만 쓰고 버린다
  DELETE /api/v1/stamps/{spot_id}  내 스탬프 지우기(멱등, 없어도 204)

위치정보 원칙: 좌표는 DB·로그 어디에도 남기지 않는다(저장되는 건 spot_id·찍은 시각뿐).
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Response

from ..db.postgres import Database
from ..deps import get_database, get_spot_repository
from ..repositories import visit_stamp_repo
from ..repositories.spot_repo import SpotRecord, SpotRepository
from ..schemas.stamps import StampItem, StampListResponse, StampRequest
from ..security.user_auth import UserIdentity
from ..services.spot_detail_service import _region_name
from ..util.time import now_kst, to_iso_kst
from .auth_deps import require_login
from .community_common import error_response

router = APIRouter(prefix="/api/v1/stamps", tags=["stamps"])

# 스팟 좌표 오차(관광공사 좌표 ±수십 m)와 브라우저 위치 오차(Wi-Fi/기지국 수십~수백 m)를 함께 받아 주는 반경.
STAMP_RADIUS_M = 500
# 이보다 부정확한 위치(IP 기반 등, 수 km)는 "현장"의 증거가 못 된다.
MAX_ACCURACY_M = 1000


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


def _to_item(spot: SpotRecord, row: dict) -> StampItem:
    return StampItem(
        spot_id=spot.id,
        name=spot.name,
        region_code=spot.region_code,
        region_name=_region_name(spot.region_code),
        category=spot.category,
        stamped_at=row["stamped_at"],
    )


@router.get("", response_model=StampListResponse)
async def list_stamps(
    db: Database = Depends(get_database),
    identity: UserIdentity = Depends(require_login),
    spot_repo: SpotRepository = Depends(get_spot_repository),
):
    rows = await db.aread(lambda conn: visit_stamp_repo.list_by_user(conn, user_id=identity.user_id))
    items = []
    for row in rows:
        spot = spot_repo.by_id(int(row["spot_id"]))
        if spot is not None:  # 시드에서 사라진 스팟은 조용히 제외(행은 남긴다)
            items.append(_to_item(spot, row))
    return StampListResponse(items=items)


@router.post("/{spot_id}", response_model=StampItem)
async def stamp_spot(
    spot_id: int,
    req: StampRequest,
    db: Database = Depends(get_database),
    identity: UserIdentity = Depends(require_login),
    spot_repo: SpotRepository = Depends(get_spot_repository),
):
    spot = spot_repo.by_id(spot_id)
    if spot is None:
        return error_response(404, "SPOT_NOT_FOUND", "해당 스팟을 찾을 수 없습니다.")
    if req.accuracy_m is not None and req.accuracy_m > MAX_ACCURACY_M:
        return error_response(
            422, "LOW_ACCURACY", "현재 위치가 너무 부정확해요. 위치 서비스를 켜고 야외에서 다시 시도해 주세요."
        )
    dist = distance_m(req.lat, req.lng, spot.lat, spot.lng)
    if dist > STAMP_RADIUS_M:
        return error_response(
            422,
            "TOO_FAR",
            f"이곳에서 약 {round(dist / 10) * 10:,}m 떨어져 있어요. 현장 {STAMP_RADIUS_M}m 안에서 찍을 수 있어요.",
            {"distance_m": round(dist)},
        )
    try:
        row = await db.awrite(
            lambda conn: visit_stamp_repo.add(
                conn, user_id=identity.user_id, spot_id=spot_id, now_iso=to_iso_kst(now_kst())
            )
        )
    except visit_stamp_repo.StampLimitError:
        return error_response(409, "STAMP_LIMIT", f"스탬프는 계정당 {visit_stamp_repo.MAX_PER_USER}곳까지예요.")
    return _to_item(spot, row)


@router.delete("/{spot_id}", status_code=204)
async def unstamp_spot(
    spot_id: int,
    db: Database = Depends(get_database),
    identity: UserIdentity = Depends(require_login),
):
    await db.awrite(lambda conn: visit_stamp_repo.delete(conn, user_id=identity.user_id, spot_id=spot_id))
    return Response(status_code=204)
