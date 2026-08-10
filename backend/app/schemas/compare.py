"""compare(핫플 vs 숨은길 1:1 대조) 요청/응답 모델 = 01-interface-contract.md 부록 D 코드화.

계약(부록 D.2/D.4)이 정본이다. CompareSpot 은 SpotCard(부록 C.2)의 부분집합 + role/source.
hotspot·hidden 은 **동일 키 구조**(designer 대칭 렌더 전제, 08 #3). 신규 필드는 role·source 뿐.
verdict.headline 은 backend 템플릿 조립값(수치·enum·개수만) — 외부 문자열 미삽입(D.4.1).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .places import ProfileInput, SpotCongestion, SpotThemes, MatchReasons, SpotCategory

CompareRole = Literal["hotspot", "hidden"]
CompareSource = Literal["m2_board", "local_store"]


# ---------- 응답: CompareSpot (D.2, hotspot/hidden 대칭) ----------

class CompareSpot(BaseModel):
    role: CompareRole
    spot_id: int | None = None                 # 로컬 스토어 PK. 핫플 lean 케이스는 null
    name: str
    category: SpotCategory | None = None        # 핫플 미매칭 시 null (지어내지 않음)
    congestion: SpotCongestion | None = None
    themes: SpotThemes
    is_hidden_gem: bool = False
    match_score: float | None = None            # 프로필 소비 + 스토어 매칭 시에만
    match_reasons: MatchReasons | None = None
    # ★ 부록 D.8 additive(2026-08-01, 대표 지시 "비교할 거면 사진도 나와야") —
    # 비교 카드에 실제 관광 사진을 띄우기 위한 필드. 시드(TourAPI firstimage)를 먼저 쓰고,
    # 없으면 부록 H.3 폴백 체인(detailImage2 → 포토갤러리 엄격매칭)까지만 시도한다.
    # **웹에서 임의로 긁어오지 않는다** — 권리가 확인된 원천만 쓴다. 못 찾으면 null.
    image_url: str | None = None
    photo_credit: str | None = None
    source: CompareSource


# ---------- 응답: deltas / verdict / region / meta ----------

class CompareDeltas(BaseModel):
    congestion_diff: float | None = None        # hidden.index - hotspot.index (음수=숨은길 여유)
    congestion_diff_pct: int | None = None      # 상대 % 반올림 (음수=낮음). 한쪽 null이면 null
    fit_diff: float | None = None               # hidden.match_score - hotspot.match_score
    matched_count: int = 0                       # hidden matched_tags 개수 (프로필 없으면 0)


class CompareVerdict(BaseModel):
    headline: str                                # backend 템플릿 조립 (D.4.1). LLM 미사용.
    template_id: str                             # 어느 템플릿을 썼는지 (QA/디버그)


class CompareRegion(BaseModel):
    region_code: str
    region_name: str | None = None


class CompareMeta(BaseModel):
    # ★ 부록 D.9 additive(2026-08-01) — 두 곳이 얼마나 비슷한 성격인지(0~1, 태그 코사인).
    # null 이면 "비슷함을 확인하지 못했다"는 뜻이다(0 이 아니다 — 모름과 다름을 섞지 않는다).
    similarity: float | None = None
    source: str = "compare_v1"
    fetched_at: str
    personalized: bool = False
    hotspot_source: CompareSource = "m2_board"
    distance_axis: bool = False                  # MVP-5 고정 false (거리 축 없음)
    review_axis: bool = False                    # MVP-5 고정 false (리뷰 축 없음)
    notice: str | None = None


class CompareResponse(BaseModel):
    comparison_id: str                           # cmp_ + ULID. 저장·재조회 없음(추적용)
    generated_at: str
    region: CompareRegion
    hotspot: CompareSpot
    hidden: CompareSpot
    deltas: CompareDeltas
    verdict: CompareVerdict
    meta: CompareMeta


# ---------- 요청 (D.4) ----------

class CompareRequest(BaseModel):
    region_code: str | None = None
    profile: ProfileInput | None = None          # 부록 C.4 재검증 그대로 재사용
    hidden_id: int | None = None                 # 지정 시 숨은길 고정. 없으면 auto(D.1.2)
    hotspot_id: int | None = None                # 지정 시 핫플 고정. 없으면 board rank1(D.1.1)
    category: SpotCategory | None = None         # hidden auto 선정 시 필터
