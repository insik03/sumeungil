/**
 * 지역 컨텍스트(region_code) URL 전파 유틸 — 03-design-spec.md §35(2026-07-31), 백로그 D21.
 *
 * 홈에서 고른 지역이 `/recommend`·`/course`·`/ask`로 이어지지 않고 끊기던 문제를 없애기 위해,
 * "링크에 붙이는 쪽"과 "쿼리를 읽는 쪽"이 같은 검증 규칙을 쓰도록 한 곳에 모았다.
 *
 * 검증 규칙: 법정동 시군구 코드(sigungu_cd)는 숫자 5자리다(components/regions/constants.ts의
 * SIDO_REGIONS·backend seed 모두 5자리). 형식이 다르면 값을 고쳐 쓰지 않고 그냥 무시한다 —
 * 지어낸 코드로 백엔드를 때리지 않기 위함이고, 소비하는 화면은 기존 기본 지역을 그대로 쓴다.
 */

/** sigungu_cd 형식(숫자 5자리). area_cd(2자리)는 이 쿼리로 전달하지 않는다. */
const REGION_CODE_PATTERN = /^\d{5}$/;

/**
 * 쿼리/외부 입력 문자열을 검증한다. 유효하면 정규화된 코드, 아니면 null.
 * (URL은 사용자가 손으로 고칠 수 있으므로 항상 이 함수를 거쳐서 쓴다.)
 */
export function readRegionCode(value: string | null | undefined): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return REGION_CODE_PATTERN.test(trimmed) ? trimmed : null;
}

/**
 * 링크 href에 region_code를 덧붙인다. 코드가 없거나 형식이 어긋나면 원래 href를 그대로 돌려준다
 * (지역 미선택 시 기존 동작 100% 유지). 이미 쿼리가 있는 href(`/ask?q=...`)면 `&`로 잇는다.
 */
export function withRegionCode(href: string, code: string | null | undefined): string {
  const valid = readRegionCode(code);
  if (!valid) return href;
  const separator = href.includes("?") ? "&" : "?";
  return `${href}${separator}region_code=${encodeURIComponent(valid)}`;
}
