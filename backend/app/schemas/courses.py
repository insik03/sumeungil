"""courses(AI 추천 코스) 요청/응답 모델 = 01-interface-contract.md 부록 I 코드화.

additive: 기존 places 계약(부록 C)·스키마 불변. CourseSpot 은 SpotCard(§C.2)에 slot_label
(시간대 라벨) 1개만 더한 상위집합이라 프론트가 SpotCard 렌더 로직을 그대로 재사용한다.
CourseLeg 은 스팟쌍 이동(도보/차 소요·경로선). Tmap 실패 구간은 해당 필드 null(지어내지 않음).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .places import ProfileInput, RecommendRegion, SpotCard


class RouteMode(BaseModel):
    """한 이동수단(도보 또는 차)의 소요시간·거리."""

    minutes: int  # 초→분 반올림(최소 1)
    meters: int


class CourseLeg(BaseModel):
    """spots[i] → spots[i+1] 이동. Tmap 실패/좌표이상 시 각 필드 null(코스는 유지)."""

    walk: RouteMode | None = None
    car: RouteMode | None = None
    path: list[list[float]] | None = None  # 경로선 [[lng, lat], ...] (WGS84GEO, 보행자 우선)


class CourseSpot(SpotCard):
    """SpotCard(§C.2) + slot_label. match_score/match_reasons 는 profile 소비 시에만 값.

    slot_label 은 조립 방식에 따라 다르다:
      - /courses/recommend  → 시간대 라벨("아침 카페" 등, 서버가 하루 흐름을 설계했으므로)
      - /courses/arrange    → 순서 라벨("1번째"~"N번째"). 사용자가 고른 스팟이라 시간대를
        추정하면 지어내기가 된다 → 순서만 표기한다.

    ★ 부록 I.12 additive(코스를 "읽는 경험"으로): 스텝마다 사진 1장 + 짧은 설명 1~2문장.
      둘 다 **기존 24h detail 캐시(detailCommon2)** 를 재사용하며, 없으면 null(지어내지 않음).
    """

    slot_label: str
    # TourAPI 대표이미지(https 승격) — featured/spot detail 과 **같은 체인·같은 캐시·같은 값**.
    image_url: str | None = None
    # ★ 부록 H.3 additive(2026-07-29): 사진 출처 표기. image_url 있을 때만. 없으면 null.
    photo_credit: str | None = None
    # overview 원문의 **첫 1~2문장 발췌**(LLM 아님 — 문장 분리 규칙). overview 없으면 null.
    blurb: str | None = None


class CourseResponse(BaseModel):
    region: RecommendRegion
    spots: list[CourseSpot] = Field(default_factory=list)  # 순서 있는 코스(목표 4~5)
    legs: list[CourseLeg] = Field(default_factory=list)     # len == max(0, len(spots)-1)
    notice: str | None = None  # 수치·정형문구만(스팟명 미삽입 = 인젝션 안전)
    # ★ 부록 I.11 additive: 코스 전체를 로컬 LLM 이 2~3문장 평문으로 요약(스팟명 포함 가능).
    # LLM 실패/타임아웃/비활성 → null(코스 자체는 정상). 프론트는 **텍스트노드로만** 렌더한다.
    ai_summary: str | None = None
    # ★ 부록 I.12 additive: 코스 제목 1줄(15자 내외 평문). ai_summary 와 **한 번의 LLM 호출**로 함께
    # 생성한다(호출 수 절약). 실패/비활성 → null. 프론트는 텍스트노드로만 렌더한다.
    ai_title: str | None = None
    # ★ 부록 I.12 additive: 코스 총 도보거리(m). **모든 leg 의 walk 가 있을 때만** 합계를 낸다.
    # 하나라도 null(Tmap 실패·좌표이상)이면 null — 부분합을 총거리처럼 보여주지 않는다(정직).
    total_distance_m: int | None = None


class CourseRequest(BaseModel):
    region_code: str | None = None
    profile: ProfileInput | None = None  # 선택. 부록 C.3/C.4 재검증 그대로 재사용


class ArrangeRequest(BaseModel):
    """POST /api/v1/courses/arrange — 사용자가 고른 스팟의 방문 순서만 최적화(부록 I §arrange).

    spot_ids 는 **int 리스트로만** 받는다(pydantic 이 비정수 입력을 422 로 차단 → 문자열
    주입 경로 없음). 개수 상한 8은 서비스 레이어에서 400 INVALID_SPOTS 로 판정한다
    (에러 봉투 통일 목적). region_code 는 표시용 선택값 — 스팟이 여러 지역이어도 동작한다.
    """

    spot_ids: list[int] = Field(default_factory=list)
    region_code: str | None = None
