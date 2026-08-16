"use client";

/**
 * 구글 로그인(임시, 2026-08-17 대표 지시) — 데모 닉네임 로그인(§R.0)을 완전히 대체한다.
 *
 * 실제 인증(누가 로그인했는지 증명)은 백엔드가 HttpOnly 세션 쿠키(backend/app/security/
 * user_auth.py)로 관리한다 — 이 모듈은 그 쿠키를 읽거나 흉내내지 않는다. 여기 저장하는
 * 값은 **표시용 이름 캐시**뿐이다: 로그인 팝업이 완료되면 백엔드가 postMessage로 이름을
 * 알려주고(LoginModal.tsx), 그 값만 localStorage에 넣어 헤더 등이 매 페이지 로드마다
 * 네트워크 왕복 없이 동기적으로 "로그인 상태"를 읽을 수 있게 한다(기존 LoginGateProvider의
 * requireLogin이 동기 체크를 전제로 짜여 있어, 이 계약을 그대로 유지해야 8개 소비 파일을
 * 안 건드릴 수 있다).
 *
 * 저장 스키마: sessionStorage 온보딩·localStorage 저장코스와 동일한 네임스페이스·버전 규칙.
 */
import { API_BASE } from "./api";

const NICKNAME_KEY = "sumeungil:nickname:v1";

/** 브라우저 커스텀 이벤트명 — 여러 컴포넌트(헤더 등)가 로그인 상태 변화를 즉시 반영하기 위함. */
export const AUTH_CHANGED_EVENT = "sumeungil:auth-changed";

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

/** 표시용 이름(로그인 상태). 없으면 null(비로그인). 실제 인증 여부의 근거가 아니라
 *  "화면에 뭐라고 표시할지"의 캐시일 뿐이다 — 서버 API는 이 값을 절대 신뢰하지 않는다. */
export function getNickname(): string | null {
  if (!isBrowser()) return null;
  try {
    const v = window.localStorage.getItem(NICKNAME_KEY);
    return v && v.trim().length > 0 ? v : null;
  } catch {
    return null;
  }
}

/** 로그인 팝업이 성공을 알려온 직후(LoginModal.tsx)에만 호출한다. */
export function setLoggedInName(name: string): void {
  if (!isBrowser()) return;
  const trimmed = name.trim();
  if (trimmed.length === 0) return;
  try {
    window.localStorage.setItem(NICKNAME_KEY, trimmed.slice(0, 100));
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
  } catch {
    // localStorage 비활성(시크릿 모드 등) — 조용히 무시. 화면 흐름을 막지 않는다.
  }
}

/** 로그아웃. 로컬 표시 캐시를 즉시 지우고(체감 즉시 반영), 서버 세션 쿠키도 지운다
 *  (실패해도 로컬 상태는 이미 지워졌으니 화면은 정상 — fire-and-forget). */
export function logout(): void {
  if (!isBrowser()) return;
  try {
    window.localStorage.removeItem(NICKNAME_KEY);
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
  } catch {
    /* noop */
  }
  fetch(`${API_BASE}/api/v1/auth/logout`, { method: "POST", credentials: "include" }).catch(() => {
    // 네트워크 실패해도 로컬은 이미 로그아웃 상태 — 쿠키는 만료되면 어차피 무효화된다.
  });
}
