"""테마별 큐레이션 컬렉션 서비스 (부록 J) — 이미 만든 조각을 재조립한다.

홈/발견 화면에서 "조용히 힐링", "인생샷 스팟"처럼 **테마별로 묶은 스팟 컬렉션**을 사진과 함께
내려준다. **additive** — 기존 recommend/compare/detail/featured 엔드포인트·스키마·동작 불변.

숨은길 차별점: 각 컬렉션은 **저혼잡·숨은(is_hidden_gem) 스팟 우선**으로 정렬한다(구석구석의
인기순 큐레이션과 반대 컨셉). 테마 매칭은 스팟의 registry-검증된 tag_values(mood/spot_pref/
accessibility) + category + themes(pet_allowed) 로만 한다. 테마 title 은 enum→한국어 고정
매핑이라 외부 문자열이 응답에 섞이지 않는다(인젝션 표면 0).

재사용(신규 공공 API·신규 데이터 없음):
  - 지역 스팟: spot_repo.by_region
  - 혼잡도(M2 board) + 이름매칭: featured/recommend 와 동일 로직
  - 대표이미지: spot_detail_service.get_image_url(detailCommon2 firstimage, 24h 캐시 공유)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable

from ..cache.base import Cache
from ..config import settings
from ..regions.nationwide import REGION_BLOCKS
from ..regions.seed import REGIONS
from ..repositories.congestion_repo import CongestionRepository
from ..repositories.spot_repo import SpotRecord, SpotRepository
from ..schemas.places import (
    CollectionsResponse,
    FeaturedSpot,
    RecommendRegion,
    ThemeCollection,
)
from ..spots.region_map import get_tourapi_region
from . import recommend_service, sampling, spot_detail_service
from .photo_service import NO_PHOTO

logger = logging.getLogger("sumeungil.services.collections")

# 각 컬렉션은 4~8개 목표. 이 수 미만인 테마는 스킵(지어내지 않음).
MIN_PER_COLLECTION = 3
MAX_PER_COLLECTION = 8

# --- 부록 S.8 additive(2026-08-01): 테마당 개수 제어 + 더보기(페이지네이션) ---
# 대표 지시: "테마별로 몇 개만 나오는데 전체를 다 볼 수 있게 더보기가 있으면 좋겠다."
# per_theme 상한. 사진 조회는 노출 개수의 1.5배까지 나갈 수 있으므로 이 상한이 곧 비용 상한이다
# (테마 1개 더보기 = 최대 50×1.5 = 75건 조회, 그나마 시드 사진 보유분은 원천 콜 0).
PER_THEME_MAX = 50
# 더보기 요청의 offset 상한(그 위는 후보가 사실상 소진된다 — 무한 페이지 방지).
OFFSET_MAX = 2000

# --- 부록 S.5 additive(2026-08-01): diverse 모드 상수 ---
# 결정적 순열의 **청크(8개)당** 같은 시군구가 차지할 수 있는 최대 자리 수. 9권역을 섞어도 한
# 지역이 과반이 되면 "전국 테마"가 아니라 "그 지역 테마"가 된다(대표 지적: 홈에 부산만 많다).
# 청크 단위라 per_theme 이 얼마든(8이든 50이든) 연속 구간에서 한 지역 비중이 1/4 근처로 유지된다.
DIVERSE_MAX_PER_SIGUNGU = sampling.SEQ_GROUP_CAP
# 테마별 후보 풀(스팟 id 목록) 캐시. 시드 데이터만의 함수라 혼잡도·난수와 무관하고,
# **표본 추출은 이 캐시 밖에서 매 요청 수행**한다(부록 S.4: 캐시가 랜덤을 죽이면 안 된다).
DIVERSE_POOL_TTL_SEC = 6 * 3600
# v2(2026-08-01 결정 1): photo 테마에 "사진 보유" 자격이 추가돼 풀 구성이 달라졌다 —
# 키를 올려 배포 직후 옛 풀(6h)이 남지 않게 한다.
_DIVERSE_POOL_KEY = "collections:diverse:pool:v2"


@dataclass(frozen=True)
class _Theme:
    key: str
    title: str  # enum→한국어 고정 라벨(인젝션 안전)
    match: Callable[[SpotRecord, dict[str, set[str]]], bool]
    # 2026-08-01(오케스트레이터 결정 1): **사진이 곧 테마의 내용**인 테마만 True.
    # 그런 테마는 "시드 대표사진 보유"가 등급 가점이 아니라 **자격 조건**이다 —
    # "인생샷 스팟"에 사진 없는 회색 카드가 절반이면 테마 자체가 성립하지 않는다.
    # 다른 테마(힐링·로컬카페·자연 등)는 사진이 없어도 정보 가치가 남으므로 종전대로 가점만.
    require_photo: bool = False


def _qualifies(theme: _Theme, spot: SpotRecord, tagset: dict[str, set[str]]) -> bool:
    """테마 자격 = 매칭 조건 + (사진 필수 테마면) 시드 대표사진 보유.

    시드 `image_url` 만 본다 — 이미 메모리에 있어 원천 호출이 0이고 판정이 결정적이다.
    (`image_resolved=False`(아직 배치가 안 훑은 스팟)도 여기서는 자격 미달로 본다:
     런타임에 사진이 나올 수도 있지만, 확실하지 않은 후보로 "인생샷"을 채우지 않는다.)
    """
    if not theme.match(spot, tagset):
        return False
    return bool(spot.image_url) if theme.require_photo else True


def _tag_sets(spot: SpotRecord) -> dict[str, set[str]]:
    """스팟의 (axis, value) 목록 → {axis: {value, ...}} (매칭 편의)."""
    out: dict[str, set[str]] = {}
    for axis, value in spot.tags:
        out.setdefault(axis, set()).add(value)
    return out


# 테마 정의(고정 순서). match 는 enum 값만 본다 — 외부 텍스트/스팟명 미참조.
THEMES: list[_Theme] = [
    _Theme(
        "healing", "조용히 힐링",
        lambda s, t: bool(t.get("mood", set()) & {"calm", "healing", "contemplative"}),
    ),
    _Theme(
        "quiet_cafe", "숨은 로컬 카페",
        lambda s, t: s.category == "cafe" or "local_cafe" in t.get("spot_pref", set()),
    ),
    _Theme(
        "photo", "인생샷 스팟",
        lambda s, t: "photo_spot" in t.get("spot_pref", set()),
        require_photo=True,  # 결정 1 — 사진이 곧 이 테마의 내용이다
    ),
    _Theme(
        "nature", "자연 속으로",
        lambda s, t: s.category in {"nature", "trail"}
        or bool(t.get("spot_pref", set()) & {"nature_view", "walking_trail"}),
    ),
    _Theme(
        "pet", "반려동물과 함께",
        lambda s, t: (s.themes or {}).get("pet_allowed") is True
        or "pet_friendly_required" in t.get("accessibility", set()),
    ),
    _Theme(
        "market", "전통시장 구경",
        lambda s, t: s.category == "market" or "traditional_market" in t.get("spot_pref", set()),
    ),
    _Theme(
        "craft", "공방·만들기 체험",
        lambda s, t: s.category == "craft" or "craft_shop" in t.get("spot_pref", set()),
    ),
]


def theme_keys() -> list[str]:
    """유효한 theme_key 목록(고정 순서). API 레이어의 `theme` 파라미터 검증 단일 소스."""
    return [t.key for t in THEMES]


def _clamp(value: int | None, default: int, lo: int, hi: int) -> int:
    if value is None:
        return default
    return max(lo, min(hi, int(value)))


def _themes_for(theme: str | None) -> list[_Theme]:
    """`theme` 지정 시 그 테마 하나만. 미지정이면 전체(고정 순서)."""
    if not theme:
        return THEMES
    return [t for t in THEMES if t.key == theme]


@dataclass
class _Picked:
    """테마 1개의 선택 결과(노출분·후보 총 수)."""

    theme: _Theme
    primary: list[SpotRecord]
    total: int
    # 결정적 순열에 다음 아이템이 남아 있는가(sampling.sample_paged). 순열은 모든 후보를
    # 담으므로 사실상 `offset+노출 < total` 과 같지만, 순열을 직접 확인한 값이라 더 정확하다.
    has_next: bool


def _resolve_region_code(region_code: str | None) -> str:
    rc = (region_code or "").strip()
    if rc and rc.isdigit():
        return rc
    return settings.default_sigungu_cd


def _region_name(region_code: str) -> str | None:
    tr = get_tourapi_region(region_code)
    if tr:
        return tr.region_name
    return next((r.label for r in REGIONS if r.region_id == region_code), None)


async def _congestion_map(
    region_code: str, congestion_repo: CongestionRepository
) -> dict[str, float | None]:
    """그 지역 board 이름매칭용 {정규화 스팟명: 혼잡률}. 실패/없음 → 빈 맵(graceful)."""
    area_cd = next((r.area_cd for r in REGIONS if r.region_id == region_code), None)
    if not area_cd:
        return {}
    try:
        result = await congestion_repo.get_board(area_cd, region_code)
    except Exception as exc:  # noqa: BLE001 — 혼잡도 실패는 컬렉션을 막지 않는다
        logger.info("collections 혼잡도 조회 스킵(원천 실패) region=%s: %s", region_code, exc)
        return {}
    return {
        recommend_service._norm(r.spot_name): r.congestion_rate
        for r in result.records
        if r.spot_name
    }


def _hidden_lowcong_key(spot: SpotRecord, cmap: dict[str, float | None]) -> tuple[int, float, str]:
    """정렬키: 숨은 스팟 먼저(0) → 저혼잡 먼저 → 이름(안정). 숨은길 컨셉의 핵심 정렬."""
    hidden_rank = 0 if spot.is_hidden_gem else 1
    c = recommend_service._match_congestion(spot.name, cmap)
    idx = c.index if (c and c.index is not None) else 101.0  # 혼잡 미상은 뒤로
    return (hidden_rank, idx, spot.name)


async def build_collections_response(
    region_code: str | None,
    spot_repo: SpotRepository,
    congestion_repo: CongestionRepository,
    cache: Cache,
    diverse: bool = False,
    seed: int | None = None,
    per_theme: int | None = None,
    theme: str | None = None,
    offset: int = 0,
) -> CollectionsResponse:
    """seed(부록 S, 2026-08-01): 테마 아이템 표본의 난수 시드. None 이면 서버가 새로 뽑는다.

    2026-08-01 대표 지시로 각 테마의 아이템은 **무작위 표본**이 됐다. 테마 매칭(자격)과
    "숨은 스팟 먼저 → 저혼잡 먼저"라는 등급은 그대로다 — 무작위는 *같은 등급 안에서만*
    작용한다(품질 하한 불변). 순위성 섹션(홈 trending, seasonal.popular)은 손대지 않았다.

    diverse(부록 S.5 additive, 2026-08-01): true + region_code 미지정이면 9권역을 합친 풀에서
    뽑는다(featured 와 같은 규약). 기본 false → 기존 호출부 응답 불변(하위호환).

    per_theme / theme / offset (부록 S.8 additive, 2026-08-01 — "전체 보기·더보기"):
      - per_theme: 테마당 노출 개수(기본 8 = 종전, 1~50 클램프).
      - theme    : 그 테마 하나만 조회(더보기가 쓰는 모드). 없으면 전체 테마.
      - offset   : **결정적 순열의 시작 인덱스**(= 지금까지 받은 개수). 응답은 정확히
                   `순열[offset : offset+per_theme]` 이다. **전체 조회에도 같은 규칙**으로
                   적용된다(테마마다 독립적인 순열).
    응답의 `seed` 를 그대로 재사용해 offset 만 늘리면 중복·누락 없이 이어진다.
    S.8.6 수정(2026-08-01): 순열이 per_theme 과 무관하므로 **더보기 도중 per_theme 을 바꿔도**
    중복·누락이 없다(운영에서 8 → 50 조합으로 중복이 실제 발생해 고친 결함).
    """
    per_theme = _clamp(per_theme, MAX_PER_COLLECTION, 1, PER_THEME_MAX)
    offset = _clamp(offset, 0, 0, OFFSET_MAX)
    # 시드는 항상 확정한다 — 응답에 실어 보내야 더보기가 같은 순열을 이어받는다(S.8).
    seed = seed if seed is not None else sampling.new_seed()

    if diverse and not (region_code or "").strip():
        return await _build_diverse_response(
            spot_repo, congestion_repo, cache, seed, per_theme, theme, offset
        )

    region_code = _resolve_region_code(region_code)
    region_name = _region_name(region_code)
    all_spots = spot_repo.by_region(region_code, None)
    cmap = await _congestion_map(region_code, congestion_repo)
    wanted = {t.key for t in _themes_for(theme)}

    # --- 테마별 자격 → 등급(숨은/일반)별 저혼잡 정렬 → 등급 순서대로 무작위 표본 ---
    tagset_by_id = {s.id: _tag_sets(s) for s in all_spots}
    selected: list[_Picked] = []
    needed_ids: set[int] = set()
    used_ids: set[int] = set()  # 테마 간 중복 회피용(후보가 모자라면 허용 — 빈 자리보다 낫다)
    # `theme` 이 지정돼도 **THEMES 전체를 순회**한다. used_ids(테마 간 중복 회피 등급)가
    # 앞 테마들의 **순열 앞 8개**에 의존하기 때문이다 — 이걸 건너뛰면 더보기 요청의 등급
    # 기준이 달라져 같은 시드인데도 순열이 흔들린다(중복/누락 발생). 조립·사진 조회는
    # 요청된 테마만 하므로 추가 비용은 순수 CPU 뿐이다.
    for th in THEMES:
        matched = [s for s in all_spots if _qualifies(th, s, tagset_by_id[s.id])]
        total = len(matched)
        if total < MIN_PER_COLLECTION:
            continue  # 스팟 부족 테마는 지어내지 않고 스킵
        matched.sort(key=lambda s: _hidden_lowcong_key(s, cmap))
        need = min(per_theme, total)
        # 등급: 숨은 스팟 > 시드 사진 보유 > 다른 테마에 아직 안 쓰임(_tier_index, diverse 와 공용).
        # 품질(숨은 우선)이 사진·신선도보다 앞선다. 사진 등급은 여유분(spare)을 없앤 대신
        # 앞쪽 아이템이 사진을 갖게 하는 장치다(S.8.6).
        tiers = _tiers_by_index(matched, used_ids)
        # S.8.6: offset 은 **결정적 순열의 아이템 인덱스**다 — page_size 를 도중에 바꿔도
        # 중복·누락이 없다. (단일 지역 경로는 등급에 사진이 추가돼 종전과 조합이 달라질 수
        # 있다 — 대신 여유분 없이도 사진 채움률이 유지된다. 실측은 01-backend-design.md.)
        primary, prefix, has_next = sampling.sample_paged(
            tiers,
            need,
            offset if th.key in wanted else 0,
            seed,
            f"collections:{th.key}",
        )
        # 등급 기준은 **항상 순열 앞 8개 기준**이다(offset·per_theme·theme 필터와 무관) —
        # 그래야 어떤 요청에서도 같은 순열이 재현된다. 노출되지 않는 테마(3개 미만)는
        # 종전과 동일하게 used_ids 에 넣지 않는다.
        if len(prefix) >= MIN_PER_COLLECTION:
            used_ids.update(s.id for s in prefix)
        if th.key not in wanted:
            continue
        # 첫 페이지에서만 "3개 미만 스킵"을 적용한다. 더보기(offset>0)의 마지막 페이지가
        # 1~2개 남는 건 정상이며, 그걸 버리면 "전체 보기"가 성립하지 않는다.
        if offset == 0 and len(primary) < MIN_PER_COLLECTION:
            continue
        if not primary:
            continue
        selected.append(_Picked(th, primary, total, has_next))
        needed_ids.update(s.id for s in primary)

    # --- 선택된 스팟들 사진 동시 조회(체인+캐시 공유, 중복 id 는 1회) ---
    needed_spots = [s for s in all_spots if s.id in needed_ids]
    photos = await spot_detail_service.get_photos(needed_spots, cache)
    photo_by_id = {s.id: p for s, p in zip(needed_spots, photos)}

    collections = _assemble(
        selected,
        photo_by_id,
        cmap_for=lambda s: cmap,
        region_name_for=lambda s: region_name,
    )
    region = RecommendRegion(region_code=region_code, region_name=region_name)
    return CollectionsResponse(region=region, collections=collections, seed=seed)


def _assemble(
    selected: list[_Picked],
    photo_by_id: dict[int, object],
    cmap_for: Callable[[SpotRecord], dict[str, float | None]],
    region_name_for: Callable[[SpotRecord], str | None],
) -> list[ThemeCollection]:
    """선택 결과 → ThemeCollection 목록. 단일 지역/diverse 공용 조립부.

    표시 순서는 숨은 먼저 → 저혼잡 → 이름. 노출 대상은 **결정적 순열의 해당 구간 그대로**다
    (S.8.6) — 여유분으로 자리를 바꿔치기하지 않는다. 사진 우선은 순열을 만들 때 등급으로
    이미 반영돼 있고, 여기서 바꿔치기하면 그 후보가 다음 페이지에도 남아 중복이 된다.

    `total`(S.8)은 노출 개수가 아니라 **자격 통과 후보 총 수**다. 후보가 모자라면 있는 만큼만
    내려주고 total 로 정직하게 알린다(자격 미달을 끌어올려 채우지 않는다).
    """
    collections: list[ThemeCollection] = []
    for picked in selected:
        theme, primary = picked.theme, picked.primary
        spots = list(primary)
        spots.sort(key=lambda s: _hidden_lowcong_key(s, cmap_for(s)))
        collections.append(
            ThemeCollection(
                theme_key=theme.key,
                title=theme.title,
                total=picked.total,
                has_more=picked.has_next,
                spots=[
                    FeaturedSpot(
                        id=s.id,
                        name=s.name,
                        category=s.category,  # type: ignore[arg-type]
                        region_name=region_name_for(s),
                        address=s.address,
                        location={"lat": s.lat, "lng": s.lng},
                        congestion=recommend_service._match_congestion(s.name, cmap_for(s)),
                        is_hidden_gem=s.is_hidden_gem,
                        image_url=(p := photo_by_id.get(s.id, NO_PHOTO)).url,  # type: ignore[union-attr]
                        photo_credit=p.credit,  # type: ignore[union-attr]
                    )
                    for s in spots
                ],
            )
        )
    return collections


# ---------------------------------------------------------------------------
# 부록 S.5 — 지역 다양성 모드(diverse=true, region_code 미지정)
#
# 왜 필요했나(2026-08-01 대표 재보고 "새로고침해도 테마별 여행은 계속 같은 곳"):
# 컬렉션은 **단일 지역(기본 해운대)** 스팟만 후보로 썼다. 실측 후보 수가 힐링 15 / 로컬카페 7 /
# 자연 8 밖에 안 돼(노출은 7~8개) 섞을 여지가 사실상 없었다 — 랜덤이 고장난 게 아니라 풀이
# 없었다. 여기서는 9권역(REGION_BLOCKS) 대표 시군구를 **합친 풀**에서 뽑는다(같은 실측 기준
# 힐링 546 / 로컬카페 318 / 자연 228).
#
# 원천 비용은 늘지 않는다:
#   - board(혼잡도)  : featured diverse 와 **같은 캐시 키**(congestion:{area}:{sigungu}) 재사용.
#   - 사진(firstimage): **노출할 구간만**(S.8.6 로 여유분 폐지 — 조회 수 = 노출 수).
#   - 후보 풀(테마 매칭) : 시드만의 함수라 6h 캐시. 단 **표본 추출은 매 요청**이다.
# ---------------------------------------------------------------------------


def _theme_pool_ids(spot_repo: SpotRepository) -> dict[str, dict[str, list[int]]]:
    """theme_key → {시군구코드: [스팟 id]}. 혼잡도·난수와 무관한 순수 함수(캐시 안전).

    id 만 담는 이유: 캐시 값이 JSON 직렬화 가능해야 나중에 Redis 로 바꿔도 그대로 쓴다
    (SpotRecord 객체를 캐시에 넣으면 인메모리 캐시에서만 동작한다).
    """
    out: dict[str, dict[str, list[int]]] = {}
    for block in REGION_BLOCKS:
        spots = spot_repo.by_region(block.region_code, None)
        if not spots:
            continue
        tagset_by_id = {s.id: _tag_sets(s) for s in spots}
        for theme in THEMES:
            ids = [s.id for s in spots if _qualifies(theme, s, tagset_by_id[s.id])]
            if ids:
                out.setdefault(theme.key, {})[block.region_code] = ids
    return out


async def _diverse_pool_ids(
    spot_repo: SpotRepository, cache: Cache
) -> dict[str, dict[str, list[int]]]:
    cached = await cache.get(_DIVERSE_POOL_KEY)
    if isinstance(cached, dict):
        return cached
    pools = _theme_pool_ids(spot_repo)
    await cache.set(_DIVERSE_POOL_KEY, pools, DIVERSE_POOL_TTL_SEC)
    return pools


def _round_robin(lists: list[list[SpotRecord]]) -> list[SpotRecord]:
    """지역별 목록을 번갈아 이어 붙인다 — 풀 상한(sampling.pool_cap)에 잘려도 지역 균형 유지.

    지역별로 이어 붙이면 앞쪽 48개가 한두 지역으로 차서 "시군구당 2곳" 상한에 걸려 컬렉션이
    비어 버린다. 라운드로빈이면 어느 위치에서 잘라도 지역이 고루 섞인다.
    """
    out: list[SpotRecord] = []
    for i in range(max((len(v) for v in lists), default=0)):
        for v in lists:
            if i < len(v):
                out.append(v[i])
    return out


# 등급(작을수록 우선): 시드 사진 보유 > 숨은 스팟 > 다른 테마에 아직 안 쓰임.
# 사진 등급은 오케스트레이터 실측 근거다 — 등급 없이 뽑으면 사진 채움률이 61%까지 떨어져
# 카드 대부분이 플레이스홀더가 된다. 시드 image_url 은 이미 메모리에 있어 등급화 비용 0.
#
# 2026-08-01(부록 H.7, 대표 지시 "군데군데 빈 사진이 너무 많다") — 사진과 숨은 스팟의 가중치를
# **맞바꿨다**. 종전엔 숨은(4) > 사진(2) 이라 `숨은+사진없음`이 `일반+사진있음`보다 앞에 와서,
# 더보기로 깊이 들어갈수록 플레이스홀더가 쌓였다(실측 per_theme=50 에서 92%).
# 컨셉 훼손은 거의 없다: is_hidden_gem 은 "대표이미지가 없으면 덜 알려진 곳"이라는 프록시를
# 포함하므로(category_map.py:97), 이 교체로 뒤로 밀리는 스팟의 상당수는 *사진이 없다는 이유
# 하나로* 숨은 자격을 얻은 곳이다. 카테고리 근거(cafe·craft·market·trail)로 숨은 곳이 된
# 스팟은 90%가 사진을 갖고 있어 그대로 앞에 남는다(실측).
_TIER_COUNT = 8


def _tier_index(spot: SpotRecord, used_ids: set[int]) -> int:
    return (
        (0 if spot.image_url else 4)
        + (0 if spot.is_hidden_gem else 2)
        + (0 if spot.id not in used_ids else 1)
    )


def _tiers_by_index(candidates: list[SpotRecord], used_ids: set[int]) -> list[list[SpotRecord]]:
    """선호순 정렬된 후보 → 등급별 풀(단일 지역 경로용. diverse 는 지역 라운드로빈판을 쓴다).

    S.8.6(2026-08-01): 단일 지역 경로도 diverse 와 **같은 등급 정의**를 쓴다. 종전에는 사진
    등급 없이 여유분(spare)으로 사진 없는 자리를 메웠는데, 그 여유분이 페이지 간 중복·누락의
    원인이라 없앴다 — 대신 사진 보유를 등급에 넣어 앞쪽 아이템이 사진을 갖게 한다.
    """
    return [[s for s in candidates if _tier_index(s, used_ids) == t] for t in range(_TIER_COUNT)]


def _diverse_tiers(
    by_region_sorted: dict[str, list[SpotRecord]], used_ids: set[int]
) -> list[list[SpotRecord]]:
    """{시군구: 선호순 정렬된 후보} → 등급별 풀(각 등급 안은 지역 라운드로빈)."""
    tiers: list[list[SpotRecord]] = []
    for t in range(_TIER_COUNT):
        per_region = [
            [s for s in recs if _tier_index(s, used_ids) == t] for recs in by_region_sorted.values()
        ]
        tiers.append(_round_robin([v for v in per_region if v]))
    return tiers


async def _build_diverse_response(
    spot_repo: SpotRepository,
    congestion_repo: CongestionRepository,
    cache: Cache,
    seed: int | None = None,
    per_theme: int = MAX_PER_COLLECTION,
    theme: str | None = None,
    offset: int = 0,
) -> CollectionsResponse:
    pools = await _diverse_pool_ids(spot_repo, cache)
    wanted = {t.key for t in _themes_for(theme)}

    # 9권역 board — featured diverse 와 같은 캐시 키라 워밍된 상태면 원천 호출 0.
    # (_congestion_map 은 실패를 빈 맵으로 흡수한다 — 혼잡도가 컬렉션을 막지 않는다.)
    cmaps: dict[str, dict[str, float | None]] = dict(
        zip(
            [b.region_code for b in REGION_BLOCKS],
            await asyncio.gather(
                *[_congestion_map(b.region_code, congestion_repo) for b in REGION_BLOCKS]
            ),
        )
    )
    region_names = {b.region_code: _region_name(b.region_code) for b in REGION_BLOCKS}

    selected: list[_Picked] = []
    needed_ids: set[int] = set()
    used_ids: set[int] = set()  # 테마 간 중복 회피(등급으로만 작용 — 후보가 모자라면 허용)
    # 단일 지역 경로와 같은 이유로 **THEMES 전체를 순회**한다(used_ids 등급 재현. S.8).
    for th in THEMES:
        by_region_ids = pools.get(th.key, {})
        total = sum(len(v) for v in by_region_ids.values())
        if total < MIN_PER_COLLECTION:
            continue  # 후보 부족 테마는 지어내지 않고 스킵(단일 지역 경로와 동일 규칙)
        by_region_sorted: dict[str, list[SpotRecord]] = {}
        for rc, ids in by_region_ids.items():
            recs = [r for r in (spot_repo.by_id(i) for i in ids) if r is not None]
            cmap = cmaps.get(rc, {})
            recs.sort(key=lambda s: _hidden_lowcong_key(s, cmap))
            if recs:
                by_region_sorted[rc] = recs
        need = min(per_theme, total)
        primary, prefix, has_next = sampling.sample_paged(
            _diverse_tiers(by_region_sorted, used_ids),
            need,
            offset if th.key in wanted else 0,
            seed,
            f"collections:diverse:{th.key}",
            group_key=lambda s: s.region_code,        # 시군구당 …
            group_cap=DIVERSE_MAX_PER_SIGUNGU,        # … 순열 청크(8개)당 최대 2곳
        )
        if len(prefix) >= MIN_PER_COLLECTION:
            used_ids.update(s.id for s in prefix)
        if th.key not in wanted:
            continue
        if offset == 0 and len(primary) < MIN_PER_COLLECTION:
            continue
        if not primary:
            continue
        selected.append(_Picked(th, primary, total, has_next))
        needed_ids.update(s.id for s in primary)

    # --- 사진 동시 조회(중복 id 는 1회, 캐시·체인은 단일 지역 경로와 공유) ---
    needed_spots: list[SpotRecord] = []
    seen: set[int] = set()
    for picked in selected:
        for s in picked.primary:
            if s.id not in seen:
                seen.add(s.id)
                needed_spots.append(s)
    photos = await spot_detail_service.get_photos(needed_spots, cache)
    photo_by_id = {s.id: p for s, p in zip(needed_spots, photos)}

    # 조립은 단일 지역 경로와 공용(_assemble) — 지역별 cmap/region_name 만 다르게 준다.
    collections = _assemble(
        selected,
        photo_by_id,
        cmap_for=lambda s: cmaps.get(s.region_code, {}),
        region_name_for=lambda s: region_names.get(s.region_code),
    )

    # 여러 지역이 섞인 목록이라 대표 region 이 없다 — null(featured diverse 와 같은 규약).
    # 카드별 region_name 이 어느 지역인지 알려준다(FeaturedSpot 에 이미 있는 필드).
    return CollectionsResponse(region=None, collections=collections, seed=seed)
