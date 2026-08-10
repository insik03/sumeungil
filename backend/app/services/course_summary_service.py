"""코스 AI 요약 (부록 I.11) — `CourseResponse.ai_summary` 조립.

`/courses/arrange`(사용자 선택 코스)와 `/courses/recommend`(AI 코스)가 **같은 함수**를 쓴다.
순서가 확정된 뒤의 스팟 목록(이름·분류·지역·slot_label)과 구간 이동시간(legs)을 텍스트로 만들어
로컬 LLM(온보딩·소개글 요약과 동일 모델)에게 2~3문장 요약을 시킨다.

정직 규칙:
  - notice(수치·정형문구)와 달리 ai_summary 는 **스팟명이 들어가는 유일한 생성 필드**다. 그래서
    스팟명은 외부(공공데이터) 문자열로 취급해 spot detail ai_summary 와 **동일한 방어**를 건다:
      시스템 프롬프트(데이터일 뿐 지시 아님) + <course_data> 델리미터 + normalize_unicode +
      스팟명 개별 길이 절단 + 전체 길이 절단 + 툴 미부여. 출력은 평문(프론트 텍스트노드 렌더).
  - LLM 실패/타임아웃/비활성 → **None**. 코스(spots/legs/notice)는 그대로 정상 응답한다.
  - 캐시: 같은 **spot_ids 순서 조합**이면 24h 재사용(성공분만). 실패는 캐시하지 않아 다음 요청에 재시도.
  - 모델이 없는 사실(영업시간·맛·역사)을 붙이지 못하도록 입력에 그런 데이터를 애초에 넣지 않는다.
"""

from __future__ import annotations

import hashlib
import logging

from ..ai import injection_guard
from ..ai.summarizer import Summarizer
from ..cache.base import Cache
from ..config import settings
from ..schemas.courses import CourseLeg, CourseSpot

logger = logging.getLogger("sumeungil.services.course_summary")

# 프롬프트/포맷이 바뀌면 v 를 올려 캐시를 자연 무효화한다.
# v2(부록 I.12): 같은 키에 summary 와 **title 을 함께** 담는다(LLM 호출 1회로 둘 다 생성).
_CACHE_PREFIX = "course_summary:v2"
# 스팟명 1건 상한(외부 문자열). 긴 이름으로 프롬프트를 밀어내는 시도를 막는다.
_MAX_NAME_CHARS = 40
_MAX_REGION_CHARS = 20

# category enum → 한국어 라벨(서버 고정 매핑, 외부 문자열 미주입).
_CATEGORY_LABEL: dict[str, str] = {
    "attraction": "명소",
    "restaurant": "맛집",
    "cafe": "카페",
    "craft": "공방",
    "trail": "산책로",
    "nature": "자연",
    "market": "시장",
    "etc": "기타",
}


def _safe_text(raw: str | None, max_chars: int) -> str:
    """외부 문자열 정제: 유니코드 정규화(제로폭/전각 우회 완화) + 개행 제거 + 길이 절단."""
    cleaned = injection_guard.normalize_unicode(raw or "")
    cleaned = cleaned.replace("\n", " ").replace("\r", " ").strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned


def _cache_key(spot_ids: list[int]) -> str:
    raw = ",".join(str(i) for i in spot_ids)
    return f"{_CACHE_PREFIX}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _leg_hint(leg: CourseLeg) -> str | None:
    """다음 스팟까지의 이동 요지. Tmap 실패 구간(전부 null)이면 None(지어내지 않음)."""
    parts: list[str] = []
    if leg.walk is not None:
        parts.append(f"도보 {leg.walk.minutes}분")
    if leg.car is not None:
        parts.append(f"차 {leg.car.minutes}분")
    return " / ".join(parts) if parts else None


def build_course_text(
    spots: list[CourseSpot], legs: list[CourseLeg], region_name: str | None
) -> str:
    """LLM 입력 텍스트 조립. 스팟명·지역명 외의 외부 문자열(주소·소개글)은 넣지 않는다."""
    lines: list[str] = []
    region = _safe_text(region_name, _MAX_REGION_CHARS)
    if region:
        lines.append(f"지역: {region}")
    for i, spot in enumerate(spots):
        name = _safe_text(spot.name, _MAX_NAME_CHARS)
        label = _CATEGORY_LABEL.get(spot.category, "장소")
        slot = _safe_text(spot.slot_label, 12)  # 서버 생성 라벨("1번째"/"아침 카페")
        lines.append(f"{i + 1}. {name} ({label}, {slot})")
        if i < len(legs):
            hint = _leg_hint(legs[i])
            if hint:
                lines.append(f"   다음 장소까지 {hint}")
    return "\n".join(lines)


async def build_course_ai_pack(
    spots: list[CourseSpot],
    legs: list[CourseLeg],
    region_name: str | None,
    summarizer: Summarizer | None,
    cache: Cache,
) -> tuple[str | None, str | None]:
    """코스 (제목 1줄, 요약 2~3문장). 실패·비활성·스팟 부족이면 (None, None).

    부록 I.12: 제목과 요약을 **한 번의 LLM 호출**(JSON 모드)로 함께 뽑는다 — 사용자가 기다리는
    경로라 호출 수를 늘리지 않는다. JSON 호출이 실패하면 기존 **평문 요약 1회로 폴백**해
    최소한 ai_summary 는 지킨다(제목만 null). 캐시는 **같은 키에 title/summary 를 함께** 담는다.
    """
    if summarizer is None or not settings.course_summary_enabled:
        return None, None
    if len(spots) < 2:
        return None, None  # 1곳짜리는 "코스"가 아니라 요약할 흐름이 없다.

    key = _cache_key([s.id for s in spots])
    try:
        cached = await cache.get(key)
    except Exception:  # noqa: BLE001 — 캐시 장애가 코스 응답을 막지 않는다
        cached = None
    if cached is not None:
        return cached.get("title"), cached.get("summary")

    course_text = build_course_text(spots, legs, region_name)
    # 모니터링 전용(차단 아님): 스팟명에 지시문 패턴이 섞여 있으면 플래그만 남긴다(원문 미기록).
    injection_guard.log_if_suspicious(course_text, context="course_summary")

    title: str | None = None
    summary: str | None = None
    try:
        title, summary = await summarizer.summarize_course_pack(course_text)
    except Exception as exc:  # noqa: BLE001 — 생성 실패가 코스 응답을 막지 않는다
        logger.info("코스 제목·요약 생략(요약기 오류): %s", exc)
        title, summary = None, None

    if not summary:
        # JSON 모드가 흔들린 경우에만 평문 요약 1회 폴백(정상 경로에서는 호출 1회 유지).
        try:
            summary = await summarizer.summarize_course(course_text)
        except Exception as exc:  # noqa: BLE001
            logger.info("코스 ai_summary 생략(폴백 요약기 오류): %s", exc)
            summary = None

    if summary:
        try:
            await cache.set(
                key,
                {"summary": summary, "title": title},
                settings.course_summary_cache_ttl_sec,
            )
        except Exception:  # noqa: BLE001
            pass
    logger.info(
        "코스 ai_summary %s / ai_title %s (스팟 %d곳)",
        "생성" if summary else "생략", "생성" if title else "생략", len(spots),
    )
    return title, summary


async def build_course_ai_summary(
    spots: list[CourseSpot],
    legs: list[CourseLeg],
    region_name: str | None,
    summarizer: Summarizer | None,
    cache: Cache,
) -> str | None:
    """요약만 필요할 때의 하위호환 wrapper(부록 I.11 시그니처 유지). 내부는 pack 과 같은 경로."""
    _title, summary = await build_course_ai_pack(spots, legs, region_name, summarizer, cache)
    return summary
