"use client";

import { useState } from "react";
import { API_BASE } from "../lib/api";
import { logout } from "../lib/authStorage";
import { TERMS_VERSION } from "../lib/consent";

/**
 * 기존 회원 동의 모달 (2026-09-14).
 *
 * 이용약관을 새로 만들면서 "가입(첫 로그인) 시 약관·방침 동의를 기록"하도록 바꿨다(LoginModal 표시
 * 이름 단계). 그 전에 가입한 회원과, 약관 버전이 올라간 뒤 다시 방문한 회원에게는 이 모달이 한 번
 * 뜬다 — `/me` 가 `terms_agreed:false` 를 주면 Header 가 연다. 동의하면 `POST /auth/consent` 로
 * 시각·버전을 기록하고, 동의하지 않으면 로그아웃한다(계정은 남는다 — 탈퇴는 마이페이지에서).
 */
export default function ConsentModal({ open, onDone }: { open: boolean; onDone: () => void }) {
  const [checked, setChecked] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const agree = async () => {
    if (!checked || saving) return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/consent`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ terms_version: TERMS_VERSION }),
      });
      if (!res.ok) {
        setError("동의를 저장하지 못했어요. 잠시 후 다시 시도해주세요.");
        return;
      }
      onDone();
    } catch {
      setError("네트워크 오류로 저장하지 못했어요.");
    } finally {
      setSaving(false);
    }
  };

  const decline = () => {
    logout();
    onDone();
  };

  return (
    <div className="login-modal__backdrop" role="presentation">
      <div className="login-modal" role="dialog" aria-modal="true" aria-labelledby="consentTitle">
        <h2 className="login-modal__title" id="consentTitle">
          약관 동의가 필요해요
        </h2>
        <p className="login-modal__sub">
          이용약관과 개인정보처리방침이 개정됐어요(버전 {TERMS_VERSION}). 계속 이용하려면 한 번
          확인하고 동의해주세요. 동의하지 않으면 로그아웃되고, 계정은 그대로 남아요.
        </p>
        <p className="login-modal__sub">
          이번 변경은 네이버 로그인, 탈퇴 시 후기 삭제, 기존 스탬프 기록과 위치 기능 중단,
          외부 AI 처리 안내를 반영합니다. 개인정보처리방침 확인은 별도 수집·이용 또는 국외이전 동의를 대신하지 않아요.
          계정 삭제 등 권리 행사는 로그아웃 후에도 개인정보처리방침의 이메일로 요청할 수 있어요.
        </p>
        <label className="consent-check">
          <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
          <span>
            <a href="/terms" target="_blank" rel="noopener noreferrer">
              이용약관
            </a>
            과{" "}
            <a href="/privacy" target="_blank" rel="noopener noreferrer">
              개인정보처리방침
            </a>
            을 확인했으며, 이용약관에 동의해요.
          </span>
        </label>
        {error && (
          <p className="login-modal__note" role="alert">
            {error}
          </p>
        )}
        <div className="login-modal__actions">
          <button type="button" className="btn btn--ghost-text" onClick={decline} disabled={saving}>
            동의하지 않음(로그아웃)
          </button>
          <button type="button" className="btn btn--coral" onClick={agree} disabled={!checked || saving}>
            {saving ? "저장 중…" : "동의하고 계속"}
          </button>
        </div>
      </div>
    </div>
  );
}
