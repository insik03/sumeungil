"""GET /api/v1/collections — 테마별 큐레이션 컬렉션 (부록 J).

홈/발견 화면에서 "조용히 힐링", "인생샷 스팟" 등 테마별로 묶은 스팟 컬렉션을 사진과 함께
내려준다. additive: 기존 places/recommend/compare/featured/detail 엔드포인트·스키마 불변.
저혼잡·숨은 스팟 우선 정렬(숨은길 컨셉). 원천 API 는 요청 경로에서 직접 호출하지 않는다
(board·firstimage 는 기존 캐시/리포지토리 재사용).

2026-08-01(부록 S.8) additive — "테마별 전체 보기": `per_theme`(테마당 개수) / `theme`(한 테마만)
/ `offset`(더보기) + 응답의 `total`·`has_more`·`seed`. 파라미터를 안 주면 응답은 종전 그대로다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ..cache.base import Cache
from ..deps import get_cache, get_congestion_repository, get_spot_repository
from ..repositories.congestion_repo import CongestionRepository
from ..repositories.spot_repo import SpotRepository
from ..schemas.places import CollectionsResponse
from ..services import collections_service

logger = logging.getLogger("sumeungil.api.collections")

router = APIRouter(prefix="/api/v1/collections", tags=["collections"])


@router.get("", response_model=CollectionsResponse)
async def get_collections(
    region_code: str | None = None,
    # 부록 S.5 additive(2026-08-01): true + region_code 미지정이면 9권역을 합친 풀에서 뽑는다
    # (테마당 후보가 7~15개뿐이라 새로고침해도 같은 곳만 나오던 문제). 기본 false → 기존
    # 호출부 응답 그대로(하위호환). region_code 가 있으면 무시된다(featured 와 같은 규약).
    diverse: bool = False,
    # 부록 S additive(2026-08-01): 각 테마 아이템은 매 요청 무작위 표본이다. seed 를 주면
    # 결정적이 된다(검증·재현용). 테마 목록·순서와 매칭 자격은 시드와 무관하게 고정.
    seed: int | None = Query(None, ge=0, le=2_147_483_647),
    # --- 부록 S.8 additive(2026-08-01): 테마당 개수 제어 + 더보기 ---
    # per_theme: 테마당 노출 개수(기본 8 = 종전 동작). 상한 50 = 사진 조회 비용 상한.
    per_theme: int | None = Query(
        None, ge=1, le=collections_service.PER_THEME_MAX, description="테마당 노출 개수(기본 8)"
    ),
    # theme: 그 테마 하나만 조회(더보기가 쓰는 모드). 서버 고정 enum 만 허용한다.
    theme: str | None = Query(None, max_length=40, description="특정 테마 1개만 조회"),
    # offset: 같은 seed 가 만든 **결정적 순열의 시작 인덱스**(= 지금까지 받은 개수).
    # per_theme 을 도중에 바꿔도 중복·누락이 없다(S.8.6). 전체 조회에도 테마별로 동일 적용.
    offset: int = Query(0, ge=0, le=collections_service.OFFSET_MAX, description="더보기 시작 위치"),
    spot_repo: SpotRepository = Depends(get_spot_repository),
    congestion_repo: CongestionRepository = Depends(get_congestion_repository),
    cache: Cache = Depends(get_cache),
):
    # theme 은 서버 고정 enum 목록으로만 검증한다(외부 문자열이 로직·응답에 흐르지 않게).
    # 잘못된 값은 조용히 빈 목록을 주지 않고 400 으로 알려준다(프론트 오타를 숨기지 않는다).
    if theme is not None and theme not in collections_service.theme_keys():
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "INVALID_THEME",
                    "message": "알 수 없는 테마입니다.",
                    # 값은 전부 서버 소유 문자열 — 입력값을 되비추지 않는다(reflection 차단).
                    "detail": {"valid": collections_service.theme_keys()},
                }
            },
        )
    try:
        return await collections_service.build_collections_response(
            region_code=region_code,
            spot_repo=spot_repo,
            congestion_repo=congestion_repo,
            cache=cache,
            diverse=diverse,
            seed=seed,
            per_theme=per_theme,
            theme=theme,
            offset=offset,
        )
    except Exception:  # noqa: BLE001
        logger.exception("collections 처리 중 예기치 못한 오류")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL", "message": "서버 오류가 발생했습니다.", "detail": {}}},
        )
