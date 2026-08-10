"""MVP-2 지역 사전 (정적 seed) + 전국 확장 로더.

계약 부록 A.2. 데모/추가 항목(_DEMO/_EXTRA)의 area_cd/sigungu_cd 는 backend 가 KTO 원천
API(tatsCnctrRatedList)를 **실호출**해 "혼잡도 데이터가 실제로 나오는" 조합만 채택했다.

코드 체계: 행정안전부 법정동 코드.
  - area_cd    = 시도 2자리
  - sigungu_cd = 시군구 5자리 (= region_id)
주의: 2023~2024 개편으로 강원=51(구 42), 전북=52(구 45) 신코드를 써야 데이터가 나온다.

전국 확장(2026-07-24, backend-engineer):
  - collector 가 TourAPI 스팟을 수집하며 item 의 표준 법정동 코드(lDong*)로부터 지역을
    도출해 spots_seed.json 의 region_meta 에 적재한다. 이 파일이 그 region_meta 를 읽어
    전국 시군구를 검색 사전에 자동 추가한다(스팟이 실제로 있는 지역 = 실데이터 기반).
  - 혼잡도는 전국 법정동 시군구를 커버함을 실호출로 확인(서울 종로/대구 중구/제주 등).
  - 중복(수기 _DEMO/_EXTRA 와 겹치는 region_id)은 수기 항목을 우선(별칭이 풍부).

상용 확장 시 이 파일을 DB/공식 법정동 코드셋 로더로 교체한다
(RegionRepository 인터페이스 뒤에 있으므로 엔드포인트 계약은 불변).

검증 일자: 2026-07-24 (KTO tatsCnctrRatedList + TourAPI areaBasedList2 실호출).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("sumeungil.regions.seed")

_SEED_JSON = Path(__file__).resolve().parent.parent / "spots" / "data" / "spots_seed.json"


@dataclass(frozen=True)
class RegionSeed:
    area_cd: str
    sigungu_cd: str          # = region_id
    label: str               # 화면 표시용 full name
    aliases: tuple[str, ...] = field(default_factory=tuple)  # 검색 매칭용 별칭

    @property
    def region_id(self) -> str:
        return self.sigungu_cd


# --- 데모 필수 4지역 (반드시 동작) ---
_DEMO: list[RegionSeed] = [
    RegionSeed("26", "26350", "부산광역시 해운대구",
               ("해운대", "부산", "부산 해운대", "해운대구", "haeundae", "busan")),
    RegionSeed("47", "47130", "경상북도 경주시",
               ("경주", "경주시", "경북 경주", "gyeongju")),
    RegionSeed("51", "51150", "강원특별자치도 강릉시",
               ("강릉", "강릉시", "강원 강릉", "gangneung")),
    RegionSeed("52", "52111", "전북특별자치도 전주시 완산구",
               ("전주", "전주시", "전주 한옥마을", "한옥마을", "완산구", "전북 전주", "jeonju")),
]

# --- 데모 풍부화용 추가 지역 (모두 실호출 데이터 확인됨) ---
_EXTRA: list[RegionSeed] = [
    RegionSeed("11", "11110", "서울특별시 종로구",
               ("서울", "종로", "종로구", "seoul", "jongno")),
    RegionSeed("11", "11140", "서울특별시 중구",
               ("서울", "서울 중구", "명동", "myeongdong")),
    RegionSeed("50", "50110", "제주특별자치도 제주시",
               ("제주", "제주시", "jeju")),
    RegionSeed("50", "50130", "제주특별자치도 서귀포시",
               ("서귀포", "서귀포시", "제주 서귀포", "seogwipo")),
    RegionSeed("28", "28110", "인천광역시 중구",
               ("인천", "인천 중구", "차이나타운", "incheon")),
    RegionSeed("51", "51210", "강원특별자치도 속초시",
               ("속초", "속초시", "강원 속초", "sokcho")),
    RegionSeed("41", "41820", "경기도 가평군",
               ("가평", "가평군", "경기 가평", "gapyeong")),
    RegionSeed("41", "41111", "경기도 수원시 장안구",
               ("수원", "수원시", "장안구", "suwon")),
    RegionSeed("44", "44150", "충청남도 공주시",
               ("공주", "공주시", "충남 공주", "gongju")),
    RegionSeed("46", "46130", "전라남도 여수시",
               ("여수", "여수시", "전남 여수", "yeosu")),
    RegionSeed("48", "48220", "경상남도 통영시",
               ("통영", "통영시", "경남 통영", "tongyeong")),
    RegionSeed("48", "48125", "경상남도 창원시 마산합포구",
               ("창원", "마산", "마산합포구", "창원 마산", "changwon")),
    RegionSeed("52", "52130", "전북특별자치도 군산시",
               ("군산", "군산시", "전북 군산", "gunsan")),
    RegionSeed("52", "52190", "전북특별자치도 남원시",
               ("남원", "남원시", "전북 남원", "namwon")),
    # 세종: TourAPI area8 은 lDongRegnCd 에 5자리 완성코드(36110)를 담아 기존 2+3 조립
    # 로직에서 전량 스킵됐었다(0건). collector._legal_dong_code 5자리 분기로 보강해
    # 86스팟 확보(2026-07-24). region_code=법정동 36110, area_cd=36.
    RegionSeed("36", "36110", "세종특별자치시",
               ("세종", "세종시", "sejong")),
]

# 시도명 → 짧은 별칭 (검색용). 법정동 area_cd 2자리 기준.
_SIDO_SHORT: dict[str, str] = {
    "11": "서울", "26": "부산", "27": "대구", "28": "인천", "29": "광주",
    "30": "대전", "31": "울산", "36": "세종", "41": "경기", "43": "충북",
    "44": "충남", "45": "전북", "46": "전남", "47": "경북", "48": "경남",
    "50": "제주", "51": "강원", "52": "전북", "42": "강원",
}
# 시군구명 접미사 — 별칭에서 접미사 제거형도 매칭 대상에 넣는다(예: 해운대구 → 해운대).
_SUFFIXES = ("특별자치시", "특별자치도", "광역시", "특별시", "시", "군", "구")


# --- 부록 Y additive(2026-08-11): 시도(area_cd) 단위 조회용 공용 헬퍼 ---
# 지역 허브가 "시도 선택 → 그 시도 전체"로 바뀌면서 area_cd 를 받는 엔드포인트가 셋 생겼다
# (regions/children · places/featured · festivals). 형식 검증과 시도 표기를 **한 곳**에서
# 하도록 여기에 둔다 — 지역 코드 체계의 소유자가 이 모듈이기 때문이다.

def is_area_cd(value: str | None) -> bool:
    """시도코드(법정동 2자리 숫자) 형식인가. 실재 여부는 보지 않는다(형식 검사 전용)."""
    s = (value or "").strip()
    return len(s) == 2 and s.isdigit()


def sido_label(area_cd: str | None) -> str | None:
    """시도코드 → 짧은 표기(예: '41' → '경기'). 사전에 없으면 None(지어내지 않는다).

    검색 별칭이 쓰는 _SIDO_SHORT 를 그대로 재사용한다 — 화면 표기와 별칭이 갈리지 않게.
    """
    return _SIDO_SHORT.get((area_cd or "").strip())


def _strip_suffix(name: str) -> str:
    for suf in _SUFFIXES:
        if name.endswith(suf) and len(name) > len(suf):
            return name[: -len(suf)]
    return name


# 구(區)가 있는 시의 **도시 이름 단독 별칭** 중 일반 단어와 충돌하는 것 — 생성에서 제외한다.
# ("고양"은 "고양이"의 부분문자열이라 어절 내 부분일치 매칭에서 오탐을 만든다. 정식형
#  "고양시"/"경기 고양"은 그대로 생성되므로 지역 질문("고양시 갈만한 곳")은 여전히 매칭된다.)
_AMBIGUOUS_CITY_NAMES: frozenset[str] = frozenset({"고양"})


# 도(道) 단위 구어 표현 → 해당 시도 코드. 2026-08-01 대표 지적("충청도 실내 데이트")에서 나온
# 결함: 사전에는 "충남"·"충북"처럼 **줄임 시도명**만 있고 "충청도"·"전라도"·"경상도" 같은
# **도 단위 표현이 아예 없었다**. 그래서 질문이 매칭에 실패해 조용히 기본 지역(부산)으로 떨어졌다.
#
# 광역시는 넣지 않는다 — "경상도"에 부산·대구를 포함시키면 seed 순서상 부산이 먼저 걸려
# 종전의 잘못된 폴백과 구분이 안 된다. 도 표현은 **도에만** 붙여 결과가 실제 그 도가 되게 한다.
# (사용자가 "부산"을 원하면 "부산"이라고 말한다.)
# (표시 라벨, 별칭들, 이 도에 속한 시도코드들)
PROVINCE_GROUPS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("경기도", ("경기도",), ("41",)),
    ("충청도", ("충청도", "충청"), ("44", "43")),   # 충남 → 충북 순
    ("전라도", ("전라도", "전라"), ("46", "52")),   # 전남 → 전북 순
    ("경상도", ("경상도", "경상"), ("47", "48")),   # 경북 → 경남 순
    ("강원도", ("강원도",), ("51",)),
    ("제주도", ("제주도",), ("50",)),
)

_PROVINCE_ALIASES: dict[str, tuple[str, ...]] = {
    area: aliases for _label, aliases, areas in PROVINCE_GROUPS for area in areas
}


def _auto_aliases(area_cd: str, sido_name: str, sigungu_name: str, label: str) -> tuple[str, ...]:
    short = _SIDO_SHORT.get(area_cd, _strip_suffix(sido_name))
    base = _strip_suffix(sigungu_name)  # 해운대구 → 해운대
    cands = {
        sigungu_name, base, short,
        f"{short} {sigungu_name}", f"{short}{sigungu_name}",
        f"{short} {base}", label,
    }
    # 구가 있는 시("천안시 동남구")는 도시 이름("천안시"/"천안")도 별칭에 넣는다.
    # 이게 없으면 "천안 갈만한 곳" 같은 질문이 매칭 실패 → 기본 지역으로 오폴백된다
    # (대표 실사용 보고, 2026-07-30: 천안을 물었는데 부산을 추천).
    if " " in sigungu_name:
        city = sigungu_name.split(" ", 1)[0]          # "천안시"
        city_base = _strip_suffix(city)               # "천안"
        cands.update({city, f"{short} {city}", f"{short} {city_base}"})
        if city_base not in _AMBIGUOUS_CITY_NAMES:
            cands.add(city_base)
    # 도 단위 구어 표현("충청도" 등)은 그 도의 **모든 시군구**에 붙인다. 어느 시군구가 뽑힐지는
    # detect_region 의 기존 랭킹(별칭 길이 → seed 순서)이 결정하며 결과는 결정적이다.
    # 어차피 사용자가 도 단위로 물었으므로 그 도 안의 한 곳이면 답으로 성립하고, 답변 문구가
    # "충청남도 ○○시의 장소 8곳을 찾았어요"처럼 **실제 채택한 지역명을 밝히므로** 오해가 없다.
    cands.update(_PROVINCE_ALIASES.get(area_cd, ()))
    return tuple(a for a in cands if a)


def _load_nationwide(existing_ids: set[str]) -> list[RegionSeed]:
    """spots_seed.json 의 region_meta → 전국 RegionSeed. 수기 항목과 겹치면 스킵."""
    if not _SEED_JSON.exists():
        return []
    try:
        data = json.loads(_SEED_JSON.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        logger.warning("전국 지역 로드 실패(무시): %s", exc)
        return []

    meta = data.get("region_meta") or {}
    out: list[RegionSeed] = []
    for code, m in sorted(meta.items()):
        code = str(code).strip()
        if not code.isdigit() or len(code) != 5 or code in existing_ids:
            continue
        sido = str(m.get("sido_name", "")).strip()
        sigungu = str(m.get("sigungu_name", "")).strip()
        label = str(m.get("label", "")).strip() or f"{sido} {sigungu}".strip() or code
        area_cd = str(m.get("area_cd", code[:2])).strip()
        out.append(RegionSeed(area_cd, code, label,
                              _auto_aliases(area_cd, sido, sigungu, label)))
    logger.info("전국 지역 %d곳 검색 사전 추가", len(out))
    return out


# 정렬: 데모 4지역 → 추가 수기지역 → 전국 자동지역
_curated: list[RegionSeed] = _DEMO + _EXTRA
_curated_ids: set[str] = {r.region_id for r in _curated}
REGIONS: list[RegionSeed] = _curated + _load_nationwide(_curated_ids)
