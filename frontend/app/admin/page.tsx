"use client";

import { useEffect, useState } from "react";
import AdminLogin from "../../components/admin/AdminLogin";
import AdminConsole from "../../components/admin/AdminConsole";
import { fetchAdminSession } from "../../lib/adminApi";

/**
 * `/admin` — 관리자 콘솔 단일 페이지 (03-admin-console-design.md).
 *
 * 서브라우트를 두지 않는다: 로그인 게이트와 콘솔이 같은 페이지에서 전환된다.
 * 라우트를 나누면 "로그인 안 된 상태로 /admin/reviews 직링크" 같은 경로가 생기는데,
 * 어차피 세션이 없으면 401 이라 화면만 늘고 얻는 게 없다.
 *
 * 사이트 GNB/Footer 는 `components/Header.tsx` 가 `/admin` 에서 스스로 렌더를 건너뛴다
 * (중첩 레이아웃으로는 부모 레이아웃을 제거할 수 없기 때문 — 그쪽 주석 참고).
 */
export default function AdminPage() {
  const [state, setState] = useState<"checking" | "out" | "in">("checking");
  const [operator, setOperator] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [expiredNotice, setExpiredNotice] = useState(false);

  // 새로고침해도 쿠키가 살아 있으면 로그인 화면을 거치지 않는다.
  useEffect(() => {
    let alive = true;
    fetchAdminSession()
      .then((s) => {
        if (!alive) return;
        setExpiresAt(s.expires_at);
        // 표시 이름은 서버 세션 응답에 없다(토큰 안에만 있고 밖으로 내보내지 않는다).
        // 새로고침 후 상단바 이름이 비는 것은 **표시상의 공백일 뿐**이며,
        // 감사 로그는 서버가 토큰에서 꺼내 이미 정확히 남긴다.
        setOperator(sessionStorage.getItem("sumeungil:admin:operator") ?? "");
        setState("in");
      })
      .catch(() => alive && setState("out"));
    return () => {
      alive = false;
    };
  }, []);

  if (state === "checking") {
    return (
      <div className="admin-boot">
        <span className="admin-boot__spinner" aria-label="확인 중" />
      </div>
    );
  }

  if (state === "out") {
    return (
      <AdminLogin
        expiredNotice={expiredNotice}
        onSuccess={(name, exp) => {
          setOperator(name);
          setExpiresAt(exp);
          // 새로고침 후 상단바 표시용. 권한과 무관한 **표시 문자열**이라 위조돼도
          // 서버 판정에 영향이 없다(감사 로그는 서명된 토큰에서 나온다).
          try {
            sessionStorage.setItem("sumeungil:admin:operator", name);
          } catch {
            /* 프라이빗 모드 등에서 실패해도 기능에는 지장 없다 */
          }
          setExpiredNotice(false);
          setState("in");
        }}
      />
    );
  }

  return (
    <AdminConsole
      operator={operator}
      expiresAt={expiresAt}
      onSessionLost={() => {
        try {
          sessionStorage.removeItem("sumeungil:admin:operator");
        } catch {
          /* noop */
        }
        setExpiredNotice(true);
        setState("out");
      }}
    />
  );
}
