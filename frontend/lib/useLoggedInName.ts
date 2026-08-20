"use client";

/**
 * 로그인 표시 이름을 실시간으로 반환하는 훅(2026-08-17, 대표 지시 — 온보딩·AI 문답·AI
 * 코스짜기 로그인 필수화).
 *
 * `Header.tsx`가 원래 자기 안에서만 쓰던 "getNickname() 초기값 + AUTH_CHANGED_EVENT/
 * storage 리스너" 패턴을 그대로 추출한 것 — 이제 로그인 게이트가 필요한 페이지
 * (OnboardingContent/CourseContent/MyPageContent 등)도 같은 로직이 필요해져서 중복을 피하려고
 * 훅으로 분리했다. `Header.tsx`도 이 훅을 쓰도록 리팩터한다(동작은 그대로).
 *
 * `syncSessionFromServer()`(부팅 시 서버 세션과 로컬 캐시를 맞추는 1회성 호출, QA M-2)는
 * 이 훅에 넣지 않는다 — 앱 전역에 한 번이면 충분한데, 훅을 여러 컴포넌트가 쓰면 그만큼
 * 중복 호출된다. 그 호출은 항상 마운트돼 있는 `Header.tsx`에만 남겨둔다.
 */
import { useEffect, useState } from "react";
import { AUTH_CHANGED_EVENT, getNickname } from "./authStorage";

export function useLoggedInName(): string | null {
  const [name, setName] = useState<string | null>(null);

  useEffect(() => {
    setName(getNickname());
    const sync = () => setName(getNickname());
    window.addEventListener(AUTH_CHANGED_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(AUTH_CHANGED_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return name;
}
