/**
 * `/regions` 지역 허브 — 17개 시도 상수 맵 (03-design-spec.md §29 근거).
 *
 * 신규 backend 0을 지키기 위해 시도별 "대표 시군구(region_code)"를 상수로 고정한다. 코드값은
 * 전부 backend/app/regions/seed.py(법정동 코드)가 이미 검증해 쓰고 있는 값 또는
 * backend/app/spots/data/spots_seed.json의 region_meta/region_counts에 실제 스팟이 잡혀 있는
 * 값만 채택했다(지어낸 코드 없음). 대구·광주·대전·울산·충북은 seed.py의 수기 큐레이션(_DEMO/_EXTRA)
 * 밖이라 region_meta에서 스팟 카운트가 0보다 큰 시군구를 직접 확인해 골랐다(§29 표 참고).
 * 인천은 seed.py의 _EXTRA가 "인천 중구"(28110)를 쓰지만 region_counts상 스팟 0건이라
 * 대신 "인천 연수구"(28185, 87건)를 대표로 삼았다 — 코드 자체는 여전히 실재하는 법정동 코드다.
 */
export interface SidoRegion {
  /** 법정동 시도 2자리 코드(backend app/regions/seed.py _SIDO_SHORT와 동일 체계). */
  sidoCode: string;
  /** 짧은 시도명 — backend _SIDO_SHORT 표기와 1:1(프론트가 새로 지어내지 않음). */
  shortName: string;
  /** 원형 배지에 쓰는 이니셜(짧은 시도명의 첫 글자, 이모지 아님). */
  initial: string;
  /** 이 시도를 대표해서 조회하는 시군구 코드(sigungu_cd) — fetchFeatured 등 region_code 인자. */
  regionCode: string;
  /** 대표 시군구 전체 명칭 — "이 지역은 사실 ○○ 기준"이라는 정직 캡션에 쓴다(지어내지 않음). */
  representativeLabel: string;
}

/** 지시서 순서(서울→전북, area_cd 오름차순)를 그대로 따른다. */
export const SIDO_REGIONS: SidoRegion[] = [
  { sidoCode: "11", shortName: "서울", initial: "서", regionCode: "11110", representativeLabel: "서울특별시 종로구" },
  { sidoCode: "26", shortName: "부산", initial: "부", regionCode: "26350", representativeLabel: "부산광역시 해운대구" },
  { sidoCode: "27", shortName: "대구", initial: "대", regionCode: "27110", representativeLabel: "대구광역시 중구" },
  { sidoCode: "28", shortName: "인천", initial: "인", regionCode: "28185", representativeLabel: "인천광역시 연수구" },
  { sidoCode: "29", shortName: "광주", initial: "광", regionCode: "29110", representativeLabel: "광주광역시 동구" },
  { sidoCode: "30", shortName: "대전", initial: "대", regionCode: "30110", representativeLabel: "대전광역시 동구" },
  { sidoCode: "31", shortName: "울산", initial: "울", regionCode: "31110", representativeLabel: "울산광역시 중구" },
  { sidoCode: "36", shortName: "세종", initial: "세", regionCode: "36110", representativeLabel: "세종특별자치시" },
  { sidoCode: "41", shortName: "경기", initial: "경", regionCode: "41111", representativeLabel: "경기도 수원시 장안구" },
  { sidoCode: "43", shortName: "충북", initial: "충", regionCode: "43111", representativeLabel: "충청북도 청주시 상당구" },
  { sidoCode: "44", shortName: "충남", initial: "충", regionCode: "44150", representativeLabel: "충청남도 공주시" },
  { sidoCode: "46", shortName: "전남", initial: "전", regionCode: "46130", representativeLabel: "전라남도 여수시" },
  { sidoCode: "47", shortName: "경북", initial: "경", regionCode: "47130", representativeLabel: "경상북도 경주시" },
  { sidoCode: "48", shortName: "경남", initial: "경", regionCode: "48220", representativeLabel: "경상남도 통영시" },
  { sidoCode: "50", shortName: "제주", initial: "제", regionCode: "50110", representativeLabel: "제주특별자치도 제주시" },
  { sidoCode: "51", shortName: "강원", initial: "강", regionCode: "51150", representativeLabel: "강원특별자치도 강릉시" },
  { sidoCode: "52", shortName: "전북", initial: "전", regionCode: "52111", representativeLabel: "전북특별자치도 전주시 완산구" },
];

/**
 * 기본 선택 — 지시서 "기본 선택: 부산(데모 대표)". 홈 전광판·recommend 기본 지역(26350, 해운대)과도
 * 동일해 "지역 전환은 사이트 전체와 일관되게" 원칙을 별도 하드코딩 없이 만족한다.
 */
export const DEFAULT_SIDO_CODE = "26";
