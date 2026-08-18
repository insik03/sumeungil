"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../lib/api";
import { deleteAccount, setLoggedInName } from "../lib/authStorage";

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
 * 직접 확인/수정해야 로그인이 완료된다. 여기서 취소하면 로그인 자체를 취소로 본다
 * (서버 세션 쿠키도 지운다) — "인증은 됐는데 표시 이름은 미정"인 애매한 상태를 안 만든다.
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
  const popupRef = useRef<Window | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const startButtonRef = useRef<HTMLButtonElement>(null);
  const nicknameInputRef = useRef<HTMLInputElement>(null);
  // 2026-08-18(QA M-3) — 아래 useEffect는 [open, onClose]에만 의존해 모달이 열릴 때 한 번만
  // onKey를 등록한다. setStep("nickname")으로 단계가 바뀌어도 그 클로저 안의 step은 등록 당시
  // 값("provider")에 그대로 고정된 채라, 닉네임 확인 단계에서 Esc를 눌러도 항상 "provider"로
  // 취급돼 cancelAtNicknameStep(계정 삭제)이 아니라 그냥 onClose()만 호출되고 있었다 — 구글
  // 인증은 됐는데 표시 이름은 확인 안 된 계정 행이 그대로 DB에 남는 경로였다. ref로 최신
  // step을 따로 들고 있으면 이 클로저 문제 없이 항상 최신 단계를 본다.
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
    const t = window.setTimeout(() => startButtonRef.current?.focus(), 30);
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (stepRef.current === "nickname") {
        // cancelAtNicknameStep과 동일한 처리(아래 정의보다 먼저 쓰여야 해서 인라인) —
        // "인증은 됐는데 표시 이름은 미정"인 애매한 상태를 안 남기려고 계정 자체를 지운다.
        void deleteAccount();
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
          setNickname(data.name.slice(0, NICKNAME_MAX));
          setStep("nickname");
        } else {
          // 2026-08-18(대표 지시) — 재로그인마다 매번 닉네임을 확인시키지 않는다. 이미
          // DB에 저장된 이름을 그대로 신뢰하고 바로 로그인 완료로 처리한다.
          setLoggedInName(data.name);
          onLoggedIn(data.name);
          onClose();
        }
      }
      // 실패(ok:false)면 조용히 무시 — 모달은 열린 채로 남아 다시 시도할 수 있다.
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [open]);

  if (!open) return null;

  const startProviderLogin = (provider: "google" | "kakao") => {
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
    if (trimmed.length === 0) return;
    setSaving(true);
    setSaveError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/display-name`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: trimmed }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setSaveError(
          typeof body?.detail === "string" ? body.detail : "표시 이름 저장에 실패했어요. 다시 시도해주세요."
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

  // 닉네임 단계에서 취소 — 구글 인증(서버 세션 쿠키)까지 됐지만 표시 이름은 안 정했으니
  // 로그인 자체를 취소로 본다(애매한 반쯤 로그인 상태를 남기지 않는다). QA M-3(2026-08-17)
  // 지적대로, 예전엔 logout()(쿠키만 삭제)이라 구글 원본 이름이 담긴 계정 행이 users
  // 테이블에 그대로 남았다 — deleteAccount()로 그 행 자체를 지워야 "취소"가 말 그대로
  // 취소가 된다.
  const cancelAtNicknameStep = () => {
    void deleteAccount();
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
              로그인은 완료됐어요. 리뷰 등에 공개로 보일 이름을 정해주세요 — 방금 쓴 이름을
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
                disabled={nickname.trim().length === 0 || saving}
                onClick={confirmNickname}
              >
                {saving ? "저장 중…" : "시작하기"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
