"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../lib/api";
import { setLoggedInName } from "../lib/authStorage";
import { TERMS_VERSION } from "../lib/consent";

interface LoginModalProps {
  open: boolean;
  onClose: () => void;
  onLoggedIn: (name: string) => void;
  /** §40(신규) — 로그인 게이트가 동작별 문구로 덮어쓸 때 쓴다. 없으면 기존 헤더 기본 문구 그대로. */
  title?: string;
  message?: string;
}

const POPUP_MESSAGE_SOURCE = "sumeungil-login";
const NICKNAME_MAX = 20;

/**
 * 구글·카카오 로그인 모달(임시, 2026-08-17 대표 지시. 카카오는 같은 날 추가) — 데모
 * 닉네임 로그인을 완전히 대체.
 *
 * 팝업 창(전체 페이지 이동 아님)으로 OAuth를 띄운다 — 이 화면(부모 창)은 페이지 전환
 * 없이 그대로 남아있고, LoginGateProvider가 "로그인 완료 즉시 원래 하려던 동작을 이어서
 * 실행"하는 기존 UX(onLoggedIn 콜백)를 그대로 유지할 수 있는 유일한 방법이다. 구글·카카오
 * 둘 다 팝업이 같은 포맷(`POPUP_MESSAGE_SOURCE`)으로 postMessage를 보내므로 어느 쪽으로
 * 로그인했는지 이 컴포넌트가 구분할 필요가 없다.
 *
 * §닉네임 확인 단계(2026-08-17, legal-counsel 07-legal-review-google-login.md §3 권고) —
 * 로그인이 성공해도 그 이름을 바로 리뷰 표시 이름으로 쓰지 않는다. "로그인 목적으로 받은
 * 이름을 동의 없이 다른 목적(공개 게시물 작성자 표시)에 자동 전용하는 구조"라는 지적에
 * 따라, provider가 준 이름을 기본값으로 미리 채운 입력창을 한 번 더 보여주고 사용자가
 * 직접 확인/수정해야 로그인이 완료된다. 2026-09-20 가입 순서 변경 이후 이 단계에는 계정도
 * 세션도 아직 없으므로(가입 보류 쿠키뿐), 취소는 그 쿠키만 폐기하고 닫는다.
 *
 * 2026-08-18(대표 지시 "로그인할 때마다 닉네임 정하게 할 건 아니지?") — 이 확인 단계는
 * **최초 가입 때 한 번만** 보여준다(백엔드가 postMessage에 실어 보내는 `is_new` 플래그로
 * 판정, api/auth.py `_complete_oauth_login` 참고). 재로그인은 이미 사용자가 한 번 확인/
 * 동의한 이름을 그대로 재사용하는 것뿐이라 위 legal-counsel 지적("동의 없이 자동 전용")과
 * 충돌하지 않는다 — 동의는 최초 1회로 이미 성립했고, 값도 그때와 동일하다.
 */
export default function LoginModal({ open, onClose, onLoggedIn, title, message }: LoginModalProps) {
  const [step, setStep] = useState<"provider" | "nickname">("provider");
  const [popupBlocked, setPopupBlocked] = useState(false);
  const [nickname, setNickname] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  // 2026-09-14 — 첫 로그인(표시 이름 단계)에서 약관·처리방침 동의를 명시적으로 받는다.
  const [agreed, setAgreed] = useState(false);
  // 2026-09-20 — 서버에 설정된 로그인 방식만 버튼을 보인다(네이버 키 미설정 시 버튼 숨김).
  const [enabled, setEnabled] = useState<{ google: boolean; kakao: boolean; naver: boolean }>({ google: true, kakao: true, naver: false });
  const popupRef = useRef<Window | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const startButtonRef = useRef<HTMLButtonElement>(null);
  const nicknameInputRef = useRef<HTMLInputElement>(null);
  // 아래 Esc 핸들러는 [open, onClose] 에만 의존해 모달이 열릴 때 한 번만 등록된다 — 그 클로저
  // 안의 step 은 등록 당시 값("provider")에 고정되므로, 최신 단계는 ref 로 따로 들고 본다.
  const stepRef = useRef(step);
  useEffect(() => {
    stepRef.current = step;
  }, [step]);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    setStep("provider");
    setPopupBlocked(false);
    setNickname("");
    setSaving(false);
    setSaveError(null);
    // 2026-09-20(qa-reviewer F-1, Blocker) — 이 모달은 LoginGateProvider 가 한 번만 마운트하고
    // `if (!open) return null` 로 감추기만 해서 상태가 탭 수명 내내 남는다. agreed 를 같이
    // 되돌리지 않으면 앞사람이 켜둔 체크가 그대로 남아, 다음 신규 사용자가 약관을 본 적도
    // 없이 동의가 기록된다(agreed 가 가입 완료 버튼의 유일한 게이트다).
    setAgreed(false);
    const t = window.setTimeout(() => startButtonRef.current?.focus(), 30);
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // 2026-09-20 — 약관 동의 전엔 계정이 아직 없다(가입 보류). 다만 닉네임 단계에서 빠져나갈
      // 땐 보류 쿠키를 서버에서 지워야 해서 cancelAtNicknameStep 과 같은 처리를 태운다.
      // 이 클로저는 등록 시점 step("provider")에 고정되므로 ref 로 최신 단계를 본다.
      if (stepRef.current === "nickname") {
        void fetch(`${API_BASE}/api/v1/auth/signup/cancel`, {
          method: "POST",
          credentials: "include",
        }).catch(() => undefined);
      }
      onClose();
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

  useEffect(() => {
    if (!open) return;
    const c = new AbortController();
    fetch(`${API_BASE}/api/v1/auth/providers`, { signal: c.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (j && typeof j.google === "boolean") setEnabled(j);
      })
      .catch(() => undefined);
    return () => c.abort();
  }, [open]);

  // 팝업이 보내는 postMessage 수신 — 모달이 열려 있는 동안만 리스너를 둔다.
  useEffect(() => {
    if (!open) return;
    const onMessage = (e: MessageEvent) => {
      // origin 검증: 우리 백엔드(API_BASE)가 렌더한 콜백 페이지에서만 온 메시지를 신뢰한다.
      if (e.origin !== new URL(API_BASE).origin) return;
      const data = e.data as { source?: string; ok?: boolean; name?: string; is_new?: boolean } | null;
      if (!data || data.source !== POPUP_MESSAGE_SOURCE) return;
      if (data.ok && data.name) {
        if (data.is_new) {
          // 신규 가입일 때만 닉네임 확인 단계로 — provider 인증까지는 성공했지만
          // 아직 로그인 완료로 치지 않는다(§닉네임 확인 단계 주석 참고).
          // 2026-09-20 대표 지시 — 순서는 "구글 로그인 → 약관 동의 팝업 → 가입 완료". 이 단계에서
          // 약관·처리방침 동의와 표시 이름을 한 화면에서 받고, 동의해야 가입이 끝난다.
          setNickname(data.name.slice(0, NICKNAME_MAX));
          setStep("nickname");
        } else {
          // 2026-08-18(대표 지시) — 재로그인마다 매번 닉네임을 확인시키지 않는다. 이미
          // DB에 저장된 이름을 그대로 신뢰하고 바로 로그인 완료로 처리한다. 약관이 개정돼 미동의면
          // Header 의 ConsentModal 이 따로 묻는다.
          setLoggedInName(data.name);
          onLoggedIn(data.name);
          onClose();
        }
      }
      // 실패(ok:false)면 조용히 무시 — 모달은 열린 채로 남아 다시 시도할 수 있다.
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [open, onClose, onLoggedIn]);

  if (!open) return null;

  const startProviderLogin = (provider: "google" | "kakao" | "naver") => {
    setPopupBlocked(false);
    const url = `${API_BASE}/api/v1/auth/${provider}/login?next=${encodeURIComponent("/")}`;
    const popup = window.open(url, "sumeungil-login", "width=480,height=640");
    if (!popup) {
      setPopupBlocked(true);
      return;
    }
    popupRef.current = popup;
    popup.focus();
  };

  // 대표 지시(2026-08-17, "로그인 붙였으니 DB도 그에 맞게") — 확인한 표시 이름을 로컬
  // 캐시(동기 UI 체크용, authStorage.ts)뿐 아니라 서버 계정(users 테이블)에도 저장한다.
  // 저장 전까지는 로그인을 완료로 치지 않는다 — 서버 실패를 조용히 삼키면 다음 로그인
  // 때 구글 원본 이름으로 되돌아가는 문제가 재발한다(user_repo.upsert_login 참고).
  const confirmNickname = async () => {
    const trimmed = nickname.trim();
    if (trimmed.length === 0 || !agreed) return;
    setSaving(true);
    setSaveError(null);
    try {
      // 2026-09-20 — 신규 가입은 여기서 비로소 계정이 만들어진다(약관 동의 전엔 서버에 계정·세션 없음).
      const res = await fetch(`${API_BASE}/api/v1/auth/signup/complete`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: trimmed, terms_version: TERMS_VERSION }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setSaveError(
          typeof body?.error?.message === "string"
            ? body.error.message
            : typeof body?.detail === "string"
              ? body.detail
              : "가입을 완료하지 못했어요. 다시 시도해주세요."
        );
        return;
      }
    } catch {
      setSaveError("네트워크 오류로 저장하지 못했어요. 다시 시도해주세요.");
      return;
    } finally {
      setSaving(false);
    }
    setLoggedInName(trimmed);
    onLoggedIn(trimmed);
    onClose();
  };

  // 2026-09-20 — 약관 동의 전엔 서버에 계정도 세션도 없다(가입 보류 쿠키뿐, 5분 뒤 만료).
  // 다만 그 쿠키엔 provider 가 증명한 신원(이메일 포함)이 들어 있어, 공용 PC 에서 다음 사람이
  // 남은 쿠키로 가입을 마쳐버릴 수 있다(security-engineer F-1). 취소 시 서버에 폐기를 맡긴다 —
  // 실패해도 닫는 건 그대로다(만료가 마지막 방어선).
  const cancelAtNicknameStep = () => {
    void fetch(`${API_BASE}/api/v1/auth/signup/cancel`, {
      method: "POST",
      credentials: "include",
    }).catch(() => undefined);
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
        {step === "provider" ? (
          <>
            <h2 className="login-modal__title" id="loginModalTitle">
              {title ?? "숨은길 시작하기"}
            </h2>
            <p className="login-modal__sub">{message ?? "간편로그인으로 바로 시작해요."}</p>
            {/* 구글 브랜딩 가이드라인(Sign in with Google branding guidelines) 준수 — 흰 배경 +
                공식 4색 G 로고 + 회색 테두리. 로고 색상·비율을 임의로 바꾸지 않는다. */}
            <button
              ref={startButtonRef}
              type="button"
              className="btn-google"
              onClick={() => startProviderLogin("google")}
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
            {/* 카카오 로그인 버튼 매뉴얼(공식 브랜드 가이드) 준수 — 배경 #FEE500 고정,
                텍스트/아이콘은 검정 계열 고정색, 임의 배색 금지. 2026-08-17 신설. */}
            <button
              type="button"
              className="btn-kakao"
              onClick={() => startProviderLogin("kakao")}
            >
              <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
                <path
                  fill="#191919"
                  d="M9 2.4c-4.28 0-7.75 2.73-7.75 6.1 0 2.17 1.44 4.08 3.62 5.17-.16.57-.58 2.06-.66 2.38-.1.4.15.4.31.29.13-.09 2.06-1.4 2.9-1.96.5.07 1.02.11 1.58.11 4.28 0 7.75-2.73 7.75-6.1S13.28 2.4 9 2.4z"
                />
              </svg>
              <span>카카오로 로그인</span>
            </button>
            {/* 2026-09-20 대표 결정 — 네이버 로그인. 서버에 키가 없으면(/auth/providers naver:false) 버튼을 숨긴다. */}
            {enabled.naver && (
              <button
                type="button"
                className="btn-naver"
                onClick={() => startProviderLogin("naver")}
              >
                <span className="btn-naver__mark" aria-hidden="true">N</span>
                <span>네이버로 로그인</span>
              </button>
            )}
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
              로그인 제공자에게서 이메일·이름만 받아요. 처음 가입할 때 이용약관·개인정보처리방침 동의를 받은 뒤 가입이 완료돼요.
            </p>
          </>
        ) : (
          <>
            <h2 className="login-modal__title" id="loginModalTitle">
              약관 동의하고 가입 완료
            </h2>
            <p className="login-modal__sub">
              로그인 인증은 됐어요. 이용약관·개인정보처리방침에 동의하고, 리뷰 등에 공개로 보일 표시 이름을
              정하면 가입이 완료돼요.
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
            <label className="consent-check">
              <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
              <span>
                <a href="/terms" target="_blank" rel="noopener noreferrer">
                  이용약관
                </a>
                과{" "}
                <a href="/privacy" target="_blank" rel="noopener noreferrer">
                  개인정보처리방침
                </a>
                을 확인했고 동의해요. (만 14세 이상)
              </span>
            </label>
            {saveError && (
              <p className="login-modal__note" role="alert">
                {saveError}
              </p>
            )}
            <div className="login-modal__actions">
              <button
                type="button"
                className="btn btn--ghost-text"
                onClick={cancelAtNicknameStep}
                disabled={saving}
              >
                취소
              </button>
              <button
                type="button"
                className="btn btn--mint"
                disabled={nickname.trim().length === 0 || saving || !agreed}
                onClick={confirmNickname}
              >
                {saving ? "저장 중…" : "동의하고 가입 완료"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
