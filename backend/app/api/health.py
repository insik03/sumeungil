"""헬스체크 — /api/v1/health 와 /health 동일 응답 (계약 §2).

원천을 매 호출마다 찌르지 않는다. upstream_kto 는 리포지토리가 보관한
'최근 원천 호출 결과'를 읽는다.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends

from ..ai import gemini_client
from ..cache.base import Cache
from ..config import settings
from ..deps import get_cache, get_congestion_repository
from ..repositories.congestion_repo import CongestionRepository
from ..schemas.congestion import HealthChecks, HealthResponse
from ..util.time import KST, now_kst, to_iso_kst

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


@router.get("/api/v1/health/llm")
async def health_llm():
    """LLM 한도 상태 (2026-09-07) — 외부 감시(n8n)가 10분마다 폴링한다.

    Gemini 무료 티어 하루 20회(#99)에 걸리면 코스 선택·코스 설명이 조용히 폴백되므로,
    최근 1시간 안에 429 가 있으면 `fallback_suspected=true` 로 알린다. 키·개인정보·본문 없음.
    프로세스 메모리 기반이라 재시작 후엔 0 부터 센다(정직: 재시작 시각도 함께 준다).
    """
    q = gemini_client.quota_status()

    def _iso(ts: float | None) -> str | None:
        return to_iso_kst(datetime.fromtimestamp(ts, tz=KST)) if ts else None

    return {
        "provider": settings.course_llm_provider,
        "model": settings.gemini_model if settings.course_llm_provider == "gemini" else settings.ollama_model,
        "quota_429_last_hour": q["quota_429_last_hour"],
        "quota_429_last_24h": q["quota_429_last_24h"],
        "last_429_at": _iso(q["last_429_ts"]),
        "last_success_at": _iso(q["last_success_ts"]),
        "fallback_suspected": q["quota_429_last_hour"] > 0,
        "time": to_iso_kst(now_kst()),
    }


@router.get("/health", response_model=HealthResponse)
async def health_root(
    cache: Cache = Depends(get_cache),
    repo: CongestionRepository = Depends(get_congestion_repository),
):
    return await _build_health(cache, repo)
