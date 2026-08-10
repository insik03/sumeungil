"""사용자 선택 스팟 코스 순서 최적화 (부록 I §arrange).

"AI가 짜주는 코스"(/courses/recommend)와 달리 **스팟 선택은 사용자가 이미 끝냈다.**
이 서비스가 하는 일은 단 하나 — 고른 스팟들의 **방문 순서를 이동거리 기준으로 재배열**하고
Tmap 실호출로 구간 이동시간(legs)을 붙이는 것.

소관 분리(재계산 금지):
  - match_score  → 항상 null. 이 엔드포인트는 profile 을 받지 않는다(추천이 아니라 정렬).
  - congestion   → recommend_service 의 검증된 조인 함수를 **그대로 호출**(자체 판정 로직 없음).
  - legs         → course_service._leg_between 재사용(보행자/자동차 + 좌표쌍 24h 캐시).

정직 규칙:
  - 스토어에 없는 spot_id 는 조용히 무시하되 notice 에 **개수만** 남긴다(스팟명 미삽입 = 인젝션 규약).
  - 좌표 이상(해외/0,0/누락) 스팟은 최적화 대상에서 빼고 **입력 순서대로 맨 뒤**에 붙인다.
    그 스팟이 걸린 leg 는 Tmap 을 호출하지 않고 walk/car/path 전부 null(기존 규약).
  - slot_label 은 "1번째"~"N번째". 사용자가 고른 스팟에 시간대("점심" 등)를 붙이면 추정이 된다.
"""

from __future__ import annotations

import asyncio
import logging
import math

from ..ai.summarizer import Summarizer
from ..cache.base import Cache
from ..clients import tmap_client
from ..repositories.congestion_repo import CongestionRepository
from ..repositories.spot_repo import SpotRecord, SpotRepository
from ..schemas.courses import CourseLeg, CourseResponse, CourseSpot
from ..schemas.places import RecommendRegion
from . import (
    course_enrich_service,
    course_service,
    course_summary_service,
    recommend_service,
)

logger = logging.getLogger("sumeungil.services.arrange")

MIN_SPOTS = 2
MAX_SPOTS = 8  # Tmap 콜 상한(N-1 legs × 2모드 = 최대 14콜). 초과 시 400.
_EARTH_R_M = 6_371_000.0
_TWO_OPT_MAX_PASSES = 8  # n<=8 이라 실제로는 1~2패스에서 수렴. 무한루프 방어용 상한.


class InvalidSpotsError(Exception):
    """유효 스팟 부족/개수 초과 — API 레이어가 400 INVALID_SPOTS 로 매핑."""


# ---------- 거리 ----------

def _haversine_m(a: SpotRecord, b: SpotRecord) -> float:
    """두 스팟 간 직선(대권) 거리 m. 순서 최적화의 비용함수 — 실도로거리 대신 쓰는 이유는
    후보 순열마다 Tmap 을 부르면 콜이 폭증하기 때문(정렬은 직선, 표시는 Tmap 실측)."""
    lat1, lng1, lat2, lng2 = map(math.radians, (a.lat, a.lng, b.lat, b.lng))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * _EARTH_R_M * math.asin(min(1.0, math.sqrt(h)))


def _path_length_m(order: list[SpotRecord]) -> float:
    return sum(_haversine_m(order[i], order[i + 1]) for i in range(len(order) - 1))


# ---------- 순서 최적화 ----------

def _nearest_neighbor(spots: list[SpotRecord], start: int) -> list[SpotRecord]:
    """start 에서 출발해 매번 가장 가까운 미방문 스팟으로 이동. 동률은 입력 순서 우선(결정적)."""
    remaining = list(range(len(spots)))
    remaining.remove(start)
    route = [spots[start]]
    cur = spots[start]
    while remaining:
        best = min(remaining, key=lambda i: (_haversine_m(cur, spots[i]), i))
        remaining.remove(best)
        cur = spots[best]
        route.append(cur)
    return route


def _two_opt(order: list[SpotRecord]) -> tuple[list[SpotRecord], int]:
    """열린 경로 2-opt: 구간 [i..j] 뒤집기로 총거리가 줄면 채택. 수렴까지 반복.

    n<=8 이라 후보쌍이 최대 28개뿐이라 총거리를 매번 전량 재계산해도 무시할 비용이다
    (델타 계산 최적화를 넣어 버그 리스크를 사는 것보다 낫다).
    """
    n = len(order)
    best = list(order)
    best_len = _path_length_m(best)
    improved_count = 0
    for _ in range(_TWO_OPT_MAX_PASSES):
        improved = False
        for i in range(n - 1):
            for j in range(i + 1, n):
                cand = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                cand_len = _path_length_m(cand)
                if cand_len < best_len - 1e-6:  # 부동소수 잡음은 개선으로 치지 않음
                    best, best_len = cand, cand_len
                    improved = True
                    improved_count += 1
        if not improved:
            break
    return best, improved_count


def _optimize_order(spots: list[SpotRecord]) -> tuple[list[SpotRecord], dict]:
    """좌표 있는 스팟들의 방문 순서 최적화.

    알고리즘 (n<=8 이라 전 구간 저비용):
      1. **멀티스타트 nearest-neighbor** — 모든 스팟을 한 번씩 시작점으로 NN 을 돌려
         총 직선거리가 최소인 경로를 채택(동률이면 입력 순서가 앞선 시작점). 시작점을
         "첫 스팟"이나 "최서단" 하나로 고정하지 않는 이유: 그 선택이 결과 품질을 좌우하는데
         근거가 없다. 전부 돌려보는 편이 싸고 결정적이다.
      2. **2-opt** 수렴까지 — NN 이 남기는 교차(자기 경로를 가로지르는 구간)를 제거.
      3. **방향 결정** — 열린 경로는 뒤집어도 거리가 같으므로, 두 끝점 중 **사용자 입력에서
         먼저 나온 스팟**이 1번째가 되도록 정렬(사용자 의도 존중 + 결정적).
    """
    n = len(spots)
    if n < 2:
        return list(spots), {"baseline_m": 0.0, "optimized_m": 0.0, "two_opt_gain": 0}

    baseline_m = _path_length_m(spots)  # 사용자가 보낸 입력 순서의 총 직선거리(비교 기준)

    best_route = None
    best_len = float("inf")
    for start in range(n):
        route = _nearest_neighbor(spots, start)
        length = _path_length_m(route)
        if length < best_len - 1e-6:
            best_route, best_len = route, length

    assert best_route is not None
    nn_len = best_len
    best_route, gain = _two_opt(best_route)
    opt_len = _path_length_m(best_route)

    # 방향: 입력에서 먼저 나온 끝점을 1번째로
    idx = {id(s): i for i, s in enumerate(spots)}
    if idx[id(best_route[-1])] < idx[id(best_route[0])]:
        best_route = best_route[::-1]

    return best_route, {
        "baseline_m": baseline_m,
        "nn_m": nn_len,
        "optimized_m": opt_len,
        "two_opt_gain": gain,
    }


# ---------- 응답 조립 ----------

def _reduction_pct(baseline_m: float, optimized_m: float) -> int:
    """입력 순서 대비 직선거리 감소율(%). 개선 없으면 0."""
    if baseline_m <= 0:
        return 0
    pct = (baseline_m - optimized_m) / baseline_m * 100.0
    return max(0, int(round(pct)))


def _build_notice(
    n_ordered: int, missing: int, no_coord: int, regions: int, reduction_pct: int
) -> str:
    """수치·정형문구만. 스팟명·주소 등 외부 문자열을 절대 넣지 않는다(인젝션 규약)."""
    parts = [f"고른 {n_ordered}곳을 이동거리가 짧은 순서로 배치했어요."]
    if reduction_pct > 0:
        parts.append(f"직선 이동거리를 처음 순서보다 {reduction_pct}% 줄였어요.")
    if missing > 0:
        parts.append(f"찾을 수 없는 스팟 {missing}곳은 제외했어요.")
    if no_coord > 0:
        parts.append(f"좌표 정보가 없는 {no_coord}곳은 순서 맨 뒤에 두었어요.")
    if regions > 1:
        parts.append(f"서로 다른 지역 {regions}곳이 섞여 있어 구간 이동이 길 수 있어요.")
    return " ".join(parts)


def _resolve_region(region_code: str | None, spots: list[SpotRecord]) -> RecommendRegion:
    """표시용 지역. 요청 region_code 가 유효하면 그대로, 아니면 스팟 다수결(동률=입력 순서)."""
    code = (region_code or "").strip()
    if not (code and code.isdigit()):
        counts: dict[str, int] = {}
        for s in spots:
            counts[s.region_code] = counts.get(s.region_code, 0) + 1
        code = max(counts, key=lambda k: (counts[k], -[s.region_code for s in spots].index(k)))
    return RecommendRegion(region_code=code, region_name=course_service._region_name(code))


async def build_arrange_response(
    spot_ids: list[int],
    region_code: str | None,
    spot_repo: SpotRepository,
    congestion_repo: CongestionRepository,
    cache: Cache,
    summarizer: Summarizer | None = None,
) -> CourseResponse:
    # --- 입력 검증 (Tmap 콜 폭주 방지: 조회 전에 개수부터 자른다) ---
    if len(spot_ids) > MAX_SPOTS:
        raise InvalidSpotsError(f"spot_ids 개수 초과({len(spot_ids)}>{MAX_SPOTS})")
    if len(spot_ids) < MIN_SPOTS:
        raise InvalidSpotsError(f"spot_ids 개수 부족({len(spot_ids)}<{MIN_SPOTS})")

    # 중복 제거(입력 순서 보존) — 같은 스팟을 두 번 고르면 leg 가 0m 가 되어 코스가 망가진다.
    unique_ids: list[int] = []
    for sid in spot_ids:
        if sid not in unique_ids:
            unique_ids.append(sid)

    found: list[SpotRecord] = []
    for sid in unique_ids:
        rec = spot_repo.by_id(sid)
        if rec is not None:
            found.append(rec)
    missing = len(unique_ids) - len(found)

    if len(found) < MIN_SPOTS:
        raise InvalidSpotsError(f"유효 스팟 부족({len(found)}<{MIN_SPOTS})")

    # 좌표 있는 것만 최적화 대상. 없는 것은 입력 순서 그대로 맨 뒤.
    geo = [s for s in found if tmap_client.valid_coord(s.lat, s.lng)]
    no_geo = [s for s in found if not tmap_client.valid_coord(s.lat, s.lng)]

    ordered_geo, meta = _optimize_order(geo)
    ordered = ordered_geo + no_geo
    reduction = _reduction_pct(meta["baseline_m"], meta["optimized_m"])
    logger.info(
        "arrange 순서 최적화: n=%d 입력=%.0fm → NN=%.0fm → 2opt=%.0fm (개선 %d%%, 2opt채택 %d회)",
        len(ordered_geo), meta["baseline_m"], meta.get("nn_m", 0.0),
        meta["optimized_m"], reduction, meta["two_opt_gain"],
    )

    # --- congestion 조인: recommend_service 검증 함수 재사용(자체 판정 금지) ---
    region_codes = {s.region_code for s in ordered}
    cmaps: dict[str, dict] = {}
    for rc in region_codes:
        cmaps[rc] = await recommend_service._congestion_by_name(rc, congestion_repo)

    course_spots: list[CourseSpot] = []
    for i, spot in enumerate(ordered):
        cong = recommend_service._match_congestion(spot.name, cmaps.get(spot.region_code, {}))
        # match_score/reasons=None — profile 을 받지 않는 엔드포인트라 재계산 자체가 없다.
        card = recommend_service._to_card(
            recommend_service._Scored(spot, cong, None, None, 101.0)
        )
        course_spots.append(CourseSpot(**card.model_dump(), slot_label=f"{i + 1}번째"))

    # --- legs: 좌표 둘 다 유효할 때만 Tmap 호출, 아니면 전 필드 null(기존 규약) ---
    legs: list[CourseLeg] = []
    for i in range(len(ordered) - 1):
        a, b = ordered[i], ordered[i + 1]
        if tmap_client.valid_coord(a.lat, a.lng) and tmap_client.valid_coord(b.lat, b.lng):
            legs.append(await course_service._leg_between(a, b, cache))
        else:
            legs.append(CourseLeg())

    # --- ai_title/ai_summary(LLM 1회) + 스텝 사진·발췌: 순서가 확정된 뒤에만. 실패는 null(graceful) ---
    region = _resolve_region(region_code, ordered)
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
        notice=_build_notice(
            n_ordered=len(course_spots),
            missing=missing,
            no_coord=len(no_geo),
            regions=len(region_codes),
            reduction_pct=reduction,
        ),
    )
