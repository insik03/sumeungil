"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../lib/api";
import { adminLogin, fetchAdminOperators } from "../../lib/adminApi";

/**
 * 관리자 로그인 (03-admin-console-design.md §5.1, 계약 부록 T·V)
 *
 * ## 실패 사유를 구분해 알려주지 않는다
 * 비밀번호가 틀렸는지 이름이 목록에 없는지 **화면도 구분하지 않는다**. 백엔드가 둘 다 동일한
 * 401 로 수렴시키는 이유와 같다 — 어느 쪽이 맞았는지 알려주면 추측을 도와주는 셈이다.
 *
 * ## 이름 선택은 보안 장치가 아니다
 * 비밀번호를 아는 세 사람은 서로의 이름을 고를 수 있다(자기 신고 방식). 감사 로그에 "누가"를
 * 남기기 위한 장치이지 신원 인증이 아니다. 그래서 화면에도 "본인 확인"·"인증" 같은 과신 유발
 * 단어를 쓰지 않고, 한계를 상시 노출한다.
 */
export default function AdminLogin({
  onSuccess,
  expiredNotice,
}: {
  onSuccess: (operator: string, expiresAt: string) => void;
  /** 세션 만료로 되돌아온 직후 1회 표시하는 중립 톤 안내(에러가 아니다). */
  expiredNotice?: boolean;
}) {
  const [operators, setOperators] = useState<string[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  /** 관리자 기능 자체가 꺼져 있음(라우터 미등록 → 404). 폼을 아예 그리지 않는다. */
  const [disabled, setDisabled] = useState(false);

  const [operator, setOperator] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryAfter, setRetryAfter] = useState(0);
  const passwordRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let alive = true;
    fetchAdminOperators()
      .then((list) => alive && setOperators(list))
      .catch((e: unknown) => {
        if (!alive) return;
        // 404 = ADMIN_PASSWORD_HASH 미설정으로 라우터가 없는 상태. "기능이 있는데 막혔다"는
        // 잘못된 인상을 주지 않도록 폼 자체를 렌더하지 않는다.
        if (e instanceof ApiError && e.status === 404) setDisabled(true);
        else setLoadFailed(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  // 429 카운트다운. 서버 판정을 **예측만** 할 뿐 보장하지 않는다 — 0이 돼도 다시 429가 올 수 있고,
  // 그러면 새 retry_after_sec 로 다시 시작한다.
  useEffect(() => {
    if (retryAfter <= 0) return;
    const t = setTimeout(() => setRetryAfter((n) => n - 1), 1000);
    return () => clearTimeout(t);
  }, [retryAfter]);

  const needsOperator = operators !== null && operators.length > 0;
  const ready = operators !== null;
  const canSubmit =
    ready && !submitting && retryAfter <= 0 && password.length > 0 && (!needsOperator || !!operator);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const session = await adminLogin(password, operator);
      onSuccess(operator, session.expires_at);
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        const sec = Number(err.detail?.retry_after_sec ?? 60);
        setRetryAfter(Number.isFinite(sec) && sec > 0 ? sec : 60);
        setError(null);
      } else {
        setError("이름 또는 비밀번호를 확인해주세요.");
      }
      // 비밀번호만 비우고 이름은 남긴다 — 같은 사람이 다시 시도할 확률이 높다.
      setPassword("");
      passwordRef.current?.focus();
    } finally {
      setSubmitting(false);
    }
  }

  if (disabled) {
    return (
      <div className="admin-auth">
        <div className="admin-auth__card">
          <h1 className="admin-auth__title">숨은길 관리자 콘솔</h1>
          <p className="admin-auth__msg">관리자 기능이 설정되지 않았습니다.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-auth">
      <form className="admin-auth__card" onSubmit={submit}>
        <h1 className="admin-auth__title">숨은길 관리자 콘솔</h1>
        <p className="admin-auth__sub">운영자 전용 화면입니다.</p>

        {expiredNotice && (
          <p className="admin-auth__notice">세션이 만료됐어요. 다시 로그인해주세요.</p>
        )}

        {loadFailed ? (
          <>
            <p className="admin-auth__msg">운영자 목록을 불러오지 못했습니다.</p>
            <button
              type="button"
              className="admin-btn admin-btn--primary"
              onClick={() => window.location.reload()}
            >
              새로고침
            </button>
          </>
        ) : (
          <>
            {needsOperator && (
              <label className="admin-field">
                <span className="admin-field__label">이름</span>
                <select
                  className="admin-field__input"
                  value={operator}
                  onChange={(e) => setOperator(e.target.value)}
                  disabled={submitting}
                >
                  {/* 자동 선택하지 않는다 — 남의 이름으로 무심코 로그인하는 것을 막는다. */}
                  <option value="">선택해주세요</option>
                  {operators!.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
            )}

            <label className="admin-field">
              <span className="admin-field__label">비밀번호</span>
              <input
                ref={passwordRef}
                className="admin-field__input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                disabled={submitting}
              />
            </label>

            <button type="submit" className="admin-btn admin-btn--primary admin-auth__submit" disabled={!canSubmit}>
              {submitting ? "로그인 중…" : !ready ? "불러오는 중…" : "로그인"}
            </button>

            <p className="admin-auth__hint">
              이름 선택은 감사 기록용 표시일 뿐, 비밀번호 없이는 아무 것도 할 수 없어요.
            </p>

            {retryAfter > 0 && (
              <p className="admin-auth__error" role="alert">
                로그인 시도가 너무 잦아요. {retryAfter}초 후 다시 시도해주세요.
              </p>
            )}
            {error && (
              <p className="admin-auth__error" role="alert">
                {error}
              </p>
            )}
          </>
        )}
      </form>
    </div>
  );
}
