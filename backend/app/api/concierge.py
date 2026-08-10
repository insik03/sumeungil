"""AI 여행 문답(컨시어지) 라우터 — `POST /api/v1/concierge/ask` (계약 부록 N).

자연어 한 문장을 받아 조건 해석 → 지역 감지 → 추천 → 대화형 답변을 한 번에 돌려준다.
라우터는 HTTP 봉투(요청 파싱·에러코드·응답 직렬화)만 담당하고, 실제 조립은
services/concierge_service.py 가 소유한다(다른 라우터와 동일한 얇은 레이어 규약).

2026-07-30 additive: "축제/페스티벌" 질문은 스팟 추천 대신 축제 목록으로 답한다(부록 N.9).
라우터는 cache 의존만 추가로 넘기고, 분기 판단은 전부 서비스가 한다.

additive: 기존 엔드포인트(온보딩·추천·코스·축제 등)는 한 줄도 바꾸지 않는다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..ai.llm_provider import LLMProvider
from ..ai.summarizer import Summarizer
from ..cache.base import Cache
from ..deps import (
    get_cache,
    get_congestion_repository,
    get_llm_provider,
    get_spot_repository,
    get_summarizer,
    get_weather_provider,
)
from ..repositories.congestion_repo import CongestionRepository
from ..repositories.spot_repo import SpotRepository
from ..schemas.concierge import ConciergeAskRequest, ConciergeAskResponse
from ..services import concierge_service
from ..services.recommend_service import ProfileValidationError
from ..services.weather_provider import WeatherProvider

logger = logging.getLogger("sumeungil.api.concierge")

router = APIRouter(prefix="/api/v1/concierge", tags=["concierge"])


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": {}}},
    )


@router.post("/ask", response_model=ConciergeAskResponse)
async def ask_concierge(
    req: ConciergeAskRequest,
    llm_provider: LLMProvider = Depends(get_llm_provider),
    summarizer: Summarizer = Depends(get_summarizer),
    spot_repo: SpotRepository = Depends(get_spot_repository),
    congestion_repo: CongestionRepository = Depends(get_congestion_repository),
    weather_provider: WeatherProvider = Depends(get_weather_provider),
    cache: Cache = Depends(get_cache),  # 축제 의도 질문에서 festival_service 캐시 재사용
):
    """질문 길이 위반(2자 미만/200자 초과)은 pydantic 기본 422(계약 N.4)."""
    question = (req.question or "").strip()
    if not question:
        return _error(400, "EMPTY_QUESTION", "무엇이 궁금한지 적어주세요.")

    try:
        return await concierge_service.build_concierge_answer(
            question=question,
            region_code=req.region_code,
            llm_provider=llm_provider,
            summarizer=summarizer,
            spot_repo=spot_repo,
            congestion_repo=congestion_repo,
            weather_provider=weather_provider,
            cache=cache,
        )
    except ProfileValidationError:
        # 서버가 스스로 만든 프로필이라 정상 경로에서는 발생할 수 없다(방어적 500).
        logger.exception("concierge/ask 내부 프로필 검증 실패")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")
    except Exception:  # noqa: BLE001
        logger.exception("concierge/ask 처리 중 예기치 못한 오류")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")
