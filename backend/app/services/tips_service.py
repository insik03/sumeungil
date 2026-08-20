"""개인화 여행 팁 — 피처 조립 · 캐시 · 후처리 · 정적 폴백. 계약 부록 Z.

## 이 서비스의 계약 한 줄
**화면이 비는 경우가 없다.** 비로그인 · 프로필 없음 · LLM 실패/타임아웃 · 킬스위치 OFF —
어떤 경우에도 정적 5건을 `source:"static"` 으로 200 응답한다. 5xx 를 내지 않는다(부록 Z.0-2).

## 소유 경계
여기(backend)는 피처 조립·캐시·타임아웃·킬스위치·**출력 재검증**(카테고리 allowlist · 길이
절단 · 단정 표현 필터 · 건수 하한)·정적 폴백을 한다. 프롬프트와 LLM 호출은
`ai/tips_generator.py` 가 한다 — 그쪽은 실패 시 예외/빈 리스트만 돌려주고, **폴백 판정은
여기서만** 내린다(두 곳에서 판정하면 "부분 응답"이 새어 나온다).

## 안전
요청에 자유 텍스트 필드가 없어(schemas/tips.py) 인젝션 표면이 0 이다. 그래도 온보딩과 동일한
`injection_guard` 를 **모니터링 용도로 배선만 열어 둔다**(현재 입력이 서버 생성 enum·숫자뿐이라
실제 트립은 0 이며, 차단이 아니라 로그만 남긴다).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..ai import injection_guard, tag_registry
from ..ai.tips_generator import GeneratedTip, TipFeatures, TipsGenerator
from ..cache.base import Cache
from ..config import settings
from ..db.postgres import Database
from ..regions.seed import REGIONS
from ..repositories import ai_course_repo, onboarding_profile_repo
from ..repositories.congestion_repo import CongestionRepository
from ..schemas.tips import AI_NOTICE, BODY_MAX, TITLE_MAX, TipItem, TipsResponse
from ..util.time import now_kst
from .congestion_service import classify_level
from .weather_provider import WeatherProvider

logger = logging.getLogger("sumeungil.services.tips")

_CACHE_PREFIX = "tips:v1"
_STATIC_PATH = Path(__file__).resolve().parent.parent / "content" / "travel_tips.ko.json"

# 부록 Z.2 고정 enum. 이 밖의 카테고리를 낸 팁은 **버린다**(온보딩 registry allowlist 와 같은 태도).
_ALLOWED_CATEGORIES = frozenset({"혼잡", "교통", "날씨", "반려동물", "안전"})

# 02-ai-strategy.md §10.3 — 프롬프트 규칙만으로는 7B 로컬 모델의 이탈을 완전히 막지 못한다.
# 매칭되면 **해당 tip 1건만 폐기**한다(팁은 여러 건이라 부분 폐기가 가능하다). 폐기 후 남은
# 건수가 하한 미만이면 요청 전체를 실패로 보고 정적 폴백으로 전환한다.
#
# 2026-08-20 보안 재작업(Low L-1): "반드시" 류 직접 단정 표현은 막혔지만 "안전이 보장됩니다"·
# "전혀 위험하지 않아요"·"치료 효과가 있어요"·"1 0 0 %"(공백 우회) 같은 **동등 표현**이 실측에서
# 통과했다. 아래 6개를 보강한다 — 지나치게 넓은 정규식(예: "괜찮" 단독)은 정상 문장까지
# 과잉 차단하므로 넣지 않는다.
_TIP_UNSAFE_PATTERNS = [
    r"반드시", r"100\s*%", r"완치", r"무조건", r"절대\s*안전", r"부작용\s*없", r"확실히\s*낫",
    r"법적으로\s*문제\s*없", r"불법\s*아니", r"의학적으로\s*증명", r"치료(?:됩니다|돼요|해요)",
    r"안전이?\s*보장", r"위험하지\s*않", r"문제\s*없(?:어요|습니다)",
    r"걱정\s*(?:하지\s*마|없이)", r"치료\s*효과", r"1\s*0\s*0\s*%",
]
_UNSAFE_RE = re.compile("|".join(_TIP_UNSAFE_PATTERNS))


# --- 정적 폴백 원본 -------------------------------------------------------------


@lru_cache(maxsize=1)
def load_static_tips() -> list[dict[str, str]]:
    """서버 사본 5건. 파일이 깨져도 예외를 밖으로 내보내지 않는다(폴백의 폴백이 없다).

    프론트 `content/travel-tips.ko.json` 과 id·category 가 일치해야 한다(verify_tips.py 가 대조).
    """
    try:
        data = json.loads(_STATIC_PATH.read_text(encoding="utf-8"))
        tips = data["tips"]
    except Exception:  # noqa: BLE001 — 파일 손상/부재로 200 계약이 깨지면 안 된다
        logger.exception("정적 여행 팁 파일을 읽지 못했습니다: %s", _STATIC_PATH.name)
        return []
    return [
        {"id": t["id"], "category": t["category"], "title": t["title"], "body": t["body"]}
        for t in tips
        if isinstance(t, dict) and t.get("category") in _ALLOWED_CATEGORIES
    ]


def static_response() -> TipsResponse:
    """정적 5건 응답. `notice` 는 null(AI 생성분이 아니므로 고지 문구를 붙이지 않는다)."""
    return TipsResponse(
        tips=[TipItem(**t, source="static") for t in load_static_tips()],
        generated_by="static-v2",
        notice=None,
    )


# --- 후처리 (LLM 출력 재검증) ----------------------------------------------------


def postprocess_tip(raw: GeneratedTip) -> dict[str, str] | None:
    """카테고리 allowlist · 빈 값 · 단정 표현을 검사하고 길이를 절단한다. 못 쓰면 None."""
    category = (raw.category or "").strip()
    title = " ".join((raw.title or "").split())
    body = " ".join((raw.body or "").split())
    if category not in _ALLOWED_CATEGORIES or not title or not body:
        return None
    if _UNSAFE_RE.search(title) or _UNSAFE_RE.search(body):
        # 어떤 문구였는지는 로그에 남기지 않는다(출력 원문 미기록 관례).
        logger.info("tips: 단정/과장 표현 감지 → 해당 팁 1건 폐기")
        return None
    return {
        "category": category,
        "title": title[:TITLE_MAX].rstrip(),
        "body": body[:BODY_MAX].rstrip(),
    }


def build_ai_response(generated: list[GeneratedTip]) -> TipsResponse | None:
    """유효 팁이 하한 이상이면 AI 응답, 아니면 None(호출부가 정적 폴백으로 간다).

    id 는 여기서 부여한다 — LLM 이 id 를 지어내 중복·충돌하는 사고를 원천 차단한다(§10.2).
    """
    kept: list[dict[str, str]] = []
    for raw in generated:
        item = postprocess_tip(raw)
        if item is not None:
            kept.append(item)
        if len(kept) >= max(1, settings.tips_max_items):
            break
    if len(kept) < max(1, settings.tips_min_items):
        # 어중간하게 1~2건만 보여주지 않는다 — "지어내지 않는다"와 같은 기조.
        return None
    return TipsResponse(
        tips=[
            TipItem(id=f"ai-{i + 1}", source="ai", **item) for i, item in enumerate(kept)
        ],
        generated_by="ai-v1",
        notice=AI_NOTICE,
    )


# --- 피처 조립 (부록 Z.3 — 여기 적힌 것이 프롬프트 입력의 전부다) -------------------


def _region_label(region_code: str | None) -> str | None:
    """서버 상수(REGIONS) 의 label 만 쓴다. 등록되지 않은 코드는 **무시**(오류가 아니다)."""
    if not region_code:
        return None
    return next((r.label for r in REGIONS if r.region_id == region_code), None)


def _area_cd(region_code: str) -> str | None:
    return next((r.area_cd for r in REGIONS if r.region_id == region_code), None)


def _profile_tags(profile: dict[str, Any] | None) -> tuple[str, ...]:
    """온보딩 프로필 JSON → registry 로 **재검증된** 영문 코드 튜플.

    저장된 값이라도 그대로 믿지 않는다(registry 가 바뀌었을 수 있다). 순서를 고정해야
    같은 취향이 같은 캐시 키를 만든다.
    """
    if not profile:
        return ()
    try:
        tags = json.loads(profile.get("tags") or "{}")
    except (TypeError, ValueError):
        return ()
    if not isinstance(tags, dict):
        return ()
    out: list[str] = []
    for axis in tag_registry.AXES:
        for entry in tags.get(axis) or []:
            value = entry.get("value") if isinstance(entry, dict) else None
            if isinstance(value, str) and tag_registry.is_valid(axis, value):
                out.append(value)
    return tuple(out)


def _category_mix(payload_json: str | None) -> dict[str, int]:
    """최근 저장 코스 1건의 스팟 **카테고리 코드** 집계. 스팟명은 쓰지 않는다(부록 Z.3)."""
    if not payload_json:
        return {}
    try:
        course = json.loads(payload_json)
    except (TypeError, ValueError):
        return {}
    spots = course.get("spots") if isinstance(course, dict) else None
    if not isinstance(spots, list):
        return {}
    mix: dict[str, int] = {}
    for spot in spots:
        code = spot.get("category") if isinstance(spot, dict) else None
        if isinstance(code, str) and code:
            mix[code] = mix.get(code, 0) + 1
    return mix


async def _congestion_level(
    region_code: str | None, congestion_repo: CongestionRepository
) -> str | None:
    """선택 지역의 혼잡 레벨. 원천 실패는 None(팁이 없는 사실을 지어내지 않게).

    board 는 관광지 여러 곳의 값이라 **평균을 기존 classify_level 에 그대로 통과**시킨다 —
    새 임계값을 만들지 않는다(홈·비교 화면과 같은 기준을 쓰기 위해서다).
    """
    if not region_code:
        return None
    area = _area_cd(region_code)
    if not area:
        return None
    try:
        result = await congestion_repo.get_board(area, region_code)
    except Exception:  # noqa: BLE001 — 혼잡도 실패가 팁 응답을 막지 않는다
        return None
    rates = [r.congestion_rate for r in result.records if r.congestion_rate is not None]
    if not rates:
        return None
    return classify_level(sum(rates) / len(rates))


async def _rain_prob(region_code: str | None, weather: WeatherProvider) -> int | None:
    if not region_code:
        return None
    try:
        snapshot = await weather.get_region_forecast(region_code)
    except Exception:  # noqa: BLE001 — 날씨 실패도 graceful(피처만 빠진다)
        return None
    return snapshot.precip_probability if snapshot else None


def _cache_key(features: TipFeatures) -> str:
    """태그·카테고리분포·지역·혼잡·강수구간 + **날짜**.

    날짜를 넣는 이유: 혼잡·강수는 시점 데이터라 하루를 넘겨 재사용하면 거짓이 된다.
    강수는 구간(10% 단위)으로 접는다 — 1%p 차이로 캐시가 갈리면 캐시가 사실상 안 듣는다.
    """
    rain_band = "na" if features.rain_prob_pct is None else str(features.rain_prob_pct // 10)
    raw = "|".join(
        [
            ",".join(features.tags),
            ",".join(f"{k}:{v}" for k, v in sorted(features.category_mix.items())),
            features.region_label or "",
            features.congestion_level or "",
            rain_band,
            str(features.month),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{_CACHE_PREFIX}:{digest}:{now_kst().date().isoformat()}"


async def build_features(
    db: Database,
    *,
    user_id: int,
    region_code: str | None,
    congestion_repo: CongestionRepository,
    weather: WeatherProvider,
) -> TipFeatures | None:
    """로그인 사용자의 피처를 조립한다. **취향 프로필이 없으면 None**(= 정적 폴백)."""

    def _tx(conn) -> tuple[dict[str, Any] | None, str | None]:
        profile = onboarding_profile_repo.get_by_user_id(conn, user_id)
        latest = ai_course_repo.list_by_user(conn, user_id=user_id, limit=1)
        payload = None
        if latest:
            row = ai_course_repo.get(conn, course_id=int(latest[0]["id"]))
            # 남의 코스를 읽지 않는다 — list_by_user 로 얻은 id 지만 소유권을 한 번 더 본다.
            if row is not None and int(row["user_id"]) == user_id:
                payload = row["payload"]
        return profile, payload

    try:
        profile, payload_json = await db.aread(_tx)
    except Exception:  # noqa: BLE001 — 저장소 장애도 정적 폴백으로 흡수한다(5xx 금지)
        logger.info("tips: 프로필 조회 실패 → 정적 폴백")
        return None
    tags = _profile_tags(profile)
    if not tags:
        return None
    return TipFeatures(
        tags=tags,
        category_mix=_category_mix(payload_json),
        congestion_level=await _congestion_level(region_code, congestion_repo),
        rain_prob_pct=await _rain_prob(region_code, weather),
        month=now_kst().month,
        region_label=_region_label(region_code),
    )


# --- 엔트리포인트 ---------------------------------------------------------------


async def build_personalized_tips(
    db: Database,
    *,
    user_id: int | None,
    region_code: str | None,
    generator: TipsGenerator,
    cache: Cache,
    congestion_repo: CongestionRepository,
    weather: WeatherProvider,
) -> TipsResponse:
    """부록 Z.5 폴백 판정표를 그대로 구현한다. **어떤 경로로도 예외를 던지지 않는다.**"""
    # ① 비로그인 · ② 킬스위치 OFF → LLM 미호출 + 즉시 정적
    if user_id is None or not settings.tips_enabled:
        return static_response()

    features = await build_features(
        db,
        user_id=user_id,
        region_code=region_code,
        congestion_repo=congestion_repo,
        weather=weather,
    )
    # ③ 온보딩 프로필 없음 → 정적(개인화할 근거가 없는데 개인화된 척하지 않는다)
    if features is None:
        return static_response()

    key = _cache_key(features)
    try:
        cached = await cache.get(key)
    except Exception:  # noqa: BLE001 — 캐시 장애가 응답을 막지 않는다
        cached = None
    if isinstance(cached, dict):
        try:
            return TipsResponse.model_validate(cached)
        except Exception:  # noqa: BLE001 — 손상 캐시는 무시하고 새로 만든다
            pass

    # 모니터링 전용(차단 아님) — 입력이 서버 생성 enum·숫자뿐이라 실제 트립은 0이어야 한다.
    # 여기서 뭔가 걸린다면 피처 조립 경로에 사용자 문자열이 새어 들어온 것이다(회귀 신호).
    injection_guard.log_if_suspicious(_features_probe(features), context="tips")

    # ④ LLM 타임아웃·예외·비정상 JSON → 정적
    try:
        generated = await generator.generate(features, timeout_sec=settings.tips_timeout_sec)
    except Exception:  # noqa: BLE001 — 생성기의 어떤 실패도 화면을 비우지 않는다
        logger.info("tips: 생성기 실패 → 정적 폴백")
        return static_response()

    # ⑤ 유효 팁이 하한 미만(카테고리 위반·빈 body·단정 표현 폐기 후) → 정적
    response = build_ai_response(generated or [])
    if response is None:
        return static_response()

    try:
        await cache.set(key, response.model_dump(), settings.tips_cache_ttl_sec)
    except Exception:  # noqa: BLE001
        pass
    return response


def _features_probe(features: TipFeatures) -> str:
    """인젝션 모니터링용 문자열(피처를 사람이 읽는 형태로 이어붙인 것)."""
    return " ".join(
        [*features.tags, *features.category_mix.keys(), features.region_label or ""]
    )


__all__ = (
    "build_ai_response",
    "build_features",
    "build_personalized_tips",
    "load_static_tips",
    "postprocess_tip",
    "static_response",
)
