"""TourAPI 분류(contentTypeId + cat1/2/3) → SpotCard category + 스팟 태그 매핑.

근거: backend가 KorService2/areaBasedList2를 데모 4지역에서 실호출해 관측한 실제
contentTypeId·cat3 코드값(2026-07-24)에 기반한다. **추측한 코드는 넣지 않는다.**
관측 예:
  - ct12 관광지: cat1 A01(자연)=자연경관, A02(인문)=관광지
  - ct39 음식점: cat A05, cat3 A05020900=카페/전통찻집 → cafe, 그 외 → restaurant
  - ct38 쇼핑:   cat3 A040102xx=시장 → market, A040107xx=공예품 → craft
  - ct14 문화시설: 박물관/미술관/공연장 → attraction
  - ct28 레포츠: cat3 A030227xx=걷기/둘레길 → trail
  - ct15 축제:   '장소'가 아니라 '이벤트'라 스팟 수집에서 제외한다(카드=장소).

스팟 태그(mood + spot_pref)는 우리 registry(tag_registry) 값으로만 부여한다. 근거 없는
축(companion/accessibility 등)은 스팟에 부여하지 않는다(빈 값) — accessibility는 원천
themes 데이터가 있어야 확정 가능한데 MVP-4 원천(무장애/반려 테마 서비스)이 미인가(403/404)
상태라 themes는 null(미확인)로 둔다.
"""

from __future__ import annotations

# SpotCard.category enum (C.2.1)
CATEGORIES = (
    "attraction", "restaurant", "cafe", "craft", "trail", "nature", "market", "etc",
)

# 스팟 수집에서 제외할 contentTypeId (이벤트·숙박 등 '장소 카드'로 부적합)
EXCLUDED_CONTENT_TYPES = {"15", "25", "32"}  # 축제공연행사, 여행코스, 숙박


def classify_category(content_type_id: str, cat1: str, cat2: str, cat3: str) -> str:
    """원천 분류 → SpotCard category enum. 실호출 관측 코드 기반."""
    ct = (content_type_id or "").strip()
    c1 = (cat1 or "").strip()
    c3 = (cat3 or "").strip()

    if ct == "39":  # 음식점
        if c3 == "A05020900":  # 카페/전통찻집
            return "cafe"
        return "restaurant"

    if ct == "38":  # 쇼핑
        if c3.startswith("A040102"):  # 상설시장/전통시장
            return "market"
        if c3.startswith("A040107"):  # 공예품/공방류
            return "craft"
        return "etc"

    if ct == "28":  # 레포츠
        if c3.startswith("A030227"):  # 걷기/둘레길
            return "trail"
        return "attraction"

    if ct == "12":  # 관광지
        if c1 == "A01":  # 자연
            return "nature"
        return "attraction"

    if ct == "14":  # 문화시설 (박물관/미술관/공연장)
        return "attraction"

    return "etc"


# category → (mood 값들, spot_pref 값들). registry 값만 사용.
# spot_fit 코사인은 registry MOOD_SPOT_SLICE(idx 14~28)만 보므로 mood+spot_pref만 채운다.
_CATEGORY_TAGS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    #                mood                          spot_pref
    "restaurant": ((),                            ("restaurant",)),
    "cafe":       (("calm",),                     ("local_cafe",)),
    "craft":      (("unique",),                   ("craft_shop",)),
    "market":     (("lively",),                   ("traditional_market",)),
    "nature":     (("calm", "healing"),           ("nature_view",)),
    "trail":      (("calm", "contemplative"),     ("walking_trail",)),
    "attraction": ((),                            ("photo_spot",)),
    "etc":        ((),                            ()),
}


def spot_tag_values(category: str) -> list[tuple[str, str]]:
    """category → [(axis, value), ...] (registry 값). 스팟 태그벡터 조립·matched_tags용."""
    moods, spots = _CATEGORY_TAGS.get(category, ((), ()))
    pairs: list[tuple[str, str]] = [("mood", m) for m in moods]
    pairs += [("spot_pref", s) for s in spots]
    return pairs


# is_hidden_gem 휴리스틱 (P3): TourAPI는 popularity/방문수 필드를 주지 않는다.
# 근거 있는 프록시로 대체한다 — (1) 로컬/소규모 성격이 강한 카테고리(카페·공방·전통시장·
# 산책로)이거나, (2) 대표 홍보 이미지(firstimage)가 없는 = 덜 알려진 스팟을 '숨은 곳'으로 본다.
# 대형 관광지/자연 랜드마크는 보통 이미지가 있고 널리 알려져 hidden_gem=False로 남는다.
_HIDDEN_GEM_CATEGORIES = {"cafe", "craft", "market", "trail"}


def is_hidden_gem(category: str, has_image: bool) -> bool:
    if category in _HIDDEN_GEM_CATEGORIES:
        return True
    return not has_image
