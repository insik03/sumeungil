/**
 * 약관·개인정보처리방침 동의 버전 (2026-09-14 신설).
 *
 * 서버(`backend/app/api/auth.py` TERMS_VERSION)와 같은 값을 쓴다. 약관·방침을 실질적으로 바꾸면
 * 양쪽 값을 같이 올린다 — 그러면 기존 회원도 다음 방문 때 ConsentModal 로 다시 동의를 받는다.
 */
export const TERMS_VERSION = "2026-09-14";

export interface SessionInfo {
  authenticated: boolean;
  name?: string | null;
  /** 현재 TERMS_VERSION 에 동의했는가. 비로그인·구버전 동의·미동의는 false. */
  terms_agreed?: boolean;
  /** 2026-09-18 — 연결된 로그인 방식(google/kakao → true). 마이페이지 "로그인 연결"과 가입 직후 안내에 쓴다. */
  providers?: Record<string, boolean>;
}
