"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../lib/api";
import { setLoggedInName } from "../lib/authStorage";

interface LoginModalProps {
  open: boolean;
  onClose: () => void;
  onLoggedIn: (name: string) => void;
  /** §40(신규) — 로그인 게이트가 동작별 문구로 덮어쓸 때 쓴다. 없으면 기존 헤더 기본 문구 그대로. */
  title?: string;
  message?: string;
}

const POPUP_MESSAGE_SOURCE = "sumeungil-google-login";

/**
 * 구글 로그인 모달(임시, 2026-08-17 대표 지시) — 데모 닉네임 로그인을 완전히 대체.
 *
 * 팝업 창(전체 페이지 이동 아님)으로 구글 OAuth를 띄운다 — 이 화면(부모 창)은 페이지
 * 전환 없이 그대로 남아있고, LoginGateProvider가 "로그인 완료 즉시 원래 하려던 동작을
 * 이어서 실행"하는 기존 UX(onLoggedIn 콜백)를 그대로 유지할 수 있는 유일한 방법이다
 * (전체 페이지 리디렉션 방식이면 원래 페이지의 React 상태가 통째로 날아간다).
 *
 * 팝업이 완료되면 backend/app/api/auth.py의 콜백 페이지가 window.opener로 결과를
 * postMessage하고 스스로 닫힌다 — 여기서는 그 메시지를 받아서 처리만 한다. 팝업 차단
 * 시(브라우저 설정) window.open이 null을 돌려주므로 안내 문구로 대체한다.
 */
export default function LoginModal({ open, onClose, onLoggedIn, title, message }: LoginModalProps) {
  const [popupBlocked, setPopupBlocked] = useState(false);
  const popupRef = useRef<Window | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const startButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    setPopupBlocked(false);
    const t = window.setTimeout(() => startButtonRef.current?.focus(), 30);
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
      popupRef.current = null;
    };
  }, [open, onClose]);

  // 팝업이 보내는 postMessage 수신 — 모달이 열려 있는 동안만 리스너를 둔다.
  useEffect(() => {
    if (!open) return;
    const onMessage = (e: MessageEvent) => {
      // origin 검증: 우리 백엔드(API_BASE)가 렌더한 콜백 페이지에서만 온 메시지를 신뢰한다.
      if (e.origin !== new URL(API_BASE).origin) return;
      const data = e.data as { source?: string; ok?: boolean; name?: string } | null;
      if (!data || data.source !== POPUP_MESSAGE_SOURCE) return;
      if (data.ok && data.name) {
        setLoggedInName(data.name);
        onLoggedIn(data.name);
        onClose();
      }
      // 실패(ok:false)면 조용히 무시 — 모달은 열린 채로 남아 다시 시도할 수 있다.
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [open, onClose, onLoggedIn]);

  if (!open) return null;

  const startGoogleLogin = () => {
    setPopupBlocked(false);
    const url = `${API_BASE}/api/v1/auth/google/login?next=${encodeURIComponent("/")}`;
    const popup = window.open(url, "sumeungil-google-login", "width=480,height=640");
    if (!popup) {
      setPopupBlocked(true);
      return;
    }
    popupRef.current = popup;
    popup.focus();
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
        <p className="login-modal__sub">{message ?? "구글 계정으로 로그인하면 바로 시작해요."}</p>
        {/* 구글 브랜딩 가이드라인(Sign in with Google branding guidelines) 준수 — 흰 배경 +
            공식 4색 G 로고 + 회색 테두리. 로고 색상·비율을 임의로 바꾸지 않는다. */}
        <button
          ref={startButtonRef}
          type="button"
          className="btn-google"
          onClick={startGoogleLogin}
        >
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <path
              fill="#4285F4"
              d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.874 2.684-6.615z"
            />
            <path
              fill="#34A853"
              d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z"
            />
            <path
              fill="#FBBC05"
              d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z"
            />
            <path
              fill="#EA4335"
              d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"
            />
          </svg>
          <span>Google로 로그인</span>
        </button>
        {popupBlocked && (
          <p className="login-modal__note" role="alert">
            팝업이 차단됐어요. 브라우저 주소창의 팝업 차단 아이콘을 눌러 이 사이트의 팝업을
            허용한 뒤 다시 시도해주세요.
          </p>
        )}
        <div className="login-modal__actions">
          <button type="button" className="btn btn--ghost-text" onClick={onClose}>
            취소
          </button>
        </div>
        <p className="login-modal__note">지금은 임시로 붙인 로그인이에요.</p>
      </div>
    </div>
  );
}
