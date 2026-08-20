"""홈 "지금 뜨는 여행지" 발견형 화면 서비스 (부록 H) — 이미 만든 조각을 조립한다.

홈이 대뜸 추천이 아니라 **사진 있는 발견형 화면**이 되도록 두 묶음을 내려준다:
  - trending    : "지금 뜨는 여행지" = 예상 혼잡도 상위(지금 사람 몰리는 유명 관광지). board 상위 →
                  스토어 이름매칭으로 id/category 확보 → 각 firstimage(대표이미지) 조회.
  - hidden_picks: "오늘의 숨은 스팟" = is_hidden_gem 스팟 몇 개(사진 있는 것 우선).

재사용(신규 공공 API·신규 데이터 없음):
  - 혼잡도(M2 board): congestion_repo.get_board → 상위 정렬(compare 와 동일 패턴)
  - 이름매칭/혼잡도 매칭: recommend_service._norm / _match_congestion 재사용
  - 대표이미지: spot_detail_service.get_image_url(= detailCommon2 firstimage, 24h 캐시 공유)

additive: 기존 recommend/compare/detail 엔드포인트·스키마·동작 불변. 이 조립만 신규.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import date

from ..cache.base import Cache
from ..config import settings
from ..regions.nationwide import REGION_BLOCKS
from ..regions.seed import REGIONS, sido_label
from ..repositories.congestion_repo import CongestionRecord, CongestionRepository
from ..repositories.spot_repo import SpotRecord, SpotRepository
from ..schemas.places import (
    AreaRef,
    FeaturedResponse,
    FeaturedSpot,
    RecommendRegion,
    SpotCongestion,
)
from ..spots.region_map import get_tourapi_region
from . import recommend_service, sampling, spot_detail_service
from .congestion_service import classify_level
from .photo_service import Photo
from .region_targets import province_targets  # 부록 Y: 시도→시군구 상위 N곳(선례 재사용)

logger = logging.getLogger("sumeungil.services.featured")

LIMIT_MIN, LIMIT_MAX, LIMIT_DEFAULT = 1, 50, 8
# 숨은 스팟의 **기본** 개수 상한. 2026-08-01(부록 H.6): 종전엔 이 값이 하드 상한이라
# limit 을 24·48 로 키워도 hidden_picks 가 6개에서 멈췄다(/regions "더보기"가 눌러도 아무것도
# 늘지 않던 원인). 이제는 **limit 을 명시하지 않은 요청의 기본값**으로만 쓴다 —
# 명시 요청은 limit 까지 늘어난다. diverse(홈) 경로는 종전대로 이 상한을 그대로 유지한다.
HIDDEN_PICKS_MAX = 6


def _clamp_limit(limit: int) -> int:
    return max(LIMIT_MIN, min(LIMIT_MAX, limit))


def _resolve_region_code(region_code: str | None) -> str:
    """미지정/형식오류면 기본 지역(해운대 26350 등)으로 폴백 — 홈은 에러 대신 항상 채운다."""
    rc = (region_code or "").strip()
    if rc and rc.isdigit():
        return rc
    return settings.default_sigungu_cd


def _region_name(region_code: str) -> str | None:
    tr = get_tourapi_region(region_code)
    if tr:
        return tr.region_name
    return next((r.label for r in REGIONS if r.region_id == region_code), None)


def _match_store(board_name: str, spots: list[SpotRecord]) -> SpotRecord | None:
    """board 관광지명 → 스토어 스팟(정확일치 우선, 부분일치 보조). 없으면 None(억지매칭 금지)."""
    nn = recommend_service._norm(board_name)
    for s in spots:
        if recommend_service._norm(s.name) == nn:
            return s
    for s in spots:
        sn = recommend_service._norm(s.name)
        if sn and (sn in nn or nn in sn):
            return s
    return None


def _featured_spot(
    spot: SpotRecord,
    congestion: SpotCongestion | None,
    photo: Photo,
    region_name: str | None,
) -> FeaturedSpot:
    return FeaturedSpot(
        id=spot.id,
        name=spot.name,
        category=spot.category,  # type: ignore[arg-type]
        region_name=region_name,
        address=spot.address,
        congestion=congestion,
        is_hidden_gem=spot.is_hidden_gem,
        image_url=photo.url,
        photo_credit=photo.credit,
    )


async def _images_for(spots: list[SpotRecord], cache: Cache) -> list[Photo]:
    """여러 스팟의 사진을 동시 조회(체인+캐시 공유). 실패/없음은 Photo(url=None)."""
    return await spot_detail_service.get_photos(spots, cache)


async def build_featured_response(
    region_code: str | None,
    limit: int | None,
    spot_repo: SpotRepository,
    congestion_repo: CongestionRepository,
    cache: Cache,
    diverse: bool = False,
    seed: int | None = None,
    area_cd: str | None = None,
) -> FeaturedResponse:
    """seed(부록 S, 2026-08-01): hidden_picks 표본의 난수 시드. None 이면 요청마다 다르다.
    **trending 은 시드와 무관하게 항상 고정**(예상 혼잡도 상위 순위 자체가 정보다).

    limit(부록 H.6, 2026-08-01): `None` 이면 기본 8 + 숨은 스팟은 기본 상한 6(종전 동작 그대로).
    **명시하면 hidden_picks 도 그 수까지 늘어난다** — 후보가 모자라면 있는 만큼만(지어내지 않음).

    area_cd(부록 Y, 2026-08-11): 시도 전체 집계. **region_code 가 있으면 무시**된다(더 좁은
    지정이 이긴다) → 기존 호출부의 동작은 완전히 불변이다. 우선순위는 region_code > area_cd >
    diverse 순이며, area_cd 형식 검증(2자리 숫자)은 API 레이어가 400 으로 막는다.
    """
    # 명시 여부를 구분해야 "기본값 8"과 "명시적 limit=8"을 다르게 다룰 수 있다
    # (기본 요청의 응답 바이트를 그대로 두기 위한 장치 — 하위호환).
    limit_explicit = limit is not None
    limit = _clamp_limit(limit if limit is not None else LIMIT_DEFAULT)

    # 부록 Y additive(2026-08-11): region_code 가 없고 area_cd 가 있으면 시도 전체를 집계한다.
    # region_code 분기보다 **뒤**, diverse 분기보다 **앞**이다(둘 다 새 파라미터라 무회귀).
    if not (region_code or "").strip() and (area_cd or "").strip():
        return await _build_province_response(
            area_cd.strip(), limit, limit_explicit, spot_repo, congestion_repo, cache, seed,
        )

    # 부록 Q.4 additive(2026-07-31): diverse=true + region_code 미지정이면 9권역을 훑어
    # **시군구당 최대 1곳**으로 섞는다(홈이 한 지역으로 쏠리던 문제). 기본값 false 라
    # 기존 호출부의 응답 바이트는 그대로다(하위호환). region_code 가 있으면 기존 동작 유지.
    if diverse and not (region_code or "").strip():
        return await _build_diverse_response(limit, spot_repo, congestion_repo, cache, seed)

    region_code = _resolve_region_code(region_code)
    # limit 을 명시했으면 숨은 스팟도 그만큼 준다(더보기의 근거). 미지정이면 종전 기본 6.
    hidden_n = limit if limit_explicit else min(limit, HIDDEN_PICKS_MAX)
    region_name = _region_name(region_code)

    all_spots = spot_repo.by_region(region_code, None)

    # --- M2 board 1회 조회: 혼잡 상위 정렬 + 이름매칭 맵(혼잡도 실패는 홈을 막지 않는다) ---
    board_sorted: list[CongestionRecord] = []
    cmap: dict[str, float | None] = {}
    area_cd = next((r.area_cd for r in REGIONS if r.region_id == region_code), None)
    if area_cd:
        try:
            result = await congestion_repo.get_board(area_cd, region_code)
            board_sorted = sorted(
                result.records,
                key=lambda r: r.congestion_rate if r.congestion_rate is not None else -1.0,
                reverse=True,
            )
            cmap = {
                recommend_service._norm(r.spot_name): r.congestion_rate
                for r in result.records
                if r.spot_name
            }
        except Exception as exc:  # noqa: BLE001 — 혼잡도 실패는 발견형 화면을 막지 않는다
            logger.info("featured 혼잡도 조회 스킵(원천 실패) region=%s: %s", region_code, exc)

    # --- trending: board 상위 → 스토어 매칭(id/category 확보)된 것만, limit 개 ---
    # 2026-08-01(부록 H.6): 매칭을 **끝까지 돌려** 후보 총 수(trending_total)를 먼저 구하고
    # 그 뒤 limit 으로 자른다. limit 을 키워도 늘지 않는 이유가 "board 가 주는 개수"라는 사실을
    # 프론트가 알 수 있어야 더보기 버튼을 정확히 감출 수 있다(순수 CPU — 원천 호출 증가 0).
    matched_pairs: list[tuple[SpotRecord, SpotCongestion]] = []
    matched_ids: set[int] = set()
    for rec in board_sorted:
        match = _match_store(rec.spot_name, all_spots)
        if match is None or match.id in matched_ids:
            continue
        matched_ids.add(match.id)
        cong = SpotCongestion(
            index=rec.congestion_rate,
            level=classify_level(rec.congestion_rate),
            tier="B",
        )
        matched_pairs.append((match, cong))

    trending_total = len(matched_pairs)
    trending_pairs = matched_pairs[:limit]
    # 숨은 스팟 중복 제외는 **실제로 노출되는 trending** 기준이다(matched 전체가 아니다).
    # 이래야 limit 을 키우기 전후로 hidden 후보 풀이 종전과 동일하다(무회귀).
    seen_ids: set[int] = {s.id for s, _ in trending_pairs}

    # --- hidden_picks: 숨은 스팟 후보(자기중복 방지) → **무작위 표본** → 사진 있는 것 우선 ---
    # 2026-08-01(대표 지시): 여기는 순위가 정보가 아니라 "발견"이 정보다. 항상 저혼잡 상위
    # 몇 곳만 나오면 홈이 매번 똑같아 보이므로, 자격(is_hidden_gem·비중복) 통과 후보의 앞쪽
    # 풀에서 무작위로 뽑는다. 자격 기준은 그대로다(품질 하한 불변).
    hidden_candidates = [
        s for s in all_spots if s.is_hidden_gem and s.id not in seen_ids
    ]
    # 저혼잡 우선 정렬(대개 board 미매칭이라 혼잡 null → 안정 정렬로 이름순). 풀 상한의 기준이 된다.
    def _cong_key(s: SpotRecord) -> tuple[float, str]:
        c = recommend_service._match_congestion(s.name, cmap)
        idx = c.index if (c and c.index is not None) else 101.0
        return (idx, s.name)

    hidden_candidates.sort(key=_cong_key)

    # --- 사진 백필 후보(부록 H.7, 2026-08-01 대표 지시 "군데군데 빈 사진이 너무 많다") ---
    # 근본 원인은 표시 로직이 아니라 **자격 조건**에 있다. is_hidden_gem 은 "대표이미지가 없으면
    # 덜 알려진 곳"이라는 프록시를 쓴다(category_map.py:97). 그 결과 숨은 후보 4,789곳 중
    # 1,979곳(41%)이 *오직 사진이 없다는 이유로* 자격을 얻고, 그 1,979곳의 사진 채움률은
    # 정의상 0%다. 사진 있는 숨은 후보가 떨어지는 순간부터 남은 자리를 전부 이들이 메우므로
    # 더보기를 누를수록 플레이스홀더만 늘어난다(실측: limit=24 에서 채움률 54%).
    #
    # is_hidden_gem 정의를 카테고리 근거로 좁히는 안은 폐기했다 — 시군구 252곳 중 103곳의 풀이
    # 6곳 미만으로, 8곳은 0으로 붕괴한다(실측). 대신 모자란 자리를 **사진 있는 저혼잡 비trending
    # 스팟**으로 메운다. 섹션 라벨이 "아직 붐비지 않는 ○○의 발견"이므로 저혼잡·비노출이라는
    # 성격은 그대로 지켜지고, 없는 사진을 지어내지도 않는다.
    # 효과(실측): 사진 있는 후보가 6곳 미만인 시군구 114곳 → 0곳.
    #
    # 정렬 키는 미리 계산한다 — _cong_key 는 이름 정규화·매칭을 하므로 sort 가 O(n log n)번
    # 부르면 백필 풀(지역당 수백 곳)에서 비용이 눈에 띈다.
    photo_backfill = [
        s for s in all_spots if s.image_url and not s.is_hidden_gem and s.id not in seen_ids
    ]
    _backfill_keys = {s.id: _cong_key(s) for s in photo_backfill}
    photo_backfill.sort(key=lambda s: _backfill_keys[s.id])
    # 사진은 **최종 선택 개수의 1.5배까지만** 조회한다(풀 전체 조회 금지 — 원천 쿼터·지연 폭증).
    # 여유분은 시드 사진이 없는 확정 후보 수만큼만 실제로 조회한다(sampling.sample_with_spares).
    # 2026-08-01 보정(오케스트레이터 실측): 순수 무작위로 뽑으니 숨은 스팟 사진 채움이
    # 61%(11/18)까지 떨어졌다 — 카드 대부분이 플레이스홀더면 "발견형 화면"이 무너진다.
    # 시드에 사진이 있는 후보를 **상위 등급**으로 두고 그 안에서 무작위로 뽑는다(모자랄 때만
    # 사진 없는 후보로 내려간다). 등급 분리는 공짜다 — 시드 image_url 은 이미 메모리에 있어
    # 원천 호출이 늘지 않고, 무작위성도 등급 안에서 그대로 유지된다.
    # 2026-08-01 결정 2(오케스트레이터): 종전 `sample_tiered(take=photo_budget)` +
    # `trim_photo_candidates` 조합은 **후보 풀이 사진 예산(=ceil(1.5×n)) 이하이면 표본이
    # 결정적으로 퇴화**한다(풀 전체를 뽑아 선호순 복원 후 앞 n 개 절삭 → 매 요청 같은 결과).
    # 숨은 스팟이 적은 지역에서 이 조건이 성립한다. 확정 후보를 먼저 n 개만 무작위로 뽑는다.
    hidden_with_seed_img = [s for s in hidden_candidates if s.image_url]
    hidden_no_seed_img = [s for s in hidden_candidates if not s.image_url]
    # 등급 순서 = 숨은+사진 → 사진 있는 백필 → 숨은+사진없음(최후 수단).
    hidden_primary, hidden_spares = sampling.sample_with_spares(
        (hidden_with_seed_img, photo_backfill, hidden_no_seed_img),
        hidden_n,
        sampling.make_rng(seed, "featured:hidden"),
        has_seed_photo=lambda s: bool(s.image_url),
    )
    hidden_pool = hidden_primary + hidden_spares

    # --- 이미지 동시 조회(trending 전부 + hidden_pool) ---
    trending_imgs, hidden_imgs = await asyncio.gather(
        _images_for([s for s, _ in trending_pairs], cache),
        _images_for(hidden_pool, cache),
    )

    trending = [
        _featured_spot(spot, cong, img, region_name)
        for (spot, cong), img in zip(trending_pairs, trending_imgs)
    ]

    # 사진 있는 숨은 스팟 우선(없으면 뒤), hidden_n 개 절삭
    hidden_with = [(s, i) for s, i in zip(hidden_pool, hidden_imgs) if i.url]
    hidden_without = [(s, i) for s, i in zip(hidden_pool, hidden_imgs) if not i.url]
    # 노출 개수는 확정 후보 수 기준(여유분은 사진 없는 자리를 대신할 때만 들어간다).
    hidden_final = (hidden_with + hidden_without)[: len(hidden_primary)]
    hidden_picks = [
        _featured_spot(
            spot,
            recommend_service._match_congestion(spot.name, cmap),
            img,
            region_name,
        )
        for spot, img in hidden_final
    ]

    region = RecommendRegion(region_code=region_code, region_name=region_name)
    return FeaturedResponse(
        region=region,
        trending=trending,
        hidden_picks=hidden_picks,
        # 부록 H.6 additive(2026-08-01): "더보기"가 의미 있는지 프론트가 판단할 근거.
        trending_total=trending_total,
        # 부록 H.7(2026-08-01): 이 축이 실제로 더 내려줄 수 있는 총 수 = 숨은 후보 + 사진 백필.
        # 프론트는 이 값으로 더보기 버튼을 감추므로(부록 H.6), 백필을 빼면 아직 남았는데도
        # 버튼이 사라진다. "숨은 자격 후보 수"가 아니라 "노출 가능 수"가 이 필드의 계약이다.
        hidden_total=len(hidden_candidates) + len(photo_backfill),
    )


# ---------------------------------------------------------------------------
# 부록 Q.4 — 지역 다양성 모드(diverse=true, region_code 미지정)
# 9권역 대표 시군구를 병렬로 훑어 각 지역에서 trending 1곳 / 숨은 스팟 1곳만 뽑는다.
# 응답 스키마는 불변(FeaturedResponse) — 여러 지역이 섞이므로 region 은 null 이고,
# 각 카드의 region_name 이 어느 지역인지 알려준다(FeaturedSpot 에 이미 있는 필드).
# ---------------------------------------------------------------------------

# 한 지역에서 사진을 확인해볼 숨은 스팟 후보 수(사진 있는 쪽을 고르기 위한 최소 여유분).
_DIVERSE_HIDDEN_CANDIDATES = 2


async def _diverse_one_region(
    region_code: str,
    area_cd: str,
    spot_repo: SpotRepository,
    congestion_repo: CongestionRepository,
    seed: int | None = None,
) -> tuple[tuple[SpotRecord, SpotCongestion] | None, list[SpotRecord]]:
    """지역 1곳 → (trending 최상위 1곳, 숨은 스팟 후보들). 실패는 (None, []) 로 흡수."""
    spots = spot_repo.by_region(region_code, None)
    if not spots:
        return None, []

    board_sorted: list[CongestionRecord] = []
    cmap: dict[str, float | None] = {}
    try:
        result = await congestion_repo.get_board(area_cd, region_code)
        board_sorted = sorted(
            result.records,
            key=lambda r: r.congestion_rate if r.congestion_rate is not None else -1.0,
            reverse=True,
        )
        cmap = {
            recommend_service._norm(r.spot_name): r.congestion_rate
            for r in result.records
            if r.spot_name
        }
    except Exception as exc:  # noqa: BLE001 — 한 지역 실패가 홈 전체를 막지 않는다
        logger.info("featured(diverse) 혼잡도 스킵 region=%s: %s", region_code, exc)

    top: tuple[SpotRecord, SpotCongestion] | None = None
    for rec in board_sorted:
        match = _match_store(rec.spot_name, spots)
        if match is None:
            continue
        top = (
            match,
            SpotCongestion(
                index=rec.congestion_rate,
                level=classify_level(rec.congestion_rate),
                tier="B",
            ),
        )
        break

    taken_id = top[0].id if top else None
    hidden = [s for s in spots if s.is_hidden_gem and s.id != taken_id]

    def _cong_key(s: SpotRecord) -> tuple[float, str]:
        c = recommend_service._match_congestion(s.name, cmap)
        idx = c.index if (c and c.index is not None) else 101.0
        return (idx, s.name)

    hidden.sort(key=_cong_key)
    # 2026-08-01: 권역 회전(날짜 시드)은 그대로 두고, **권역 안에서 어떤 스팟을 뽑을지**를
    # 무작위로 한다. rng 는 권역별로 독립 생성한다 — 권역들이 병렬(asyncio)로 도는데 하나의
    # rng 를 공유하면 응답 도착 순서에 따라 같은 seed 로도 결과가 흔들린다.
    # 사진 있는 후보를 상위 등급으로(단일 지역 경로와 동일 이유 — 실측 채움률 저하 방지).
    # 부록 H.7 과 동일한 3등급(단일 지역 경로 주석 참고): 사진 없는 숨은 곳을 마지막에 둔다.
    backfill = [s for s in spots if s.image_url and not s.is_hidden_gem and s.id != taken_id]
    _bf_keys = {s.id: _cong_key(s) for s in backfill}  # 키 선계산(정렬 중 재매칭 방지)
    backfill.sort(key=lambda s: _bf_keys[s.id])
    return top, sampling.sample_tiered(
        (
            [s for s in hidden if s.image_url],
            backfill,
            [s for s in hidden if not s.image_url],
        ),
        _DIVERSE_HIDDEN_CANDIDATES,
        sampling.make_rng(seed, f"featured:diverse:{region_code}"),
    )


async def _build_diverse_response(
    limit: int,
    spot_repo: SpotRepository,
    congestion_repo: CongestionRepository,
    cache: Cache,
    seed: int | None = None,
) -> FeaturedResponse:
    limit = _clamp_limit(limit)
    hidden_n = min(limit, HIDDEN_PICKS_MAX)

    results = await asyncio.gather(
        *[
            _diverse_one_region(b.region_code, b.area_cd, spot_repo, congestion_repo, seed)
            for b in REGION_BLOCKS
        ],
        return_exceptions=True,
    )

    trending_pairs: list[tuple[str, SpotRecord, SpotCongestion]] = []
    hidden_by_region: dict[str, list[SpotRecord]] = {}
    for block, res in zip(REGION_BLOCKS, results):
        if isinstance(res, BaseException):
            logger.warning("featured(diverse) 지역 %s 예외: %s", block.region_code, res)
            continue
        top, hidden = res
        if top is not None:
            trending_pairs.append((block.region_code, top[0], top[1]))
        if hidden:
            hidden_by_region[block.region_code] = list(hidden)

    # 혼잡도 높은 순(=지금 뜨는) 정렬 후 limit 절삭. 지역당 1곳이라 이미 다양성이 보장된다.
    trending_pairs.sort(
        key=lambda t: (-(t[2].index if t[2].index is not None else -1.0), t[1].name)
    )
    trending_pairs = trending_pairs[:limit]

    # QA 약식(2026-07-31) m-4: 앞에서 hidden_n 개를 그냥 자르면 REGION_BLOCKS 앞쪽 6권역만
    # 영구히 노출되고 부산·경북·제주는 숨은 스팟 자리에 한 번도 못 나온다(실측). 날짜 시드
    # 회전으로 시작 위치를 바꿔 모든 권역이 돌아가며 노출되게 한다 — random 이 아니라 날짜
    # 기반이라 "오늘 어느 권역이 나오나"는 고정이고, **그 권역 안에서 어떤 스팟이 나오나**만
    # 매 요청 무작위다(2026-08-01 대표 지시).
    region_codes = list(hidden_by_region.keys())
    if region_codes:
        offset = date.today().toordinal() % len(region_codes)
        region_codes = region_codes[offset:] + region_codes[:offset]
    shown_regions = region_codes[:hidden_n]

    # 사진 조회는 **표시할 권역의 후보에만**, 그것도 선택 개수의 1.5배까지만 한다.
    # 종전엔 9권역 × 후보 2 = 18곳을 전부 조회했다(선택 6곳). 권역 1순위 후보를 먼저 깔고
    # 남는 예산을 2순위 후보에 주는 순서(breadth-first)라, 표시되는 권역은 최소 1곳은 조회된다.
    # 2순위 후보는 1순위에 시드 사진이 없는 권역에만 붙인다(시드 사진이 있으면 원천 콜 0이라
    # 대체 후보가 필요 없다). 그 결과 조회 수는 표시 권역 수 ~ 1.5배 사이다.
    fetch_list: list[tuple[str, SpotRecord]] = [
        (rc, hidden_by_region[rc][0]) for rc in shown_regions if hidden_by_region.get(rc)
    ]
    spare_budget = max(0, sampling.photo_budget(hidden_n) - len(fetch_list))
    for rc in shown_regions:
        if spare_budget <= 0:
            break
        cands = hidden_by_region.get(rc, [])
        if len(cands) >= 2 and not cands[0].image_url:
            fetch_list.append((rc, cands[1]))
            spare_budget -= 1

    trending_imgs, hidden_imgs = await asyncio.gather(
        _images_for([s for _, s, _ in trending_pairs], cache),
        _images_for([s for _, s in fetch_list], cache),
    )

    trending = [
        _featured_spot(spot, cong, img, _region_name(rc))
        for (rc, spot, cong), img in zip(trending_pairs, trending_imgs)
    ]

    # 숨은 스팟: 지역당 1곳(사진 있는 후보 우선)
    best_by_region: dict[str, tuple[SpotRecord, Photo]] = {}
    for (rc, spot), img in zip(fetch_list, hidden_imgs):
        current = best_by_region.get(rc)
        if current is None or (img.url and not current[1].url):
            best_by_region[rc] = (spot, img)
    hidden_picks = [
        _featured_spot(best_by_region[rc][0], None, best_by_region[rc][1], _region_name(rc))
        for rc in shown_regions
        if rc in best_by_region
    ][:hidden_n]

    # 여러 지역이 섞인 목록이라 대표 region 이 없다 — null 로 두고 카드별 region_name 으로 표기.
    # trending_total/hidden_total 은 **의도적으로 null**(집계 안 함)이다: 이 모드는 권역당 1곳이라
    # limit 을 키워도 홈 구성이 달라지지 않아야 하고(무회귀), 총 수를 내려주면 프론트가 눌러도
    # 안 늘어나는 더보기 버튼을 다시 만들게 된다. null = "더보기 없음"으로 읽는다(부록 H.6).
    return FeaturedResponse(region=None, trending=trending, hidden_picks=hidden_picks)


# ---------------------------------------------------------------------------
# 부록 Y — 시도 전체 집계 모드 (area_cd 지정, region_code 미지정) · 2026-08-11
# 대표 지시(A안): "경기를 고르면 수원 장안구 한 곳만 나오는" 문제를 고친다. 시도를 고르면
# 그 시도의 **모든 시군구 스팟 풀**에서 뽑고, 각 카드의 region_name 이 어느 시·군인지 밝힌다.
# 응답 스키마는 additive 한 필드(area) 하나만 늘었고 기존 필드 의미는 불변이다.
# ---------------------------------------------------------------------------

# 혼잡도 board 를 실제로 호출할 시군구 수 상한 = region_targets 의 도 단위 선정과 **같은 규칙**을
# 재사용한다(스팟 많은 순 상위 PROVINCE_SWEEP_MAX=6곳, 결정적). 경기 44곳·경북 23곳을 전부
# 부르면 요청 1건이 원천 호출 수십 건이 되어 쿼터를 태운다(2026-07-29 실사고와 같은 경로).
# 어느 6곳인지가 결정적이라 캐시가 그대로 듣고, hidden_picks 는 애초에 원천을 안 부르므로
# **시도 전체 풀**에서 뽑힌다 — 즉 "지금 뜨는 곳"만 상위 시·군 기준이고 발견형 목록은 전역이다.


def _province_region_codes(area_cd: str, spot_repo: SpotRepository) -> list[str]:
    """그 시도 소속이면서 스팟이 1곳 이상 실재하는 시군구 코드(사전 순서 보존)."""
    return [
        r.region_id
        for r in REGIONS
        if r.area_cd == area_cd and spot_repo.by_region(r.region_id, None)
    ]


def _group_cap_for(hidden_n: int, region_count: int) -> int:
    """숨은 스팟이 한 시·군에 쏠리지 않게 하는 시군구당 상한.

    상한 × 시군구 수 < 필요 개수가 되면 채우지 못해 결과가 줄어든다(세종처럼 시군구가 1곳인
    시도가 실제로 있다). 그래서 **용량이 항상 필요 개수 이상이 되도록** 올려 잡는다.
    """
    if region_count <= 0:
        return 1
    return max(2, math.ceil(hidden_n / region_count))


async def _build_province_response(
    area_cd: str,
    limit: int,
    limit_explicit: bool,
    spot_repo: SpotRepository,
    congestion_repo: CongestionRepository,
    cache: Cache,
    seed: int | None = None,
) -> FeaturedResponse:
    area = AreaRef(area_cd=area_cd, label=sido_label(area_cd))
    hidden_n = limit if limit_explicit else min(limit, HIDDEN_PICKS_MAX)

    codes = _province_region_codes(area_cd, spot_repo)
    if not codes:
        # 실재하지 않는/스팟 없는 시도 → 빈 목록 + 200(에러 아님). 지어내지 않는다.
        return FeaturedResponse(
            region=None, area=area, trending=[], hidden_picks=[],
            trending_total=0, hidden_total=0,
        )

    code_set = set(codes)
    board_codes = [c for c in province_targets((area_cd,), spot_repo) if c in code_set]

    results = await asyncio.gather(
        *[congestion_repo.get_board(area_cd, c) for c in board_codes],
        return_exceptions=True,
    )

    # --- trending: 조회한 시·군의 board 를 각자 자기 지역 스팟과 매칭 → 혼잡도 상위 순 병합 ---
    # 이름 매칭을 **시·군 단위로** 하는 게 중요하다. 시도 전체 스팟(수천 곳)에 부분일치를 돌리면
    # 다른 시·군의 동명 스팟에 잘못 붙는다(원천 board 는 그 시군구의 관광지만 담는다).
    matched_pairs: list[tuple[SpotRecord, SpotCongestion]] = []
    matched_ids: set[int] = set()
    cmap_by_region: dict[str, dict[str, float | None]] = {}
    for code, res in zip(board_codes, results):
        if isinstance(res, BaseException):
            logger.info("featured(province) 혼잡도 스킵 area=%s region=%s: %s", area_cd, code, res)
            continue
        spots_here = spot_repo.by_region(code, None)
        cmap_by_region[code] = {
            recommend_service._norm(r.spot_name): r.congestion_rate
            for r in res.records
            if r.spot_name
        }
        board_sorted = sorted(
            res.records,
            key=lambda r: r.congestion_rate if r.congestion_rate is not None else -1.0,
            reverse=True,
        )
        for rec in board_sorted:
            match = _match_store(rec.spot_name, spots_here)
            if match is None or match.id in matched_ids:
                continue
            matched_ids.add(match.id)
            matched_pairs.append((
                match,
                SpotCongestion(
                    index=rec.congestion_rate,
                    level=classify_level(rec.congestion_rate),
                    tier="B",
                ),
            ))

    # 시도 하나의 목록으로 보이도록 혼잡도 상위 순 재정렬(단일 지역 경로와 같은 기준).
    matched_pairs.sort(
        key=lambda p: (-(p[1].index if p[1].index is not None else -1.0), p[0].name)
    )
    trending_total = len(matched_pairs)
    trending_pairs = matched_pairs[:limit]
    seen_ids: set[int] = {s.id for s, _ in trending_pairs}

    # --- hidden_picks: 시도 **전체** 스팟 풀에서(원천 호출 0) ---
    all_spots = [s for c in codes for s in spot_repo.by_region(c, None)]

    def _cong_key(s: SpotRecord) -> tuple[float, str]:
        # 혼잡도는 board 를 부른 시·군에만 있다. 다른 시·군 스팟에 남의 board 이름을 매칭시키면
        # 오정보가 되므로 자기 지역 cmap 만 본다(없으면 미상=101.0 → 이름순 안정 정렬).
        cmap = cmap_by_region.get(s.region_code)
        if not cmap:
            return (101.0, s.name)
        c = recommend_service._match_congestion(s.name, cmap)
        idx = c.index if (c and c.index is not None) else 101.0
        return (idx, s.name)

    hidden_candidates = [s for s in all_spots if s.is_hidden_gem and s.id not in seen_ids]
    _hidden_keys = {s.id: _cong_key(s) for s in hidden_candidates}  # 키 선계산(정렬 중 재매칭 방지)
    hidden_candidates.sort(key=lambda s: _hidden_keys[s.id])

    photo_backfill = [
        s for s in all_spots if s.image_url and not s.is_hidden_gem and s.id not in seen_ids
    ]
    _backfill_keys = {s.id: _cong_key(s) for s in photo_backfill}
    photo_backfill.sort(key=lambda s: _backfill_keys[s.id])

    # 시군구당 상한을 둬 "숨은 스팟이 전부 한 도시" 를 막는다(시도 단위라 특히 티가 난다).
    candidate_regions = {s.region_code for s in hidden_candidates}
    candidate_regions |= {s.region_code for s in photo_backfill}
    cap = _group_cap_for(hidden_n, len(candidate_regions))
    hidden_primary, hidden_spares = sampling.sample_with_spares(
        (
            [s for s in hidden_candidates if s.image_url],
            photo_backfill,
            [s for s in hidden_candidates if not s.image_url],
        ),
        hidden_n,
        sampling.make_rng(seed, f"featured:province:{area_cd}"),
        has_seed_photo=lambda s: bool(s.image_url),
        group_key=lambda s: s.region_code,
        group_cap=cap,
    )
    hidden_pool = hidden_primary + hidden_spares

    trending_imgs, hidden_imgs = await asyncio.gather(
        _images_for([s for s, _ in trending_pairs], cache),
        _images_for(hidden_pool, cache),
    )

    trending = [
        _featured_spot(spot, cong, img, _region_name(spot.region_code))
        for (spot, cong), img in zip(trending_pairs, trending_imgs)
    ]

    hidden_with = [(s, i) for s, i in zip(hidden_pool, hidden_imgs) if i.url]
    hidden_without = [(s, i) for s, i in zip(hidden_pool, hidden_imgs) if not i.url]
    hidden_final = (hidden_with + hidden_without)[: len(hidden_primary)]
    hidden_picks = [
        _featured_spot(
            spot,
            recommend_service._match_congestion(
                spot.name, cmap_by_region.get(spot.region_code) or {}
            ),
            img,
            _region_name(spot.region_code),
        )
        for spot, img in hidden_final
    ]

    return FeaturedResponse(
        region=None,          # 시군구 1곳이 아니다 — 대표 지역을 지어내지 않는다
        area=area,            # 대신 어느 시도를 집계했는지 밝힌다(부록 Y additive)
        trending=trending,
        hidden_picks=hidden_picks,
        trending_total=trending_total,
        hidden_total=len(hidden_candidates) + len(photo_backfill),
    )
