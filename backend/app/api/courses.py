"""POST /api/v1/courses/* — 코스 조립 + Tmap 도보/차 legs (계약 부록 I).

  - `/recommend` : AI가 스팟까지 골라 하루 코스를 짜준다(slot_label = 시간대 라벨).
  - `/arrange`   : 사용자가 고른 스팟의 **순서만** 최적화한다(slot_label = "N번째").
    응답 스키마는 둘 다 CourseResponse 로 동일 — 프론트 렌더 재사용.


취향(profile, 선택)/저혼잡 스팟을 시간대 슬롯으로 엮어 순서 있는 코스(spots)를 만들고,
연속 스팟쌍마다 Tmap 실호출로 도보·차 소요시간·경로선(legs)을 붙인다. profile 은 부록 C.4
재검증을 그대로 재사용한다(신뢰경계 밖). additive: 기존 places 엔드포인트는 불변.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..ai.summarizer import Summarizer
from ..cache.base import Cache
from ..deps import (
    get_cache,
    get_congestion_repository,
    get_spot_repository,
    get_summarizer,
)
from ..repositories.congestion_repo import CongestionRepository
from ..repositories.spot_repo import SpotRepository
from ..schemas.courses import ArrangeRequest, CourseRequest, CourseResponse
from ..services import arrange_service, course_service
from ..services.arrange_service import InvalidSpotsError
from ..services.recommend_service import ProfileValidationError
from .auth_deps import require_login

logger = logging.getLogger("sumeungil.api.courses")

router = APIRouter(prefix="/api/v1/courses", tags=["courses"])


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": {}}},
    )


@router.post("/recommend", response_model=CourseResponse)
async def recommend_course(
    req: CourseRequest,
    spot_repo: SpotRepository = Depends(get_spot_repository),
    congestion_repo: CongestionRepository = Depends(get_congestion_repository),
    cache: Cache = Depends(get_cache),
    summarizer: Summarizer = Depends(get_summarizer),
    identity=Depends(require_login),
):
    """2026-08-17(대표 지시) — AI 코스짜기(추천 모드)도 로그인 필수."""
    region_code = (req.region_code or "").strip()
    # 부록 C.6 와 동일: region_code 누락/형식오류 → 400 INVALID_REGION
    if not region_code or not region_code.isdigit():
        return _error(400, "INVALID_REGION", "지역을 선택해 주세요.")

    try:
        return await course_service.build_course_response(
            region_code=region_code,
            profile=req.profile,
            spot_repo=spot_repo,
            congestion_repo=congestion_repo,
            cache=cache,
            summarizer=summarizer,
            wish=req.wish,
            user_id=identity.user_id,
        )
    except ProfileValidationError as exc:
        logger.warning("프로필 구조 위반 → 400 INVALID_PROFILE: %s", exc)
        return _error(400, "INVALID_PROFILE", "프로필이 유효하지 않습니다. 온보딩을 다시 진행해 주세요.")
    except Exception:  # noqa: BLE001
        logger.exception("courses/recommend 처리 중 예기치 못한 오류")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")


@router.post("/arrange", response_model=CourseResponse)
async def arrange_course(
    req: ArrangeRequest,
    spot_repo: SpotRepository = Depends(get_spot_repository),
    congestion_repo: CongestionRepository = Depends(get_congestion_repository),
    cache: Cache = Depends(get_cache),
    summarizer: Summarizer = Depends(get_summarizer),
    _identity=Depends(require_login),
):
    """사용자가 고른 스팟(2~8개)의 방문 순서만 최적화한다 (부록 I §arrange).

    응답은 /recommend 와 **동일한 CourseResponse** — 프론트는 기존 타임라인/지도 렌더를
    그대로 재사용한다. 차이는 slot_label 이 시간대가 아니라 "1번째"~"N번째" 순서 라벨이라는 점뿐.
    profile 을 받지 않으므로 match_score 는 항상 null(추천이 아니라 정렬이다).

    2026-08-17(대표 지시) — AI 코스짜기(직접 만들기 모드)도 로그인 필수.
    """
    try:
        return await arrange_service.build_arrange_response(
            spot_ids=req.spot_ids,
            region_code=req.region_code,
            spot_repo=spot_repo,
            congestion_repo=congestion_repo,
            cache=cache,
            summarizer=summarizer,
        )
    except InvalidSpotsError as exc:
        logger.info("arrange 입력 거절 → 400 INVALID_SPOTS: %s", exc)
        return _error(
            400,
            "INVALID_SPOTS",
            f"코스로 묶으려면 스팟을 {arrange_service.MIN_SPOTS}~{arrange_service.MAX_SPOTS}곳 "
            "골라 주세요. (선택한 스팟 중 일부는 찾을 수 없을 수 있어요)",
        )
    except Exception:  # noqa: BLE001
        logger.exception("courses/arrange 처리 중 예기치 못한 오류")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")
