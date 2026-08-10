/**
 * 전국 9권역(도 단위) 상수 — backend `app/regions/nationwide.py` REGION_BLOCKS 와 1:1 미러.
 *
 * 대표 지시(2026-07-31): "광역시까지 다 포함하라는 게 아니고 서울도 경기도로 포함시켜서
 * 전국 9도로." 즉 **광역시는 소속 도에 흡수**한다(서울·인천→경기, 대전·세종→충남,
 * 광주→전남, 대구→경북, 부산·울산→경남). 17개 시도 칩(SIDO_REGIONS)은 지역 탐색용으로
 * 그대로 두고, **날씨 보드·출발일 플래너처럼 "도 단위"가 맞는 화면만** 이 상수를 쓴다.
 *
 * region_code 는 각 권역의 대표 시군구(법정동 5자리)로, 백엔드 seed 에 실재하는 값이다 —
 * 프론트가 지어내지 않는다. 순서·key 는 백엔드와 동일하게 유지한다(변경 시 양쪽 함께).
 */
export interface RegionBlock {
  /** 백엔드 RegionBlock.key 와 동일(변경 금지). */
  key: string;
  /** 화면 표시용 권역명. */
  label: string;
  /** 이 권역을 대표하는 시군구 코드 — region_code 계약값으로 그대로 넘긴다. */
  regionCode: string;
}

export const REGION_BLOCKS: RegionBlock[] = [
  { key: "gyeonggi", label: "경기·서울", regionCode: "11110" },
  { key: "gangwon", label: "강원", regionCode: "51150" },
  { key: "chungbuk", label: "충북", regionCode: "43111" },
  { key: "chungnam", label: "충남·대전·세종", regionCode: "44150" },
  { key: "jeonbuk", label: "전북", regionCode: "52111" },
  { key: "jeonnam", label: "전남·광주", regionCode: "46130" },
  { key: "gyeongbuk", label: "경북·대구", regionCode: "47130" },
  { key: "gyeongnam", label: "경남·부산·울산", regionCode: "26350" },
  { key: "jeju", label: "제주", regionCode: "50110" },
];

export const DEFAULT_BLOCK_KEY = "gyeonggi";
