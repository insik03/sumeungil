"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../lib/api";

const POPUP_MESSAGE_SOURCE = "sumeungil-login";

export type LinkOutcome = "linked" | "already" | "conflict" | "not_logged_in" | "error";

interface LinkProviderButtonsProps {
  /** /me 의 providers — 이미 붙은 provider 는 버튼 대신 "연결됨"으로 보인다. */
  providers: Record<string, boolean>;
  /** 연결 시도가 끝나면(성공·이미 연결·충돌·실패) 호출. 성공이면 호출부가 /me 를 다시 읽는다. */
  onDone: (provider: "google" | "kakao", outcome: LinkOutcome) => void;
}

const LABEL: Record<"google" | "kakao", string> = { google: "구글", kakao: "카카오" };

/**
 * 2026-09-18(대표 결정 "로그인으로 묶자") — 로그인 중인 계정에 다른 로그인 방식을 붙인다.
 * 이름·전화번호 입력이 아니라 **그 provider 로 실제 로그인**해서 소유를 증명하는 방식. 팝업은
 * LoginModal 과 같은 콜백 페이지를 쓰되 `link=1` 로 시작해, 서버가 새 세션 대신 현재 계정에
 * provider 를 붙이고(user_repo.link_provider) `linked` 결과를 postMessage 로 돌려준다.
 */
export default function LinkProviderButtons({ providers, onDone }: LinkProviderButtonsProps) {
  const [busy, setBusy] = useState<"google" | "kakao" | null>(null);
  const [blocked, setBlocked] = useState(false);
  const popupRef = useRef<Window | null>(null);

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== new URL(API_BASE).origin) return;
      const data = e.data as { source?: string; linked?: LinkOutcome | null } | null;
      if (!data || data.source !== POPUP_MESSAGE_SOURCE || !data.linked) return;
      const provider = busy;
      setBusy(null);
      if (provider) onDone(provider, data.linked);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [busy, onDone]);

  const start = (provider: "google" | "kakao") => {
    setBlocked(false);
    const url = `${API_BASE}/api/v1/auth/${provider}/login?link=1&next=${encodeURIComponent("/mypage")}`;
    const popup = window.open(url, "sumeungil-login", "width=480,height=640");
    if (!popup) {
      setBlocked(true);
      return;
    }
    popupRef.current = popup;
    setBusy(provider);
    popup.focus();
  };

  return (
    <div className="link-providers">
      {(["google", "kakao"] as const).map((p) =>
        providers[p] ? (
          <span key={p} className="link-providers__done">
            {LABEL[p]} 연결됨
          </span>
        ) : (
          <button
            key={p}
            type="button"
            className="btn btn--outline"
            disabled={busy !== null}
            onClick={() => start(p)}
          >
            {busy === p ? "연결 중…" : `${LABEL[p]} 계정 연결`}
          </button>
        )
      )}
      {blocked && (
        <p className="login-modal__note" role="alert">
          팝업이 차단됐어요. 팝업을 허용한 뒤 다시 시도해주세요.
        </p>
      )}
    </div>
  );
}
