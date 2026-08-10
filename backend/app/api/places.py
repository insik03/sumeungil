"""POST /api/v1/places/recommend — 프로필 맞춤 로컬 스팟 추천 (계약 부록 C.3).

프론트가 sessionStorage OnboardingResult(프로필)를 body로 보내면, 백엔드가 로컬
스토어(TourAPI 배치 수집분)의 스팟을 스코어링해 정렬된 SpotCard 목록을 내려준다.
프로필은 신뢰경계 밖이라 소비 전 재검증한다(C.4). 원천 API는 요청 경로에서 호출하지 않는다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ..cache.base import Cache
from ..ai.summarizer import Summarizer
from ..deps import (
    get_cache,
    get_congestion_repository,
    get_spot_repository,
    get_summarizer,
    get_weather_provider,
)
from ..repositories.congestion_repo import CongestionRepository
from ..repositories.spot_repo import SpotRepository
from ..schemas.outlook import SeasonalResponse
from ..schemas.places import (
    SORT_MODES,
    SPOT_TYPES,
    FeaturedResponse,
    PlaceSearchResponse,
    RecommendRequest,
    SpotDetail,
)
from ..services import (
    featured_service,
    recommend_service,
    search_service,
    seasonal_service,
    spot_detail_service,
)
from ..services.recommend_service import ProfileValidationError
from ..services.spot_detail_service import SpotNotFound
from ..services.weather_provider import WeatherProvider

logger = logging.getLogger("sumeungil.api.places")

router = APIRouter(prefix="/api/v1/places", tags=["places"])


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": {}}},
    )


# response_model 을 지정하지 않는다: rerank 미요청이면 RecommendResponse(바이트 동일),
# 요청이면 RecommendResponseRerank(rerank 블록 포함)를 반환하는 하위호환 확장이라
# 고정 모델로 강제하면 rerank 필드가 잘려나간다(부록 F.6 무회귀 조건).
@router.post("/recommend")
async def recommend_places(
    req: RecommendRequest,
    spot_repo: SpotRepository = Depends(get_spot_repository),
    congestion_repo: CongestionRepository = Depends(get_congestion_repository),
    weather_provider: WeatherProvider = Depends(get_weather_provider),
):
    region_code = (req.region_code or "").strip()
    # C.6: region_code 누락/형식오류 → 400 INVALID_REGION
    if not region_code or not region_code.isdigit():
        return _error(400, "INVALID_REGION", "지역을 선택해 주세요.")

    # C.9: spot_type / sort enum 검증 — region 과 동일한 수동 400 패턴(정의 밖 값 거절)
    if req.spot_type not in SPOT_TYPES:
        return _error(400, "INVALID_SPOT_TYPE", "지원하지 않는 유형입니다.")
    if req.sort not in SORT_MODES:
        return _error(400, "INVALID_SORT", "지원하지 않는 정렬입니다.")

    try:
        return await recommend_service.build_recommend_response(
            region_code=region_code,
            profile=req.profile,
            category=req.category,
            sort=req.sort,
            limit=req.limit,
            spot_repo=spot_repo,
            congestion_repo=congestion_repo,
            rerank=req.rerank,
            weather_provider=weather_provider,
            spot_type=req.spot_type,
        )
    except ProfileValidationError as exc:
        # C.4a 권장 정책: 구조 위반(V1/V3)은 400으로 명확히 거절 → 프론트가 프로필 폐기·온보딩 재유도
        logger.warning("프로필 구조 위반 → 400 INVALID_PROFILE: %s", exc)
        return _error(400, "INVALID_PROFILE", "프로필이 유효하지 않습니다. 온보딩을 다시 진행해 주세요.")
    except Exception:  # noqa: BLE001
        logger.exception("places/recommend 처리 중 예기치 못한 오류")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")


# 부록 H — 홈 "지금 뜨는 여행지"(사진 포함) 발견형 화면. additive: 새 GET 만 추가.
# 주의: 이 라우트는 반드시 GET /{content_id} 보다 먼저 선언한다. 뒤에 두면 "featured" 가
# {content_id}(int) 경로에 잡혀 422 가 난다(선언 순서가 매칭 우선순위).
@router.get("/featured", response_model=FeaturedResponse)
async def get_featured(
    region_code: str | None = None,
    # 부록 H.6(2026-08-01): 기본은 None = "미지정"(서버 기본 8 + 숨은 스팟 상한 6, 종전 그대로).
    # **명시하면 hidden_picks 도 그 수까지 늘어난다** — /regions 더보기(8→24→48)가 실제로 동작하는
    # 근거다. 1~50 클램프는 서비스가 한다(종전과 동일, 범위 밖 값도 422 없이 흡수).
    limit: int | None = None,
    # 부록 Q.4 additive: true + region_code 미지정이면 9권역에서 시군구당 1곳씩 섞어 보여준다.
    # 기본 false → 기존 응답 바이트 그대로(하위호환). region_code 가 있으면 무시된다.
    diverse: bool = False,
    # 부록 S additive(2026-08-01): hidden_picks 는 매 요청 무작위 표본이다. seed 를 주면
    # 그 표본이 결정적이 된다(검증·재현용). trending 은 seed 와 무관하게 항상 고정.
    seed: int | None = Query(None, ge=0, le=2_147_483_647),
    spot_repo: SpotRepository = Depends(get_spot_repository),
    congestion_repo: CongestionRepository = Depends(get_congestion_repository),
    cache: Cache = Depends(get_cache),
):
    try:
        return await featured_service.build_featured_response(
            region_code=region_code,
            limit=limit,
            spot_repo=spot_repo,
            congestion_repo=congestion_repo,
            cache=cache,
            diverse=diverse,
            seed=seed,
        )
    except Exception:  # noqa: BLE001
        logger.exception("places/featured 처리 중 예기치 못한 오류")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")


# 부록 Q.3 — 계절 추천(그 계절에 붐비는 곳 / 한적한 숨은 명소).
# 주의: /featured·/search 와 같은 이유로 반드시 GET /{content_id}(int) **앞**에 선언한다.
@router.get("/seasonal", response_model=SeasonalResponse)
async def get_seasonal(
    season: str | None = Query(None, max_length=10),
    region_code: str | None = Query(None, max_length=20),
    # 부록 Q.3.2 additive(2026-08-01): 9권역 key(gyeonggi…jeju). 미지정이면 전국.
    # region_code 와 함께 오면 region_code 가 이긴다(더 좁은 지정).
    region_block: str | None = Query(None, max_length=20),
    limit: int = seasonal_service.LIMIT_DEFAULT,
    # 부록 Q.3/S additive(2026-08-01): hidden 표본의 시드(선택). popular 는 항상 고정.
    seed: int | None = Query(None, ge=0, le=2_147_483_647),
    spot_repo: SpotRepository = Depends(get_spot_repository),
    congestion_repo: CongestionRepository = Depends(get_congestion_repository),
    cache: Cache = Depends(get_cache),
):
    """season 미지정/미정의 값이면 오늘(KST) 기준 현재 계절로 폴백한다(에러 아님)."""
    try:
        return await seasonal_service.build_seasonal_response(
            season=season,
            region_code=region_code,
            region_block=region_block,
            limit=limit,
            spot_repo=spot_repo,
            congestion_repo=congestion_repo,
            cache=cache,
            seed=seed,
        )
    except Exception:  # noqa: BLE001
        logger.exception("places/seasonal 처리 중 예기치 못한 오류")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")


# 부록 L — 스팟 이름 검색(코스 빌더에서 "가게를 검색해 코스에 넣기").
# 주의: /featured 와 같은 이유로 반드시 GET /{content_id}(int) **앞**에 선언한다.
# 뒤에 두면 "search" 가 int 경로에 잡혀 422 가 난다(선언 순서 = 매칭 우선순위).
@router.get("/search", response_model=PlaceSearchResponse)
async def search_places(
    q: str = Query(..., min_length=1, max_length=search_service.MAX_QUERY_CHARS),
    region_code: str | None = Query(None, max_length=20),
    limit: int = search_service.DEFAULT_LIMIT,
    spot_repo: SpotRepository = Depends(get_spot_repository),
):
    """이름 부분일치 검색. q 길이 위반은 FastAPI 기본 422(계약 L.1), 매치 없음은 200 items:[]."""
    try:
        return search_service.build_search_response(
            q=q, region_code=region_code, limit=limit, spot_repo=spot_repo,
        )
    except Exception:  # noqa: BLE001
        logger.exception("places/search 처리 중 예기치 못한 오류")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")


# 부록 G — 스팟 상세 조회. 스팟 클릭 시 소개 요약(overview)+"이런 분께 추천"(recommended_for)을
# 보여준다. additive: 기존 POST /recommend·/compare 등은 불변, 이 GET 만 추가.
@router.get("/{content_id}", response_model=SpotDetail)
async def get_place_detail(
    content_id: int,
    spot_repo: SpotRepository = Depends(get_spot_repository),
    congestion_repo: CongestionRepository = Depends(get_congestion_repository),
    cache: Cache = Depends(get_cache),
    summarizer: Summarizer = Depends(get_summarizer),
):
    try:
        return await spot_detail_service.build_spot_detail(
            content_id=content_id,
            spot_repo=spot_repo,
            congestion_repo=congestion_repo,
            cache=cache,
            summarizer=summarizer,
        )
    except SpotNotFound:
        return _error(404, "SPOT_NOT_FOUND", "해당 장소를 찾을 수 없습니다.")
    except Exception:  # noqa: BLE001
        logger.exception("places/{content_id} 처리 중 예기치 못한 오류")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")
