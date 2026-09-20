"""핫플 vs 숨은길 1:1 비교 서비스 (부록 D) — 이미 만든 조각을 조립한다.

재사용(신규 데이터/공공 API 호출 없음):
  - 프로필 재검증(C.4): recommend_service.validate_profile (그대로)
  - 혼잡도(M2 board): congestion_repo.get_board → rank1 을 핫플 baseline 으로
  - 스팟 스코어링: recommend_service._score_spot (spot_fit 코사인 + 축 결합) 재사용
  - 이름매칭: recommend_service._norm / _match_congestion 재사용

소관 분리(D.6): AI 신규 없음(spot_fit 재사용). backend 는 선정·deltas·verdict 템플릿만.

보안(D.4.1): verdict.headline 은 수치·enum·개수만 조립한다. 스팟 name·category 등
외부(공공데이터) 유래 문자열을 headline 에 **절대 삽입하지 않는다** → 간접 인젝션·XSS 표면 0.
LLM 을 호출하지 않는다.
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime

from ..regions.seed import REGIONS
from ..repositories.congestion_repo import CongestionRecord, CongestionRepository
from ..repositories.spot_repo import SpotRecord, SpotRepository
from ..schemas.compare import (
    CompareDeltas,
    CompareMeta,
    CompareRegion,
    CompareResponse,
    CompareSpot,
    CompareVerdict,
)
from ..schemas.places import SpotCongestion, SpotThemes
from ..spots.region_map import get_tourapi_region
from ..util.images import kto_credit, normalize_image_url
from ..util.time import KST, to_iso_kst
from ..ai import spot_fit
from . import photo_service, recommend_service
from .congestion_service import classify_level

logger = logging.getLogger("sumeungil.services.compare")

HEADLINE_MAX = 120

# 카테고리 enum → 한국어 라벨 (고정 매핑이라 외부 문자열 아님 → 에러 메시지 삽입 안전, D.4.1)
_CATEGORY_LABELS: dict[str, str] = {
    "attraction": "관광지",
    "restaurant": "맛집",
    "cafe": "카페",
    "craft": "공방",
    "trail": "산책로",
    "nature": "자연경관",
    "market": "시장",
    "etc": "기타",
}


class CompareUnavailable(Exception):
    """핫플 또는 숨은길을 못 골랐을 때 — API 레이어가 404 COMPARE_UNAVAILABLE 로 매핑(D.5).

    reason(사유 enum)·category(있으면)·user_message(사용자 노출 문구)를 담아
    API 레이어가 상세 사유/문구를 응답한다. user_message 미지정이면 기본 문구 사용.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str = "unavailable",
        category: str | None = None,
        user_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.category = category
        self.user_message = user_message


# ---------- comparison_id: cmp_ + ULID (외부 의존 없이 자체 생성, 저장 안 함) ----------

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _ulid() -> str:
    """26자 Crockford base32 ULID (48-bit 시간 + 80-bit 랜덤). 추적용, 영속 아님."""
    ts = int(time.time() * 1000) & ((1 << 48) - 1)
    rnd = secrets.randbits(80)
    value = (ts << 80) | rnd
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def _comparison_id() -> str:
    return f"cmp_{_ulid()}"


# ---------- 이름매칭: board 스팟명 ↔ 로컬 스토어 스팟 ----------

def _match_store(board_name: str, spots: list[SpotRecord]) -> SpotRecord | None:
    """board 관광지명을 스토어 스팟에 매칭(recommend _norm 재사용). 없으면 None(억지매칭 금지)."""
    nn = recommend_service._norm(board_name)
    for s in spots:
        if recommend_service._norm(s.name) == nn:
            return s
    for s in spots:
        sn = recommend_service._norm(s.name)
        if sn and (sn in nn or nn in sn):
            return s
    return None


# ---------- CompareSpot 조립 ----------

def _spot_from_record(
    role: str, spot: SpotRecord, congestion: SpotCongestion | None, prof
) -> CompareSpot:
    if prof is not None:
        score, reasons = recommend_service._score_spot(spot, congestion, prof)
    else:
        score, reasons = None, None
    return CompareSpot(
        role=role,  # type: ignore[arg-type]
        spot_id=spot.id,
        name=spot.name,
        category=spot.category,  # type: ignore[arg-type]
        congestion=congestion,
        themes=SpotThemes(**(spot.themes or {})),
        is_hidden_gem=spot.is_hidden_gem,
        match_score=score,
        match_reasons=reasons,
        image_url=normalize_image_url(spot.image_url),
        photo_credit=kto_credit() if spot.image_url else None,
        source="local_store",
    )


def _hotspot_from_board(rec: CongestionRecord, store_match: SpotRecord | None, prof) -> CompareSpot:
    """board rank1 을 핫플로. 스토어 이름매칭되면 category/themes/match_score enrich, 아니면 lean(null)."""
    cong = SpotCongestion(
        index=rec.congestion_rate,
        level=classify_level(rec.congestion_rate),
        tier="B",
    )
    if store_match is not None:
        if prof is not None:
            score, reasons = recommend_service._score_spot(store_match, cong, prof)
        else:
            score, reasons = None, None
        return CompareSpot(
            role="hotspot",
            spot_id=store_match.id,
            name=rec.spot_name,  # board 명(= 알려진 핫플)을 표시명으로
            category=store_match.category,  # type: ignore[arg-type]
            congestion=cong,
            themes=SpotThemes(**(store_match.themes or {})),
            is_hidden_gem=store_match.is_hidden_gem,
            match_score=score,
            match_reasons=reasons,
            image_url=normalize_image_url(store_match.image_url),
            photo_credit=kto_credit() if store_match.image_url else None,
            source="m2_board",
        )
    # lean: 스토어 미매칭 → 없는 값을 지어내지 않는다(category/match_score = null)
    return CompareSpot(
        role="hotspot",
        spot_id=None,
        name=rec.spot_name,
        category=None,
        congestion=cong,
        themes=SpotThemes(),
        is_hidden_gem=False,
        match_score=None,
        match_reasons=None,
        source="m2_board",
    )


# ---------- 부록 D.9(2026-08-01, 대표 지시) — "비슷한 곳"과 짝지어 비교한다 ----------
# 지적 두 가지:
#   (1) "항상 똑같은 거랑 비교한다" — 후보를 늘 1등만 뽑아 같은 지역이면 결과가 고정이었다.
#   (2) "적어도 비슷한 업종/관광지끼리" — 카테고리만 맞추면 attraction 안에서
#       박물관 ↔ 암자처럼 성격이 딴판인 짝이 나온다(실측).
# 그래서 **같은 카테고리 + 태그 벡터 코사인 유사도**로 후보를 걸러 상위에서 무작위로 고른다.
# 유사한 곳이 없으면 억지로 짝짓지 않고 "비슷한 곳 없음"으로 알린다(대표 지시).
SIMILARITY_MIN = 0.30   # 이 아래면 "비슷하다"고 말하지 않는다
SIMILARITY_POOL = 5     # 상위 몇 곳 안에서 매번 다르게 고를지


def _similar_candidates(base: SpotRecord, spots: list[SpotRecord]) -> list[tuple[float, SpotRecord]]:
    """base 와 **같은 카테고리**이면서 태그 유사도가 임계 이상인 후보를 유사도순으로."""
    out: list[tuple[float, SpotRecord]] = []
    for s in spots:
        if s.id == base.id or s.category != base.category:
            continue
        sim = spot_fit.cosine_spot_fit(base.tag_vector, s.tag_vector)
        if sim >= SIMILARITY_MIN:
            out.append((sim, s))
    out.sort(key=lambda t: (-t[0], t[1].name))
    return out


# ---------- 스팟 정렬(hidden auto 선정) — recommend 파이프라인 순서 재사용 ----------

@dataclass
class _Ranked:
    spot: SpotRecord
    congestion: SpotCongestion | None
    score: float | None
    sort_cong: float


def _rank_spots(spots: list[SpotRecord], cmap, prof) -> list[_Ranked]:
    ranked: list[_Ranked] = []
    for spot in spots:
        cong = recommend_service._match_congestion(spot.name, cmap)
        sort_cong = cong.index if (cong and cong.index is not None) else 101.0
        score = None
        if prof is not None:
            score, _ = recommend_service._score_spot(spot, cong, prof)
        ranked.append(_Ranked(spot, cong, score, sort_cong))
    if prof is not None:
        ranked.sort(key=lambda x: (-(x.score or 0.0), x.sort_cong, x.spot.name))
    else:
        ranked.sort(key=lambda x: (x.sort_cong, not x.spot.is_hidden_gem, x.spot.name))
    return ranked


# ---------- deltas ----------

def _build_deltas(hotspot: CompareSpot, hidden: CompareSpot) -> CompareDeltas:
    h_idx = hotspot.congestion.index if hotspot.congestion else None
    d_idx = hidden.congestion.index if hidden.congestion else None

    congestion_diff = None
    congestion_diff_pct = None
    if h_idx is not None and d_idx is not None:
        congestion_diff = round(d_idx - h_idx, 1)
        if h_idx > 0:
            congestion_diff_pct = round((d_idx - h_idx) / h_idx * 100)
        # h_idx == 0 이면 상대 % 정의 불가 → null (지어내지 않음)

    fit_diff = None
    if hotspot.match_score is not None and hidden.match_score is not None:
        fit_diff = round(hidden.match_score - hotspot.match_score, 4)

    matched_count = 0
    if hidden.match_reasons is not None:
        matched_count = len(hidden.match_reasons.matched_tags)

    return CompareDeltas(
        congestion_diff=congestion_diff,
        congestion_diff_pct=congestion_diff_pct,
        fit_diff=fit_diff,
        matched_count=matched_count,
    )


# ---------- verdict.headline (D.4.1 템플릿 조립 — 수치·enum·개수만) ----------

def build_verdict(
    deltas: CompareDeltas, personalized: bool, hidden_level: str | None = None, picked: bool = False
) -> CompareVerdict:
    pct = deltas.congestion_diff_pct
    matched = deltas.matched_count
    # 2026-09-20 대표 지적 — 사용자가 고른 스팟(hotspot_source=local_store)에서 시작한 비교면
    # 왼쪽은 "유명 핫플"이 아니라 "내가 고른 곳"이다. 문구도 그에 맞춘다(수치·개수만 조립, D.4.1 유지).
    left = "고른 곳" if picked else "붐비는 유명 스팟"
    generic = (
        "고른 곳과 비슷한 성격의 더 한적한 곳을 찾았어요." if picked
        else "유명 핫플 대신 붐비지 않는 숨은 곳을 찾았어요."
    )

    # 혼잡도 델타가 '음수(숨은길 여유)'일 때만 "낮다"고 말한다(양수/ null → 폴백, 과장 금지)
    congestion_lower = pct is not None and pct < 0
    has_fit = personalized and matched > 0

    # 부록 D.7(2026-08-01) — **상대 차이만 보고 "한적한 곳"이라 부르지 않는다.**
    # 실측(부산 해운대): 핫플 미포항 98.7 → 대안 장산 86.7. 12% 낮은 건 맞지만 86.7 은 여전히
    # high 다. 그걸 "한적한 곳"이라 부르면 가서 실망한다 — 오늘 고친 "미상을 낮음이라 부르기"와
    # 같은 유형의 과장이다. 대안 자체가 high 면 덜 붐빈다는 사실만 말하고 한적하다고는 안 한다.
    # (대안 선정은 이미 같은 카테고리 중 **가장 덜 붐비는 곳**이라, 이 경우는 "더 나은 선택지가
    #  이 지역에 없다"는 뜻이다. 없는 걸 있다고 하지 않는다.)
    if congestion_lower and hidden_level == "high":
        headline = f"그나마 혼잡도가 {abs(pct)}% 낮지만, 이곳도 지금은 붐비는 편이에요."
        if has_fit:
            headline += f" 맞춤 조건 {matched}개를 만족합니다."
        if len(headline) <= HEADLINE_MAX:
            return CompareVerdict(headline=headline, template_id="congestion_lower_but_crowded")

    if congestion_lower and has_fit:
        template_id = "congestion_and_fit"
        headline = (
            f"{left} 대신 혼잡도 {abs(pct)}% 낮은 한적한 곳이에요. "
            f"맞춤 조건 {matched}개를 만족합니다."
        )
    elif congestion_lower and not has_fit:
        template_id = "congestion_only"
        headline = f"{left}보다 혼잡도가 {abs(pct)}% 낮은 한적한 곳이에요."
    elif not congestion_lower and has_fit:
        template_id = "fit_only"
        headline = f"한적한 숨은 곳으로, 맞춤 조건 {matched}개를 만족합니다."
    else:
        template_id = "hidden_gem_generic"
        headline = generic

    # 길이 상한 초과 시 generic 폴백
    if len(headline) > HEADLINE_MAX:
        template_id = "hidden_gem_generic"
        headline = generic

    return CompareVerdict(headline=headline, template_id=template_id)


# ---------- 지역명 ----------

def _region_name(region_code: str) -> str | None:
    tr = get_tourapi_region(region_code)
    if tr:
        return tr.region_name
    return next((r.label for r in REGIONS if r.region_id == region_code), None)


# ---------- 메인 조립 ----------

async def build_compare_response(
    region_code: str,
    profile,
    hidden_id: int | None,
    hotspot_id: int | None,
    category: str | None,
    spot_repo: SpotRepository,
    congestion_repo: CongestionRepository,
    cache=None,
) -> CompareResponse:
    prof = recommend_service.validate_profile(profile)  # 구조 위반 시 ProfileValidationError
    personalized = prof is not None

    all_spots = spot_repo.by_region(region_code, None)
    store_by_id = {s.id: s for s in all_spots}

    # --- M2 board 1회 조회 (핫플 rank1 + 혼잡도 이름매칭 맵) ---
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
        except Exception as exc:  # noqa: BLE001 — 혼잡도 실패는 비교를 막지 않는다(핫플만 영향)
            logger.info("compare 혼잡도 조회 스킵(원천 실패) region=%s: %s", region_code, exc)

    # --- 부록 D.7(2026-08-01) — **핫플에서 시작하는 방향**을 지원한다 ---
    # 종전엔 항상 숨은길을 먼저 확정하고 그 카테고리에 맞는 핫플을 찾았다. 그런데 혼잡도 board 는
    # 사실상 attraction/nature 만 준다. 반면 숨은길 auto 후보는 is_hidden_gem 정의상 카페가 압도적
    # (실측: 현재 노출 중인 숨은 스팟 20곳 중 카페 16 · 산책로 2 · 공방 1 · 시장 1)이라,
    # "같은 카테고리 핫플"이 **구조적으로 존재할 수 없었다** → 실측 성공률 0/20(전부
    # no_hotspot_in_category). 지정과제2("쏠림 완화")에 가장 직결되는 기능이 사실상 죽어 있었다.
    #
    # 방향을 뒤집으면 이 문제가 사라진다: **핫플을 먼저 확정**(board 에서 오므로 혼잡도가 반드시
    # 있다)하고, 그 **같은 카테고리** 안에서 한적한 대안을 고른다. 카테고리 매칭이라는 정직성
    # 기준(억지 비교 금지)은 그대로 유지하면서 성립 가능성만 확보한다.
    #
    # 우선순위: hidden_id 명시(스팟 상세의 "이 곳과 비교") > hotspot_id 명시 > 둘 다 없으면 핫플 우선.
    hidden_spot: SpotRecord | None = None
    hotspot: CompareSpot | None = None
    hotspot_source = "m2_board"
    similarity: float | None = None  # 부록 D.9 — 두 곳이 얼마나 비슷한지(0~1). 없으면 null

    if hidden_id is not None:
        hidden_spot = store_by_id.get(hidden_id)  # 없으면 아래 auto 로 떨어진다

    if hidden_spot is None:
        # 핫플 우선 경로 — 지정된 hotspot_id, 없으면 board 최상위(=지금 이 지역에서 가장 붐비는 곳).
        if hotspot_id is not None:
            hs = store_by_id.get(hotspot_id)
            if hs is not None:
                hs_cong = recommend_service._match_congestion(hs.name, cmap)
                hotspot = _spot_from_record("hotspot", hs, hs_cong, prof)
                hotspot_source = "local_store"
        if hotspot is None:
            for rec in board_sorted:
                store_match = _match_store(rec.spot_name, all_spots)
                if store_match is None:
                    continue  # 카테고리 불명 → 대안을 같은 카테고리로 고를 수 없다
                hotspot = _hotspot_from_board(rec, store_match, prof)
                break

        if hotspot is not None and hotspot.spot_id is not None:
            # 부록 D.9 — 핫플과 **비슷한 성격**(같은 카테고리 + 태그 유사도)인 곳 중에서 고른다.
            base = store_by_id.get(hotspot.spot_id)
            region_spots = spot_repo.by_region(region_code, None)
            if base is not None:
                sims = _similar_candidates(base, region_spots)
                # 유사도 상위 풀 안에서 **한적한 순**으로 정렬한 뒤 무작위로 하나 —
                # 같은 지역을 다시 봐도 매번 같은 짝이 나오지 않게(대표 지적).
                pool = [sp for _sim, sp in sims[: SIMILARITY_POOL * 3]]
                ranked = _rank_spots(pool, cmap, prof)[:SIMILARITY_POOL]
                if ranked:
                    hidden_spot = secrets.choice(ranked).spot
                    similarity = next(
                        (sim for sim, sp in sims if sp.id == hidden_spot.id), None
                    )

    if hidden_spot is None:
        # 폴백: 종전 경로(숨은길 먼저) — 핫플을 못 잡았거나 같은 카테고리 대안이 없을 때.
        ranked = _rank_spots(spot_repo.by_region(region_code, category), cmap, prof)
        if ranked:
            hidden_spot = ranked[0].spot
    if hidden_spot is None:
        raise CompareUnavailable("지역 스팟 0 — 숨은길을 고를 수 없음", reason="no_spots")

    hidden_cong = recommend_service._match_congestion(hidden_spot.name, cmap)
    hidden = _spot_from_record("hidden", hidden_spot, hidden_cong, prof)

    # --- HOTSPOT(핫플) 확정 — 위에서 못 잡았거나 자기비교가 된 경우 ---
    if hotspot is not None and hotspot.spot_id == hidden_spot.id:
        hotspot = None  # 자기비교 방지
    if hotspot is None and hotspot_id is not None:
        hs = store_by_id.get(hotspot_id)
        if hs is not None and hs.id != hidden_spot.id:
            hs_cong = recommend_service._match_congestion(hs.name, cmap)
            hotspot = _spot_from_record("hotspot", hs, hs_cong, prof)
            hotspot_source = "local_store"

    if hotspot is None:
        # auto: 숨은길과 **같은 카테고리** 중 board 혼잡도 최상위를 핫플로(카테고리 매칭 비교).
        # board_sorted 는 congestion_rate 내림차순 → 같은 카테고리로 첫 매칭이 곧 최고 혼잡 핫플.
        # 카테고리를 확인하려면 스토어 이름매칭이 필수 → 미매칭(카테고리 불명) 스팟은 후보에서 제외.
        # hidden 자기 자신도 제외(자기비교 방지).
        hidden_category = hidden_spot.category
        for rec in board_sorted:
            store_match = _match_store(rec.spot_name, all_spots)
            if store_match is None:
                continue  # 카테고리 불명 → 같은 카테고리인지 확인 불가 → 제외
            if store_match.id == hidden_spot.id:
                continue  # 자기비교 방지
            if store_match.category != hidden_category:
                continue  # 다른 카테고리 → 비교 무의미
            hotspot = _hotspot_from_board(rec, store_match, prof)
            similarity = spot_fit.cosine_spot_fit(hidden_spot.tag_vector, store_match.tag_vector)
            break

        # 부록 D.9 — board 에 같은 카테고리가 없어도 **그 지역에서 가장 붐비는 비슷한 곳**을
        # 핫플로 삼는다. 종전엔 여기서 곧바로 "비교 불가"였다(실측: 스팟 상세 경로 17/18 실패).
        # 카페·시장·산책로는 혼잡도 board 자체가 없어 구조적으로 짝을 못 찾던 것이라,
        # 같은 카테고리 안에서 **혼잡도가 가장 높은 곳**을 핫플로 쓰면 비교가 성립한다.
        if hotspot is None:
            sims = _similar_candidates(hidden_spot, all_spots)
            best = None
            best_sim = None
            # 초기값은 후보의 어떤 값보다 작아야 한다. 혼잡도가 없는 스팟(카페·시장 등)은
            # idx 가 -1.0 이라 초기값을 -1.0 으로 두면 **아무도 선택되지 않는다**(실측: 12건 전부 실패).
            best_idx = float("-inf")
            for sim, sp in sims:
                c = recommend_service._match_congestion(sp.name, cmap)
                idx = c.index if (c and c.index is not None) else -1.0
                if idx > best_idx:
                    best, best_idx, best_sim = sp, idx, sim
            if best is not None:
                cong = recommend_service._match_congestion(best.name, cmap)
                hotspot = _spot_from_record("hotspot", best, cong, prof)
                similarity = best_sim

    if hotspot is None:
        # 같은 카테고리 핫플 후보가 없다 — board 는 attraction/nature 만 혼잡도 데이터가 있으므로
        # 숨은길이 cafe/trail/restaurant 등이면 이 분기로 온다. 억지로 다른 카테고리와 비교하지 않는다.
        label = _CATEGORY_LABELS.get(hidden_spot.category, "이 카테고리")
        raise CompareUnavailable(
            f"같은 카테고리(category={hidden_spot.category}) 핫플 후보 없음",
            reason="no_hotspot_in_category",
            category=hidden_spot.category,
            user_message=(
                f"이 카테고리({label})는 예상 혼잡도 비교 데이터가 없어 비교할 핫플이 없어요."
            ),
        )

    # --- 부록 D.8: 사진이 비어 있으면 기존 폴백 체인으로 한 번 더 시도한다 ---
    # 대표 요청 "없는 사진은 리서치해서라도". 다만 **웹 임의 수집은 하지 않는다** — 권리가
    # 확인되지 않은 이미지는 공모전 저작권 조항·상용화 양쪽에서 위험하다. 대신 이미 갖고 있는
    # 정식 경로(detailImage2 → 한국관광공사 포토갤러리 엄격매칭, photo_service)를 쓴다.
    # 대상이 최대 2곳이라 원천 호출 상한이 명확하고, 결과는 24h 캐시된다.
    # 그래도 못 찾으면 null 이다(다른 장소 사진으로 채우지 않는다).
    if cache is not None:
        for card in (hotspot, hidden):
            if card.image_url or card.spot_id is None:
                continue
            rec = store_by_id.get(card.spot_id)
            try:
                photo = await photo_service.fallback_photo(
                    card.spot_id, card.name, getattr(rec, "address", None), cache
                )
            except Exception as exc:  # noqa: BLE001 — 사진 때문에 비교가 막히지 않는다
                logger.info("compare 사진 폴백 스킵(spot_id=%s): %s", card.spot_id, exc)
                continue
            if photo.url:
                card.image_url = photo.url
                card.photo_credit = photo.credit

    deltas = _build_deltas(hotspot, hidden)
    verdict = build_verdict(
        deltas,
        personalized,
        hidden_level=hidden.congestion.level if hidden.congestion else None,
        picked=hotspot_source == "local_store",
    )

    now: datetime = datetime.now(KST)
    fetched = to_iso_kst(now)
    return CompareResponse(
        comparison_id=_comparison_id(),
        generated_at=fetched,
        region=CompareRegion(region_code=region_code, region_name=_region_name(region_code)),
        hotspot=hotspot,
        hidden=hidden,
        deltas=deltas,
        verdict=verdict,
        meta=CompareMeta(
            source="compare_v1",
            fetched_at=fetched,
            personalized=personalized,
            hotspot_source=hotspot_source,  # type: ignore[arg-type]
            distance_axis=False,
            review_axis=False,
            similarity=round(similarity, 3) if similarity is not None else None,
            # 부록 D.9 — 비슷한 곳을 못 찾았으면 **숨기지 말고 그렇게 말한다**(대표 지시).
            notice=(
                None
                if similarity is not None and similarity >= SIMILARITY_MIN
                else "이 지역엔 성격이 비슷한 곳이 마땅치 않아, 가까운 조건으로 골랐어요."
            ),
        ),
    )
