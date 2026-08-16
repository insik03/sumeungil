"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../lib/api";
import { logout, setLoggedInName } from "../lib/authStorage";

interface LoginModalProps {
  open: boolean;
  onClose: () => void;
  onLoggedIn: (name: string) => void;
  /** §40(신규) — 로그인 게이트가 동작별 문구로 덮어쓸 때 쓴다. 없으면 기존 헤더 기본 문구 그대로. */
  title?: string;
  message?: string;
}

const POPUP_MESSAGE_SOURCE = "sumeungil-google-login";
const NICKNAME_MAX = 20;

/**
 * 구글 로그인 모달(임시, 2026-08-17 대표 지시) — 데모 닉네임 로그인을 완전히 대체.
 *
 * 팝업 창(전체 페이지 이동 아님)으로 구글 OAuth를 띄운다 — 이 화면(부모 창)은 페이지
 * 전환 없이 그대로 남아있고, LoginGateProvider가 "로그인 완료 즉시 원래 하려던 동작을
 * 이어서 실행"하는 기존 UX(onLoggedIn 콜백)를 그대로 유지할 수 있는 유일한 방법이다.
 *
 * §닉네임 확인 단계(2026-08-17, legal-counsel 07-legal-review-google-login.md §3 권고) —
 * 구글 로그인이 성공해도 그 이름을 바로 리뷰 표시 이름으로 쓰지 않는다. "로그인 목적으로
 * 받은 이름을 동의 없이 다른 목적(공개 게시물 작성자 표시)에 자동 전용하는 구조"라는
 * 지적에 따라, 구글 이름을 기본값으로 미리 채운 입력창을 한 번 더 보여주고 사용자가
 * 직접 확인/수정해야 로그인이 완료된다. 여기서 취소하면 로그인 자체를 취소로 본다
 * (서버 세션 쿠키도 지운다) — "구글 인증은 됐는데 표시 이름은 미정"인 애매한 상태를 안 만든다.
 */
export default function LoginModal({ open, onClose, onLoggedIn, title, message }: LoginModalProps) {
  const [step, setStep] = useState<"google" | "nickname">("google");
  const [popupBlocked, setPopupBlocked] = useState(false);
  const [nickname, setNickname] = useState("");
  const popupRef = useRef<Window | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const startButtonRef = useRef<HTMLButtonElement>(null);
  const nicknameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    setStep("google");
    setPopupBlocked(false);
    setNickname("");
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

  // 닉네임 단계로 넘어가면 입력창에 포커스(구글 이름이 이미 채워진 채로 바로 수정 가능).
  useEffect(() => {
    if (step === "nickname") {
      const t = window.setTimeout(() => nicknameInputRef.current?.focus(), 30);
      return () => window.clearTimeout(t);
    }
  }, [step]);

  // 팝업이 보내는 postMessage 수신 — 모달이 열려 있는 동안만 리스너를 둔다.
  useEffect(() => {
    if (!open) return;
    const onMessage = (e: MessageEvent) => {
      // origin 검증: 우리 백엔드(API_BASE)가 렌더한 콜백 페이지에서만 온 메시지를 신뢰한다.
      if (e.origin !== new URL(API_BASE).origin) return;
      const data = e.data as { source?: string; ok?: boolean; name?: string } | null;
      if (!data || data.source !== POPUP_MESSAGE_SOURCE) return;
      if (data.ok && data.name) {
        // 구글 인증까지는 성공 — 여기서 바로 로그인 완료로 치지 않고, 닉네임 확인 단계로.
        setNickname(data.name.slice(0, NICKNAME_MAX));
        setStep("nickname");
      }
      // 실패(ok:false)면 조용히 무시 — 모달은 열린 채로 남아 다시 시도할 수 있다.
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [open]);

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

  const confirmNickname = () => {
    const trimmed = nickname.trim();
    if (trimmed.length === 0) return;
    setLoggedInName(trimmed);
    onLoggedIn(trimmed);
    onClose();
  };

  // 닉네임 단계에서 취소 — 구글 인증(서버 세션 쿠키)까지 됐지만 표시 이름은 안 정했으니
  // 로그인 자체를 취소로 본다(애매한 반쯤 로그인 상태를 남기지 않는다).
  const cancelAtNicknameStep = () => {
    logout();
    onClose();
  };

  return (
    <div
      className="login-modal__backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="loginModalTitle"
      onClick={(e) => {
        if (e.target === e.currentTarget) (step === "nickname" ? cancelAtNicknameStep : onClose)();
      }}
    >
      <div className="login-modal">
        {step === "google" ? (
          <>
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
            <p className="login-modal__note">
              지금은 임시로 붙인 로그인이에요. 계속하면{" "}
              <a href="/privacy" target="_blank" rel="noopener noreferrer">
                개인정보처리방침
              </a>
              에 동의하는 것으로 간주해요.
            </p>
          </>
        ) : (
          <>
            <h2 className="login-modal__title" id="loginModalTitle">
              표시 이름 정하기
            </h2>
            <p className="login-modal__sub">
              구글 로그인은 완료됐어요. 리뷰 등에 공개로 보일 이름을 정해주세요 — 구글 이름을
              그대로 써도 되고, 바꿔도 돼요.
            </p>
            <label className="login-modal__label" htmlFor="loginNickname">
              표시 이름
            </label>
            <input
              ref={nicknameInputRef}
              id="loginNickname"
              className="login-modal__input"
              type="text"
              maxLength={NICKNAME_MAX}
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") confirmNickname();
              }}
            />
            <div className="login-modal__actions">
              <button type="button" className="btn btn--ghost-text" onClick={cancelAtNicknameStep}>
                취소
              </button>
              <button
                type="button"
                className="btn btn--mint"
                disabled={nickname.trim().length === 0}
                onClick={confirmNickname}
              >
                시작하기
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
