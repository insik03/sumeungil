"""places(스팟 추천) 응답/요청 모델 = 01-interface-contract.md 부록 C.2/C.3 코드화.

계약이 정본이다. enum은 영문 소문자, 한국어 라벨/변환은 프론트 몫(§0 승계).
SpotCard.match_score/match_reasons 는 프로필 소비 시에만 값, 아니면 null.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, Field

from .congestion import ForecastDay  # 부록 M 예보 1일치 — visit_tip 이 재사용(스키마 재정의 금지)

SpotCategory = Literal[
    "attraction", "restaurant", "cafe", "craft", "trail", "nature", "market", "etc",
]
CongestionLevel = Literal["high", "mid", "low", "unknown"]
# sort: MVP-4 레거시(personalized/congestion/distance) + MVP-7 명시정렬(recommended/popular/calm)
# 를 additive 로 합친 확장 집합. 계약 부록 C.9(신규 소절)에 명기. 정본 정렬 규칙은 recommend_service.
SortMode = Literal[
    "personalized", "recommended", "congestion", "distance", "popular", "calm",
]
# spot_type: 유형 필터(정렬 이전 적용). all=전체, hidden=is_hidden_gem true, popular=false.
SpotType = Literal["all", "hidden", "popular"]

# 검증 단일 소스 — API 레이어가 이 집합으로 400(INVALID_SORT/INVALID_SPOT_TYPE) 판정.
# 필드 자체는 str 로 두고(Literal 이면 pydantic 이 422 를 던짐), region_code 와 동일한
# 수동 400 검증 패턴을 재사용한다(부록 C.6 에러 계약 일관).
SORT_MODES: tuple[str, ...] = get_args(SortMode)
SPOT_TYPES: tuple[str, ...] = get_args(SpotType)


# ---------- 응답: SpotCard (C.2) ----------

class SpotLocation(BaseModel):
    lat: float
    lng: float


class SpotCongestion(BaseModel):
    index: float | None = None
    level: CongestionLevel = "unknown"
    tier: Literal["A", "B", "C", "none"] = "none"


class SpotThemes(BaseModel):
    pet_allowed: bool | None = None
    barrier_free: bool | None = None
    wellness: bool | None = None


class MatchReasons(BaseModel):
    matched_tags: list[str] = Field(default_factory=list)  # registry 영문 코드
    signals: list[str] = Field(default_factory=list)       # C.2.2 enum


class SpotCard(BaseModel):
    id: int
    name: str
    category: SpotCategory
    region_code: str
    address: str | None = None
    location: SpotLocation
    congestion: SpotCongestion | None = None
    themes: SpotThemes
    is_hidden_gem: bool = False
    match_score: float | None = None
    match_reasons: MatchReasons | None = None


# ---------- 응답: SpotDetail (부록 G) — 스팟 상세 조회 ----------
# GET /api/v1/places/{content_id} 전용. SpotCard(C.2)의 상위집합이 아니라 별도 계약이며,
# 추천 목록(SpotCard)과 필드가 겹치되 overview·recommended_for·region_name·source 가 추가된다.
# match_score/match_reasons 는 없다(단건 조회는 프로필 스코어링을 하지 않음).

class SpotImage(BaseModel):
    """★ 부록 P.1 additive(2026-07-31) — 상세 슬라이드용 사진 1장.

    url 은 항상 https 승격된 실제 원천 URL, credit 은 photo_credit 과 **같은 규칙**(없으면 null).
    다른 장소 사진으로 채우지 않는다 — 원천에 없으면 리스트가 짧아질 뿐이다.
    """

    url: str
    credit: str | None = None


class VisitTip(BaseModel):
    """부록 M additive — 이 스팟의 '한적한 날/붐비는 날'. 예보(forecast) 데이터 재사용.

    혼잡도 원천(KTO)에 **이름이 매칭되는 관광지**일 때만 채워진다(사실상 attraction/nature).
    매칭 없음·비교할 날 2일 미만·원천 실패 → SpotDetail.visit_tip 자체가 null(지어내지 않음).
    """

    best_day: ForecastDay
    worst_day: ForecastDay
    days: int = 14  # 판단에 쓴 조회 윈도우(일)


class SpotDetail(BaseModel):
    id: int
    name: str
    category: SpotCategory
    region_code: str
    region_name: str | None = None
    address: str | None = None
    location: SpotLocation
    congestion: SpotCongestion | None = None  # 그 지역 board 이름매칭 재사용. 없으면 null
    themes: SpotThemes
    is_hidden_gem: bool = False
    overview: str | None = None               # TourAPI detailCommon2 소개글. 없으면 null(지어내지 않음)
    ai_summary: str | None = None             # ★ Phase2: 로컬 LLM 3줄 요약(평문). overview 없거나 LLM 실패 시 null
    image_url: str | None = None              # TourAPI firstimage(대표이미지, https 승격). 없으면 null
    # ★ 부록 H.3 additive(2026-07-29): 사진 출처 표기. image_url 이 있을 때만 채워진다.
    #   "한국관광공사" | "한국관광공사 포토갤러리 / 촬영: {촬영자}". 없으면 null(프론트는 미표기).
    photo_credit: str | None = None
    # ★ 부록 P.1 additive(2026-07-31): 상세 슬라이드용 사진 목록(대표사진이 항상 첫 번째).
    #   image_url/photo_credit 는 불변(하위호환) — images 는 그 위에 얹은 확장이다.
    #   대표사진조차 없으면 [] (플레이스홀더가 정답. 다른 장소 사진으로 채우지 않는다).
    images: list[SpotImage] = Field(default_factory=list)
    recommended_for: list[str] = Field(default_factory=list)  # 스팟 태그 기반 한국어 문구(서버 조립)
    visit_tip: VisitTip | None = None          # ★ 부록 M: 한적한 날/붐비는 날. 매칭 없으면 null
    source: str = "tourapi_local_store"


# ---------- 응답 봉투 (C.3) ----------

class RecommendRegion(BaseModel):
    region_code: str
    region_name: str | None = None


# ---------- 응답: Featured (부록 H) — 홈 "지금 뜨는 여행지" 발견형 화면 ----------
# GET /api/v1/places/featured 전용. 사진(image_url) 포함. additive: 기존 엔드포인트 불변.
# SpotCard(C.2)/SpotDetail(G) 와 별도 계약이며 match_score·recommended_for 는 없다(발견형 목록).

class FeaturedSpot(BaseModel):
    id: int
    name: str
    category: SpotCategory
    region_name: str | None = None
    address: str | None = None
    congestion: SpotCongestion | None = None  # board 이름매칭(추천과 동일 로직). 없으면 null
    is_hidden_gem: bool = False
    image_url: str | None = None              # TourAPI firstimage(https 승격). 없으면 null(지어내지 않음)
    # ★ 부록 H.3 additive(2026-07-29): 사진 출처 표기(SpotDetail.photo_credit 과 같은 규칙).
    photo_credit: str | None = None


class FeaturedResponse(BaseModel):
    region: RecommendRegion | None = None
    trending: list[FeaturedSpot] = Field(default_factory=list)      # 지금 뜨는(붐비는 유명 관광지)
    hidden_picks: list[FeaturedSpot] = Field(default_factory=list)  # 오늘의 숨은 스팟(저노출)
    # --- 부록 H.6 additive(2026-08-01): "더보기" 판단용 총 수 ---
    # 프론트가 limit 을 키워 재조회하는 방식(/regions)이라, **더 있는지**를 알 방법이 없어
    # 눌러도 안 늘어나는 버튼이 남아 있었다. 여기 총 수를 실어 정확히 감추게 한다.
    #   trending_total: board 이름매칭에 성공한 후보 총 수(= 이 지역 trending 의 실제 상한)
    #   hidden_total  : is_hidden_gem + trending 비중복 자격을 통과한 후보 총 수
    # 둘 다 **노출 개수가 아니라 후보 총 수**다. null = 집계하지 않음(diverse 모드) → 더보기 없음.
    # optional(기본 null)이라 구버전 프론트는 무시하면 그만이다(하위호환).
    trending_total: int | None = None
    hidden_total: int | None = None


# ---------- 응답: Search (부록 L) — 스팟 이름 검색(코스 빌더용) ----------
# GET /api/v1/places/search?q=... 전용. 코스에 넣을 스팟을 이름으로 찾는 화면이 쓰는 **최소 필드**만
# 담는다(사진·혼잡도·좌표 없음 = 원천 호출 0, 순수 인메모리 조회라 빠르다). additive: 기존 불변.

class PlaceSearchItem(BaseModel):
    id: int                                   # content_id — 그대로 /courses/arrange 의 spot_ids 에 넣는다
    name: str
    category: SpotCategory
    region_code: str
    region_name: str | None = None
    address: str | None = None
    is_hidden_gem: bool = False
    # ★ 부록 U additive(2026-08-01) — 전국 지도에서 "그 지역 대표 명소의 실제 사진"을 띄우려면
    # 검색 결과에 사진이 필요하다. 시드(image_url)에 이미 있는 값이라 **원천 호출 증가 0**이다.
    # 없으면 null(지어내지 않는다) — 호출부는 사진 없이 이름만 보여준다.
    image_url: str | None = None


class PlaceSearchResponse(BaseModel):
    items: list[PlaceSearchItem] = Field(default_factory=list)  # 매치 없으면 [] (에러 아님)


# ---------- 응답: Collections (부록 J) — 테마별 큐레이션 컬렉션 ----------
# GET /api/v1/collections?region_code={code} 전용. 사진(FeaturedSpot) 포함. additive: 기존 불변.
# theme_key 는 서버 고정 enum, title 은 enum→한국어 고정 매핑(인젝션 안전). spots 는 FeaturedSpot 재사용.

class ThemeCollection(BaseModel):
    theme_key: str                            # 서버 고정 enum(healing/photo/pet/quiet_cafe/nature/market/craft)
    title: str                                # enum→한국어 고정 라벨(외부 문자열 미주입)
    spots: list[FeaturedSpot] = Field(default_factory=list)  # 저혼잡·숨은 우선, 기본 4~8개(사진 포함)
    # --- 부록 S.8 additive(2026-08-01): "더보기" 판단용 ---
    total: int = 0            # 그 테마의 **자격 통과 후보 총 수**(노출 개수가 아니다)
    has_more: bool = False    # offset + len(spots) < total → 프론트가 더보기 버튼을 띄운다


class CollectionsResponse(BaseModel):
    region: RecommendRegion | None = None
    collections: list[ThemeCollection] = Field(default_factory=list)  # 스팟 부족 테마는 스킵
    # 부록 S.8 additive(2026-08-01): 이번 응답을 만든 시드. 더보기 요청에 그대로 실어 보내면
    # **같은 순열의 다음 구간**이 와서 중복·누락이 없다(미지정 요청은 서버가 매번 새로 뽑는다).
    seed: int | None = None


# ---------- 응답: Festivals (부록 K) — 홈 축제 배너 실연동 ----------
# GET /api/v1/festivals?region_code={code} 전용. TourAPI searchFestival2 실호출(부록 C·H·J 와 별도 계약).
# additive: 기존 엔드포인트·스키마 불변. 날짜/장소는 API 원본값만 담는다(지어내지 않음).

class Festival(BaseModel):
    id: int
    title: str
    start_date: str                           # "YYYY-MM-DD" (원본 eventstartdate YYYYMMDD 를 하이픈만 삽입)
    end_date: str                             # "YYYY-MM-DD" (원본 eventenddate)
    address: str | None = None                # addr1. 없으면 null
    image_url: str | None = None              # firstimage(https 승격). 없으면 null(지어내지 않음)
    ongoing: bool = False                      # 오늘이 start~end 사이면 진행중, 아니면 예정


class FestivalsResponse(BaseModel):
    region: RecommendRegion | None = None
    festivals: list[Festival] = Field(default_factory=list)  # 접근불가/데이터없음이면 [] (graceful)
    total: int = 0                             # additive(2026-07-29): 필터 통과 전체 수(limit 절삭 전)


# ---------- 응답: Festival 상세 (부록 P.2, 2026-07-31 additive) ----------
# GET /api/v1/festivals/{festival_id} 전용. 목록(K.2)과 **같은 Festival 스키마**를 그대로 품고,
# 사진 슬라이드(images) / 방문 타이밍(timing) / 날씨(weather) 를 얹는다.
# 모든 문구는 **서버 고정 템플릿 + 실측 수치**만 쓴다(LLM·추측 금지).

FestivalStatus = Literal["ongoing", "upcoming", "ended"]


class FestivalTiming(BaseModel):
    """방문 타이밍 — 오늘(KST) 기준 룰 판정. 값은 전부 날짜 계산 결과다."""

    status: FestivalStatus
    d_day: int | None = None      # upcoming 일 때만: 시작까지 남은 일수(내일 시작=1)
    days_left: int | None = None  # ongoing 일 때만: 종료까지 남은 일수(오늘 포함, 마지막날=1)
    tip: str                       # 서버 고정 템플릿 문구(외부 문자열 미주입)


class FestivalWeather(BaseModel):
    """축제 지역 날씨. **예보 범위 안에 축제 기간이 걸릴 때만** available=true."""

    available: bool = False
    summary: str | None = None  # available 일 때만. 실측 강수확률(POP)만 담은 정형 문구
    notice: str | None = None   # 미가용 사유 정형 문구(지역 미매칭 / 예보 범위 밖 / 원천 미확보)


class FestivalDetailResponse(BaseModel):
    festival: Festival                       # 부록 K.2 그대로(필드 불변)
    region: RecommendRegion | None = None    # _Entry.region_code 기반. 매칭 실패면 null
    # ★ P.2 additive(2026-07-31): 축제 소개. TourAPI=detailCommon2 overview,
    #   표준데이터=원천 fstvlCo(축제내용). 태그 제거·1200자 절단한 평문. 없으면 null(지어내지 않음).
    description: str | None = None
    images: list[SpotImage] = Field(default_factory=list)  # 표준데이터 출신(id>=900M)은 항상 []
    timing: FestivalTiming
    weather: FestivalWeather


class RecommendMeta(BaseModel):
    source: str = "tourapi_local_store"
    fetched_at: str
    cache: Literal["hit", "miss"] = "hit"
    profile_applied: bool = False
    rejected_tag_count: int = 0
    notice: str | None = None


class RecommendResponse(BaseModel):
    region: RecommendRegion
    personalized: bool = False
    items: list[SpotCard]
    meta: RecommendMeta


# ---------- MVP-7 rerank 블록 (부록 F.1-3 / F.4-3) — additive ----------
# 하위호환 핵심: rerank 를 요청하지 않으면 RecommendResponse(위) 를 그대로 반환해
# 응답 바이트가 MVP-4~6 과 동일하다. rerank 요청 시에만 아래 확장 모델을 반환한다.

BalanceReason = Literal[
    "primary_over_threshold", "primary_amber_distributed", "no_alternative",
    # (신규, MVP-7 유형/정렬 확장) 명시 정렬(popular/calm) 선택 시 balance rerank 를
    # 적용하지 않았음을 정직 표기. 사용자가 고른 정렬이 우선이므로 재정렬을 건너뛴다.
    "explicit_sort",
    # (신규, 부록 F.1-7 / 2026-08-01 대표 지시) 개인화된 맞춤 추천에서는 취향 점수가 1순위라
    # 혼잡도로 순서를 뒤집지 않았음을 정직 표기. congestion 은 이미 match_score 의 5개
    # 가중치 축 중 하나라, 그 위에 하드 재배치를 얹으면 이중 반영이 된다(부록 F.1-7 참고).
    "taste_priority",
]
WeatherBand = Literal["clear", "soft", "advise_indoor", "unknown"]
WeatherProviderStatus = Literal["ok", "unavailable"]


class RerankDistribution(BaseModel):
    """파트1 로드밸런싱 결과(F.1-3). notice 엔 수치·정형문구만(스팟명 금지, F.1-6)."""

    applied: bool = False
    reason: BalanceReason | None = None
    congested_spot_ids: list[int] = Field(default_factory=list)
    boosted_spot_ids: list[int] = Field(default_factory=list)
    threshold_high: int = 70
    notice: str | None = None


class RerankWeather(BaseModel):
    """파트4 날씨 rerank 결과(F.4-3). 데이터 없으면 provider_status=unavailable/band=unknown."""

    provider_status: WeatherProviderStatus = "unavailable"
    applied: bool = False
    band: WeatherBand = "unknown"
    precip_probability: int | None = None
    threshold_soft: int = 30
    threshold_advise: int = 60
    boosted_categories: list[str] = Field(default_factory=list)
    notice: str | None = None


class RerankBlock(BaseModel):
    distribution: RerankDistribution | None = None
    weather: RerankWeather | None = None


class RecommendResponseRerank(RecommendResponse):
    """rerank 를 요청한 경우에만 반환하는 확장 모델(최상위 rerank 블록 추가).

    rerank 미요청 경로는 RecommendResponse(부모)를 반환 → 이 필드 자체가 없어
    응답 바이트가 MVP-4~6 과 동일(무회귀 보장). SpotCard 스키마는 불변, items 순서만 바뀐다.
    """

    rerank: RerankBlock


# ---------- 요청 (C.3 + F.1-3 rerank) ----------

class ProfileInput(BaseModel):
    """프론트 sessionStorage OnboardingResult 의 부분집합. **신뢰경계 밖** — 서버가 §C.4 재검증."""

    tag_vector: list[float] | None = None
    vector_version: int | None = None
    scoring_weights: dict[str, float] | None = None
    tags: dict[str, list[dict]] | None = None  # OnboardingResult.tags (재검증 대상)


class RerankInput(BaseModel):
    """MVP-7 opt-in rerank 스위치(F.1-3). 없거나 null 이면 rerank 미적용(하위호환)."""

    balance: bool = False
    weather: bool = False


class RecommendRequest(BaseModel):
    region_code: str | None = None
    profile: ProfileInput | None = None
    category: SpotCategory | None = None
    # (신규, 선택) 유형 필터. 미지정=all → 응답 바이트 동일(하위호환). 값 검증은 API 400.
    spot_type: str = "all"
    # sort: str 로 둔다(Literal 이면 미정의 값에 422). SORT_MODES 로 API 가 400 검증.
    # 미지정 기본 "personalized" = MVP-4 동작 그대로(=recommended 와 동치). 하위호환 유지.
    sort: str = "personalized"
    limit: int = 20
    rerank: RerankInput | None = None  # (신규, 선택) 없으면 MVP-4 동작 그대로
