/**
 * 01-interface-contract.md 부록 B §B.5-7 — MVP-3은 서버 저장이 없다.
 * OnboardingResult를 sessionStorage에만 임시 보관해 다음 단계(추천, MVP-5 이후)가 읽어 쓴다.
 * 서버 프로필 저장 엔드포인트는 계약 밖이므로 만들지 않는다.
 */
import { OnboardingResult } from "./api";

const STORAGE_KEY = "sumeungil:onboarding-result:v1";

export interface StoredOnboardingResult {
  result: OnboardingResult;
  savedAt: string; // ISO — 진단/표시용
  /** 2026-09-05 — 자유서술 원문. AI 코스짜기가 태그 대신 이 문장으로 후보 스팟을 고른다(wish). 칩만 골랐으면 없음. */
  text?: string;
  /**
   * 2026-09-20 — 이 문장을 코스 생성 때 Google(해외)로 전송하는 데 동의했는지. true 가 아니면 text 가 있어도
   * wish 로 쓰지 않는다(동의 도입 전 sessionStorage 에 남은 값이 동의 없이 나가지 않게).
   */
  textConsented?: boolean;
}

/** consented=true 일 때만 text 를 보관한다 — 동의 없는 자유 서술은 저장도 전송도 하지 않는다. */
export function saveOnboardingResult(result: OnboardingResult, text?: string | null, consented = false): void {
  if (typeof window === "undefined") return;
  try {
    const trimmed = consented ? (text ?? "").trim() : "";
    const payload: StoredOnboardingResult = {
      result,
      savedAt: new Date().toISOString(),
      ...(trimmed ? { text: trimmed, textConsented: true } : {}),
    };
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // sessionStorage 비활성(시크릿 모드 등) — 조용히 무시. 화면 흐름을 막지 않는다.
  }
}

export function loadOnboardingResult(): StoredOnboardingResult | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as StoredOnboardingResult;
  } catch {
    return null;
  }
}

export function clearOnboardingResult(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // 무시
  }
}
