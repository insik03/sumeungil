"""데모 지역(법정동 sigungu_cd) → TourAPI 자체 지역코드 매핑.

**중요(실호출로 확정, 2026-07-24)**: TourAPI(KorService2)는 혼잡도 API(TatsCnctrRate)나
행정안전부 법정동 코드와 **다른 자체 areaCode/sigunguCode 체계**를 쓴다.
따라서 부록 A의 region_code(=법정동 sigungu_cd)를 그대로 TourAPI에 넘기면 0건이 나온다.
(KorService2의 lDongSignguCd 파라미터로 법정동 코드를 넣어봐도 totalCount=0 확인됨.)

아래 매핑은 backend가 `KorService2/areaCode2`를 실호출해 확정한 값이다:
  - 해운대구  법정동 26350 → TourAPI area=6(부산)   sigungu=16
  - 경주시    법정동 47130 → TourAPI area=35(경북)  sigungu=2
  - 강릉시    법정동 51150 → TourAPI area=32(강원)  sigungu=1
  - 전주시    법정동 52111 → TourAPI area=37(전북)  sigungu=12(전주시; TourAPI는 완산/덕진 미분리)

전국 확장(2026-07-24, backend-engineer):
  - KorService2/areaCode2 를 실호출해 전국 17개 시도·234개 시군구 TourAPI 코드+이름을
    확정하고 tourapi_area_index.json 에 적재(이 파일이 areaCode2 실호출 원본).
  - 법정동 코드는 '추측'하지 않는다. TourAPI areaBasedList2 응답 item 이 표준 법정동
    코드(lDongRegnCd 2자리 + lDongSignguCd 3자리)를 그대로 담고 있음을 실호출로 확인
    (예: 해운대 area6/sig16 → lDongRegnCd=26 lDongSignguCd=350 = 법정동 26350).
    따라서 collector 가 수집한 item 에서 법정동 코드를 '데이터로부터' 도출한다.
  - 주의: KorService2/ldongCode2 는 비표준 코드(전남+광주 병합 code=12, 세종=36110 등)를
    반환해 표준 법정동 소스로 쓰지 않는다. 진실원은 areaBasedList2 item 의 lDong* 필드다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
AREA_INDEX_PATH = DATA_DIR / "tourapi_area_index.json"


@dataclass(frozen=True)
class TourApiRegion:
    region_code: str        # 우리 내부 코드(= 법정동 sigungu_cd, 부록 A 체계)
    tour_area_code: str     # TourAPI areaCode
    tour_sigungu_code: str  # TourAPI sigunguCode
    region_name: str        # 표시용 full name


# 실호출 확정 매핑 (KorService2/areaCode2, 2026-07-24). 데모 4지역 — 계약·데이터 불변.
TOURAPI_REGIONS: dict[str, TourApiRegion] = {
    "26350": TourApiRegion("26350", "6", "16", "부산광역시 해운대구"),
    "47130": TourApiRegion("47130", "35", "2", "경상북도 경주시"),
    "51150": TourApiRegion("51150", "32", "1", "강원특별자치도 강릉시"),
    "52111": TourApiRegion("52111", "37", "12", "전북특별자치도 전주시"),
}

# 이미 수집·확정된 데모 4지역의 TourAPI (area, sigungu) — 전국 수집에서 재수집 제외(불변 보존).
_EXISTING_TOUR_PAIRS: set[tuple[str, str]] = {
    (r.tour_area_code, r.tour_sigungu_code) for r in TOURAPI_REGIONS.values()
}


# ---------------------------------------------------------------------------
# 전국 수집 타깃 (areaCode2 실호출 인덱스에서 생성)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CollectionTarget:
    tour_area_code: str
    tour_sigungu_code: str
    tour_area_name: str      # TourAPI 시도명 (예: 부산, 경기도)
    tour_sigungu_name: str   # TourAPI 시군구명 (예: 해운대구)
    tier: str                # "full"(5개 콘텐츠타입) | "lite"(대표 1개)


# 관광 수요가 높은 우선 지역(FULL 수집). (tour_area_code, tour_sigungu_name) 기준.
# 데모 4지역(해운대/경주/강릉/전주)은 _EXISTING_TOUR_PAIRS 로 자동 제외된다.
_PRIORITY: set[tuple[str, str]] = {
    ("1", "종로구"), ("1", "중구"), ("1", "마포구"), ("1", "강남구"),      # 서울
    ("2", "중구"), ("2", "연수구"), ("2", "강화군"),                       # 인천
    ("3", "중구"), ("3", "유성구"),                                        # 대전
    ("4", "중구"), ("4", "수성구"), ("4", "달성군"),                       # 대구
    ("5", "동구"), ("5", "서구"),                                          # 광주
    ("6", "중구"), ("6", "수영구"), ("6", "부산진구"), ("6", "기장군"),    # 부산
    ("7", "남구"), ("7", "울주군"),                                        # 울산
    ("8", "세종특별자치시"),                                               # 세종
    ("31", "수원시"), ("31", "가평군"), ("31", "파주시"), ("31", "용인시"),
    ("31", "고양시"), ("31", "포천시"),                                    # 경기
    ("32", "속초시"), ("32", "춘천시"), ("32", "평창군"), ("32", "양양군"),# 강원
    ("33", "청주시"), ("33", "충주시"), ("33", "단양군"),                  # 충북
    ("34", "공주시"), ("34", "부여군"), ("34", "태안군"), ("34", "보령시"),# 충남
    ("35", "안동시"), ("35", "포항시"), ("35", "문경시"),                  # 경북
    ("36", "통영시"), ("36", "창원시"), ("36", "거제시"), ("36", "진주시"),
    ("36", "남해군"),                                                      # 경남
    ("37", "군산시"), ("37", "남원시"), ("37", "부안군"),                  # 전북
    ("38", "여수시"), ("38", "순천시"), ("38", "목포시"), ("38", "담양군"),# 전남
    ("39", "제주시"), ("39", "서귀포시"),                                  # 제주
}


def _load_area_index() -> dict:
    if not AREA_INDEX_PATH.exists():
        return {}
    try:
        return json.loads(AREA_INDEX_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def collection_targets() -> list[CollectionTarget]:
    """areaCode2 실호출 인덱스 → 전국 수집 타깃. FULL(우선) 먼저, 그다음 LITE."""
    index = _load_area_index()
    full: list[CollectionTarget] = []
    lite: list[CollectionTarget] = []
    for area_code, meta in index.items():
        area_name = meta.get("sido_name", "")
        for sig in meta.get("sigungu", []):
            sig_code = str(sig.get("code", "")).strip()
            sig_name = str(sig.get("name", "")).strip()
            if not sig_code or not sig_name:
                continue
            if (area_code, sig_code) in _EXISTING_TOUR_PAIRS:
                continue  # 데모 4지역 보존 — 재수집 안 함
            tier = "full" if (area_code, sig_name) in _PRIORITY else "lite"
            tgt = CollectionTarget(area_code, sig_code, area_name, sig_name, tier)
            (full if tier == "full" else lite).append(tgt)
    return full + lite


def get_tourapi_region(region_code: str) -> TourApiRegion | None:
    return TOURAPI_REGIONS.get(region_code.strip())


def all_regions() -> list[TourApiRegion]:
    return list(TOURAPI_REGIONS.values())
