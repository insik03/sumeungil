"""공유·저장 코스 payload 재구성(allowlist) — 2026-08-18 외부 보안감사 3차 최우선 지적 대응.

## 무엇이 문제였나
`POST /courses/share` 는 요청의 `course` JSON 을 **해석하지 않고 그대로 보관·반환**했다
(크기·중첩 깊이만 검사). `/shared/{code}` 는 공개 URL 이고 `/shared` 피드는 누구나 본다.
따라서 클라이언트는 API 한 번으로 다음을 **우리 서비스 화면 안에** 올릴 수 있었다:

  - 존재하지 않는 장소명·주소·좌표 (`spots[].name` / `.address` / `.location`)
  - "여유" 같은 혼잡도 배지 (`spots[].congestion.level` — 실시간 원천을 사칭)
  - 임의 외부 이미지 URL (`spots[].image_url` — 우리 도메인 화면에서 남의 서버 이미지 로드)
  - "이래서 추천했어요" 칩 문구 (`match_reasons.matched_tags` — 프론트가 라벨 없으면 원문 표시)
  - 임의 설명문 (`blurb`) — "공식 인증" 류 문구를 붙일 수 있었다

전부 XSS 가 아니라 **콘텐츠 위조**다. 프론트가 텍스트 노드로 렌더해도 막히지 않는다.

## 대응 원칙 — "식별자만 신뢰한다"
서버가 신뢰하는 클라이언트 입력은 **스팟 id(정수)와 그 순서**뿐이다. 이름·주소·좌표·카테고리·
테마·숨은스팟 여부는 전부 `spot_repo` 에서 서버 값으로 다시 채운다. 나머지는:

| 필드 | 처리 |
|---|---|
| `spots[].congestion` | **저장하지 않는다.** 시점 데이터이므로 상세 조회 때 서버가 다시 붙인다 |
| `spots[].image_url` / `photo_credit` / `blurb` | 저장 시 서버 보강(`course_enrich_service`) 결과로 덮어쓴다 |
| `spots[].match_reasons` | registry 에 있는 태그값 / 정해진 signal 값만 통과 |
| `spots[].slot_label` | 사용자 표시 문자열 → `clean_user_text` + 24자 |
| `legs` | 숫자·좌표 구조 검증 + 상한 clamp (텍스트가 없어 위조 가치가 낮다) |
| `notice` | **버린다.** 서버가 만든 사실 문장이라 클라이언트가 되돌려 줄 이유가 없다 |
| 그 밖의 모든 키 | **버린다**(allowlist). "공식 인증" 같은 배지 필드를 새로 만들 수 없다 |

## 과거 데이터
이미 저장된 payload 는 손대지 않는다(마이그레이션 없음). 대신 **읽을 때도 같은 필터**를
통과시킨다(`filter_stored_course`). 새 코드가 쓴 payload 에는 `"v": 2` 표식이 있고, 표식이
없는 과거 payload 는 사진·설명(`image_url`/`photo_credit`/`blurb`)을 **검증할 수 없으므로
버린다** — 스팟 카드는 플레이스홀더로 뜬다. 이름·좌표는 어차피 spot_repo 값으로 덮어써진다.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from ..ai import tag_registry
from ..clients import tmap_client
from ..repositories.spot_repo import SpotRepository
from ..util.images import CREDIT_GALLERY, CREDIT_KTO
from ..util.user_text import clean_user_text

logger = logging.getLogger("sumeungil.services.course_payload")

# 이 모듈이 다루는 입력은 **pydantic 을 통과하지 않은 임의 JSON** 이다(`course: dict[str, Any]`).
# 따라서 어떤 필드에도 int/dict/list/None 이 올 수 있다고 가정한다. 문자열 정제는
# `clean_user_text` 가 진입부에서 비문자열을 빈 값으로 수렴시켜 준다(2026-08-18 QA Critical-1)
# — 여기서 다시 isinstance 를 흩뿌리지 않는 이유는 방어를 한 곳에 모으기 위해서다.

# 새 포맷 표식. 이 값이 없으면 "과거(무검증) payload" 로 취급한다.
PAYLOAD_VERSION = 2

# 코스 하나에 담을 수 있는 스팟 수. recommend 는 4~5곳, arrange 는 최대 8곳을 만든다 —
# 12 는 두 경로 모두에 여유가 있으면서 저장소 폭주를 막는 값이다.
MAX_SPOTS = 12
SLOT_LABEL_MAX = 24
AI_TITLE_MAX = 40
AI_SUMMARY_MAX = 400
BLURB_MAX = 200
CREDIT_MAX = 80
MAX_MATCHED_TAGS = 12
MAX_SIGNALS = 6
# 경로선 좌표 상한. Tmap 보행자 경로가 이보다 길게 오는 경우는 실측상 없다(구간당 수십~수백 점).
MAX_PATH_POINTS = 1000
# leg 이동시간/거리 상한 — 한 구간이 하루를 넘거나 500km 를 넘을 수 없다.
MAX_LEG_MINUTES = 1440
MAX_LEG_METERS = 500_000

# 이미지 호스트 allowlist. 원천(TourAPI/포토갤러리) 이미지는 전부 이 CDN 하나다
# (`util/images.py` 상단 실호출 근거). 다른 호스트는 우리 화면에서 로드하지 않는다.
_ALLOWED_IMAGE_PREFIX = "https://tong.visitkorea.or.kr/"
# 출처 표기는 util/images.py 가 만드는 **고정 문구**로 시작해야 한다.
_ALLOWED_CREDIT_PREFIXES = (CREDIT_KTO, CREDIT_GALLERY)

# registry 에 실재하는 태그 값 전체(축 무관). match_reasons.matched_tags 는 이 집합 안에서만 통과.
_VALID_TAG_VALUES: frozenset[str] = frozenset(row.value for row in tag_registry.REGISTRY)
# recommend_service._score_spot 이 만드는 signal 값 전부(+ 계약 C.2.2 의 near).
_VALID_SIGNALS: frozenset[str] = frozenset(
    {"low_congestion", "hidden_gem", "high_profile_fit", "theme_match", "near"}
)

_CATEGORIES: frozenset[str] = frozenset(
    {"attraction", "restaurant", "cafe", "craft", "trail", "nature", "market", "etc"}
)


class InvalidCoursePayload(Exception):
    """코스 payload 를 서버 값으로 재구성할 수 없음 → 호출부가 400 INVALID_COURSE 로 매핑."""


# --- 작은 파서들 ----------------------------------------------------------------


def _as_int(value: Any) -> int | None:
    """정수만 받는다. bool 은 int 서브클래스라 먼저 걸러낸다(True → 1 로 새지 않게)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return None


def _as_finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _clamped_int(value: Any, *, lo: int, hi: int) -> int | None:
    n = _as_int(value)
    if n is None:
        return None
    return max(lo, min(hi, n))


def spot_id_of(raw: Any) -> int | None:
    """스팟 항목에서 **식별자만** 뽑는다. 프론트 계약(부록 C.2 SpotCard)의 정본 키는 `id` 지만,
    저장된 과거 payload·다른 호출부가 `spot_id`/`content_id` 를 쓸 수 있어 함께 받는다."""
    if not isinstance(raw, dict):
        return None
    for key in ("id", "spot_id", "content_id", "contentid"):
        sid = _as_int(raw.get(key))
        if sid is not None and sid > 0:
            return sid
    return None


def _clean_image_url(raw: Any) -> str | None:
    """허용 CDN 의 https URL 만 통과. 그 밖은 None(=사진 없음, 플레이스홀더)."""
    if not isinstance(raw, str):
        return None
    url = raw.strip()
    if not url.startswith(_ALLOWED_IMAGE_PREFIX) or len(url) > 500:
        return None
    # 공백·개행이 섞인 URL 은 받지 않는다(속성 이스케이프에 기대지 않는다).
    if any(ch.isspace() for ch in url):
        return None
    return url


def _clean_credit(raw: Any) -> str | None:
    """출처 표기 — util/images.py 가 만드는 고정 문구로 시작할 때만 통과."""
    if not isinstance(raw, str):
        return None
    text = clean_user_text(raw, max_chars=CREDIT_MAX)
    if not text or not text.startswith(_ALLOWED_CREDIT_PREFIXES):
        return None
    return text


def _clean_match_reasons(raw: Any) -> dict[str, list[str]] | None:
    """registry/enum 에 실재하는 값만 남긴다. 남는 게 없으면 None(칩 자체를 그리지 않게)."""
    if not isinstance(raw, dict):
        return None
    tags_raw = raw.get("matched_tags")
    signals_raw = raw.get("signals")
    tags = [
        t for t in (tags_raw if isinstance(tags_raw, list) else [])
        if isinstance(t, str) and t in _VALID_TAG_VALUES
    ][:MAX_MATCHED_TAGS]
    signals = [
        s for s in (signals_raw if isinstance(signals_raw, list) else [])
        if isinstance(s, str) and s in _VALID_SIGNALS
    ][:MAX_SIGNALS]
    if not tags and not signals:
        return None
    # 순서 보존 중복 제거(같은 칩이 여러 번 뜨지 않게).
    return {
        "matched_tags": list(dict.fromkeys(tags)),
        "signals": list(dict.fromkeys(signals)),
    }


def _clean_leg_mode(raw: Any) -> dict[str, int] | None:
    if not isinstance(raw, dict):
        return None
    minutes = _clamped_int(raw.get("minutes"), lo=0, hi=MAX_LEG_MINUTES)
    meters = _clamped_int(raw.get("meters"), lo=0, hi=MAX_LEG_METERS)
    if minutes is None or meters is None:
        return None
    return {"minutes": minutes, "meters": meters}


def _clean_path(raw: Any) -> list[list[float]] | None:
    """경로선 [[lng, lat], ...] — 한국 bbox 안의 좌표쌍만. 하나라도 이상하면 전체 None.

    부분적으로 살리지 않는 이유: 중간이 잘린 경로선은 지도에 **실제와 다른 선**을 그린다.
    """
    if not isinstance(raw, list) or not raw:
        return None
    if len(raw) > MAX_PATH_POINTS:
        return None
    out: list[list[float]] = []
    for point in raw:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            return None
        lng = _as_finite_float(point[0])
        lat = _as_finite_float(point[1])
        if lng is None or lat is None or not tmap_client.valid_coord(lat, lng):
            return None
        out.append([lng, lat])
    return out


_NULL_LEG: dict[str, Any] = {"walk": None, "car": None, "path": None}


def _clean_legs(raw: Any, *, kept: list[int]) -> list[dict[str, Any]]:
    """leg 목록. 길이는 항상 `len(kept) - 1` — 프론트가 `legs[i]` 로 인덱싱한다.

    `kept` 는 **살아남은 스팟의 원본 인덱스**다. 읽기 경로에서 스토어에 없는 스팟이 빠지면
    스팟과 leg 의 대응이 어긋나는데, 그때 leg 를 앞에서부터 그냥 당겨 쓰면 **1→3 구간에
    1→2 구간의 이동시간이 표시된다**(2026-08-18 QA Minor-2 — 없는 사실을 만들어낸다).

    그래서 원본에서 **바로 옆이었던 두 스팟** 사이에서만 저장된 leg 를 쓰고, 사이에 무언가
    빠졌으면 전 필드 null(= "이동 정보 없음")로 둔다. 프론트는 이 상태를 이미 처리한다
    (`SharedCourseDetailContent.tsx` 의 `CourseLegInfo` → "이동 정보 없음").
    """
    items = raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    for j in range(max(0, len(kept) - 1)):
        a, b = kept[j], kept[j + 1]
        if b != a + 1:
            out.append(dict(_NULL_LEG))  # 사이에 빠진 스팟이 있다 — 지어내지 않는다
            continue
        item = items[a] if a < len(items) and isinstance(items[a], dict) else {}
        out.append(
            {
                "walk": _clean_leg_mode(item.get("walk")),
                "car": _clean_leg_mode(item.get("car")),
                "path": _clean_path(item.get("path")),
            }
        )
    return out


def _total_distance(legs: list[dict[str, Any]]) -> int | None:
    """총 도보거리 — legs 에서 **다시 계산**한다(클라이언트 값을 믿지 않는다).

    `course_enrich_service.total_walk_distance_m` 과 같은 규칙: leg 가 하나라도 walk=null 이면
    None(부분합을 총거리처럼 보여주지 않는다).
    """
    if not legs:
        return None
    total = 0
    for leg in legs:
        walk = leg.get("walk")
        if not isinstance(walk, dict):
            return None
        total += int(walk["meters"])
    return total


# --- 스팟 재구성 ----------------------------------------------------------------


def _rebuild_spot(raw: dict[str, Any], record: Any, *, index: int, trusted_media: bool) -> dict[str, Any]:
    """스팟 1건 = **spot_repo 레코드(서버 진실) + 통과한 표시용 필드 몇 개**.

    `trusted_media` 가 False 면 사진·설명은 검증할 근거가 없으므로 통째로 버린다(과거 payload).
    """
    slot_label = clean_user_text(raw.get("slot_label"), max_chars=SLOT_LABEL_MAX)
    match_score = _as_finite_float(raw.get("match_score"))
    if match_score is not None:
        match_score = max(0.0, min(1.0, match_score))

    category = record.category if record.category in _CATEGORIES else "etc"
    blurb = clean_user_text(raw.get("blurb"), max_chars=BLURB_MAX) if trusted_media else ""
    image_url = _clean_image_url(raw.get("image_url")) if trusted_media else None

    return {
        # --- 서버 값(클라이언트 입력 무시) ---
        "id": record.id,
        "name": record.name,
        "category": category,
        "region_code": record.region_code,
        "address": record.address,
        "location": {"lat": record.lat, "lng": record.lng},
        "themes": {
            "pet_allowed": (record.themes or {}).get("pet_allowed"),
            "barrier_free": (record.themes or {}).get("barrier_free"),
            "wellness": (record.themes or {}).get("wellness"),
        },
        "is_hidden_gem": bool(record.is_hidden_gem),
        # --- 시점 데이터: 저장하지 않는다. 상세 조회 시 서버가 붙인다(attach_congestion) ---
        "congestion": None,
        # --- 검증을 통과한 표시용 값 ---
        "slot_label": slot_label or f"{index + 1}번째",
        "match_score": match_score,
        "match_reasons": _clean_match_reasons(raw.get("match_reasons")),
        "image_url": image_url,
        "photo_credit": _clean_credit(raw.get("photo_credit")) if image_url else None,
        "blurb": blurb or None,
    }


def _rebuild(
    course: Any,
    *,
    spot_repo: SpotRepository,
    strict: bool,
    trusted_media: bool,
) -> dict[str, Any]:
    if not isinstance(course, dict) or not course:
        raise InvalidCoursePayload("course 가 객체가 아닙니다")

    raw_spots = course.get("spots")
    if not isinstance(raw_spots, list) or not raw_spots:
        raise InvalidCoursePayload("spots 가 비어 있습니다")
    if len(raw_spots) > MAX_SPOTS:
        raise InvalidCoursePayload(f"스팟 수 초과({len(raw_spots)}>{MAX_SPOTS})")

    spots: list[dict[str, Any]] = []
    # 살아남은 스팟의 **원본 인덱스**. leg 를 원래 이웃 관계에 맞춰 붙이는 데 쓴다(_clean_legs).
    kept: list[int] = []
    for origin_index, raw in enumerate(raw_spots):
        sid = spot_id_of(raw)
        record = spot_repo.by_id(sid) if sid is not None else None
        if record is None:
            if strict:
                # 저장 시점에는 조용히 넘기지 않는다 — 없는 스팟을 섞어 목록 길이를 부풀리는
                # 것 자체가 조작이다. 스팟명은 메시지에 넣지 않는다(외부 문자열 미삽입 규약).
                raise InvalidCoursePayload("코스에 존재하지 않는 스팟이 있습니다")
            continue  # 과거 payload: 스토어에서 사라진 스팟은 조용히 뺀다
        spots.append(
            _rebuild_spot(raw if isinstance(raw, dict) else {}, record,
                          index=len(spots), trusted_media=trusted_media)
        )
        kept.append(origin_index)

    if not spots:
        raise InvalidCoursePayload("유효한 스팟이 없습니다")

    legs = _clean_legs(course.get("legs"), kept=kept)

    return {
        "v": PAYLOAD_VERSION,
        "region": _rebuild_region(course.get("region"), spots),
        "spots": spots,
        "legs": legs,
        # notice 는 서버가 만든 사실 문장이다. 클라이언트가 되돌려 줄 이유가 없으므로 버린다.
        "notice": None,
        "ai_title": clean_user_text(course.get("ai_title"), max_chars=AI_TITLE_MAX) or None,
        "ai_summary": clean_user_text(course.get("ai_summary"), max_chars=AI_SUMMARY_MAX) or None,
        # 클라이언트가 보낸 total_distance_m 은 무시하고 legs 에서 다시 계산한다.
        "total_distance_m": _total_distance(legs),
    }


def _rebuild_region(raw: Any, spots: list[dict[str, Any]]) -> dict[str, Any]:
    """지역 표시값. region_name 은 **항상 서버 표에서** 가져온다(클라이언트 문자열 미사용)."""
    from . import course_service  # 순환 import 회피(course_service → 이 모듈은 없음)

    code = ""
    if isinstance(raw, dict):
        candidate = raw.get("region_code")
        if isinstance(candidate, str) and candidate.strip().isdigit():
            code = candidate.strip()
    if not code and spots:
        code = str(spots[0]["region_code"])
    return {"region_code": code, "region_name": course_service._region_name(code) if code else None}


# --- 공개 API -------------------------------------------------------------------


def rebuild_course_for_store(course: Any, *, spot_repo: SpotRepository) -> dict[str, Any]:
    """**쓰기 경로**(공유 생성·내 코스 저장)에서 부르는 재구성. 없는 스팟이 섞이면 예외.

    사진·설명(`image_url`/`photo_credit`/`blurb`)은 여기서 **전부 버린다**(trusted_media=False).
    호스트 allowlist 만으로는 "다른 장소의 실제 사진"이나 "그럴듯한 거짓 설명"을 막지 못하기
    때문이다. 대신 저장 직전에 `enrich_stored_course` 가 서버 캐시에서 진짜 값을 채운다.

    반환 shape 은 기존 `CourseResponse` 와 호환된다(추가 키 `v` 만 늘었다) — 프론트가
    쓰던 `course.spots[].name` / `.legs[i].walk` 접근 경로가 그대로 살아 있다.
    """
    return _rebuild(course, spot_repo=spot_repo, strict=True, trusted_media=False)


async def enrich_stored_course(
    course: dict[str, Any], *, cache: Any, spot_repo: SpotRepository
) -> None:
    """저장 직전에 사진·설명을 **서버 값**으로 채운다(제자리 갱신).

    `/courses/recommend`·`/courses/arrange` 가 쓰는 `course_enrich_service.enrich_course_spots`
    를 그대로 재사용한다 — 같은 24h 캐시라, 방금 만든 코스를 공유하는 정상 흐름에서는
    원천 호출이 0 이다(캐시 미스여도 스팟별 병렬 1회분).

    실패는 전부 삼킨다. 사진이 없으면 카드가 플레이스홀더로 뜰 뿐이고, 공유 저장 자체가
    사진 때문에 실패하면 안 된다.
    """
    from ..schemas.courses import CourseSpot
    from . import course_enrich_service

    spots = course.get("spots")
    if not isinstance(spots, list) or not spots:
        return
    try:
        models = [CourseSpot(**spot) for spot in spots]
        await course_enrich_service.enrich_course_spots(models, cache, spot_repo)
        for spot, model in zip(spots, models):
            spot["image_url"] = model.image_url
            spot["photo_credit"] = model.photo_credit
            spot["blurb"] = model.blurb
    except Exception as exc:  # noqa: BLE001 — 보강 실패가 저장을 막지 않는다
        logger.info("코스 payload 사진/설명 보강 스킵: %s", exc)


def filter_stored_course(payload: Any, *, spot_repo: SpotRepository) -> dict[str, Any]:
    """**읽기 경로**에서 부르는 필터. 저장된 값도 한 번 더 allowlist 를 통과시킨다.

    이 함수가 있어야 "이 코드 배포 전에 이미 조작해 넣어둔 payload" 가 화면에 뜨지 않는다.
    실패(구조 손상·스팟 전멸)는 예외 대신 **빈 코스**로 수렴시킨다 — 상세 화면이 500 이
    되는 것보다 "표시할 스팟이 없어요" 안내가 낫다(프론트가 이미 그 분기를 갖고 있다).
    """
    trusted_media = isinstance(payload, dict) and _as_int(payload.get("v")) == PAYLOAD_VERSION
    try:
        return _rebuild(payload, spot_repo=spot_repo, strict=False, trusted_media=trusted_media)
    except InvalidCoursePayload as exc:
        logger.info("저장된 코스 payload 필터 결과 비어 있음(무시하고 빈 코스 반환): %s", exc)
        return {"v": PAYLOAD_VERSION, "region": {"region_code": "", "region_name": None},
                "spots": [], "legs": [], "notice": None,
                "ai_title": None, "ai_summary": None, "total_distance_m": None}


async def attach_congestion(course: dict[str, Any], congestion_repo: Any) -> None:
    """상세 조회 응답에 **현재** 혼잡도를 붙인다(제자리 갱신).

    저장 시점의 라벨을 그대로 되돌려주면 "3주 전의 한적함"을 지금 값처럼 보여주게 된다.
    판정 로직은 만들지 않고 `recommend_service` 의 검증된 함수를 그대로 호출한다.
    실패는 전부 삼킨다 — 혼잡도가 없으면 배지가 안 뜰 뿐이고, 공유 코스 열람은 계속돼야 한다.
    """
    from . import recommend_service

    spots = course.get("spots")
    if not isinstance(spots, list) or not spots:
        return
    try:
        cmaps: dict[str, dict] = {}
        for spot in spots:
            code = str(spot.get("region_code") or "")
            if code and code not in cmaps:
                cmaps[code] = await recommend_service._congestion_by_name(code, congestion_repo)
        for spot in spots:
            cong = recommend_service._match_congestion(
                str(spot.get("name") or ""), cmaps.get(str(spot.get("region_code") or ""), {})
            )
            spot["congestion"] = cong.model_dump() if cong is not None else None
    except Exception as exc:  # noqa: BLE001 — 혼잡도 실패가 공유 코스 열람을 막지 않는다
        logger.info("공유 코스 혼잡도 부착 스킵(원천 실패): %s", exc)


__all__ = (
    "InvalidCoursePayload",
    "MAX_SPOTS",
    "PAYLOAD_VERSION",
    "attach_congestion",
    "enrich_stored_course",
    "filter_stored_course",
    "rebuild_course_for_store",
    "spot_id_of",
)
