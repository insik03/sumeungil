import { MatchSignal, SpotCategory } from "../../lib/api";
import { readRegionCode } from "../../lib/regionQuery";
import { SIDO_REGIONS } from "../regions/constants";

/**
 * 백엔드 기본 지역(backend/app/config.py DEFAULT_AREA_CD/DEFAULT_SIGUNGU_CD = "26"/"26350",
 * 부산광역시 해운대구)과 동일한 값을 프론트 기본 선택 지역으로 둔다.
 * 홈 전광판의 기본 지역과 같은 값이라 "지역 전환은 홈과 일관되게" 요구를 별도 하드코딩 없이 만족한다.
 */
export const DEFAULT_REGION = {
  areaCd: "26",
  sigunguCd: "26350",
  label: "부산광역시 해운대구",
};

/**
 * §30(03-design-spec.md, 2026-07-29) — "자주 찾는 지역" 칩을 데모 4개(경주·전주·강릉·부산)에서
 * 17개 시도 각 1곳으로 확장한다(대표 지시: "각 도마다 여행지 하나씩 추천에 떠야 한다"). 새 코드를
 * 지어내지 않고 components/regions/constants.ts의 검증된 SIDO_REGIONS(§29, Phase B 산출물)를
 * 그대로 매핑해 단일 소스를 유지한다. sigunguCd는 칩 클릭 시 /regions/search 없이 바로 선택하는
 * 데 쓰고(왕복이 4→17회로 느는 걸 막는다), label(대표 시군구 전체명)은 선택 후 상태문구에 정직
 * 캡션으로 쓴다. 이 상수는 recommend/RegionPicker.tsx와 festivals/FestivalRegionFilter.tsx가
 * 함께 쓴다 — 두 화면 모두 같은 17개 칩·같은 무왕복 선택 방식으로 맞춰야 해서다.
 */
export interface QuickRegionChip {
  /** 칩에 표시하는 짧은 시도명(예: "부산"). "부산 해운대"처럼 구 단위 대표지를 붙이지 않는다 —
   *  대구 중구/광주 동구처럼 대표지가 "구"인 시도는 문자열을 잘라 "중"/"동" 같은 검증 안 된
   *  한 글자 애칭을 만들게 돼 오히려 부정확하다(코드 지어내기 금지 원칙과 같은 이유). 전체 대표
   *  명칭은 title 툴팁·선택 후 상태문구로 별도 노출한다. */
  name: string;
  /** 검증된 대표 시군구 코드(SIDO_REGIONS.regionCode) — 검색 API 없이 바로 선택. */
  sigunguCd: string;
  /** 대표 시군구 전체 명칭 — 선택 후 상태문구("OO 추천을 보고 있어요")·title 툴팁에 쓴다. */
  label: string;
}

export const QUICK_REGIONS: QuickRegionChip[] = SIDO_REGIONS.map((sido) => ({
  name: sido.shortName,
  sigunguCd: sido.regionCode,
  label: sido.representativeLabel,
}));

/**
 * §35(2026-07-31, 03-design-spec.md — 지역 컨텍스트 전파/백로그 D21) — 칩 17개 밖의 코드(홈
 * 검색창에서 고른 임의 시군구 등)는 프론트에 이름이 없다. 지명을 지어내지 않고 이 중립 라벨을
 * 쓰고, 실제 지역명은 백엔드 응답의 region.region_name으로 화면 제목에 표시된다.
 */
export const UNKNOWN_REGION_LABEL = "선택한 지역";

/**
 * §35 — URL `?region_code=` 값을 지역 선택 상태로 변환한다. 형식(숫자 5자리)이 어긋나면 null을
 * 돌려주고, 호출부는 기존 기본 지역(DEFAULT_REGION)을 그대로 쓴다 — 잘못된 쿼리로 기존 동작이
 * 바뀌지 않게 하기 위함. 라벨은 QUICK_REGIONS(검증된 17개)에 있으면 그 값을, 없으면 중립 라벨.
 * 반환 형태는 RegionPicker의 SelectedRegion과 구조가 동일하다(타입 순환 참조를 피하려고 여기서
 * 다시 선언하지 않는다).
 */
export function regionSelectionFromCode(
  code: string | null | undefined
): { sigunguCd: string; label: string } | null {
  const valid = readRegionCode(code);
  if (!valid) return null;
  const known = QUICK_REGIONS.find((r) => r.sigunguCd === valid);
  return { sigunguCd: valid, label: known?.label ?? UNKNOWN_REGION_LABEL };
}

/**
 * §C.2.1 category enum — 축·값을 내려주는 스키마 엔드포인트가 계약에 없어(tag-schema류 부재)
 * 계약이 명시한 8개 값만 그대로 상수화했다(임의 카테고리 추가 금지).
 */
export const CATEGORY_META: { value: SpotCategory; label: string }[] = [
  { value: "attraction", label: "관광지" },
  { value: "restaurant", label: "음식점" },
  { value: "cafe", label: "카페" },
  { value: "craft", label: "공방" },
  { value: "trail", label: "산책로" },
  { value: "nature", label: "자연경관" },
  { value: "market", label: "전통시장" },
  { value: "etc", label: "그 외" },
];

/** §C.2.2 signals enum → 한국어 매핑(프론트 소유, 계약이 값 자체를 고정). */
export const SIGNAL_LABEL: Record<MatchSignal, string> = {
  low_congestion: "혼잡도 낮음",
  hidden_gem: "붐비지 않는 숨은 곳",
  high_profile_fit: "취향에 잘 맞음",
  theme_match: "원하는 테마 충족",
  near: "가까움",
};

/**
 * 유형 필터(신규) — is_hidden_gem 기준 all/hidden/popular. backend `spot_type` 파라미터와 1:1.
 * 필터링은 backend가 수행한다 — 프론트는 값을 그대로 전달만 하고 재판정하지 않는다.
 */
export type SpotTypeFilterValue = "all" | "hidden" | "popular";

export const SPOT_TYPE_META: { value: SpotTypeFilterValue; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "hidden", label: "숨은 명소" },
  { value: "popular", label: "인기 명소" },
];

/**
 * 정렬 옵션(신규). "distance"는 backend sort 값이 아니라 클라이언트 전용 옵션이다 —
 * 호출부(RecommendContent)가 backend에는 항상 "recommended"로 보내고, 응답을 받은 뒤
 * navigator.geolocation 좌표로 프론트가 재정렬한다(match_score·congestion 등 서버 값은 재판정하지 않음).
 * 별점순은 만들지 않는다(별점 데이터 없음, 지어내기 금지).
 */
export type SortOption = "recommended" | "popular" | "calm" | "distance";

export const SORT_META: { value: SortOption; label: string }[] = [
  { value: "recommended", label: "추천순" },
  { value: "popular", label: "인기순" },
  { value: "calm", label: "한적한 순" },
  { value: "distance", label: "거리순 (내 위치)" },
];
