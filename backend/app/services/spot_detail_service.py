"""스팟 상세 조회 서비스 (부록 G) — SpotDetail 조립.

GET /api/v1/places/{content_id} 소관. 추천(recommend_service)과 달리 프로필 스코어링을
하지 않고 단건을 조립한다. 재사용:
  - congestion: recommend_service 의 board 이름매칭 로직을 그대로 재사용(동일 규칙).
  - region_name: recommend_service 와 동일(get_tourapi_region → REGIONS 폴백).

두 개의 신규 조립분:
  - overview: TourAPI detailCommon2 실호출(캐시 TTL 24h). 소개글 없으면 None(지어내지 않음).
  - recommended_for: 스팟 자체 태그(tags)/category/themes/is_hidden_gem 를 **enum→한국어 문구**로
    매핑해 생성. 외부 문자열·스팟명·overview 텍스트를 넣지 않는다(인젝션 표면 0).

ai_summary 경로(2026-07-31, AI 커버리지 개선): 운영 서버는 저사양(2 vCPU)이라 7B 로컬 추론이
50초+ 걸려 사실상 매 요청 LLM 미호출로 운영됐다(ai_summary 100% null). `backend/scripts/
build_spot_summaries.py` 배치가 미리 만들어 둔 `app/spots/data/spot_summaries.json` 을 최우선
으로 쓰도록 바꿔 **파일이 있으면 그 스팟은 LLM 호출이 0**이 된다. 순서: ① 사전 생성 파일
→ ② 런타임 캐시(성공분 24h) → ③ 라이브 LLM(가능할 때만). 응답 스키마(ai_summary: str|null)는
불변 — 어느 경로로 채워졌는지는 로그에만 남긴다(운영 확인용, 계약에 영향 없음).
"""

from __future__ import annotations

import asyncio
import json
import logging
from functools import lru_cache
from pathlib import Path

from ..ai import tag_registry
from ..ai.summarizer import Summarizer
from ..cache.base import Cache
from ..clients import tourapi_detail_client
from ..config import settings
from ..clients.tourapi_detail_client import TourApiDetailError
from ..regions.seed import REGIONS
from ..repositories.congestion_repo import CongestionRepository
from ..repositories.spot_repo import SpotRecord, SpotRepository
from ..schemas.places import SpotDetail, SpotImage, SpotLocation, SpotThemes, VisitTip
from ..spots.region_map import get_tourapi_region
from ..util.images import kto_credit, normalize_image_url
from ..util.names import name_matches, norm_name
from ..util.regions import resolve_area_cd
from . import congestion_service, live_weather_service, photo_service, recommend_service
from .photo_service import NO_PHOTO, Photo

logger = logging.getLogger("sumeungil.services.spot_detail")

# detail(overview+대표이미지) 캐시 TTL — 매 클릭마다 원천을 때리지 않는다. 거의 불변이라 24h 로 충분.
# overview 와 firstimage 는 같은 detailCommon2 응답에서 함께 오므로 한 번의 호출·한 키로 캐시한다.
OVERVIEW_CACHE_TTL_SEC = 24 * 60 * 60

# 원천 실패(429/타임아웃)를 굳히지 않되 폭주도 막는 짧은 음성 캐시 TTL.
DETAIL_FAIL_TTL_SEC = 10 * 60

# ai_summary(로컬 LLM 3줄 요약) 캐시 TTL. overview 캐시와 별도 키(성공분만 캐시).
SUMMARY_CACHE_TTL_SEC = 24 * 60 * 60

# firstimage 정규화(http→https 승격)는 배치(collector)와 공용이라 util 로 내렸다.
# 기존 import 경로(`from ..services.spot_detail_service import _normalize_image_url`,
# festival_service 가 사용)를 깨지 않도록 별칭만 남긴다 — 정의는 util.images 한 곳.
_normalize_image_url = normalize_image_url


class SpotNotFound(Exception):
    """content_id 로 로컬 스토어에서 스팟을 찾지 못함 → API 레이어가 404 SPOT_NOT_FOUND."""


# ---------- recommended_for enum→한국어 매핑 (인젝션 안전: enum 만 사용) ----------

_SPOT_PREF_PHRASE: dict[str, str] = {
    "local_cafe": "로컬 카페를 좋아하는 분",
    "craft_shop": "공방·만들기를 좋아하는 분",
    "traditional_market": "전통시장 구경을 즐기는 분",
    "nature_view": "자연 풍경을 즐기는 분",
    "photo_spot": "사진 찍기 좋아하는 분",
    "restaurant": "맛집 탐방을 즐기는 분",
    "walking_trail": "산책을 즐기는 분",
    "festival": "축제·이벤트를 즐기는 분",
}
_MOOD_PHRASE: dict[str, str] = {
    "calm": "조용히 힐링하고 싶은 분",
    "healing": "조용히 힐링하고 싶은 분",
    "lively": "활기찬 분위기를 즐기는 분",
    "romantic": "로맨틱한 분위기를 찾는 분",
    "contemplative": "사색을 즐기는 분",
    "unique": "이색 체험을 찾는 분",
    "family_friendly": "가족과 함께 가는 분",
}
_THEME_PHRASE: dict[str, str] = {
    "pet_allowed": "반려동물과 함께 가는 분",
    "barrier_free": "이동이 편한 곳을 찾는 분",
    "wellness": "웰니스·휴식을 원하는 분",
}
_CATEGORY_PHRASE: dict[str, str] = {
    "attraction": "가볍게 둘러보기 좋아하는 분",
    "restaurant": "맛집 탐방을 즐기는 분",
    "cafe": "카페에서 쉬어가고 싶은 분",
    "craft": "공방·만들기를 좋아하는 분",
    "trail": "산책을 즐기는 분",
    "nature": "자연 풍경을 즐기는 분",
    "market": "전통시장 구경을 즐기는 분",
    "etc": "새로운 곳을 찾아 떠나는 분",
}
_MAX_PHRASES = 4


def _axis_values_in_registry_order(spot: SpotRecord, axis: str) -> list[str]:
    """스팟 tags 중 특정 축의 value 를 registry 인덱스 순으로(결정적) 반환."""
    present = {value for a, value in spot.tags if a == axis}
    return [r.value for r in tag_registry.REGISTRY if r.axis == axis and r.value in present]


def build_recommended_for(spot: SpotRecord) -> list[str]:
    """스팟 태그/카테고리/테마 기반 '이런 분께 추천' 문구(2~4개). enum 매핑만 사용."""
    phrases: list[str] = []

    def add(p: str | None) -> None:
        if p and p not in phrases and len(phrases) < _MAX_PHRASES:
            phrases.append(p)

    spot_prefs = _axis_values_in_registry_order(spot, "spot_pref")
    # cafe + 숨은곳 특례: 로컬 카페 문구를 "숨은" 버전으로 승격
    is_cafe = spot.category == "cafe" or "local_cafe" in spot_prefs
    cafe_hidden = is_cafe and spot.is_hidden_gem
    if cafe_hidden:
        add("숨은 로컬 카페를 찾는 분")

    for val in spot_prefs:
        if val == "local_cafe" and cafe_hidden:
            continue  # 이미 숨은 버전으로 대체
        add(_SPOT_PREF_PHRASE.get(val))

    for val in _axis_values_in_registry_order(spot, "mood"):
        add(_MOOD_PHRASE.get(val))

    themes = spot.themes or {}
    for key, phrase in _THEME_PHRASE.items():
        if themes.get(key) is True:
            add(phrase)

    # 일반 숨은곳 문구(카페-숨은 특례로 이미 다뤘으면 생략)
    if spot.is_hidden_gem and not cafe_hidden:
        add("붐비지 않는 숨은 곳을 찾는 분")

    # 태그가 하나도 없으면 category 기반 일반 문구 1개로 폴백
    if not phrases:
        add(_CATEGORY_PHRASE.get(spot.category, "새로운 곳을 찾아 떠나는 분"))

    return phrases


# ---------- detail 필드(overview+대표이미지) (detailCommon2 실호출 + 24h 캐시) ----------

async def _get_detail_fields(content_id: int, cache: Cache) -> dict:
    """detailCommon2 소개글+대표이미지를 한 번의 호출로. 캐시 우선.

    반환 {"overview": str|None, "image_url": str|None}. 원천 실패 시 둘 다 None(엔드포인트는 계속 200,
    캐시하지 않아 다음 호출에 재시도). overview/image 없음(None)도 캐시해 재호출을 막는다(null 캐시).
    """
    key = f"spot_overview:{content_id}"  # overview·image 를 함께 담는 detail 캐시(같은 원천 호출)
    cached = await cache.get(key)
    if cached is not None:
        return {"overview": cached.get("overview"), "image_url": cached.get("image_url")}

    try:
        item = await tourapi_detail_client.fetch_detail_common(content_id)
    except TourApiDetailError as exc:
        # 원천 실패는 조회를 막지 않는다(혼잡도 실패와 동일 graceful).
        # 다만 **짧은 음성 캐시**를 둔다: 원천이 429(일일 한도)로 죽으면 이 함수는 매 요청마다
        # 사진 없는 스팟 수십 곳을 재조회해 실패 호출만 계속 쌓는다(자기 DoS + 쿼터 소모).
        # 10분이면 일시적 장애는 곧 회복되고, 한도 소진 상황에서도 폭주하지 않는다.
        logger.info("detail 조회 스킵(원천 실패) content_id=%s: %s", content_id, exc)
        await cache.set(key, {"overview": None, "image_url": None}, DETAIL_FAIL_TTL_SEC)
        return {"overview": None, "image_url": None}

    overview: str | None = None
    image_url: str | None = None
    if item is not None:
        raw = item.get("overview")
        if isinstance(raw, str) and raw.strip():
            overview = raw.strip()
        image_url = _normalize_image_url(item.get("firstimage"))
    fields = {"overview": overview, "image_url": image_url}
    await cache.set(key, fields, OVERVIEW_CACHE_TTL_SEC)
    return fields


async def _get_overview(content_id: int, cache: Cache) -> str | None:
    """소개글만 필요할 때(하위호환 wrapper). detail 캐시를 공유한다."""
    return (await _get_detail_fields(content_id, cache)).get("overview")


async def get_image_url(content_id: int, cache: Cache) -> str | None:
    """(하위호환) 대표이미지 URL만. detail 캐시를 공유해 중복 호출 없음.

    없으면 None. **폴백 체인 없음** — 스팟 레코드(이름/주소)가 없어 갤러리 매칭을 할 수 없다.
    폴백까지 원하는 호출부는 `get_photo(spot, cache)` 를 쓴다.
    """
    return (await _get_detail_fields(content_id, cache)).get("image_url")


# ---------- 사진 조회 공용 진입점 (featured / collections / course / detail 공통) ----------

async def get_photo(spot: SpotRecord, cache: Cache) -> Photo:
    """스팟 1곳의 사진을 체인으로 결정. 못 찾으면 Photo(url=None) — 지어내지 않는다.

        ① 시드 image_url        : 배치가 areaBasedList2 로 적재. **원천 콜 0**
        ② detailCommon2 first…  : 시드에 판정값이 없는 스팟만(24h 캐시 공유)
        ③ detailImage2 첫 장    : photo_service
        ④ 포토갤러리 엄격매칭    : photo_service (규칙은 photo_service 독스트링)
        ⑤ null

    ①을 맨 앞에 둔 이유(2026-07-29): 예전엔 스팟 1건마다 detailCommon2 를 1콜씩 썼는데,
    홈·컬렉션이 한 번에 수십 곳을 조회하다 보니 그 오퍼레이션의 **일일 한도가 429 로 소진**되어
    전 지역 사진이 통째로 null 이 되는 사고가 났다. 시드 값은 같은 원천의 같은 firstimage 필드라
    값이 바뀌지 않으면서(무회귀) 콜만 사라진다.
    """
    if spot.image_url:
        return Photo(url=spot.image_url, credit=kto_credit(), source="seed")

    # 시드에 사진이 없어도 **detailCommon2 는 여전히 물어본다**. 두 오퍼레이션이 같은
    # firstimage 를 항상 같게 주지는 않기 때문이다(실측: 동십자각·벡스코는 areaBasedList2
    # firstimage=""인데 detailCommon2 에는 값이 있다). 이 단계를 건너뛰면 종전에 사진이
    # 있던 스팟의 URL 이 바뀌어 무회귀가 깨진다. 콜은 '시드에 사진 없는 소수'에만 발생한다
    # (표면 522곳 기준 522콜 → 31콜, 94% 감소).
    url = (await _get_detail_fields(spot.id, cache)).get("image_url")
    if url:
        return Photo(url=url, credit=kto_credit(), source="firstimage")

    return await photo_service.fallback_photo(spot.id, spot.name, spot.address, cache)


async def get_photos(spots: list[SpotRecord], cache: Cache) -> list[Photo]:
    """여러 스팟의 사진을 동시 조회(순서 보존). 개별 실패는 그 스팟만 NO_PHOTO."""
    if not spots:
        return []

    async def one(s: SpotRecord) -> Photo:
        try:
            return await get_photo(s, cache)
        except Exception as exc:  # noqa: BLE001 — 사진 1장 실패가 목록을 막지 않는다
            logger.info("사진 조회 스킵 content_id=%s: %s", s.id, exc)
            return NO_PHOTO

    return await asyncio.gather(*(one(s) for s in spots))


# ---------- images (부록 P.1 additive) — 상세 슬라이드용 사진 목록 ----------

# 슬라이드 한 벌의 상한(대표사진 포함). 원천이 더 줘도 여기서 자른다.
DETAIL_IMAGES_MAX = photo_service.DETAIL_IMAGES_MAX


async def build_images(content_id: int, photo: Photo, cache: Cache) -> list[SpotImage]:
    """대표사진(첫 번째) + detailImage2 추가사진(중복 제거, 총 최대 8장).

    - detailImage2 는 **상세 진입 시에만** 호출되고 스팟당 7일 캐시된다(쿼터 방어).
    - 429/실패 → 추가사진 [] → 결과는 [대표사진 1장]. 대표사진도 없으면 [](빈 배열).
    - 다른 장소 사진으로 채우지 않는다 — 짧으면 짧은 대로 정직하게.
    """
    extra = await photo_service.detail_image_urls(content_id, cache)
    return [
        SpotImage(url=url, credit=credit)
        for url, credit in photo_service.build_image_list(
            photo.url, photo.credit, extra, DETAIL_IMAGES_MAX
        )
    ]


# ---------- ai_summary (로컬 LLM 3줄 요약, 부록 G additive) ----------

# build_spot_summaries.py 산출물 경로(단일 소스). 스크립트와 이 상수가 어긋나면 배치가 만든
# 파일을 서버가 못 찾는 사고가 나므로 이름을 그대로 맞춘다.
PREGENERATED_SUMMARIES_PATH = (
    Path(__file__).resolve().parent.parent / "spots" / "data" / "spot_summaries.json"
)


@lru_cache(maxsize=1)
def _pregenerated_summaries() -> dict[str, str]:
    """사전 생성 요약 파일을 프로세스 수명 동안 1회만 읽어 메모리 dict 로 유지.

    파일이 없거나(N1: 아직 배치를 안 돌림) 깨져 있어도(N2: 파싱 실패) **앱은 죽지 않는다** —
    빈 dict 를 반환해 하위 경로(런타임 캐시 → 라이브 LLM)로 그대로 폴백된다.
    """
    try:
        raw = json.loads(PREGENERATED_SUMMARIES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.info("사전 생성 요약 파일 없음(%s) — 런타임/라이브 경로로 폴백", PREGENERATED_SUMMARIES_PATH)
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("사전 생성 요약 파일 파싱 실패(%s): %s — 런타임/라이브 경로로 폴백",
                        PREGENERATED_SUMMARIES_PATH, exc)
        return {}

    raw_summaries = raw.get("summaries") if isinstance(raw, dict) else None
    if not isinstance(raw_summaries, dict):
        return {}

    out: dict[str, str] = {}
    for spot_id, entry in raw_summaries.items():
        if not isinstance(entry, dict):
            continue
        summary = entry.get("summary")
        if isinstance(summary, str) and summary.strip():
            out[str(spot_id)] = summary
    logger.info("사전 생성 요약 %d건 로드 완료(%s)", len(out), PREGENERATED_SUMMARIES_PATH)
    return out


async def _get_ai_summary(
    content_id: int,
    overview: str | None,
    summarizer: Summarizer | None,
    cache: Cache,
) -> tuple[str | None, str | None]:
    """ai_summary 조립 → (summary, provider). **① 사전 생성 파일 → ② 런타임 캐시 → ③ 라이브 LLM** 순.

    provider(QA 2026-09-05 P2): 라이브/런타임 캐시는 만든 시점의 settings.llm_provider
    ("gemini"/"ollama"), 사전 생성 파일은 배치 산출물이라 None(출처 미상 → 프론트는 일반 "AI"
    마크). 프론트가 모든 요약에 Gemini 마크를 붙이던 오표시를 막는다.

    - 사전 생성 파일에 있으면 그대로 반환(LLM 호출 0, overview 유무와 무관 — 배치 시점엔
      overview 가 있었다는 뜻이므로 지금 원천이 잠깐 흔들려도 정상 표시된다).
    - overview 없음(현재 조회 기준) → None(요약을 만들지 않음, LLM 미호출).
    - summarizer 미주입(비활성) → None(graceful).
    - LLM 실패/타임아웃/빈응답 → None(원문 overview 는 호출부에서 그대로 유지). 실패는 캐시하지
      않아 다음 클릭에 재시도(overview 원천 실패 처리와 동일 정책).
    """
    pregenerated = _pregenerated_summaries().get(str(content_id))
    if pregenerated:
        logger.debug("ai_summary source=pregenerated content_id=%s", content_id)
        return pregenerated, None

    if not overview or summarizer is None:
        return None, None

    key = f"spot_summary:{content_id}"
    cached = await cache.get(key)
    if cached is not None:
        logger.debug("ai_summary source=runtime_cache content_id=%s", content_id)
        return cached.get("summary"), cached.get("provider")  # 구 캐시 항목엔 provider 없음 → None

    summary = await summarizer.summarize(overview)  # 내부에서 모든 오류를 None 으로 흡수
    provider = settings.llm_provider if summary else None
    if summary:
        await cache.set(key, {"summary": summary, "provider": provider}, SUMMARY_CACHE_TTL_SEC)
        logger.debug("ai_summary source=live_llm(%s) content_id=%s", provider, content_id)
    return summary, provider


# ---------- visit_tip (부록 M additive) — 이 스팟의 한적한 날/붐비는 날 ----------

# 상세 화면 문구가 "이번 주~다음 주"라 2주 윈도우로 본다(forecast 기본값과 동일).
VISIT_TIP_DAYS = congestion_service.FORECAST_DAYS_DEFAULT


async def _visit_tip(
    spot: SpotRecord, congestion_repo: CongestionRepository
) -> VisitTip | None:
    """예보 캐시(6h)를 재사용해 best/worst day 를 뽑는다. 못 뽑으면 None(지어내지 않음).

    None 이 되는 경우: 지역코드 해석 불가 / 원천 실패 / 그 지역 데이터 없음 /
    스팟명이 혼잡도 관광지와 매칭 안 됨(카페·공방 등 대부분) / 비교할 날이 2일 미만.
    혼잡도 배지(congestion)와 **같은 이름매칭 규칙**을 써서 둘이 다른 관광지를 가리키지 않게 한다.
    """
    area_cd = resolve_area_cd(spot.region_code)
    if not area_cd:
        return None
    try:
        result = await congestion_repo.get_forecast(area_cd, spot.region_code)
    except Exception as exc:  # noqa: BLE001 — 예보 실패가 상세 조회를 막지 않는다
        logger.info("visit_tip 스킵(원천 실패) region=%s: %s", spot.region_code, exc)
        return None
    if not result.spots:
        return None

    nn = norm_name(spot.name)
    matched = next((s for s in result.spots if norm_name(s.spot_name) == nn), None)
    if matched is None:
        matched = next((s for s in result.spots if name_matches(nn, norm_name(s.spot_name))), None)
    if matched is None:
        return None  # 혼잡도 원천에 없는 스팟 = 정직하게 null

    days = congestion_service.clamp_days(VISIT_TIP_DAYS)
    sf = congestion_service.build_spot_forecast(
        matched, *congestion_service.forecast_window(days)
    )
    if sf.best_day is None or sf.worst_day is None:
        return None
    return VisitTip(best_day=sf.best_day, worst_day=sf.worst_day, days=days)


def _region_name(region_code: str) -> str | None:
    tr = get_tourapi_region(region_code)
    if tr:
        return tr.region_name
    return next((r.label for r in REGIONS if r.region_id == region_code), None)


async def build_spot_detail(
    content_id: int,
    spot_repo: SpotRepository,
    congestion_repo: CongestionRepository,
    cache: Cache,
    summarizer: Summarizer | None = None,
) -> SpotDetail:
    """content_id 로 SpotDetail 조립. 없으면 SpotNotFound.

    summarizer 가 주어지면 overview 를 로컬 LLM 으로 3줄 요약해 ai_summary 에 담는다
    (실패/없음 → null, 원문 overview 는 그대로). 미주입이면 ai_summary=null(하위호환).
    """
    spot = spot_repo.by_id(content_id)
    if spot is None:
        raise SpotNotFound(f"content_id={content_id}")

    # 혼잡도: 그 스팟 지역 board 에서 이름매칭(recommend 와 동일 로직 재사용). 실패/없음 → None.
    cmap = await recommend_service._congestion_by_name(spot.region_code, congestion_repo)
    congestion = recommend_service._match_congestion(spot.name, cmap)

    # 부록 M: 이 스팟의 한적한 날/붐비는 날(예보 캐시 재사용). 매칭 안 되면 null.
    visit_tip = await _visit_tip(spot, congestion_repo)

    fields = await _get_detail_fields(content_id, cache)  # overview+대표이미지 한 번에
    ai_summary, ai_provider = await _get_ai_summary(content_id, fields.get("overview"), summarizer, cache)

    # 사진: 상세는 이미 detailCommon2 를 부른 뒤라 firstimage 가 있으면 그걸 그대로 쓰고,
    # 없을 때만 폴백 체인(시드 → detailImage2 → 갤러리)을 탄다.
    if fields.get("image_url"):
        photo = Photo(url=fields["image_url"], credit=kto_credit(), source="firstimage")
    else:
        photo = await get_photo(spot, cache)

    # 부록 P.1: 슬라이드용 사진 목록(대표 + detailImage2). 기존 image_url/photo_credit 은 불변.
    images = await build_images(content_id, photo, cache)

    # 2026-09-20 — 이 스팟 **좌표 기준** 지금 날씨(기상청 5km 격자). 같은 격자의 스팟들이
    # 원천 호출 1건을 나눠 쓴다(30분 캐시). 실패·미확보면 null 이고 상세는 그대로 나간다.
    live_weather = await live_weather_service.for_point(spot.lat, spot.lng, cache)

    return SpotDetail(
        id=spot.id,
        name=spot.name,
        category=spot.category,  # type: ignore[arg-type]
        region_code=spot.region_code,
        region_name=_region_name(spot.region_code),
        address=spot.address,
        location=SpotLocation(lat=spot.lat, lng=spot.lng),
        congestion=congestion,
        themes=SpotThemes(**(spot.themes or {})),
        is_hidden_gem=spot.is_hidden_gem,
        overview=fields.get("overview"),
        ai_summary=ai_summary,
        ai_provider=ai_provider,
        image_url=photo.url,
        photo_credit=photo.credit,
        images=images,
        recommended_for=build_recommended_for(spot),
        visit_tip=visit_tip,
        live_weather=live_weather,
        source="tourapi_local_store",
    )
