/**
 * 대표 지시(2026-08-17) — "앞으로 모든 기본 화면의 기준 지역은 [사용자가] 마지막으로 고른
 * 지역을 기준으로 보여주자". 온보딩은 취향(동행/이동수단/분위기 등)만 다루고 지역을 받지
 * 않으므로(OnboardingAxis 참고), 온보딩이 아니라 사용자가 실제로 고른 지역 선택을 세션에
 * 기억해뒀다가 다음 화면·다음 방문의 기본값으로 쓴다. onboardingStorage.ts와 동일 패턴
 * (sessionStorage, 실패 시 조용히 무시 — 화면 흐름을 막지 않는다).
 */
import { RegionSearchItem } from "./api";

const STORAGE_KEY = "sumeungil:last-region:v1";

export function saveLastRegion(region: RegionSearchItem): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(region));
  } catch {
    // sessionStorage 비활성(시크릿 모드 등) — 조용히 무시.
  }
}

export function loadLastRegion(): RegionSearchItem | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (
      typeof parsed?.region_id === "string" &&
      typeof parsed?.label === "string" &&
      typeof parsed?.area_cd === "string" &&
      typeof parsed?.sigungu_cd === "string"
    ) {
      return parsed as RegionSearchItem;
    }
    return null;
  } catch {
    return null;
  }
}

export function clearLastRegion(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // 무시
  }
}
