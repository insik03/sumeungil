"""개인화 여행 팁 라우터 — `POST /api/v1/tips/personalized` (계약 부록 Z).

라우트 1개. 이 라우터가 하는 일은 HTTP 봉투(422·429)뿐이고, 폴백 판정과 후처리는 전부
`services/tips_service.py` 가 소유한다.

세 가지 계약을 기억할 것:
  1. **로그인은 선택**이다. 쿠키가 없으면 401 이 아니라 **정적 5건 200**을 준다(PRD U-4).
  2. **에러 응답이 사실상 없다.** 400/500 을 만들지 않는다 — 예외는 형식 위반 422(스키마)와
     레이트리밋 429(미들웨어 `BUCKET_LLM`)뿐이다.
  3. 요청에 **자유 텍스트 필드가 없다**(schemas/tips.py). 추가하는 순간 이 엔드포인트의
     프롬프트 인젝션 표면이 0 이라는 전제가 깨진다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from ..ai.tips_generator import TipsGenerator
from ..cache.base import Cache
from ..db.postgres import Database
from ..deps import (
    get_cache,
    get_congestion_repository,
    get_database,
    get_tips_generator,
    get_weather_provider,
)
from ..repositories.congestion_repo import CongestionRepository
from ..schemas.tips import TipsRequest, TipsResponse
from ..security.user_auth import UserIdentity
from ..services import tips_service
from ..services.weather_provider import WeatherProvider
from .auth_deps import optional_identity

logger = logging.getLogger("sumeungil.api.tips")

router = APIRouter(prefix="/api/v1/tips", tags=["tips"])


@router.post("/personalized", response_model=TipsResponse)
async def personalized_tips(
    req: TipsRequest,
    db: Database = Depends(get_database),
    identity: UserIdentity | None = Depends(optional_identity),
    generator: TipsGenerator = Depends(get_tips_generator),
    cache: Cache = Depends(get_cache),
    congestion_repo: CongestionRepository = Depends(get_congestion_repository),
    weather: WeatherProvider = Depends(get_weather_provider),
):
    """취향·최근 코스·혼잡·날씨를 반영한 팁 3~5건. 실패하면 정적 5건(화면이 비지 않는다)."""
    try:
        return await tips_service.build_personalized_tips(
            db,
            user_id=identity.user_id if identity else None,
            region_code=req.region_code,
            generator=generator,
            cache=cache,
            congestion_repo=congestion_repo,
            weather=weather,
        )
    except Exception:  # noqa: BLE001 — 마지막 안전망. 여기까지 오면 안 되지만 5xx 를 내지 않는다
        logger.exception("tips: 예상치 못한 오류 → 정적 폴백")
        return tips_service.static_response()
