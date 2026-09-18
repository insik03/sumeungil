import { OnboardingResult, fetchMyOnboardingProfile } from "./api";
import { loadOnboardingResult, saveOnboardingResult } from "./onboardingStorage";

/**
 * 2026-09-18(대표: "취향 등록했는데 붐비는 곳 대신에서 취향 정보 없다고 뜬다") — 취향 프로필은 계정(서버,
 * /onboarding/me)에 저장되지만 추천·비교 화면은 이 탭의 sessionStorage 만 봤다. 재로그인(토큰 v2 전환)·
 * 로그아웃·새 탭이면 로컬이 비어 "취향 정보 없음"으로 보였다. CourseContent 가 이미 쓰던 "서버 우선 →
 * 로컬 폴백" 규칙을 한 곳으로 모은다. 서버 값은 로컬에도 넣어 다른 화면(홈 인사말 등)이 같이 본다.
 */
export async function resolveOnboardingProfile(loggedIn: boolean): Promise<OnboardingResult | null> {
  const local = loadOnboardingResult();
  if (local?.result) return local.result;
  if (!loggedIn) return null;
  try {
    const server = await fetchMyOnboardingProfile();
    if (server) saveOnboardingResult(server);
    return server;
  } catch {
    return null;
  }
}
