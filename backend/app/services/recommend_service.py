"""스팟 추천 서비스 (부록 C.3~C.5) — 프로필 재검증 + 스코어링 + SpotCard 조립.

소관 분리(부록 C.5, 08 D1 패턴):
  - AI(app/ai/spot_fit.py): spot_fit(코사인) + matched_tags 만 계산.
  - backend(이 파일): 프로필 신뢰경계 재검증(C.4), 혼잡도(M2)·local_exposure·
    accessibility 하드필터 결합, scoring_weights 가중합·정규화, 정렬, signals 조립.

프로필은 프론트 sessionStorage에서 온 값이라 **신뢰경계 밖**이다. 소비 전 반드시
재검증한다(C.4). 프로필 값은 스코어링 입력(벡터·enum·수치)으로만 쓰고 화면에
원문 렌더하지 않는다 — 자유텍스트가 없어 LLM/DB 주입 경로가 존재하지 않는다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from ..ai import spot_fit, tag_registry
from ..regions.seed import REGIONS
from ..repositories.congestion_repo import CongestionRepository
from ..repositories.spot_repo import SpotRecord, SpotRepository
from ..schemas.places import (
    MatchReasons,
    RecommendMeta,
    RecommendRegion,
    RecommendResponse,
    RecommendResponseRerank,
    RerankBlock,
    RerankDistribution,
    RerankInput,
    SpotCard,
    SpotCongestion,
    SpotLocation,
    SpotThemes,
)
from ..spots.region_map import get_tourapi_region
from ..util.names import norm_name
from ..util.time import KST, to_iso_kst
from . import rerank_service
from .congestion_service import classify_level
from .weather_provider import WeatherProvider

logger = logging.getLogger("sumeungil.services.recommend")

LIMIT_MIN, LIMIT_MAX, LIMIT_DEFAULT = 1, 50, 20
WEIGHT_KEYS = ("congestion", "profile_fit", "distance", "local_exposure", "trust")

# 명시 정렬(사용자가 고른) — 이 정렬이면 balance rerank 재정렬을 적용하지 않는다(explicit_sort).
_EXPLICIT_SORTS = frozenset({"popular", "calm"})
# recommended 는 personalized 의 별칭(match_score 내림차순, 프로필 없으면 기존 기본순).
_RECOMMENDED_SORTS = frozenset({"personalized", "recommended"})

HIGH_FIT_THRESHOLD = 0.5
# accessibility registry value → 스팟 themes 키 (하드필터 대조용)
_ACCESS_THEME_MAP = {
    "pet_friendly_required": "pet_allowed",
    "wheelchair_friendly": "barrier_free",
    "stroller_friendly": "barrier_free",
}


class ProfileValidationError(Exception):
    """구조 위반(V1/V3) — 조작 신호. API 레이어가 400 INVALID_PROFILE 로 매핑(C.4a 권장)."""


@dataclass
class ValidatedProfile:
    tag_vector: list[float]
    scoring_weights: dict[str, float]
    accessibility_values: set[str]
    rejected_tag_count: int = 0


def clamp_limit(limit: int) -> int:
    return max(LIMIT_MIN, min(LIMIT_MAX, limit))


# ---------- C.4 신뢰경계 재검증 ----------

def validate_profile(profile) -> ValidatedProfile | None:
    """프론트 프로필 재검증. 프로필 없음 또는 관대 폐기(V2)면 None, 구조 위반(V1/V3)이면 raise.

    - None 반환  → 비개인화 진행(personalized:false)
    - raise      → 400 INVALID_PROFILE (조작 의심 명확 실패)
    """
    if profile is None or profile.tag_vector is None:
        return None

    vec = profile.tag_vector

    # V1: 길이 36 · 원소 이진(0.0/1.0)
    if len(vec) != tag_registry.VECTOR_DIM or any(x not in (0.0, 1.0) for x in vec):
        raise ProfileValidationError("tag_vector 길이/이진 위반")

    # V2: vector_version 일치 — 불일치는 관대 폐기(스키마 진화 허용), 비개인화 200
    if profile.vector_version != tag_registry.VECTOR_VERSION:
        logger.info("vector_version 불일치(%s≠%s) → 프로필 관대 폐기, 비개인화 진행",
                    profile.vector_version, tag_registry.VECTOR_VERSION)
        return None

    # V3: scoring_weights 5키 존재 · 각 0~1 · 합 1.0±0.01
    w = profile.scoring_weights or {}
    if set(w.keys()) != set(WEIGHT_KEYS):
        raise ProfileValidationError("scoring_weights 키 불일치")
    if any(not isinstance(v, (int, float)) or v < 0.0 or v > 1.0 for v in w.values()):
        raise ProfileValidationError("scoring_weights 값 범위 위반")
    if abs(sum(w.values()) - 1.0) > 0.01:
        raise ProfileValidationError("scoring_weights 합 != 1.0")

    # V4: tags[].value registry 검증 → registry 밖은 개별 폐기(에러 아님), 카운트
    accessibility_values: set[str] = set()
    rejected = 0
    for axis, values in (profile.tags or {}).items():
        for tv in values or []:
            val = tv.get("value") if isinstance(tv, dict) else None
            if val is None:
                continue
            if tag_registry.is_valid(axis, val):
                if axis == "accessibility":
                    accessibility_values.add(val)
            else:
                rejected += 1

    return ValidatedProfile(
        tag_vector=[float(x) for x in vec],
        scoring_weights={k: float(w[k]) for k in WEIGHT_KEYS},
        accessibility_values=accessibility_values,
        rejected_tag_count=rejected,
    )


# ---------- 혼잡도(M2) 조인 ----------

# 정규화 규칙의 정의는 util.names 로 이동(예보 서비스와 공유 — congestion_service 가
# recommend_service 를 import 하면 순환이라 공용 모듈로 내렸다). 동작·호출부는 불변.
_norm = norm_name


async def _congestion_by_name(
    region_code: str, congestion_repo: CongestionRepository
) -> dict[str, float | None]:
    """M2 전광판 데이터에서 관광지명→집중률 맵을 만든다. 실패/없음이면 빈 맵."""
    area_cd = next((r.area_cd for r in REGIONS if r.region_id == region_code), None)
    if not area_cd:
        return {}
    try:
        result = await congestion_repo.get_board(area_cd, region_code)
    except Exception as exc:  # noqa: BLE001 — 혼잡도 실패는 추천을 막지 않는다
        logger.info("혼잡도 조인 스킵(원천 실패) region=%s: %s", region_code, exc)
        return {}
    return {_norm(rec.spot_name): rec.congestion_rate for rec in result.records if rec.spot_name}


def _match_congestion(name: str, cmap: dict[str, float | None]) -> SpotCongestion | None:
    """스팟명 ↔ 혼잡도 관광지명 매칭. 없으면 None(억지 매칭 금지)."""
    if not cmap:
        return None
    nn = _norm(name)
    rate: float | None = None
    if nn in cmap:
        rate = cmap[nn]
    else:
        for cname, crate in cmap.items():
            if cname and (cname in nn or nn in cname):
                rate = crate
                break
        else:
            return None
    return SpotCongestion(index=rate, level=classify_level(rate), tier="B")


# ---------- 스코어링 ----------

@dataclass
class _Scored:
    spot: SpotRecord
    congestion: SpotCongestion | None
    match_score: float | None
    reasons: MatchReasons | None
    _sort_cong: float = field(default=101.0)  # 정렬용: 낮을수록 여유(없으면 뒤로)


# 희소 태그 가중(IDF) 공급자. 앱 시작 시 main.py 가 연결한다 — 추천·비교·코스가 **같은 스팟에 같은
# 매칭도**를 내도록 셋 다 이 한 곳을 거친다. 연결하지 않으면(테스트) 종전 이진 코사인이다.
_TAG_WEIGHTS_SOURCE: Callable[[], list[float] | None] | None = None


def use_tag_weights(source: Callable[[], list[float] | None] | None) -> None:
    global _TAG_WEIGHTS_SOURCE
    _TAG_WEIGHTS_SOURCE = source


def _score_spot(
    spot: SpotRecord,
    congestion: SpotCongestion | None,
    prof: ValidatedProfile,
) -> tuple[float, MatchReasons]:
    w = prof.scoring_weights
    tag_weights = _TAG_WEIGHTS_SOURCE() if _TAG_WEIGHTS_SOURCE is not None else None
    fit = spot_fit.cosine_spot_fit(prof.tag_vector, spot.tag_vector, tag_weights)

    scores: dict[str, float] = {"profile_fit": fit, "local_exposure": 1.0 if spot.is_hidden_gem else 0.0}
    weights: dict[str, float] = {"profile_fit": w["profile_fit"], "local_exposure": w["local_exposure"]}

    if congestion is not None and congestion.index is not None:
        scores["congestion"] = 1.0 - congestion.index / 100.0
        weights["congestion"] = w["congestion"]
    # distance·trust 축은 MVP-4 중립 → 재정규화에서 제외

    total_w = sum(weights.values())
    base = sum(scores[k] * weights[k] for k in scores) / total_w if total_w > 0 else fit

    # accessibility 하드필터: 충돌 시 감점(하드컷 아님), null은 중립, 충족은 theme_match
    matched_access: list[str] = []
    penalty = 1.0
    themes = spot.themes or {}
    for acc in prof.accessibility_values:
        theme_key = _ACCESS_THEME_MAP.get(acc)
        if not theme_key:
            continue
        val = themes.get(theme_key)
        if val is False:
            penalty *= 0.7
        elif val is True:
            matched_access.append(acc)
    score = max(0.0, min(1.0, base * penalty))

    # signals 조립 (C.2.2)
    signals: list[str] = []
    if congestion is not None and congestion.level == "low":
        signals.append("low_congestion")
    if spot.is_hidden_gem:
        signals.append("hidden_gem")
    if fit >= HIGH_FIT_THRESHOLD:
        signals.append("high_profile_fit")
    if matched_access:
        signals.append("theme_match")

    matched = spot_fit.matched_tags(prof.tag_vector, spot.tag_vector) + matched_access
    return score, MatchReasons(matched_tags=matched, signals=signals)


def _to_card(scored: _Scored) -> SpotCard:
    s = scored.spot
    return SpotCard(
        id=s.id,
        name=s.name,
        category=s.category,  # type: ignore[arg-type]
        region_code=s.region_code,
        address=s.address,
        location=SpotLocation(lat=s.lat, lng=s.lng),
        congestion=scored.congestion,
        themes=SpotThemes(**(s.themes or {})),
        is_hidden_gem=s.is_hidden_gem,
        match_score=scored.match_score,
        match_reasons=scored.reasons,
    )


async def build_recommend_response(
    region_code: str,
    profile,
    category: str | None,
    sort: str,
    limit: int,
    spot_repo: SpotRepository,
    congestion_repo: CongestionRepository,
    rerank: RerankInput | None = None,
    weather_provider: WeatherProvider | None = None,
    spot_type: str = "all",
) -> RecommendResponse:
    limit = clamp_limit(limit)
    prof = validate_profile(profile)  # 구조 위반 시 여기서 ProfileValidationError

    spots = spot_repo.by_region(region_code, category)
    # 유형 필터(정렬 이전 적용, 부록 C.9). all=전체 → 필터 없음(하위호환).
    if spot_type == "hidden":
        spots = [s for s in spots if s.is_hidden_gem]
    elif spot_type == "popular":
        spots = [s for s in spots if not s.is_hidden_gem]
    cmap = await _congestion_by_name(region_code, congestion_repo)

    scored: list[_Scored] = []
    for spot in spots:
        cong = _match_congestion(spot.name, cmap)
        sort_cong = cong.index if (cong and cong.index is not None) else 101.0
        if prof is not None:
            score, reasons = _score_spot(spot, cong, prof)
            scored.append(_Scored(spot, cong, score, reasons, sort_cong))
        else:
            scored.append(_Scored(spot, cong, None, None, sort_cong))

    personalized = prof is not None
    effective_sort = sort
    if sort in _RECOMMENDED_SORTS and not personalized:
        effective_sort = "congestion"  # 프로필 없이 추천 요청 → 기존 기본순(혼잡도)로 강등

    def _cidx(x: _Scored) -> float | None:
        c = x.congestion
        return c.index if (c is not None and c.index is not None) else None

    if effective_sort in _RECOMMENDED_SORTS:
        # recommended/personalized: match_score 내림차순(기존 동작 그대로)
        scored.sort(key=lambda x: (-(x.match_score or 0.0), x._sort_cong, x.spot.name))
    elif effective_sort == "popular":
        # 인기명소(is_hidden_gem=false) 우선 + congestion.index 내림차순(붐빌수록 인기 프록시). null 뒤.
        scored.sort(key=lambda x: (
            x.spot.is_hidden_gem,                    # False(인기)=0 먼저
            0 if _cidx(x) is not None else 1,        # 그룹 내 congestion 있는 것 먼저, null 뒤
            -(_cidx(x) or 0.0),                      # index 내림차순
            x.spot.name,
        ))
    elif effective_sort == "calm":
        # congestion.index 오름차순(한적한 순). _sort_cong 는 null 이면 101.0 → 맨 뒤.
        scored.sort(key=lambda x: (x._sort_cong, x.spot.name))
    else:  # congestion / distance(MVP-4=congestion) — 혼잡도 오름차순, 숨은곳 우선, 이름
        scored.sort(key=lambda x: (x._sort_cong, not x.spot.is_hidden_gem, x.spot.name))

    items = [_to_card(s) for s in scored[:limit]]

    region_name = None
    tr = get_tourapi_region(region_code)
    if tr:
        region_name = tr.region_name
    else:
        region_name = next((r.label for r in REGIONS if r.region_id == region_code), None)

    now: datetime = datetime.now(KST)
    rejected = prof.rejected_tag_count if prof else 0
    # 무스팟 지역 graceful: 빈 목록이라도 200 으로 정직히 "준비 중"을 알린다(404·거짓 데이터 금지).
    notice = None
    if not items:
        notice = "이 지역은 아직 숨은 명소를 준비 중이에요. 곧 추가할게요."
    meta = RecommendMeta(
        source="tourapi_local_store",
        fetched_at=to_iso_kst(now),
        cache="hit",
        profile_applied=personalized,
        rejected_tag_count=rejected,
        notice=notice,
    )
    region = RecommendRegion(region_code=region_code, region_name=region_name)

    # --- MVP-7 rerank (부록 F) — opt-in. 미요청이면 아래 확장을 타지 않아 응답 바이트 동일(무회귀) ---
    if rerank is None or not (rerank.balance or rerank.weather):
        return RecommendResponse(
            region=region, personalized=personalized, items=items, meta=meta,
        )

    block = RerankBlock()
    # [2] 혼잡 분산 rerank(단 1회, 순서만). 요청 시에만.
    # 명시 정렬(popular/calm) 이면 사용자가 고른 순서가 우선 → balance 재정렬을 적용하지 않고
    # applied:false, reason:"explicit_sort" 로 정직 표기(부록 C.9). match_score 불변.
    # 부록 F.1-7(2026-08-01, 대표 지시): *"맞춤 추천은 내 취향에 맞춰서 추천을 우선적으로
    # 해줘야지 혼잡도 무관하게."* — 개인화가 걸린 맞춤 추천에서는 balance 재정렬을 적용하지 않는다.
    #
    # 단순한 취향 반영 문제가 아니라 **이중 반영 결함**이었다: `congestion` 은 이미 match_score 의
    # 5개 가중치 축 중 하나다(WEIGHT_KEYS, _score() 참고). 사용자가 온보딩에서 정한 비중만큼
    # 점수에 이미 녹아 있는데, 그 위에 `apply_balance_rerank` 가 **비-high 전부를 high 전부보다
    # 위로 올리는 하드 파티션**을 걸어 취향 점수를 통째로 덮어썼다. 취향이 훨씬 잘 맞는 곳이
    # 붐빈다는 이유만으로 덜 맞는 곳 아래로 내려갔다.
    #
    # 재정렬을 빼도 혼잡도가 버려지는 게 아니다 — (1) match_score 안에 가중치로 남아 있고,
    # (2) 기본 정렬이 `(-match_score, _sort_cong, name)` 이라 **점수가 같으면 한적한 곳이 위**다.
    # 즉 "취향 1순위, 동점이면 한적한 곳"이 된다.
    if rerank.balance:
        if effective_sort in _EXPLICIT_SORTS:
            block.distribution = RerankDistribution(applied=False, reason="explicit_sort")
        elif personalized and effective_sort in _RECOMMENDED_SORTS:
            # 순서는 건드리지 않되, "이 지역은 지금 전반적으로 붐빈다"는 **경고는 살린다**.
            # 이건 재정렬이 아니라 정보다 — 대안이 아예 없다는 사실은 취향 우선과 무관하게
            # 알려주는 편이 낫다(rerank_service 의 no_alternative 분기도 순서를 바꾸지 않는다).
            _, probe = rerank_service.apply_balance_rerank(items)
            block.distribution = (
                probe
                if probe.reason == "no_alternative"
                else RerankDistribution(applied=False, reason="taste_priority")
            )
        else:
            items, block.distribution = rerank_service.apply_balance_rerank(items)
    # [2.5] 날씨 rerank — 파트1 결과 안에서만(단 1회). high 스팟은 위로 안 올림(혼잡 불변식).
    if rerank.weather:
        snapshot = None
        if weather_provider is not None:
            snapshot = await weather_provider.get_region_forecast(region_code)
        items, block.weather = rerank_service.apply_weather_rerank(items, snapshot)

    return RecommendResponseRerank(
        region=region, personalized=personalized, items=items, meta=meta, rerank=block,
    )
