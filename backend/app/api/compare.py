"""POST /api/v1/compare — 핫플 vs 숨은길 1:1 대조 리포트 (계약 부록 D).

이미 만든 조각을 조립한다: M2 board rank1(핫플) + recommend 스코어링(숨은길) +
프로필 재검증(C.4) + spot_fit(적합도). deltas·verdict 은 backend 가 계산·템플릿 조립한다.
verdict.headline 은 수치·enum·개수만 넣고 외부 문자열을 넣지 않는다(D.4.1, 인젝션·XSS 표면 0).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..cache.base import Cache
from ..deps import get_congestion_repository, get_spot_repository, get_cache
from ..repositories.congestion_repo import CongestionRepository
from ..repositories.spot_repo import SpotRepository
from ..schemas.compare import CompareRequest, CompareResponse
from ..services import compare_service
from ..services.compare_service import CompareUnavailable
from ..services.recommend_service import ProfileValidationError

logger = logging.getLogger("sumeungil.api.compare")

router = APIRouter(prefix="/api/v1", tags=["compare"])


def _error(status: int, code: str, message: str, detail: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": detail or {}}},
    )


@router.post("/compare", response_model=CompareResponse)
async def compare(
    req: CompareRequest,
    spot_repo: SpotRepository = Depends(get_spot_repository),
    congestion_repo: CongestionRepository = Depends(get_congestion_repository),
    cache: Cache = Depends(get_cache),
):
    region_code = (req.region_code or "").strip()
    # D.5: region_code 누락/형식오류 → 400 INVALID_REGION (places 검증 재사용)
    if not region_code or not region_code.isdigit():
        return _error(400, "INVALID_REGION", "지역을 선택해 주세요.")

    try:
        return await compare_service.build_compare_response(
            region_code=region_code,
            profile=req.profile,
            cache=cache,
            hidden_id=req.hidden_id,
            hotspot_id=req.hotspot_id,
            category=req.category,
            spot_repo=spot_repo,
            congestion_repo=congestion_repo,
        )
    except ProfileValidationError as exc:
        # C.4a 권장 정책: 구조 위반은 400으로 명확히 거절 → 프론트가 프로필 폐기·온보딩 재유도
        logger.warning("프로필 구조 위반 → 400 INVALID_PROFILE: %s", exc)
        return _error(400, "INVALID_PROFILE", "프로필이 유효하지 않습니다. 온보딩을 다시 진행해 주세요.")
    except CompareUnavailable as exc:
        # D.5: 핫플/숨은길을 못 고름 → 404. reason(사유)을 detail 에 실어 프론트가 분기 가능.
        # 카테고리 미스매치(no_hotspot_in_category)는 사유별 안내 문구를 그대로 노출한다.
        logger.info("COMPARE_UNAVAILABLE region=%s reason=%s: %s", region_code, exc.reason, exc)
        message = exc.user_message or "비교할 스팟을 찾지 못했습니다."
        detail: dict = {"reason": exc.reason}
        if exc.category is not None:
            detail["category"] = exc.category
        return _error(404, "COMPARE_UNAVAILABLE", message, detail)
    except Exception:  # noqa: BLE001
        logger.exception("compare 처리 중 예기치 못한 오류")
        return _error(500, "INTERNAL", "서버 오류가 발생했습니다.")
