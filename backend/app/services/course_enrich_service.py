"""코스 스텝 보강 (부록 I.12) — `CourseSpot.image_url` / `.blurb` / `CourseResponse.total_distance_m`.

코스 응답이 "스팟 카드 나열"이 아니라 **읽는 경험**이 되도록, 확정된 코스의 각 스텝에
사진 1장과 짧은 설명 1~2문장을 붙이고, 코스 전체의 총 도보거리를 계산한다.
`/courses/arrange` 와 `/courses/recommend` 가 **같은 함수**를 쓴다.

정직 규칙 (지어내지 않음):
  - image_url : TourAPI detailCommon2 `firstimage`. **featured/spot detail 과 동일한 값·동일한 캐시**
    (`spot_detail_service.get_image_url` → `spot_overview:{id}` 24h 캐시)를 재사용한다. 없으면 null.
  - blurb     : 같은 캐시의 `overview` **원문 첫 1~2문장 발췌**다. LLM 생성이 아니라 문장 분리 +
    절단이므로 원문에 없는 사실이 들어갈 수 없다. overview 없으면 null.
  - total_distance_m : legs 의 **Tmap 실측 도보 meters 합**. leg 가 하나라도 walk=null 이면
    **전체를 null** 로 둔다 — 부분합을 총거리처럼 표시하면 사용자를 속이는 것이기 때문.

성능:
  - detailCommon2 호출이 스팟당 최대 1회 늘 수 있으나, 홈(featured)·스팟 상세에서 이미 24h 캐시가
    채워진 스팟이 대부분이라 warm 이면 원천 호출 0. cold 여도 스팟별 **asyncio.gather 병렬**이라
    코스 응답 지연은 (직렬 N회가 아니라) 1회분에 수렴한다.
  - 스팟 1곳의 조회 실패는 그 스팟만 null 로 떨어뜨리고 코스 응답은 그대로 200.
"""

from __future__ import annotations

import asyncio
import logging

from ..cache.base import Cache
from ..repositories.spot_repo import SpotRepository
from ..schemas.courses import CourseLeg, CourseSpot
from ..util import text as text_util
from . import photo_service, spot_detail_service
from .photo_service import NO_PHOTO, Photo

logger = logging.getLogger("sumeungil.services.course_enrich")

# blurb 상한: 카드 아래 2줄 정도. 문장 경계로 먼저 자르고, 그래도 길면 하드 절단한다.
BLURB_MAX_SENTENCES = 2
BLURB_MAX_CHARS = 200

# TourAPI overview 에는 <br>·<b> 같은 HTML 조각이 섞여 오는 건이 있다. blurb 는 표시용 발췌이므로
# 태그를 제거해 평문으로 만든다(원문 overview 자체는 /places/{id} 에서 그대로 유지 — 무회귀).
# 정제/문장분리 규칙은 util.text 한 곳에 있다(축제 상세 description 과 **같은 규칙** 재사용).
_SENTENCE_END_RE = text_util.SENTENCE_END_RE


def extract_blurb(overview: str | None) -> str | None:
    """overview 원문 → 첫 1~2문장 발췌(평문). 생성이 아니라 **발췌**다.

    - HTML 태그/엔티티 제거 + 공백 정규화(원문 문자열은 변형하지 않고 사본에서만).
    - 문장 2개까지 이어 붙인다. 그 결과가 200자를 넘으면 첫 문장만, 그래도 넘으면 하드 절단(…).
    - 문장 구분자가 전혀 없는 원문(한 덩어리)은 200자에서 절단한다.
    - overview 가 없거나 정제 후 빈 문자열이면 None.
    """
    if not overview or not isinstance(overview, str):
        return None

    text = text_util.strip_html_to_plain(overview)
    if not text:
        return None

    sentences = [s.strip() for s in _SENTENCE_END_RE.split(text) if s.strip()]
    if not sentences:
        return None

    blurb = " ".join(sentences[:BLURB_MAX_SENTENCES])
    if len(blurb) > BLURB_MAX_CHARS:
        blurb = sentences[0]  # 두 문장이 너무 길면 첫 문장만
    if len(blurb) > BLURB_MAX_CHARS:
        blurb = blurb[: BLURB_MAX_CHARS - 1].rstrip() + "…"  # 한 문장도 길면 하드 절단
    return blurb or None


async def _fields_for(content_id: int, cache: Cache) -> dict:
    """스팟 1곳의 detail 필드(overview+image). 어떤 오류도 코스 응답을 막지 않는다."""
    try:
        return await spot_detail_service._get_detail_fields(content_id, cache)
    except Exception as exc:  # noqa: BLE001 — 개별 스팟 실패는 그 스팟만 null
        logger.info("코스 스텝 보강 스킵(detail 실패) content_id=%s: %s", content_id, exc)
        return {"overview": None, "image_url": None}


async def _photo_for(
    spot: CourseSpot, spot_repo: SpotRepository | None, cache: Cache
) -> Photo:
    """코스 스텝 1곳의 사진(체인). 스토어 레코드가 있으면 시드 사진을 먼저 쓴다(원천 콜 0)."""
    rec = spot_repo.by_id(spot.id) if spot_repo is not None else None
    if rec is None:
        # 스토어에 없는 스팟(이론상 없음) — 이름/주소만으로 폴백 체인을 태운다.
        return await photo_service.fallback_photo(spot.id, spot.name, spot.address, cache)
    try:
        return await spot_detail_service.get_photo(rec, cache)
    except Exception as exc:  # noqa: BLE001 — 개별 스팟 실패는 그 스팟만 null
        logger.info("코스 스텝 사진 스킵 content_id=%s: %s", spot.id, exc)
        return NO_PHOTO


async def enrich_course_spots(
    spots: list[CourseSpot], cache: Cache, spot_repo: SpotRepository | None = None
) -> None:
    """코스 스팟들의 image_url/photo_credit/blurb 를 **제자리 갱신**(병렬, 실패는 개별 null).

    반환값이 없는 이유: 호출부가 이미 조립한 CourseSpot 리스트의 순서·기존 필드를 그대로 두고
    additive 필드만 채우기 위해서다(기존 조립 로직 무변경 = 무회귀).

    사진은 featured/spot detail 과 **같은 체인·같은 캐시**(시드 → firstimage → detailImage2 →
    포토갤러리 엄격매칭)를 쓴다. blurb 는 종전대로 detailCommon2 overview 원문 발췌다.
    """
    if not spots:
        return
    fields_list, photos = await asyncio.gather(
        asyncio.gather(*(_fields_for(s.id, cache) for s in spots)),
        asyncio.gather(*(_photo_for(s, spot_repo, cache) for s in spots)),
    )
    filled_img = 0
    filled_blurb = 0
    for spot, fields, photo in zip(spots, fields_list, photos):
        spot.image_url = photo.url
        spot.photo_credit = photo.credit
        spot.blurb = extract_blurb(fields.get("overview"))
        filled_img += 1 if spot.image_url else 0
        filled_blurb += 1 if spot.blurb else 0
    logger.info(
        "코스 스텝 보강: %d곳 중 사진 %d · 설명 %d (원문 발췌)",
        len(spots), filled_img, filled_blurb,
    )


def total_walk_distance_m(legs: list[CourseLeg]) -> int | None:
    """코스 총 도보거리(m). **모든 leg 에 walk 실측이 있을 때만** 합계, 아니면 None.

    leg 가 0개(스팟 1곳 이하)여도 None — "총 도보거리 0m"는 코스로서 의미가 없고 오해를 부른다.
    """
    if not legs:
        return None
    total = 0
    for leg in legs:
        if leg.walk is None:
            return None  # 부분합으로 속이지 않는다
        total += leg.walk.meters
    return total
