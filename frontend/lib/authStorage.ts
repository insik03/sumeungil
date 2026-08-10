"use client";

/**
 * 데모 로그인(닉네임 전용) — 대표 결정(2026-07-24): 비밀번호·개인정보·서버 저장 없이
 * 브라우저 localStorage에 닉네임만 보관한다. 법률(개인정보처리방침)·DB·소셜 키가 필요 없다.
 * 상용 공개 시 소셜 로그인(카카오 등)으로 교체 — 이 모듈 뒤(get/set/clear)만 바꾸면 된다.
 *
 * 저장 스키마: sessionStorage 온보딩·localStorage 저장코스와 동일한 네임스페이스·버전 규칙.
 */
const NICKNAME_KEY = "sumeungil:nickname:v1";

/** 브라우저 커스텀 이벤트명 — 여러 컴포넌트(헤더 등)가 로그인 상태 변화를 즉시 반영하기 위함. */
export const AUTH_CHANGED_EVENT = "sumeungil:auth-changed";

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

/** 저장된 닉네임(로그인 상태). 없으면 null(비로그인). */
export function getNickname(): string | null {
  if (!isBrowser()) return null;
  try {
    const v = window.localStorage.getItem(NICKNAME_KEY);
    return v && v.trim().length > 0 ? v : null;
  } catch {
    return null;
  }
}

/** 닉네임 로그인. 빈 문자열은 무시. 성공 시 true. */
export function login(nickname: string): boolean {
  if (!isBrowser()) return false;
  const trimmed = nickname.trim();
  if (trimmed.length === 0) return false;
  try {
    // 과도한 길이 방어(표시 안정). 개인정보가 아니라 표시용 닉네임일 뿐이다.
    window.localStorage.setItem(NICKNAME_KEY, trimmed.slice(0, 20));
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
    return true;
  } catch {
    return false;
  }
}

/** 로그아웃(닉네임 삭제). */
export function logout(): void {
  if (!isBrowser()) return;
  try {
    window.localStorage.removeItem(NICKNAME_KEY);
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
  } catch {
    /* noop */
  }
}
