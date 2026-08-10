"""AI 여행 문답(컨시어지) 서비스 — 부록 N. `POST /api/v1/concierge/ask` 뒤에서 쓰인다.

"비 오는 평일에 부모님 모시고 갈 조용한 곳 있어?" 같은 **자연어 한 문장**을 받아
① 조건 해석 → ② 지역 감지 → ③ 추천 실행 → ④ 대화형 답변 생성을 한 번에 처리한다.

**신규 외부 API 0** — 전부 이미 검증된 내부 경로의 재조합이다:
  ① 조건 해석 : app.ai.concierge_understanding.extract_concierge_understanding (부록 N.10)
                 = 온보딩 추출(부록 B)과 같은 injection guard + registry 재검증 + AXIS_CAP +
                 룰 폴백을 승계하되, LLM-first 로 태그·intent·지역힌트·요청방식을 한 번에 받는다
  ② 지역 감지 : app.regions.seed.REGIONS 라벨/별칭 부분일치 (부록 A 사전 재사용, 원천 호출 0)
                 + ①의 region_text 힌트도 **같은 함수로 재검증**(N.10 §2, 지어냄 차단)
  ③ 추천     : app.services.recommend_service.build_recommend_response (부록 C/F)
                 프로필은 ①의 결과를 프론트와 **동일한 ProfileInput 형태**로 넘겨 C.4 재검증을 탄다
  ④ 답변     : app.ai.summarizer.Summarizer.answer_concierge (부록 G/I.11 과 같은 로컬 모델)

축제 의도 분기(2026-07-30, 부록 N.9):
  "축제/페스티벌"이 들어간 질문은 스팟 추천이 아니라 **축제 목록**을 원하는 질문이다.
  그런데 ③ 이 무조건 recommend_service 를 타서 "연인과 즐길 축제 있어?" 에 갈맷길 같은
  무관한 스팟이 나왔다(대표 실사용 보고). 이제 축제 질문은 recommend_service 를 **아예
  호출하지 않고**(spots=[]) 이미 캐시된 festival_service.build_festivals_response 를 태운다.
  단 "축제 말고/빼고/외" 처럼 축제를 **배제**하는 부정형은 축제 모드로 보내지 않는다(N.9 추가).
  N.10부터는 정규식 키워드("축제") 외에 ①의 LLM intent 힌트도 OR 결합된다(부정형이 최우선).

문답 다양화(2026-07-30, 부록 N.9 — 대표 실사용 "맨날 같은 코스만 나온다" 대응):
  같은 질문을 다시 물어도 매번 정확히 같은 1곳만 언급하던 문제를 구조로 고쳤다(파인튜닝 無):
  ① 답변 문장이 언급할 스팟/축제를 상위권 안에서 **가중 무작위**로 고른다(카드 목록 순서는 불변).
  ② "여러 곳/몇 개/다양하게" 같은 **요청 방식**을 wants_multiple() 로 감지해 여러 곳을 나열한다.
  ③ "다른 곳/말고/또 있어" 같은 **대안 요청**을 wants_alternative() 로 감지해 앞서 보여줬을 법한
     상위권을 제외한 곳을 보여준다.

LLM-first 이해 전환(2026-07-30, 부록 N.10 — 대표 지시 "새 키워드가 들어오면 대답을 못한다"):
  사전 밖 표현("불꽃놀이 보러 갈 데")·사전 밖 지역명에서 기존 키워드 규칙이 손을 놓고
  엉뚱한 기본 지역(부산 등)으로 떨어졌다. extract_concierge_understanding 이 태그와 함께
  intent(spots/festivals)·region_text(지역 힌트)·wants_multiple/wants_alternative 힌트를
  **LLM 호출 1회**(①을 대체 — 호출 수 증가 없음)로 함께 받는다. 서버는 이 힌트를 그대로
  믿지 않는다: intent 는 기존 정규식과 OR(부정형 최우선), region_text 는 반드시
  detect_region() 으로 재검증하고 실패하면 기본 지역으로 폴백하지 않고 "준비 중" 안내로
  정직하게 답한다(N.10 §2 — "천안인데 부산 추천"류 오답의 구조적 재발 방지).

정직·안전 규칙(부록 N.5):
  - 사용자 질문 **원문은 답변 LLM 에 넣지 않는다**. 서버가 enum(registry 라벨)으로 접은
    결과 + 지역명 + 상위 스팟 3개(이름/분류/혼잡level)만 <travel_data> 로 전달한다.
    → 질문 안의 "이전 지시 무시하고 …" 같은 문장은 답변 프롬프트에 도달할 경로가 없다.
  - 인젝션 패턴이 탐지되면 온보딩 라우터와 동일하게 **추출 LLM 을 스킵**(룰 폴백 강등)하고,
    답변도 LLM 없이 템플릿으로 만든다 → 그 요청에서 LLM 호출 수는 0이 된다.
  - answer 는 절대 null/빈문자열이 아니다. LLM 실패·비활성·타임아웃이면 enum 라벨 기반
    템플릿으로 채우고 meta.answer_source="template" 로 표기한다.
  - 캐시 없음(질문이 매번 다름). 대신 질문 길이 상한(200자)·LLM 타임아웃으로 비용을 묶는다.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time

from ..ai import injection_guard, tag_registry
from ..ai.concierge_understanding import ConciergeUnderstanding, extract_concierge_understanding
from ..ai.llm_provider import LLMProvider
from ..ai.schemas import LLMExtractionError, OnboardingResult
from ..ai.summarizer import Summarizer
from ..cache.base import Cache
from ..config import settings
from ..regions.seed import PROVINCE_GROUPS, REGIONS, RegionSeed
from ..repositories.congestion_repo import CongestionRepository
from ..repositories.spot_repo import SpotRepository
from ..schemas.concierge import (
    ConciergeAskResponse,
    ConciergeExtracted,
    ConciergeMeta,
    ConciergeRegion,
)
from ..schemas.places import Festival, ProfileInput, RerankInput, SpotCard
from . import festival_service, recommend_service, search_service
from .weather_provider import WeatherProvider

logger = logging.getLogger("sumeungil.services.concierge")

# 답변 데이터 블록에 넣는 스팟 수(상위 N개만 — 프롬프트를 짧게 유지). wants_multiple 이면 더 늘린다.
_ANSWER_SPOT_COUNT = 3
_ANSWER_SPOT_COUNT_MULTIPLE = 5   # wants_multiple 일 때 나열 개수(N.9)
_ANSWER_FESTIVAL_COUNT = 3    # 축제 모드도 동일 규약(데이터 블록엔 상위 3건만)
_ANSWER_FESTIVAL_COUNT_MULTIPLE = 5
# 2026-07-30(N.9 다양화): 기본 모드는 상위 이 곳 중 가중 무작위 _ANSWER_SPOT_COUNT 곳을 답변에
# 언급한다(같은 질문을 다시 물어도 다른 곳이 언급되게). **spots 응답 배열(카드 목록) 순서는
# 절대 바꾸지 않는다** — 여기서 고르는 건 "답변 문장에 언급할 부분집합"일 뿐이다.
_ANSWER_SPOT_POOL = 5
# wants_alternative(N.9): 상위 concierge_spot_limit(=8)곳 중 1~3위를 제외한 곳에서 고른다.
_ALT_SPOT_POOL = 8
_ALT_SPOT_EXCLUDE_TOP = 3
# 축제 모드: 지역 필터 후 정렬된 목록에서 앞쪽만 쓴다. fetch 를 넉넉히(30) 하는 이유는
# festival_service 가 이미 정렬(진행중·종료임박 우선)해 주기 때문 — 여기서 재정렬하지 않는다.
_FESTIVAL_FETCH_LIMIT = 30
_FESTIVAL_RESULT_COUNT = 6
_MAX_NAME_CHARS = 40          # 외부(공공데이터) 스팟명 1건 상한
_MAX_REGION_CHARS = 24

# category enum → 한국어 라벨(서버 고정 매핑, 외부 문자열 미주입 — course_summary_service 와 동일 규약)
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
_CONGESTION_LABEL: dict[str, str] = {
    "low": "여유",
    "mid": "보통",
    "high": "붐빔",
    "unknown": "정보 없음",
}

# 답변 문장(LLM·템플릿 공통)에 쓸 취향 축 — 동행 → 분위기 → 선호 스팟.
# accessibility(주차·휠체어·유모차)·mobility·congestion_pref 는 **일부러 제외**한다:
# 이들은 스코어링/하드필터 입력이지 "장소의 시설 정보"가 아닌데, 데이터 블록에 넣으면
# 7B 로컬 모델이 "유모차도 편하게 이용할 수 있어요"처럼 스팟의 사실로 단정해버린다(실측).
# 프롬프트 규칙만으로는 완전히 막히지 않아 **입력 자체에서 제거**하는 구조적 방어를 택했다.
# (extracted.tags 응답에는 모든 축이 그대로 노출된다 — 정직성은 유지)
_ANSWER_AXES = ("companion", "mood", "spot_pref")
_TEMPLATE_AXES = _ANSWER_AXES
_TEMPLATE_MAX_LABELS = 3

# ---------- 정직 안내 문구(정형문구만. 사용자 질문 원문·스팟명은 절대 넣지 않는다) ----------
NOTICE_NO_REGION = "지역을 말씀해주시면 더 정확해요."
NOTICE_MULTI_REGION = "질문에 여러 지역이 보여 먼저 언급된 곳을 기준으로 안내했어요."
NOTICE_WEATHER_UNAVAILABLE = "날씨 정보 준비중이에요."
NOTICE_RULE_FALLBACK = "질문을 키워드로 이해했어요. 조금 더 자세히 적어주시면 정확해져요."
# wants_alternative(2026-07-30) 감지 시 붙는 안내 — 상위 추천 대신 다른 곳을 보여줬음을 정직하게 알린다.
NOTICE_ALTERNATIVE_SPOTS = "앞서 소개한 곳 대신 다른 곳으로 골라봤어요."
# QA Major(2026-07-30) — 축제 콜드 스윕 타임아웃 전용 답변. "찾지 못했다"(0건 템플릿)와는
# 의미가 다르다(정보가 없는 게 아니라 아직 불러오는 중)라 문구를 분리했다.
TEMPLATE_FESTIVAL_LOADING = "축제 정보를 불러오는 중이에요. 잠시 후 다시 물어봐 주세요."
# N.10 결함2(2026-07-30) — 해외/미지원 지명 전용 답변. region_text 미해석(`build_region_
# unresolved_notice`, "『X』 지역은 아직 준비 중이에요…")과 **의도적으로 문구를 분리**했다
# (하나는 "국내인데 사전에 없음", 하나는 "애초에 해외라 지원 대상이 아님" — 원인이 다르다).
TEMPLATE_FOREIGN_PLACE = "해외 여행지는 아직 준비 중이에요. 국내 여행지를 물어봐 주세요."


# ============================================================================
# ① 지역 감지 — regions/seed 라벨·별칭 부분일치 (원천 호출 0)
# ============================================================================

_WS_RE = re.compile(r"\s+")


def _norm_spaced(s: str) -> str:
    """소문자 + 연속 공백 1칸으로 접기(공백은 **보존**)."""
    return _WS_RE.sub(" ", (s or "").lower()).strip()


# 2글자 별칭 중 일반 한국어 단어와 충돌해 오탐을 만드는 것들 — 단독 매칭 대상에서 제외한다.
# ("예산 5만원", "영양 간식", "장수 마을" 처럼 지역과 무관한 문맥에서 자주 나온다.)
# 제외해도 정식명("예산군", "충남 예산")은 별칭 목록에 그대로 있어 매칭된다.
_AMBIGUOUS_ALIASES: frozenset[str] = frozenset(
    {"예산", "영양", "장수", "고성", "청양", "중구", "동구", "서구", "남구", "북구", "성동"}
)
_MIN_ALIAS_CHARS = 2


def _region_candidates() -> list[tuple[RegionSeed, list[tuple[str, str]]]]:
    """(지역, [(공백보존형, 공백제거형)]) 매칭 후보. 모듈 로드 시 1회 구성."""
    out: list[tuple[RegionSeed, list[tuple[str, str]]]] = []
    for r in REGIONS:
        spaced = {_norm_spaced(r.label), *(_norm_spaced(a) for a in r.aliases)}
        usable = [
            (s, s.replace(" ", ""))
            for s in spaced
            if len(s.replace(" ", "")) >= _MIN_ALIAS_CHARS
            and s.replace(" ", "") not in _AMBIGUOUS_ALIASES
        ]
        if usable:
            out.append((r, usable))
    return out


_REGION_INDEX: list[tuple[RegionSeed, list[tuple[str, str]]]] = _region_candidates()


def detect_region(question: str) -> tuple[RegionSeed | None, bool]:
    """질문에서 지역을 감지한다. 반환 (지역|None, 다중매치 여부).

    매칭 규칙(어절 경계를 넘는 오탐 차단):
      - 여러 어절로 된 별칭("부산 해운대")은 **공백 보존 질문 전체**와 대조하고,
      - 한 어절 별칭("전주")은 **어절의 맨 앞에서만** 찾는다(`tok.startswith`).
    이렇게 하지 않고 질문의 공백을 지워 매칭하면 "서울에서 산책" → "서산"(충남 서산시)처럼
    어절 경계를 넘는 유령 매치가 생긴다(실측으로 확인한 오탐).

    2026-08-01(대표 지적 "충청도 실내 데이트 물었더니 경북을 찾아준다") — 종전엔 한 어절
    별칭을 `nospace in tok` 으로 **어절 안 아무 위치에서나** 찾았다. 그래서 "충청도"라는 어절
    안의 "청도"가 경상북도 **청도군**으로 매칭됐다. 한국어는 조사가 뒤에 붙지 앞에 붙지 않으므로
    ("청도에서"·"청도는"은 있어도 "충청도"의 청도는 지명이 아니다) **접두 일치**로 좁힌다.
    이러면 "충청도" ⊅ 시작 "청도" → 오매칭이 사라지고, "부산은"·"전주에서" 같은 정상 표현은
    그대로 잡힌다.

    랭킹: (1) 더 긴 별칭이 매칭된 지역 우선 — "전주 한옥마을"이 "전주"보다 구체적,
          (2) 동률이면 seed 순서(데모 4지역 → 수기 추가 → 전국 자동).
    질문에 지역어가 없으면 (None, False).

    다중매치 판정은 "서로 다른 지역어가 실제로 두 개 이상 언급됐는가"로 본다.
    "서울"처럼 한 별칭이 여러 시군구에 공통으로 걸리는 경우(종로구·중구…)나 "부산 해운대"처럼
    채택된 별칭의 부분문자열로 걸린 경우는 다중매치가 아니다 — 사용자는 한 곳만 말했다.
    """
    q = _norm_spaced(injection_guard.normalize_unicode(question or ""))
    if not q:
        return None, False
    tokens = q.split(" ")

    hits: list[tuple[int, int, RegionSeed, str]] = []
    for order, (region, targets) in enumerate(_REGION_INDEX):
        matched = [
            nospace for spaced, nospace in targets
            if (" " in spaced and spaced in q) or any(tok.startswith(nospace) for tok in tokens)
        ]
        if matched:
            best = max(matched, key=len)
            hits.append((-len(best), order, region, best))

    if not hits:
        return None, False
    hits.sort(key=lambda h: (h[0], h[1]))
    top_alias = hits[0][3]
    multi = any(
        alias not in top_alias and top_alias not in alias for *_ignored, alias in hits
    )
    return hits[0][2], multi


# ---------------------------------------------------------------------------
# 부록 N.12(2026-08-01, 대표 지적) — 도(道) 단위 질문은 **그 도 전역**에서 찾는다
#
# N.11 에서 "충청도" 같은 도 표현을 인식하게 만들었지만, 결과는 랭킹 1위 시군구 한 곳
# (충청북도 청주시)뿐이었다. 대표 지적: *"충청도는 충남 충북 다 있고 그 안에 도시가 얼마나
# 많은데 왜 청주로만 하냐."* 맞는 말이다 — 도 단위로 물으면 도 단위로 답해야 한다.
#
# 다만 충청도는 시군구 30곳, 경상도는 45곳이다. 전부 훑으면 혼잡도 board 원천 호출이
# 질문 1건당 수십 건이 되어 쿼터를 태운다(2026-07-29 실사고와 같은 경로). 그래서
# **스팟이 많은 상위 6곳**만 병렬로 훑고 결과를 합친다. 어느 6곳인지는 결정적이라 캐시가 듣고,
# 답변 문구가 "충청도 6개 시·군에서"라고 **범위를 밝히므로** 도 전체를 뒤졌다고 속이지 않는다.
PROVINCE_SWEEP_MAX = 6
_PROVINCE_INDEX: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    (label, tuple(_norm_spaced(a) for a in aliases), areas)
    for label, aliases, areas in PROVINCE_GROUPS
]


def detect_region_alias(question: str) -> str | None:
    """detect_region 이 채택한 **별칭 문자열**만 돌려준다(랭킹 규칙 동일).

    도 모드 판정에 쓴다 — "충청도"로 걸린 건지, "천안"처럼 더 구체적인 지역어로 걸린 건지를
    별칭 길이로 구분하기 위해서다. `detect_region` 의 시그니처를 바꾸면 기존 호출부가 전부
    영향을 받으므로 별도 함수로 둔다(랭킹 로직은 아래 detect_region 과 같은 것을 쓴다).
    """
    q = _norm_spaced(injection_guard.normalize_unicode(question or ""))
    if not q:
        return None
    tokens = q.split(" ")
    hits: list[tuple[int, int, str]] = []
    for order, (_region, targets) in enumerate(_REGION_INDEX):
        matched = [
            nospace for spaced, nospace in targets
            if (" " in spaced and spaced in q) or any(tok.startswith(nospace) for tok in tokens)
        ]
        if matched:
            best = max(matched, key=len)
            hits.append((-len(best), order, best))
    if not hits:
        return None
    hits.sort(key=lambda h: (h[0], h[1]))
    return hits[0][2]


def detect_province(question: str) -> tuple[str, tuple[str, ...], str] | None:
    """질문에서 도 단위 표현을 감지한다 → (라벨, 시도코드들, 매칭된 별칭). 없으면 None.

    매칭 규칙은 detect_region 과 동일한 **어절 접두 일치**다(같은 오탐 방어를 공유한다).
    """
    q = _norm_spaced(injection_guard.normalize_unicode(question or ""))
    if not q:
        return None
    tokens = q.split(" ")
    best: tuple[str, tuple[str, ...], str] | None = None
    for label, aliases, areas in _PROVINCE_INDEX:
        for alias in aliases:
            if any(tok.startswith(alias) for tok in tokens):
                if best is None or len(alias) > len(best[2]):
                    best = (label, areas, alias)
    return best


def province_targets(area_cds: tuple[str, ...], spot_repo: SpotRepository) -> list[str]:
    """도에 속한 시군구 중 **스팟이 많은 순 상위 PROVINCE_SWEEP_MAX 곳**(결정적).

    스팟이 실제로 쌓인 시군구여야 추천이 나온다. 동수면 코드순으로 고정한다.
    """
    codes = [r.region_id for r in REGIONS if r.area_cd in area_cds]
    codes.sort(key=lambda rc: (-len(spot_repo.by_region(rc, None)), rc))
    return codes[:PROVINCE_SWEEP_MAX]


def _region_name(region_code: str) -> str | None:
    return next((r.label for r in REGIONS if r.region_id == region_code), None)


# ============================================================================
# ② 날씨 질문 감지 — 단순 정규식(외부 호출 0). 감지 시 rerank.weather 를 켠다.
# ============================================================================

# "비"는 1글자라 "커피/준비/나비"에 걸리므로 반드시 뒤 어미와 함께 본다.
_WEATHER_PATTERNS = [
    re.compile(p)
    for p in [
        r"비\s*(가|는|도)?\s*(오|와|온|올|내리|그치)",
        r"비\s*오는",
        r"우천",
        r"장마",
        r"소나기",
        r"빗속",
        r"눈\s*(이)?\s*(오|와|내리)",
        r"날씨",
        r"흐린",
        r"궂은",
        r"우산",
        r"실내",
    ]
]


def is_weather_question(question: str) -> bool:
    text = injection_guard.normalize_unicode(question or "")
    return any(p.search(text) for p in _WEATHER_PATTERNS)


# ============================================================================
# ②-a2 해외/미지원 지명 감지(N.10 결함2, 2026-07-30) — 정적 목록 부분일치(외부 호출 0).
# 걸리면 이해 LLM 호출까지 생략하고 조기에 "해외 준비중" 응답으로 확정한다.
#
# 배경: "몰디브 여행지 추천"처럼 지역 표현이 질문 뒤쪽에 없거나 문장 구조가 애매하면 이해
# LLM 이 region_text 를 아예 못 뽑을 때가 있다(비결정적). 그러면 기존 지역 결정 로직이
# "질문 감지 없음 + region_text 없음" 으로 보고 **기본 지역(DEFAULT_SIGUNGU_CD, 예: 부산)**
# 으로 조용히 떨어져 "몰디브 물었는데 부산 카페 추천"류 오답이 난다(대표 실측 지적,
# "몰디브에서 갈만한 곳"은 LLM 이 region_text="몰디브"를 잘 뽑아 이미 준비중으로 처리됐지만,
# "몰디브 여행지 추천"은 못 뽑아 오답으로 샜다). LLM 추출의 비결정성에 맡기지 않고, 자주
# 나올 해외/미지원 지명은 **정적 목록으로 결정론적으로** 먼저 확정한다.
#
# 스팟 이름 검색 구조(보완1, `_resolve_region_via_spot_name_search`)보다 **먼저** 검사한다 —
# "해운대 몰디브 카페"처럼 국내에 동명 스팟이 있어도 이 목록에 걸리면 그쪽으로 오구조되지
# 않고 항상 "해외 준비중"이 확정되게 하기 위함(대표 지시).
#
# 알려진 한계(문서화, 완벽 차단 아님): "어절 안 부분일치"라 지명이 포함된 국내 상호·메뉴명에서
# 오탐할 수 있다. 실측 확인된 오탐("부산에 파리바게트 어디 있어?" → 해외 안내, 2026-07-30)은
# 아래 _FOREIGN_FALSE_FRIENDS 예외 목록으로 차단한다 — 예외에 걸린 어절은 해외 지명 판정에서
# 제외된다(오케스트레이터 직접 수정). 새 오탐이 관측되면 이 목록에 추가할 것.
_FOREIGN_FALSE_FRIENDS: frozenset[str] = frozenset({
    "파리바게트", "파리바게뜨", "파리크라상", "파리공원",   # 파리
    "홍콩반점",                                             # 홍콩
    "하와이안",                                             # 하와이 (하와이안피자 등)
    "발리볼",                                               # 발리 (배구)
})

# QA 약식(2026-07-31) Major 1 반영: 한국어 일반 단어와 동음인 지명은 정적 목록에서 **뺀다**.
#   - "세부" → "세부 일정/세부사항/세부적인"과 충돌(실측 오탐: "여행 세부 일정 짜줘" 차단됨)
#   - "la"  → "LA갈비"는 물론 영문 어절(place 등)에도 부분일치로 걸림
# 뺀 지명은 이해 LLM 의 region_text → detect_region 실패 → "『X』 준비중" 경로가 처리한다
# (비결정적이지만, 오탐으로 정상 질문을 차단하는 것보다 놓치는 쪽이 낫다 — 정밀도 우선).
_FOREIGN_PLACE_NAMES: frozenset[str] = frozenset({
    "몰디브", "발리", "다낭", "나트랑", "보라카이", "방콕", "푸켓",
    "도쿄", "오사카", "교토", "후쿠오카", "오키나와", "삿포로",
    "상하이", "베이징", "홍콩", "마카오", "타이베이", "싱가포르",
    "하와이", "괌", "사이판",
    "파리", "런던", "로마", "바르셀로나", "프라하",
    "뉴욕", "엘에이",
})


def is_foreign_place_question(question: str) -> bool:
    """질문에 해외/미지원 지명이 있는지 감지. `detect_region`과 **같은 정규화**(유니코드
    정규화 + 소문자 + 공백 정리) 후 **어절 안에서 부분일치**한다(N.3 ② 한 어절 별칭 매칭과
    동일 규칙 — 어절 경계 밖 유령 매치는 막되, 어절 안 부분일치는 허용).
    """
    q = _norm_spaced(injection_guard.normalize_unicode(question or ""))
    if not q:
        return False
    tokens = q.split(" ")
    for tok in tokens:
        # "파리바게트" 같은 국내 상호가 든 어절은 통째로 제외(실측 오탐 방지).
        if any(ff in tok for ff in _FOREIGN_FALSE_FRIENDS):
            continue
        if any(name in tok for name in _FOREIGN_PLACE_NAMES):
            return True
    return False


# ============================================================================
# ②-b 축제 질문 감지 — 키워드 부분일치(외부 호출 0). 감지 시 스팟 추천 대신 축제 목록을 준다.
# ============================================================================

_FESTIVAL_KEYWORDS = ("축제", "페스티벌")

# QA Minor 4(2026-07-30): "축제 말고 조용한 곳" 처럼 축제를 **배제**하는 질문까지 위 부분일치에
# 걸려 축제 모드로 오라우팅됐다(스팟이 필요한데 스팟 추천을 건너뜀). "축제/페스티벌" 바로 뒤에
# 배제 조사·어미(말고/빼고/외/제외)가 오면 축제 의도가 아니라고 먼저 판정한다.
_FESTIVAL_NEGATION_RE = re.compile(r"(축제|페스티벌)\s*(는|은)?\s*(말고|빼고|외에?|제외)")


def is_festival_question(question: str) -> bool:
    """축제 의도 감지 — 정규화 후 "축제"/"페스티벌" **부분일치**(배제형은 먼저 False 처리).

    부분일치라 "불꽃축제", "벚꽃 축제", "머드페스티벌", "축제요?" 같은 합성·활용형이 별도
    패턴 없이 모두 걸린다(두 단어가 축제 도메인에서 사실상 유일한 표현이라 오탐이 거의 없다).

    "행사"는 **일부러 제외**한다: 사내 행사·기념 행사·행사장 대관처럼 관광 축제와 무관한
    문맥에서 더 자주 쓰여, 스팟 추천이 필요한 질문을 축제 모드로 잘못 보낼 위험이 크다.
    축제 모드는 스팟 추천을 아예 건너뛰므로(오탐 = 빈 결과) 재현율보다 정밀도를 택했다.

    "축제 말고/빼고/외/제외"처럼 배제형이면 축제 모드로 보내지 않는다(QA Minor 4) — 그 경우
    스팟 모드로 흘러 wants_alternative() 가 "다른 곳" 취향으로 자연스럽게 이어받는다.
    """
    text = injection_guard.normalize_unicode(question or "")
    if _FESTIVAL_NEGATION_RE.search(text):
        return False
    return any(k in text for k in _FESTIVAL_KEYWORDS)


# ============================================================================
# ②-c 요청 방식 감지(2026-07-30, 대표 실사용 대응) — LLM 추가 호출 0, 순수 룰.
# "여러 개 보여줘"/"다른 곳 없어?" 같은 **요청 방식**은 취향 태그(온보딩 축)가 아니라 답변
# 문장을 어떻게 조립할지에 대한 지시라 별도 규칙으로 감지한다.
# ============================================================================

_WANTS_MULTIPLE_PATTERNS = [
    re.compile(p)
    for p in [
        r"여러",                 # "여러 곳", "여러 군데"
        r"몇\s*[개곳]",           # "몇 개", "몇곳"
        r"[2-9]\s*[개곳]",        # "2개", "3 곳" ~ "9개"(10개 이상은 드물어 스코프 밖)
        r"다양",                 # "다양하게"
        r"목록",                 # "목록으로"
        r"리스트",                # "리스트로"
    ]
]


def wants_multiple(question: str) -> bool:
    """질문이 "여러 곳/몇 개/다양하게" 처럼 **복수 추천**을 원하는지 감지(부분일치).

    오탐 위험: "여러"는 "여러분"(호칭)에도 걸리지만, 이 서비스 질문 맥락상 "손님 여러분께"
    같은 문장이 나올 일이 거의 없어 실사용 위험이 낮다고 판단했다(오탐 시 최악의 결과가
    "스팟을 하나 대신 5개 나열"이라 사용자 손해가 아니라 오히려 방어적 방향).
    """
    text = injection_guard.normalize_unicode(question or "")
    return any(p.search(text) for p in _WANTS_MULTIPLE_PATTERNS)


_WANTS_ALTERNATIVE_PATTERNS = [
    re.compile(p)
    for p in [
        r"다른\s*(데|곳)",   # "다른 데", "다른 곳"
        r"말고",             # "이거 말고"
        r"또\s*있",          # "또 있어?"
        r"새로운\s*곳",       # "새로운 곳"
        r"또\s*추천",         # "또 추천해줘"
    ]
]


def wants_alternative(question: str) -> bool:
    """질문이 "다른 곳/말고/또 있어?" 처럼 **앞서 봤을 법한 상위 추천 대신 다른 곳**을 원하는지 감지.

    오탐 주의: "말고"는 "축제 말고 조용한 곳"처럼 **카테고리 배제**(is_festival_question 의
    부정형 라우팅, QA Minor 4)에도 쓰인다. 두 감지는 서로 배타적이지 않게 뒀다 — "축제 말고"는
    (a) 축제 모드를 끄고 스팟 모드로 보내고(is_festival_question=False), (b) 동시에 이 함수도
    True 가 되어 "이전과 다른 곳"으로 해석된다. 이 서비스는 무상태(캐시 없음)라 "이전에 보여준
    곳"이 실제로 없으므로, 이 경우 True 는 상위 1~3위 대신 다양한 곳을 보여주는 효과만 내고
    사용자에게 해가 되지 않는다(오탐이어도 결과가 더 나빠지지 않는 방향으로 설계).
    """
    text = injection_guard.normalize_unicode(question or "")
    return any(p.search(text) for p in _WANTS_ALTERNATIVE_PATTERNS)


# ============================================================================
# ③ 답변 데이터 블록 조립 / 템플릿 폴백 (둘 다 enum 라벨 + 서버 데이터만 사용)
# ============================================================================

def _safe_text(raw: str | None, max_chars: int) -> str:
    """외부 문자열 정제: 유니코드 정규화(제로폭/전각 우회 완화) + 개행류 제거 + 길이 절단.

    2026-07-30: \\t/\\x0b/\\x0c/유니코드 줄·문단 구분자(U+2028/U+2029)도 injection_guard의
    strip_line_breaking_chars 를 재사용해 공백으로 치환한다(QA Minor — 기존엔 \\n/\\r만 걸렀다).
    """
    cleaned = injection_guard.normalize_unicode(raw or "")
    cleaned = injection_guard.strip_line_breaking_chars(cleaned)
    cleaned = cleaned.replace("\n", " ").replace("\r", " ").strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned


# "미언급"(congestion_pref:unspecified)은 사용자가 말한 취향이 아니라 서버가 채운 기본값이라
# 답변·템플릿 문구에서 제외한다(넣으면 모델이 "무관한 취향" 같은 엉뚱한 문장을 만든다).
_SKIP_TAGS: frozenset[tuple[str, str]] = frozenset({("congestion_pref", "unspecified")})


def _tag_labels(result: OnboardingResult, axes: tuple[str, ...], limit: int | None = None) -> list[str]:
    """추출 태그 → 한국어 라벨 목록. registry 라벨만 쓴다(모델이 지어낸 문자열 미사용)."""
    labels: list[str] = []
    for axis in axes:
        for tv in result.tags.get(axis, []):
            if (axis, tv.value) in _SKIP_TAGS:
                continue
            label = tag_registry.label_for(axis, tv.value)
            if label and label not in labels:
                labels.append(label)
    if limit is not None:
        return labels[:limit]
    return labels


def _weighted_sample_without_replacement(pool: list, k: int) -> list:
    """순위 가중 비복원추출. 앞쪽(고순위) 원소가 더 자주 뽑히되 매번 같은 조합은 아니다.

    가중치는 `len(pool) - i`(1등이 가장 크고 선형 감소) — 점수 하위를 끌어올리는 게 아니라
    "이미 상위권으로 추려진 pool" 안에서만 순서를 흔든다(정직·품질 보호는 호출부가 pool 을
    좁혀서 보장한다).
    """
    items = list(pool)
    weights = [len(items) - i for i in range(len(items))]
    chosen: list = []
    for _ in range(min(k, len(items))):
        total = sum(weights)
        r = random.uniform(0, total)
        upto = 0.0
        for idx, w in enumerate(weights):
            upto += w
            if upto >= r:
                chosen.append(items.pop(idx))
                weights.pop(idx)
                break
    return chosen


def _select_answer_spots(
    spots: list[SpotCard], multi: bool, alternative: bool
) -> tuple[list[SpotCard], bool]:
    """답변 데이터 블록 "상위 추천"에 넣을 스팟 선택.

    **spots(카드 목록 응답 배열)의 점수순 정렬은 절대 바꾸지 않는다** — 여기서 고르는 건
    "답변 문장이 언급할 부분집합"일 뿐이고, 반환값은 새 리스트다(원본 미변형).

    반환 (선택된 스팟, listed_top_n) — listed_top_n=True 면 "상위 N곳을 그대로 나열"(wants_multiple
    기본 동작 — 점수 순서를 왜곡하지 않고 폭만 넓힌다). False 면 무작위 표본(기본 다양화 또는 alt).
    """
    if alternative:
        pool = spots[_ALT_SPOT_EXCLUDE_TOP:_ALT_SPOT_POOL]
        if not pool:  # 스팟이 3곳 이하라 대안이 없음 — 빈 데이터 대신 기존 상위를 그대로 쓴다.
            return spots[:_ANSWER_SPOT_COUNT], False
        k = _ANSWER_SPOT_COUNT_MULTIPLE if multi else _ANSWER_SPOT_COUNT
        return _weighted_sample_without_replacement(pool, min(k, len(pool))), False

    if multi:
        # "여러 곳" 요청은 순위를 흔들지 않고 폭만 넓힌다(사용자가 원하는 건 다양성이지 무작위성이 아니다).
        return spots[:_ANSWER_SPOT_COUNT_MULTIPLE], True

    pool = spots[:_ANSWER_SPOT_POOL]
    return _weighted_sample_without_replacement(pool, min(_ANSWER_SPOT_COUNT, len(pool))), False


def build_answer_data(
    result: OnboardingResult,
    region_name: str | None,
    spots: list[SpotCard],
    weather_line: str | None,
    multi: bool = False,
    alternative: bool = False,
) -> str:
    """LLM 에 넘길 <travel_data> 본문. **사용자 질문 원문은 절대 포함하지 않는다.**

    multi/alternative(2026-07-30, N.9): wants_multiple()/wants_alternative() 감지 결과.
    기본값 False 로 둬 기존 호출부(있다면)와 하위호환된다.
    """
    lines: list[str] = []
    region = _safe_text(region_name, _MAX_REGION_CHARS)
    lines.append(f"지역: {region}" if region else "지역: 미지정")

    # 라벨 문구 주의: "손님이 말한 조건"이라고 명시해야 모델이 이를 **장소의 시설**로 오해해
    # "휠체어 접근이 가능한 곳이에요" 처럼 데이터에 없는 사실을 단정하지 않는다(실측 교정).
    labels = _tag_labels(result, _ANSWER_AXES)
    lines.append(
        f"손님이 말한 조건: {', '.join(labels)}" if labels else "손님이 말한 조건: 특별한 조건 없음"
    )

    if weather_line:
        lines.append(f"날씨: {weather_line}")

    if spots:
        lines.append(f"찾은 장소 수: {len(spots)}곳")
        if multi:
            lines.append("손님 요청: 여러 곳을 알고 싶어함")
        chosen, _listed_top_n = _select_answer_spots(spots, multi, alternative)
        lines.append("상위 추천:")
        for i, s in enumerate(chosen):
            name = _safe_text(s.name, _MAX_NAME_CHARS)
            cat = _CATEGORY_LABEL.get(s.category, "장소")
            level = s.congestion.level if s.congestion is not None else "unknown"
            lines.append(f"{i + 1}. {name} ({cat}, 혼잡도 {_CONGESTION_LABEL.get(level, '정보 없음')})")
    else:
        lines.append("찾은 장소 수: 0곳")
    return "\n".join(lines)


def build_template_answer(
    result: OnboardingResult,
    region_name: str | None,
    spot_count: int,
    multi: bool = False,
) -> str:
    """LLM 없이 만드는 폴백 답변. registry 라벨 + 서버 지역명 + 개수만 쓴다(지어내지 않음).

    multi(2026-07-30, N.9): wants_multiple() 감지 시 둘째 문장을 "목록에서 골라보세요" 톤으로
    바꾼다. 기존 문구도 이미 "목록에서 확인해 보세요"라 뜻은 유사하지만, 여러 곳을 명시적으로
    원한 질문에는 "골라보세요"가 더 정직한 표현이라 분기했다.
    """
    labels = _tag_labels(result, _TEMPLATE_AXES, _TEMPLATE_MAX_LABELS)
    taste = ", ".join(labels) if labels else "말씀해주신 조건"
    place = _safe_text(region_name, _MAX_REGION_CHARS) or "선택하신 지역"

    # 조사(을/를) 오류를 피하려고 지역명 뒤에는 받침과 무관한 "에서"·"의"만 붙인다.
    if spot_count <= 0:
        return (
            f"{taste} 조건으로 {place}에서 찾아봤는데 지금은 보여드릴 곳이 없어요. "
            "지역이나 조건을 바꿔서 다시 물어봐 주세요."
        )
    tail = "아래 목록에서 골라보세요." if multi else "혼잡도가 낮은 곳을 먼저 보여드렸으니 목록에서 확인해 보세요."
    return f"{taste} 취향에 맞춰 {place}의 장소 {spot_count}곳을 찾았어요. {tail}"


# ---------- 축제 모드용 (위 두 함수와 같은 규약: 질문 원문 미포함, 서버 데이터만) ----------

def _fmt_period(start: str | None, end: str | None) -> str | None:
    """'2026-07-25','2026-08-03' → '7.25~8.3'. 형식이 아니면 None(지어내지 않음)."""

    def md(s: str | None) -> str | None:
        if not isinstance(s, str) or len(s) != 10 or s[4] != "-" or s[7] != "-":
            return None
        if not (s[:4].isdigit() and s[5:7].isdigit() and s[8:].isdigit()):
            return None
        return f"{int(s[5:7])}.{int(s[8:])}"

    a, b = md(start), md(end)
    return f"{a}~{b}" if a and b else None


def _select_answer_festivals(festivals: list[Festival], multi: bool, alternative: bool) -> list[Festival]:
    """답변 데이터 블록 "상위 축제"에 넣을 축제 선택. `_select_answer_spots` 와 동일 규약 —
    festivals(응답 배열, 이미 진행중·종료임박 우선 정렬돼 최대 6건으로 슬라이스돼 들어온다)의
    순서는 건드리지 않는다. 반환값만 새 부분집합이다.
    """
    if alternative:
        pool = festivals[_ANSWER_FESTIVAL_COUNT:]
        if not pool:  # 축제가 3건 이하라 대안이 없음 — 기존 상위 그대로 쓴다.
            return festivals[:_ANSWER_FESTIVAL_COUNT]
        k = _ANSWER_FESTIVAL_COUNT_MULTIPLE if multi else _ANSWER_FESTIVAL_COUNT
        return _weighted_sample_without_replacement(pool, min(k, len(pool)))
    if multi:
        return festivals[:_ANSWER_FESTIVAL_COUNT_MULTIPLE]
    return festivals[:_ANSWER_FESTIVAL_COUNT]


def build_festival_answer_data(
    result: OnboardingResult,
    region_name: str | None,
    festivals: list[Festival],
    multi: bool = False,
    alternative: bool = False,
) -> str:
    """축제 모드 <travel_data> 본문. build_answer_data 와 동일 규약 — **질문 원문 미포함**.

    프롬프트는 CONCIERGE_FESTIVAL_SYSTEM_PROMPT(N.9 전용 변형)를 쓴다 — 호출부(summarizer.
    answer_concierge(..., festival=True))가 선택한다. "데이터에 있는 것만, 2문장, 단정 금지"
    규칙은 스팟 모드와 동일하되 첫 문장 형태만 축제용으로 고정돼 있다(summarizer.py 참고).
    다만 모델이 축제를 '장소'로 부르지 않도록 라벨 문구를 "찾은 축제 수 / 상위 축제"로 둔다.

    multi/alternative(2026-07-30, N.9): wants_multiple()/wants_alternative() 감지 결과.
    """
    lines: list[str] = []
    region = _safe_text(region_name, _MAX_REGION_CHARS)
    lines.append(f"지역: {region}" if region else "지역: 미지정")

    labels = _tag_labels(result, _ANSWER_AXES)
    lines.append(
        f"손님이 말한 조건: {', '.join(labels)}" if labels else "손님이 말한 조건: 특별한 조건 없음"
    )

    lines.append(f"찾은 축제 수: {len(festivals)}건")
    if festivals:
        if multi:
            lines.append("손님 요청: 여러 곳을 알고 싶어함")
        chosen = _select_answer_festivals(festivals, multi, alternative)
        lines.append("상위 축제:")
        for i, f in enumerate(chosen):
            title = _safe_text(f.title, _MAX_NAME_CHARS)
            status = "진행중" if f.ongoing else "예정"
            period = _fmt_period(f.start_date, f.end_date)
            detail = f"기간 {period}, {status}" if period else status
            lines.append(f"{i + 1}. {title} ({detail})")
    return "\n".join(lines)


def build_festival_template_answer(
    result: OnboardingResult,
    region_name: str | None,
    festival_count: int,
    multi: bool = False,
) -> str:
    """축제 모드 폴백 답변. registry 라벨 + 서버 지역명 + 개수만 쓴다(지어내지 않음)."""
    labels = _tag_labels(result, _TEMPLATE_AXES, _TEMPLATE_MAX_LABELS)
    taste = ", ".join(labels) if labels else "말씀해주신 조건"
    place = _safe_text(region_name, _MAX_REGION_CHARS) or "전국"

    if festival_count <= 0:
        return (
            f"{place}에서 지금 진행 중이거나 예정된 축제 정보를 찾지 못했어요. "
            "다른 지역이나 전국 축제 페이지를 확인해 보세요."
        )
    tail = "아래 목록에서 골라보세요." if multi else "아래 목록에서 기간을 확인해 보세요."
    return (
        f"{taste} 조건으로 {place}의 진행 중이거나 예정된 축제 {festival_count}건을 찾았어요. "
        f"{tail}"
    )


# ============================================================================
# 인젝션 의심 입력용 프로바이더 — LLM 을 태우지 않고 룰 폴백을 유도(온보딩 라우터와 동일 패턴)
# ============================================================================

class _GuardTrippedProvider(LLMProvider):
    async def extract_tags(self, free_text: str, chips: list[str] | None = None):  # noqa: ANN201
        raise LLMExtractionError("injection suspected — LLM skipped by concierge guard")

    async def extract_concierge_understanding(self, free_text: str):  # noqa: ANN201
        # 명시적으로 override 한다(부록 N.10) — LLMProvider 기본 구현도 동일하게 raise 하지만,
        # "인젝션 의심 시 이해 LLM 도 0회"라는 계약(N.5-2)을 이 클래스만 봐도 알 수 있게 한다.
        raise LLMExtractionError("injection suspected — LLM skipped by concierge guard")


_GUARD_TRIPPED_PROVIDER = _GuardTrippedProvider()


def _drain_background_festival_task(task: asyncio.Task) -> None:
    """축제 조회 타임아웃 후에도 asyncio.shield 로 계속 도는 백그라운드 스윕의 결과/예외를 소비한다.

    이 요청은 이미 템플릿으로 응답을 끝냈으므로 결과를 쓰지 않는다 — 여기서 하는 일은
    `task.exception()` 을 한 번 읽어 "Task exception was never retrieved" 경고를 막는 것뿐이다
    (재전파하지 않는다. 실패해도 다음 요청이 캐시 미스로 재시도한다).
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.info("concierge 백그라운드 축제 스윕 실패(무시, 다음 요청이 재시도): %s", exc)


def build_region_unresolved_notice(region_hint: str) -> str:
    """부록 N.10 §2 — LLM이 감지했지만 사전(REGIONS)엔 없는 지역 표현("몰디브" 등) 전용 안내.

    `region_hint`는 호출부가 이미 `_safe_text`로 정제한 값을 받는다(이 함수는 정제하지 않음).
    기본 지역(부산 등)으로 조용히 폴백하지 않고, 있지도 않은 지역 추천을 지어내지 않는다는
    정직 원칙을 지킨다 — "천안 물었는데 부산 추천"류 오답의 구조적 재발 방지가 목적이다.
    """
    place = region_hint or "말씀하신"
    return f"『{place}』 지역은 아직 준비 중이에요. 다른 지역으로 물어봐 주세요."


def build_region_search_notice(region_hint: str) -> str:
    """부록 N.10 보완1 — region_text 가 REGIONS 사전엔 없지만 스팟 이름 검색으로 지역을
    찾았을 때("제부도" → 화성시 등, 관광지 이름 단위 지역 표현) 붙는 안내."""
    place = region_hint or "말씀하신 곳"
    return f"『{place}』 주변 지역 기준으로 찾아봤어요."


def _resolve_region_via_spot_name_search(region_hint: str, spot_repo: SpotRepository) -> str | None:
    """부록 N.10 보완1 — region_text 가 시군구 사전(REGIONS)엔 없을 때, **관광지 이름**일
    가능성을 마지막으로 확인한다("제부도"는 시군구가 아니라 화성시 소재 관광지라 detect_region
    이 못 찾는다 — 대표 실측 지적).

    `search_service.build_search_response`를 **직접 호출**한다(HTTP 왕복 없음 — 같은 프로세스
    안의 순수 함수, 원천/LLM 호출 0, 인메모리 이름 인덱스 조회뿐). 상위 1건이 있으면 그 스팟의
    `region_code`를 채택하고, 없으면 None(호출부가 기존 "준비 중" 안내로 폴백).
    """
    if not region_hint:
        return None
    resp = search_service.build_search_response(region_hint, None, 1, spot_repo)
    if not resp.items:
        return None
    # QA 약식(2026-07-31) Minor 3 — 매칭 품질 하한: 스팟 이름이 힌트로 **시작**할 때만 지역
    # 근거로 채택한다("제부도" → "제부도 갯벌체험장" OK). 이름 중간 부분일치("바다" → "OO바다
    # 횟집")까지 허용하면 LLM 이 지역이 아닌 일반어를 region_text 로 흘렸을 때 무관한 지역이
    # 조용히 확정된다.
    top_name = _norm_spaced(resp.items[0].name).replace(" ", "")
    hint_norm = _norm_spaced(region_hint).replace(" ", "")
    if not top_name.startswith(hint_norm):
        return None
    return resp.items[0].region_code


# ============================================================================
# 진입점
# ============================================================================

async def build_concierge_answer(
    question: str,
    region_code: str | None,
    llm_provider: LLMProvider,
    summarizer: Summarizer | None,
    spot_repo: SpotRepository,
    congestion_repo: CongestionRepository,
    weather_provider: WeatherProvider | None,
    cache: Cache,
) -> ConciergeAskResponse:
    t0 = time.perf_counter()
    notices: list[str] = []

    # --- 인젝션 게이팅(온보딩 라우터와 동일): 탐지 시 이해·답변 LLM 을 모두 스킵 ---
    injection_hits = injection_guard.detect_injection_patterns(question)
    if injection_hits:
        # 원문은 로그에 남기지 않는다(패턴명·길이만).
        logger.warning(
            "concierge.ask injection 의심 → LLM 스킵(이해·답변 모두), 룰 폴백 강등 "
            "patterns=%s input_len=%d",
            injection_hits, len(question),
        )
        provider: LLMProvider = _GUARD_TRIPPED_PROVIDER
    else:
        provider = llm_provider

    # --- 해외/미지원 지명 조기 확정(N.10 결함2) — 이해 LLM 호출 전에 정적 목록으로 먼저
    # 판정한다(LLM region_text 의 비결정성에 맡기지 않는다). 걸리면 이해 LLM 도 호출하지
    # 않고(비용 절감 + 결정론적 응답) 여기서 응답을 자체 조립해 조기 반환한다 — tags 는
    # 추출하지 않았으므로 빈 dict(스키마 기본값과 동일, 정직: "해석 안 함"을 있는 그대로 표시).
    if is_foreign_place_question(question):
        logger.info(
            "concierge.ask 해외 지명 감지 → 이해 LLM 스킵, 준비중 응답 확정 input_len=%d",
            len(question),
        )
        return ConciergeAskResponse(
            answer=TEMPLATE_FOREIGN_PLACE,
            extracted=ConciergeExtracted(tags={}, region=None),
            spots=[],
            festivals=[],
            meta=ConciergeMeta(
                notice=None,
                answer_source="template",
                # 정규식만으로 저비용 판정(이해 LLM 미호출) — 축제 카드 vs 스팟 카드 어느
                # 쪽으로 렌더할지 프론트에 정직하게 알려준다(둘 다 빈 배열이라 위험은 없다).
                intent="festivals" if is_festival_question(question) else "spots",
            ),
        )

    # --- ① 조건 해석 (부록 N.10, 2026-07-30: LLM-first 통합 이해로 전환) ---
    # extract_onboarding_tags 를 직접 부르는 대신 extract_concierge_understanding 을 부른다 —
    # LLM 호출 수는 그대로 1회(①을 **대체**할 뿐 추가가 아니다). 인젝션 의심·실패 시 내부에서
    # 온보딩과 동일한 키워드 룰 폴백으로 떨어지고, intent/region_text/wants_* 는 중립값을
    # 반환해 아래 기존 정규식 규칙이 그대로 최종 판단을 내린다(N.9 동작으로 완전히 회귀 — 무회귀).
    understanding: ConciergeUnderstanding = await extract_concierge_understanding(question, provider)
    result = understanding.result
    t_extract = time.perf_counter()

    if result.fallback_used:
        notices.append(NOTICE_RULE_FALLBACK)

    # --- ②-b 요청 방식 감지(2026-07-30, N.9/N.10) ---
    # want_multi 는 기존 정규식 OR LLM 힌트: 규칙이 감지 못해도 LLM 힌트가 살리고, LLM 이
    # 실패해도(중립값) 규칙이 그대로 동작한다.
    want_multi = wants_multiple(question) or understanding.wants_multiple
    # want_alt 는 **정규식 단독**(N.10 보완2, 대표 실측 오탐 수정 — OR→AND 요청 반영):
    # "천안 축제 뭐 있어?" 에서 정규식은 전혀 매치가 없는데("또 있"/"말고"/"다른 곳" 전부
    # 불일치) LLM 힌트만으로 alternative 가 True 가 돼 "앞서 소개한 곳 대신…" notice 가 잘못
    # 붙었다(원인 확인: 정규식이 아니라 LLM 쪽 — 프롬프트 예시 "또 있어?"의 "있어" 표면형에
    # 끌려 "뭐 있어?"류 존재 질의를 alternative 로 오분류하는 것으로 추정).
    # 결론적으로 alternative 판정은 **정규식 단독**이다(QA 약식 2026-07-31 Minor 1 반영 —
    # `regex AND (regex OR llm)` 은 대수적으로 regex 와 동치라 표현만 단순화했다).
    # understanding.wants_alternative 는 현재 판정에 기여하지 않는 진단용 힌트로만 남는다:
    # LLM 단독 True 경로는 "뭐 있어?"류 존재 질의 오분류가 실측돼 구조적으로 제거했고,
    # 향후 더 정교한 모델로 바꿔 재활성화할 때도 반드시 정규식 게이트와 함께 켤 것.
    want_alt = wants_alternative(question)

    # --- ② 지역 결정: ①질문 사전 매칭 > ②LLM region_text 사전 재검증 > ③요청 region_code >
    # ④기본 지역. 축제 모드만 예외: 단서가 전혀 없으면 기본 지역을 지어 붙이지 않고
    # **전국**(None)으로 둔다(축제는 전국 목록이 자연스러운 답이고, 안 물어본 지역을 답으로
    # 내미는 게 더 부정직하다).
    #
    # N.10 §2: "축제 말고"류 부정형은 LLM intent 가 뭐라고 하든 **최우선으로 축제 모드를 끈다**
    # (is_festival_question 자체가 부정형이면 내부적으로 False 를 반환하므로, 여기서는 그
    # 부정형 판정을 다시 계산해 LLM-OR 분기에서도 같은 우선순위를 지킨다).
    festival_negated = bool(_FESTIVAL_NEGATION_RE.search(injection_guard.normalize_unicode(question or "")))
    festival_mode = is_festival_question(question) or (
        understanding.intent == "festivals" and not festival_negated
    )

    detected, region_multi = detect_region(question)
    region_text_unresolved = False
    region_hint = ""
    search_resolved_code: str | None = None
    if detected is None and understanding.region_text:
        # N.10 §2: LLM 이 옮겨적은 지역 표현도 **같은 detect_region() 으로 재검증**한다 — 힌트를
        # 그대로 신뢰하지 않는다. 사전 매칭에 성공하면 질문에서 직접 감지한 것과 동일하게 취급.
        llm_detected, llm_region_multi = detect_region(understanding.region_text)
        if llm_detected is not None:
            detected, region_multi = llm_detected, llm_region_multi
        else:
            # N.10 보완1(대표 실측 지적 "제부도"): 시군구 사전엔 없지만 **관광지 이름**일 수
            # 있다 — 준비중 안내로 가기 전에 스팟 이름 검색으로 한 번 더 구제한다(HTTP 왕복 없이
            # search_service 를 직접 호출, 원천/LLM 호출 0).
            region_hint = _safe_text(understanding.region_text, _MAX_REGION_CHARS)
            search_resolved_code = _resolve_region_via_spot_name_search(region_hint, spot_repo)
            if search_resolved_code is None:
                region_text_unresolved = True

    param_code = region_code.strip() if region_code and region_code.strip().isdigit() else None
    resolved_code: str | None

    if search_resolved_code is not None:
        # 관광지 이름 검색으로 지역을 구제했다 — "『제부도』 주변 지역 기준으로 찾아봤어요."
        resolved_code = search_resolved_code
        notices.append(build_region_search_notice(region_hint))
    elif region_text_unresolved:
        # LLM 이 지역 표현을 감지했지만 사전(REGIONS)에도 스팟 이름 검색에도 없다("몰디브" 등)
        # — 기본 지역(부산 등)으로 조용히 떨어지면 "천안 물었는데 부산 추천"류 오답의 재발이다.
        # 정직하게 준비중 안내로 답한다(스팟 모드는 답변 LLM 도 부르지 않는다 — 있지도 않은
        # 지역 정보를 지어낼 근거가 없다). 축제 모드는 N.9 원칙(단서 없으면 전국)을 그대로
        # 따라 계속 진행한다.
        unresolved_notice = build_region_unresolved_notice(region_hint)
        if not festival_mode:
            # QA 약식(2026-07-31) Minor 2: 같은 문구를 answer 와 notice 에 이중 노출하지 않는다
            # — 이 조기 반환 경로에서는 answer 가 안내문 그 자체라 notice 는 나머지(폴백 안내
            # 등)만 담는다.
            t_answer = time.perf_counter()
            logger.info(
                "concierge.ask intent=spots region=unresolved_llm_hint answer=template "
                "extract=%.2fs total=%.2fs",
                t_extract - t0, t_answer - t0,
            )
            return ConciergeAskResponse(
                answer=unresolved_notice,
                extracted=ConciergeExtracted(tags=result.tags, region=None),
                spots=[],
                meta=ConciergeMeta(
                    notice=" ".join(dict.fromkeys(notices)) or None,
                    answer_source="template",
                ),
            )
        notices.append(unresolved_notice)  # 축제 모드는 계속 진행하므로 notice 로 알린다
        resolved_code = None  # 축제 모드: 전국 목록으로 계속 진행(N.9 원칙과 동일)
    elif detected is not None:
        resolved_code = detected.region_id
        if region_multi:
            notices.append(NOTICE_MULTI_REGION)
    elif festival_mode:
        resolved_code = param_code
        if resolved_code is None:
            notices.append(NOTICE_NO_REGION)
    elif param_code:
        resolved_code = param_code
        notices.append(NOTICE_NO_REGION)
    else:
        resolved_code = settings.default_sigungu_cd
        notices.append(NOTICE_NO_REGION)
    resolved_name = _region_name(resolved_code) if resolved_code else None

    # --- 부록 N.12: 도 단위 질문이면 그 도의 여러 시·군을 훑는다 ---
    # 조건: 도 표현이 감지됐고, **그보다 더 구체적인 지역 지정이 없을 때**만.
    #   - "충청도 실내 데이트"        → 도 모드(여러 시·군)
    #   - "충청도 천안 실내 데이트"    → 천안이 더 구체적 → 도 모드 아님(종전대로 천안)
    #   - region_code 파라미터가 왔으면(지역 화면에서 넘어온 문맥) 그쪽을 존중한다.
    province_codes: list[str] = []
    province_label: str | None = None
    if not festival_mode and search_resolved_code is None and not region_text_unresolved:
        prov = detect_province(question)
        if prov is not None and detected is not None:
            label, area_cds, alias = prov
            # detected 가 도 별칭 자체로 걸린 경우에만 도 모드로 간다. 더 긴(=더 구체적인)
            # 지역어가 함께 있으면 사용자가 그 도시를 콕 집은 것이다.
            _region_alias = detect_region_alias(question)
            if _region_alias is not None and len(_region_alias) <= len(alias):
                province_codes = province_targets(area_cds, spot_repo)
                if len(province_codes) > 1:
                    province_label = label
                    resolved_code = province_codes[0]
                    resolved_name = label

    # --- ③-a 축제 모드: 추천 파이프라인을 **타지 않고** 캐시된 축제 목록을 쓴다 ---
    if festival_mode:
        # QA Major(2026-07-30): 콜드 캐시(전국 스윕 미스)면 build_festivals_response 가 원천
        # 2개를 페이지네이션하며 수 초~십수 초가 걸릴 수 있어 사용자 요청을 붙잡는다.
        # asyncio.shield 로 감싸 wait_for 타임아웃이 스윕 자체를 취소하지 않게 한다 — 백그라운드
        # 에서 계속 돌아 캐시를 채우고(다음 요청은 캐시 히트), 이 요청은 즉시 템플릿으로 응답한다.
        festival_fetch_timeout = settings.concierge_festival_fetch_timeout_sec
        fest_task: asyncio.Task = asyncio.ensure_future(
            festival_service.build_festivals_response(
                region_code=resolved_code,
                limit=_FESTIVAL_FETCH_LIMIT,
                cache=cache,
            )
        )
        fetch_timed_out = False
        fest_total = 0  # 필터 통과 전체 건수(limit 절삭 전) — N.10 보완2 alt-notice 가드용
        try:
            fest_res = await asyncio.wait_for(asyncio.shield(fest_task), timeout=festival_fetch_timeout)
            # festival_service 정렬(진행중·종료임박 우선)을 그대로 신뢰한다 — 재정렬 금지.
            festivals = fest_res.festivals[:_FESTIVAL_RESULT_COUNT]
            fest_total = fest_res.total
        except (TimeoutError, asyncio.TimeoutError):
            logger.info(
                "concierge 축제 조회 타임아웃(%.1fs, 콜드 스윕 추정) → 템플릿 답변, festivals=[] "
                "(스윕은 백그라운드에서 계속 돼 다음 요청은 캐시 히트)",
                festival_fetch_timeout,
            )
            festivals = []
            fetch_timed_out = True
            fest_task.add_done_callback(_drain_background_festival_task)
        except Exception:  # noqa: BLE001 — QA 약식(2026-07-31) Major 2: 축제 조회 실패가
            # HTTP 500 이 되면 안 된다(스팟 모드의 답변 LLM 실패 처리와 방어 수준을 맞춘다).
            # 캐시 계층 장애·원천 파서 예외 등 무엇이든 graceful 하게 "불러오는 중" 템플릿으로.
            logger.exception("concierge 축제 조회 실패(비타임아웃) → 템플릿 답변, festivals=[]")
            festivals = []
            fetch_timed_out = True
        t_fetch = time.perf_counter()

        if fetch_timed_out:
            # 없는 축제를 지어내지 않는 원칙과 별개로, "찾지 못했다"가 아니라 "아직 불러오는
            # 중"이라는 게 정직한 상태라 전용 템플릿을 쓴다(축제 0건 템플릿과 문구를 분리).
            answer = TEMPLATE_FESTIVAL_LOADING
            answer_source = "template"
        else:
            # 축제 0건이면 LLM 을 부르지 않는다(스팟 0곳과 동일 원칙 — 없는 축제를 지어내지 않게).
            answer = None
            if (
                festivals
                and summarizer is not None
                and settings.concierge_answer_enabled
                and not injection_hits
            ):
                data_text = build_festival_answer_data(
                    result, resolved_name, festivals, want_multi, want_alt
                )
                try:
                    answer = await summarizer.answer_concierge(data_text, festival=True)
                except Exception as exc:  # noqa: BLE001 — 답변 실패가 축제 목록을 막지 않는다
                    logger.info("concierge 축제 답변 LLM 실패 → 템플릿 폴백: %s", exc)
                    answer = None
            answer_source = "llm" if answer else "template"
            if not answer:
                answer = build_festival_template_answer(result, resolved_name, len(festivals), want_multi)
            # N.10 보완2: 필터 통과 전체 건수가 이미 화면 표시 상한(_FESTIVAL_RESULT_COUNT) 이하면
            # 카드 목록에 전부 노출돼 "숨겨진 다른 곳"이 없다 — 이럴 때 notice 를 붙이면
            # "앞서 소개한 곳 대신…"이라 해놓고 사실 전부 같은 목록이라 오해를 준다(대표 실측 지적).
            if want_alt and festivals and fest_total > _FESTIVAL_RESULT_COUNT:
                notices.append(NOTICE_ALTERNATIVE_SPOTS)
        t_answer = time.perf_counter()

        logger.info(
            "concierge.ask intent=festivals region=%s festivals=%d answer=%s timed_out=%s "
            "extract=%.2fs festival_fetch=%.2fs answer_gen=%.2fs total=%.2fs",
            resolved_code or "nationwide", len(festivals), answer_source, fetch_timed_out,
            t_extract - t0, t_fetch - t_extract, t_answer - t_fetch, t_answer - t0,
        )

        return ConciergeAskResponse(
            answer=answer,
            extracted=ConciergeExtracted(
                tags=result.tags,
                region=(
                    ConciergeRegion(region_code=resolved_code, region_name=resolved_name)
                    if resolved_code
                    else None
                ),
            ),
            spots=[],
            festivals=festivals,
            meta=ConciergeMeta(
                notice=" ".join(dict.fromkeys(notices)) or None,
                answer_source=answer_source,  # type: ignore[arg-type]
                intent="festivals",
            ),
        )

    # 축제 모드는 위에서 반환됐다 → 여기부터 스팟 모드는 지역이 반드시 문자열이다(no-op 안전장치).
    resolved_code = resolved_code or settings.default_sigungu_cd

    # --- ③ 추천 실행 (기존 파이프라인. 프로필은 프론트와 동일한 ProfileInput 형태로 넘긴다) ---
    weather_q = is_weather_question(question)
    profile = ProfileInput(
        tag_vector=result.tag_vector,
        vector_version=result.vector_version,
        scoring_weights=result.scoring_weights,
        tags={axis: [tv.model_dump() for tv in values] for axis, values in result.tags.items()},
    )
    async def _recommend(code: str | None):
        return await recommend_service.build_recommend_response(
            region_code=code,
            profile=profile,
            category=None,
            sort="personalized",
            limit=settings.concierge_spot_limit,
            spot_repo=spot_repo,
            congestion_repo=congestion_repo,
            # balance 는 항상 켠다(혼잡 분산이 이 서비스의 정체성). weather 는 날씨 질문일 때만.
            rerank=RerankInput(balance=True, weather=weather_q),
            weather_provider=weather_provider,
            spot_type="all",
        )

    rec = await _recommend(resolved_code)
    t_recommend = time.perf_counter()

    spots = rec.items

    # --- 부록 N.12: 도 모드 — 나머지 시·군도 병렬로 훑어 합친다 ---
    if province_codes and len(province_codes) > 1:
        others = await asyncio.gather(
            *[_recommend(c) for c in province_codes[1:]], return_exceptions=True
        )
        merged = list(spots)
        for code, res in zip(province_codes[1:], others):
            if isinstance(res, BaseException):
                logger.info("concierge 도 모드 지역 %s 예외(건너뜀): %s", code, res)
                continue
            merged.extend(res.items)
        # 한 도시가 목록을 독점하지 않게 시·군당 상한을 둔다(도 단위로 물었으니 다양성이 정보다).
        per_city = max(1, -(-settings.concierge_spot_limit // len(province_codes)))
        counts: dict[str, int] = {}
        picked = []
        for card in sorted(
            merged, key=lambda c: (-(c.match_score or 0.0), c.name)
        ):
            rc = card.region_code
            if counts.get(rc, 0) >= per_city:
                continue
            counts[rc] = counts.get(rc, 0) + 1
            picked.append(card)
            if len(picked) >= settings.concierge_spot_limit:
                break
        spots = picked
        covered = len(counts)
        notices.append(
            f"{province_label} 안에서 스팟이 많은 {len(province_codes)}개 시·군을 살펴봤어요"
            f"(추천에는 {covered}곳이 담겼어요)."
        )
    if rec.meta.notice:
        notices.append(rec.meta.notice)

    # 날씨 질문일 때만 날씨를 다룬다. 답변 문장에 넣는 것은 **비 예보가 실제로 있을 때만**이다:
    # 강수확률이 낮은 날(band=clear)까지 프롬프트에 넣으면 "비 오는 날 실내" 질문에 대해
    # "날씨가 좋으니 야외에서" 처럼 질문 전제와 어긋나는 답이 나온다(실측). 수치는 meta.notice 로
    # 정직하게 알리고, 생성 문장에는 개입시키지 않는다.
    weather_line: str | None = None
    if weather_q:
        wx = getattr(rec, "rerank", None)
        wx = wx.weather if wx is not None else None
        if wx is not None and wx.provider_status == "ok" and wx.precip_probability is not None:
            pop = wx.precip_probability
            notices.append(f"오늘 이 지역 강수확률은 {pop}%로 예보돼 있어요.")
            if wx.band in ("soft", "advise_indoor"):
                weather_line = f"오늘 강수확률 {pop}%"
        else:
            notices.append(NOTICE_WEATHER_UNAVAILABLE)

    # --- ④ 답변 생성: 로컬 LLM → 실패 시 템플릿 폴백(answer 는 null 이 될 수 없다) ---
    # 스팟이 0곳이면 LLM 을 부르지 않는다 — 근거 데이터가 없는데 생성시키면 "이런 곳에서
    # 커피 한 잔 하세요" 처럼 존재하지 않는 장소를 암시하는 답이 나온다(실측). 템플릿이 정직하다.
    answer: str | None = None
    if spots and summarizer is not None and settings.concierge_answer_enabled and not injection_hits:
        data_text = build_answer_data(result, resolved_name, spots, weather_line, want_multi, want_alt)
        try:
            answer = await summarizer.answer_concierge(data_text)
        except Exception as exc:  # noqa: BLE001 — 답변 실패가 추천 결과를 막지 않는다
            logger.info("concierge 답변 LLM 실패 → 템플릿 폴백: %s", exc)
            answer = None
    answer_source = "llm" if answer else "template"
    if not answer:
        answer = build_template_answer(result, resolved_name, len(spots), want_multi)
    # N.10 보완2와 동일 로직을 스팟 모드에도 대칭 적용: 대안 후보 풀(_ALT_SPOT_EXCLUDE_TOP 초과분)
    # 이 아예 없으면 "다른 곳"을 실제로 보여준 게 아니므로 notice 를 붙이지 않는다.
    if want_alt and len(spots) > _ALT_SPOT_EXCLUDE_TOP:
        notices.append(NOTICE_ALTERNATIVE_SPOTS)
    t_answer = time.perf_counter()

    logger.info(
        "concierge.ask intent=spots region=%s spots=%d weather_q=%s answer=%s "
        "extract=%.2fs recommend=%.2fs answer_gen=%.2fs total=%.2fs",
        resolved_code, len(spots), weather_q, answer_source,
        t_extract - t0, t_recommend - t_extract, t_answer - t_recommend, t_answer - t0,
    )

    return ConciergeAskResponse(
        answer=answer,
        extracted=ConciergeExtracted(
            tags=result.tags,
            region=ConciergeRegion(region_code=resolved_code, region_name=resolved_name),
        ),
        spots=spots,
        meta=ConciergeMeta(
            notice=" ".join(dict.fromkeys(notices)) or None,  # 중복 제거, 없으면 null
            answer_source=answer_source,  # type: ignore[arg-type]
        ),
    )
