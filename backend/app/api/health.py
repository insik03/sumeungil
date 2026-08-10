"""헬스체크 — /api/v1/health 와 /health 동일 응답 (계약 §2).

원천을 매 호출마다 찌르지 않는다. upstream_kto 는 리포지토리가 보관한
'최근 원천 호출 결과'를 읽는다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..cache.base import Cache
from ..deps import get_cache, get_congestion_repository
from ..repositories.congestion_repo import CongestionRepository
from ..schemas.congestion import HealthChecks, HealthResponse
from ..util.time import now_kst, to_iso_kst

router = APIRouter(tags=["health"])


async def _build_health(cache: Cache, repo: CongestionRepository) -> HealthResponse:
    try:
        cache_ok = await cache.health()
    except Exception:  # noqa: BLE001
        cache_ok = False

    upstream = repo.last_upstream_status()  # "ok" | "unknown" | "fail"

    checks = HealthChecks(
        config="ok",  # 여기 도달했다는 건 부팅 시 필수 키 검증 통과
        upstream_kto=upstream,  # type: ignore[arg-type]
        cache="ok" if cache_ok else "fail",
    )

    status = "ok"
    if upstream == "fail" or not cache_ok:
        status = "degraded"

    return HealthResponse(
        status=status,  # type: ignore[arg-type]
        version="mvp-1",
        checks=checks,
        time=to_iso_kst(now_kst()),
    )


@router.get("/api/v1/health", response_model=HealthResponse)
async def health_v1(
    cache: Cache = Depends(get_cache),
    repo: CongestionRepository = Depends(get_congestion_repository),
):
    return await _build_health(cache, repo)


@router.get("/health", response_model=HealthResponse)
async def health_root(
    cache: Cache = Depends(get_cache),
    repo: CongestionRepository = Depends(get_congestion_repository),
):
    return await _build_health(cache, repo)
