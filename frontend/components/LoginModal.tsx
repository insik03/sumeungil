"use client";

import { useEffect, useRef, useState } from "react";
import { login } from "../lib/authStorage";

interface LoginModalProps {
  open: boolean;
  onClose: () => void;
  onLoggedIn: (nickname: string) => void;
  /** §40(신규) — 로그인 게이트가 동작별 문구로 덮어쓸 때 쓴다. 없으면 기존 헤더 기본 문구 그대로. */
  title?: string;
  message?: string;
}

/**
 * 데모 로그인 모달(닉네임 전용). 비밀번호·개인정보 없음 — 닉네임만 받아 localStorage에 저장한다.
 * 상용 시 소셜 로그인으로 교체(대표 결정). 접근성: Esc 닫기, 열릴 때 입력창 포커스, 백드롭 클릭 닫기,
 * 열리는 동안 배경 스크롤 잠금, 닫히면(취소/Esc/백드롭/로그인 성공 전부 포함) 열기 직전 포커스였던
 * 요소로 복귀(§40, LoginGateProvider.tsx가 이 컴포넌트를 그대로 재사용 — 새 모달 구현 없음).
 */
export default function LoginModal({ open, onClose, onLoggedIn, title, message }: LoginModalProps) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    setValue("");
    const t = window.setTimeout(() => inputRef.current?.focus(), 30);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      previousFocusRef.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  const submit = () => {
    if (login(value)) {
      onLoggedIn(value.trim().slice(0, 20));
      onClose();
    }
  };

  return (
    <div
      className="login-modal__backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="loginModalTitle"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="login-modal">
        <h2 className="login-modal__title" id="loginModalTitle">
          {title ?? "숨은길 시작하기"}
        </h2>
        <p className="login-modal__sub">
          {message ?? "닉네임만 입력하면 바로 시작해요. 비밀번호도, 개인정보도 필요 없어요."}
        </p>
        <label className="login-modal__label" htmlFor="loginNickname">
          닉네임
        </label>
        <input
          ref={inputRef}
          id="loginNickname"
          className="login-modal__input"
          type="text"
          maxLength={20}
          placeholder="예: 여행가는곰"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
        />
        <div className="login-modal__actions">
          <button type="button" className="btn btn--ghost-text" onClick={onClose}>
            취소
          </button>
          <button
            type="button"
            className="btn btn--mint"
            disabled={value.trim().length === 0}
            onClick={submit}
          >
            시작하기
          </button>
        </div>
        <p className="login-modal__note">
          지금은 데모 로그인이에요. 정식 오픈 때 카카오 로그인 등으로 바뀔 수 있어요.
        </p>
      </div>
    </div>
  );
}
