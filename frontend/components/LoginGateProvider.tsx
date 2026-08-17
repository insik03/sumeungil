"use client";

import { ReactNode, createContext, useCallback, useContext, useRef, useState } from "react";
import LoginModal from "./LoginModal";
import { getNickname } from "../lib/authStorage";

interface LoginGateContextValue {
  /**
   * 로그인이 필요한 동작을 감싼다. 이미 로그인 상태면 action을 즉시 실행하고 끝난다.
   * 비로그인이면 모달을 띄우고, 모달에서 로그인에 성공한 순간 원래 실행하려던 action을
   * 이어서 실행한다("모달 닫고 끝" 금지 — 지시서 핵심 요구사항).
   */
  requireLogin: (action: () => void, message?: string) => void;
}

const LoginGateContext = createContext<LoginGateContextValue | null>(null);

/**
 * §40(신규) — 로그인 유도 게이트. 하트/찜, 코스에 담기, 방문 스탬프 찍기 등 "사용자 데이터가 필요한
 * 동작"을 비로그인 상태에서 눌렀을 때 공용으로 재사용한다(호출부마다 모달을 재구현하지 않는다).
 * 새 인증 로직을 만들지 않고 기존 LoginModal.tsx(구글 로그인, 2026-08-17부터 데모 닉네임
 * 로그인을 완전히 대체) + authStorage.getNickname을 그대로 재사용한다 — 이 컴포넌트는
 * "언제 모달을 띄우고, 로그인 후 무엇을 실행할지"만 조율한다.
 */
export function useLoginGate(): LoginGateContextValue {
  const ctx = useContext(LoginGateContext);
  if (!ctx) {
    throw new Error("useLoginGate는 LoginGateProvider 하위에서만 사용할 수 있습니다.");
  }
  return ctx;
}

export default function LoginGateProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState<string | undefined>(undefined);
  // 대기 중인 동작 — 로그인 성공 시 1회 실행하고 비운다. ref라 리렌더를 유발하지 않는다.
  const pendingActionRef = useRef<(() => void) | null>(null);

  const requireLogin = useCallback((action: () => void, msg?: string) => {
    if (getNickname()) {
      action();
      return;
    }
    pendingActionRef.current = action;
    setMessage(msg);
    setOpen(true);
  }, []);

  // "나중에"/Esc/백드롭 닫기 — 대기 동작은 실행하지 않고 버린다.
  const handleClose = useCallback(() => {
    pendingActionRef.current = null;
    setOpen(false);
  }, []);

  // 로그인 성공 — 모달이 스스로 onClose도 호출하므로 여기서는 open만 내려가면 충분하다.
  // 대기 동작을 먼저 꺼내 비운 뒤 실행해, 실행 중 재호출 등으로 중복 실행되지 않게 한다.
  const handleLoggedIn = useCallback(() => {
    const action = pendingActionRef.current;
    pendingActionRef.current = null;
    setOpen(false);
    if (action) action();
  }, []);

  return (
    <LoginGateContext.Provider value={{ requireLogin }}>
      {children}
      <LoginModal
        open={open}
        onClose={handleClose}
        onLoggedIn={handleLoggedIn}
        title="로그인하고 계속하기"
        message={message ?? "로그인하면 저장한 곳을 다음에도 볼 수 있어요. 닉네임만 입력하면 바로 시작해요."}
      />
    </LoginGateContext.Provider>
  );
}
