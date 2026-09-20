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
import { clearOnboardingResult } from "./onboardingStorage";
import type { SessionInfo } from "./consent";

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
 *  서버 세션 종료에 실패하면 완료로 오인하지 않도록 알린다. */
export function logout(): void {
  if (!isBrowser()) return;
  // 2026-09-05 리뷰 P1 — 온보딩 결과(자유서술 원문 포함)는 이 계정의 것이라 같이 지운다. 안 지우면
  // 같은 탭에서 다른 계정으로 로그인했을 때 이전 사용자의 여행 문장이 새 계정의 코스 요청(wish)에 실린다.
  clearOnboardingResult();
  try {
    window.localStorage.removeItem(NICKNAME_KEY);
    // 2026-09-16 — 저장한 스팟은 이제 계정 데이터(서버 정본)라 로컬 캐시도 같이 지운다. 키 문자열은
    // savedSpotsStorage.ts 의 SAVED_SPOTS_STORAGE_KEY 와 같다(그 모듈이 이 파일을 import 하므로 순환 방지).
    // Legacy guest saves are independent of the signed-in account.
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
  } catch {
    /* noop */
  }
  fetch(`${API_BASE}/api/v1/auth/logout`, { method: "POST", credentials: "include" })
    .then((response) => { if (!response.ok) throw new Error("logout failed"); })
    .catch(() => {
      window.alert("서버 로그아웃을 완료하지 못했습니다. 연결을 복구한 뒤 새로고침하고 다시 로그아웃해주세요.");
    });
}

/** 서버 세션 진실과 localStorage 캐시를 맞춘다(QA M-2, 2026-08-17).
 *
 * 원래 이 캐시는 팝업이 로그인 직후 1회 채워줄 뿐, 그 뒤로는 **서버에 한 번도 물어보지
 * 않았다** — 세션이 7일 뒤 만료되거나 다른 기기에서 표시 이름을 바꿔도 이 브라우저는
 * 영원히 예전 상태를 보여줬다(만료 없는 로컬 캐시라 사실상 무기한). 앱 부팅 시(Header가
 * 항상 마운트되므로 거기서) 한 번 GET /me 로 실제 서버 상태를 확인해 반영한다.
 *
 * LoginGateProvider의 동기 체크 계약(모듈 상단 주석)은 그대로 둔다 — 이 함수는 그 캐시를
 * "가끔 서버와 맞추는" 백그라운드 보정일 뿐, 매 판정을 네트워크 왕복으로 바꾸지 않는다. */
export async function syncSessionFromServer(): Promise<SessionInfo | null> {
  if (!isBrowser()) return null;
  try {
    const res = await fetch(`${API_BASE}/api/v1/auth/me`, { credentials: "include" });
    if (!res.ok) return null; // 네트워크/서버 오류 — 로컬 캐시를 함부로 지우지 않는다(오프라인 등 오탐 방지).
    const data: SessionInfo = await res.json();
    const cached = getNickname();
    if (data.authenticated && data.name) {
      if (data.name !== cached) setLoggedInName(data.name);
    } else if (!data.authenticated && cached) {
      // 서버는 비로그인인데 로컬엔 이름이 남아있다 — 세션 만료 등. 조용히 로컬만 정리
      // (서버 쿠키는 이미 없으니 /logout 호출은 불필요). 온보딩 결과도 같이(리뷰 P1).
      clearOnboardingResult();
      // Legacy guest saves are independent of the signed-in account.
      window.localStorage.removeItem(NICKNAME_KEY);
      window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
    }
    return data;
  } catch {
    // 네트워크 실패 — 다음 페이지 이동/새로고침 때 다시 시도된다. 로컬 캐시는 유지.
    return null;
  }
}

/** 계정 삭제(탈퇴) — 로컬 표시 캐시를 지우고 서버 계정 행도 함께 삭제한다(users
 *  테이블에서 DELETE, 세션 쿠키도 서버가 함께 지운다). `logout()`과 달리 **완료를
 *  기다린다** — LoginModal의 "닉네임 확인 취소" 단계(QA M-3, 2026-08-17)가 "로그인
 *  자체를 취소로 본다"고 안내하면서 실제로는 계정 행이 남던 문제를 고치는 용도라,
 *  서버 삭제가 실제로 끝난 뒤에 취소를 완료로 쳐야 한다. */
export async function deleteAccount(): Promise<void> {
  if (!isBrowser()) return;
  const response = await fetch(`${API_BASE}/api/v1/auth/me`, { method: "DELETE", credentials: "include" });
  if (!response.ok) throw new Error("계정을 삭제하지 못했습니다. 로그인 상태와 연결을 확인하고 다시 시도해주세요.");
  try {
    clearOnboardingResult();
    window.localStorage.removeItem(NICKNAME_KEY);
  } catch {
    // The server deletion succeeded even if browser storage is unavailable.
  } finally {
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
  }
}
