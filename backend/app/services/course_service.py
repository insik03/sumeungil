"""AI 추천 코스 서비스 (부록 I) — 취향/저혼잡 스팟을 순서 있는 하루 코스로 엮고,
스팟쌍마다 Tmap 도보/차 소요시간·경로선(legs)을 붙인다.

소관 분리(recommend_service 조각 재사용, match_score 재계산 금지):
  - 스코어링/혼잡도조인/SpotCard 조립 → recommend_service 의 검증된 함수를 그대로 호출.
  - 이 파일은 (1) 시간대 슬롯으로 코스 순서 조립 (2) Tmap legs 결합(캐시)만 담당.

휴리스틱은 근거 있는 것만: 있는 카테고리로만 슬롯을 채우고(없으면 스킵, 지어내지 않음),
저혼잡·숨은 스팟 우선(숨은길 컨셉), profile 있으면 match_score 상위, 같은 슬롯 내에선
직전 스팟과 지리적으로 가까운 것 우선(이동 최소화). 좌표 이상 스팟은 코스에서 제외한다
(leg 를 만들 수 없어 코스 품질을 해침 — 정직).
"""

from __future__ import annotations

import asyncio
import logging
import random

from ..ai.summarizer import Summarizer
from ..cache.base import Cache
from ..clients import tmap_client
from ..config import settings
from ..regions.seed import REGIONS
from ..repositories.congestion_repo import CongestionRepository
from ..repositories.spot_repo import SpotRepository
from ..schemas.courses import CourseLeg, CourseResponse, CourseSpot, RouteMode
from ..schemas.places import RecommendRegion
from ..spots.region_map import get_tourapi_region
from . import course_enrich_service, course_summary_service, recommend_service

logger = logging.getLogger("sumeungil.services.course")

# 시간대 슬롯(순서=하루 흐름). 있는 카테고리로만 채운다. 한 스팟은 한 슬롯에만(중복 제거).
# 08 카테고리(attraction/restaurant/cafe/craft/trail/nature/market/etc) 기준.
_SLOTS: list[tuple[str, set[str]]] = [
    ("아침 카페", {"cafe"}),
    ("오전 명소", {"attraction", "nature"}),
    ("점심", {"restaurant"}),
    ("오후 산책", {"trail", "craft"}),
    ("저녁 명소", {"attraction", "nature", "market"}),  # 5번째: 오전과 다른 스팟(중복제거)
]
_TARGET_MIN, _TARGET_MAX = 4, 5
# 슬롯당 후보군 크기 — 최종 1곳을 뽑을 후보를 품질 상위 이만큼으로 한정한다(품질 하위를
# 끌어올리지 않는다는 원칙 유지). "최종 1곳 대비 4배수" 요구사항을 만족한다.
_QUALITY_POOL = 4


def _quality_key(s: "recommend_service._Scored", personalized: bool):
    """슬롯 후보 품질 순위. personalized 면 match_score 우선, 아니면 저혼잡·숨은 우선."""
    if personalized:
        return (-(s.match_score or 0.0), s._sort_cong, not s.spot.is_hidden_gem, s.spot.name)
    return (s._sort_cong, not s.spot.is_hidden_gem, s.spot.name)


def _dist2(lat: float, lng: float, anchor: tuple[float, float]) -> float:
    """위경도 제곱거리(도시 스케일 근접 tie-break용, 정밀 측지 불필요)."""
    return (lat - anchor[0]) ** 2 + (lng - anchor[1]) ** 2


def _weighted_pick(items: list, weights: list[float]) -> object:
    """가중 무작위 1곳 선택(비었으면 호출 안 함 — 호출부가 len(items)>=1 보장)."""
    total = sum(weights)
    if total <= 0:
        return random.choice(items)
    r = random.uniform(0, total)
    upto = 0.0
    for item, w in zip(items, weights):
        upto += w
        if upto >= r:
            return item
    return items[-1]


def _pick(candidates: list, personalized: bool, anchor: tuple[float, float] | None) -> object | None:
    """슬롯 후보에서 1곳 선택: 품질 상위 `_QUALITY_POOL`곳 후보군 안에서 **가중 무작위**.

    2026-07-30 변경(대표 실사용 "같은 코스만 나온다" 지적, 원인 규명):
    기존엔 anchor=None(첫 슬롯)이면 품질 argmax(ranked[0])를, anchor 가 있으면 품질 상위
    `_QUALITY_POOL`곳 중 최근접 argmin 을 **항상** 결정적으로 골랐다 — 무작위 요소가 코드
    어디에도 없어서 같은 region_code+profile 조합은 100% 같은 스팟 조합을 냈다(코스 응답
    자체를 캐싱하는 계층은 없다 — build_course_response 를 감싸는 캐시 미검색·미발견. 즉
    "캐시가 같은 결과를 돌려주는" 문제가 아니라 **알고리즘에 확률적 요소가 아예 없었던 것**이
    근본 원인이었다).
    이제 anchor 유무와 무관하게 품질 상위 `_QUALITY_POOL`(최종 1곳 대비 4배수) 후보군을 추린
    뒤, 그 안에서 (품질 순위 가중 + anchor 근접 순위 가중)으로 무작위 선택한다. 품질 하위
    스팟은 애초에 후보군에 들지 못하므로 코스 품질(정렬 규칙·API 계약)은 그대로 보호된다.
    """
    if not candidates:
        return None
    ranked = sorted(candidates, key=lambda s: _quality_key(s, personalized))
    pool = ranked[:_QUALITY_POOL]
    if len(pool) == 1:
        return pool[0]
    if anchor is None:
        weights = [len(pool) - i for i in range(len(pool))]
        return _weighted_pick(pool, weights)
    # 거리 순위 가중(가까울수록 큰 가중치) — 품질 순위 가중과 같은 스케일(1..len(pool))로 더해
    # 한쪽이 다른 쪽을 압도하지 않게 한다(원 거리값을 그대로 쓰면 좌표 스케일에 따라 사실상
    # 결정적으로 회귀할 수 있어 순위 기반으로 통일했다).
    dist_order = sorted(
        range(len(pool)), key=lambda i: _dist2(pool[i].spot.lat, pool[i].spot.lng, anchor)
    )
    dist_rank = [0] * len(pool)
    for rank, idx in enumerate(dist_order):
        dist_rank[idx] = rank
    weights = [(len(pool) - i) + (len(pool) - dist_rank[i]) for i in range(len(pool))]
    return _weighted_pick(pool, weights)


def _region_name(region_code: str) -> str | None:
    tr = get_tourapi_region(region_code)
    if tr:
        return tr.region_name
    return next((r.label for r in REGIONS if r.region_id == region_code), None)


async def _leg_between(a, b, cache: Cache) -> CourseLeg:
    """두 스팟 사이 도보/차 경로. 좌표쌍 키 24h 캐시. 실패 필드는 null(지어내지 않음)."""
    sx, sy, ex, ey = a.lng, a.lat, b.lng, b.lat
    cache_key = f"tmap:leg:{sy:.5f},{sx:.5f}:{ey:.5f},{ex:.5f}"

    cached = await cache.get(cache_key)
    if cached is not None:
        return CourseLeg(**cached)

    walk = await tmap_client.fetch_pedestrian_route(sx, sy, ex, ey)
    car = await tmap_client.fetch_car_route(sx, sy, ex, ey)

    # path 는 보행자 경로선 우선(숨은길 도보 컨셉), 없으면 자동차 경로선.
    path = None
    if walk and walk.get("path"):
        path = walk["path"]
    elif car and car.get("path"):
        path = car["path"]

    leg_dict = {
        "walk": {"minutes": walk["minutes"], "meters": walk["meters"]} if walk else None,
        "car": {"minutes": car["minutes"], "meters": car["meters"]} if car else None,
        "path": path,
    }
    # 성공/실패 무관하게 캐시(반복 호출 방지). 실패도 잠깐 캐시돼 무료 한도를 아낀다.
    await cache.set(cache_key, leg_dict, settings.tmap_cache_ttl_sec)
    return CourseLeg(
        walk=RouteMode(**leg_dict["walk"]) if leg_dict["walk"] else None,
        car=RouteMode(**leg_dict["car"]) if leg_dict["car"] else None,
        path=path,
    )


def _build_notice(personalized: bool, count: int) -> str | None:
    if count == 0:
        return "이 지역은 아직 코스로 묶을 숨은 스팟을 준비 중이에요. 곧 추가할게요."
    if count < _TARGET_MIN:
        return f"이 지역은 코스로 묶을 스팟이 아직 적어 {count}곳만 담았어요."
    if personalized:
        return f"취향을 반영해 붐비지 않는 {count}곳을 순서대로 묶었어요."
    return f"붐비지 않는 숨은 {count}곳을 하루 흐름으로 묶었어요."


async def build_course_response(
    region_code: str,
    profile,
    spot_repo: SpotRepository,
    congestion_repo: CongestionRepository,
    cache: Cache,
    summarizer: Summarizer | None = None,
) -> CourseResponse:
    prof = recommend_service.validate_profile(profile)  # 구조 위반 시 ProfileValidationError
    personalized = prof is not None

    spots = spot_repo.by_region(region_code)
    # 코스는 이동 legs 가 핵심 → 좌표 이상(해외/0,0/누락) 스팟은 제외(정직: leg 를 만들 수 없음).
    spots = [s for s in spots if tmap_client.valid_coord(s.lat, s.lng)]

    cmap = await recommend_service._congestion_by_name(region_code, congestion_repo)

    scored: list = []
    for spot in spots:
        cong = recommend_service._match_congestion(spot.name, cmap)
        sort_cong = cong.index if (cong and cong.index is not None) else 101.0
        if prof is not None:
            score, reasons = recommend_service._score_spot(spot, cong, prof)
            scored.append(recommend_service._Scored(spot, cong, score, reasons, sort_cong))
        else:
            scored.append(recommend_service._Scored(spot, cong, None, None, sort_cong))

    by_cat: dict[str, list] = {}
    for s in scored:
        by_cat.setdefault(s.spot.category, []).append(s)

    # 첫 슬롯의 anchor = 전체 스팟 중심(centroid) — 외딴 스팟에서 코스가 시작되는 것 방지.
    anchor: tuple[float, float] | None = None
    if scored:
        anchor = (
            sum(s.spot.lat for s in scored) / len(scored),
            sum(s.spot.lng for s in scored) / len(scored),
        )

    # 슬롯 순서대로 1곳씩 선택(중복 제거, anchor 근접 우선). 있는 카테고리로만.
    chosen: list[tuple[str, object]] = []
    used_ids: set[int] = set()
    for label, cats in _SLOTS:
        if len(chosen) >= _TARGET_MAX:
            break
        cand = [s for c in cats for s in by_cat.get(c, []) if s.spot.id not in used_ids]
        pick = _pick(cand, personalized, anchor)
        if pick is None:
            continue  # 그 슬롯 카테고리 없음 → 스킵(지어내지 않음)
        chosen.append((label, pick))
        used_ids.add(pick.spot.id)
        anchor = (pick.spot.lat, pick.spot.lng)  # 다음 슬롯은 직전 스팟에서 최근접

    course_spots: list[CourseSpot] = []
    for label, sc in chosen:
        card = recommend_service._to_card(sc)
        course_spots.append(CourseSpot(**card.model_dump(), slot_label=label))

    legs: list[CourseLeg] = []
    for i in range(len(chosen) - 1):
        legs.append(await _leg_between(chosen[i][1].spot, chosen[i + 1][1].spot, cache))

    region = RecommendRegion(region_code=region_code, region_name=_region_name(region_code))
    # 부록 I.11/I.12: arrange 와 **같은 함수**로 코스 제목·요약(LLM 1회) + 스텝 사진/발췌(캐시 재사용).
    # 둘은 서로 의존하지 않으므로 동시에 실행한다(응답시간 = 둘 중 느린 쪽).
    (_enriched, (ai_title, ai_summary)) = await asyncio.gather(
        course_enrich_service.enrich_course_spots(course_spots, cache, spot_repo),
        course_summary_service.build_course_ai_pack(
            spots=course_spots,
            legs=legs,
            region_name=region.region_name,
            summarizer=summarizer,
            cache=cache,
        ),
    )

    return CourseResponse(
        region=region,
        spots=course_spots,
        legs=legs,
        ai_summary=ai_summary,
        ai_title=ai_title,
        total_distance_m=course_enrich_service.total_walk_distance_m(legs),
        notice=_build_notice(personalized, len(course_spots)),
    )
