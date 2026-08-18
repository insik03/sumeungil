"use client";

import { useEffect, useState } from "react";
import AdminLogin from "../../components/admin/AdminLogin";
import AdminConsole from "../../components/admin/AdminConsole";
import { fetchAdminSession } from "../../lib/adminApi";

/**
 * 관리자 콘솔 단일 페이지 (03-admin-console-design.md).
 *
 * 폴더명(경로) 자체가 `/admin`이 아니라 무작위 문자열이다(2026-08-18, 대표 지시 — "너무
 * 찾기 쉬운거 같아서"). 페이지에는 로그인 폼만 있고 비밀 데이터는 없어 실질 방어는 여전히
 * `/api/v1/admin/*`(비밀번호+세션쿠키, deploy/nginx.conf 참고)이지만, 흔한 경로명을 스캔하는
 * 봇·사람에게 아예 안 걸리는 게 한 겹 더 낫다는 판단. 경로를 바꾸려면 이 폴더명을 바꾸고
 * Header.tsx의 pathname 체크, deploy/nginx.conf의 `location /admin` 블록도 같이 고쳐야 한다.
 *
 * 서브라우트를 두지 않는다: 로그인 게이트와 콘솔이 같은 페이지에서 전환된다.
 * 라우트를 나누면 "로그인 안 된 상태로 하위 경로 직링크" 같은 경로가 생기는데,
 * 어차피 세션이 없으면 401 이라 화면만 늘고 얻는 게 없다.
 *
 * 사이트 GNB/Footer 는 `components/Header.tsx` 가 이 경로에서 스스로 렌더를 건너뛴다
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
