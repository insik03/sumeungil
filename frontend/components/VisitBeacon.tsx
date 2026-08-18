"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { API_BASE } from "../lib/api";

/**
 * 페이지 조회 비콘 (부록 X, 2026-08-10)
 *
 * ## 왜 필요한가
 * 집계 미들웨어는 **백엔드 컨테이너**에만 있는데, 화면 페이지는 **프론트 컨테이너**가
 * 처리하고 nginx 가 `/api/` 만 백엔드로 보낸다. 그래서 서버는 "사람이 어느 페이지를
 * 봤는지"를 알 방법이 없다(2026-08-10 실측으로 확인 — 페이지 6건이 집계에 안 잡혔다).
 * 이 컴포넌트가 그 공백을 메운다.
 *
 * ## 화면을 절대 방해하지 않는다
 * - `keepalive` 로 보내 페이지를 떠나도 요청이 살아남는다
 * - 실패는 통째로 무시한다(`catch {}`) — 통계 때문에 콘솔에 에러가 뜨면 안 된다
 * - 응답을 기다리지 않는다(204, 본문 없음)
 *
 * ## 관리자 화면은 보내지 않는다
 * 운영자가 콘솔을 볼 때마다 방문자 수가 오르면 자기 통계를 자기가 오염시킨다.
 */
export default function VisitBeacon() {
  const pathname = usePathname();

  useEffect(() => {
    if (!pathname) return;
    // 경로가 무작위 문자열인 이유는 app/ops-37878f1b71/page.tsx 상단 주석 참고.
    if (pathname === "/ops-37878f1b71" || pathname.startsWith("/ops-37878f1b71/")) return;

    try {
      void fetch(`${API_BASE}/api/v1/visit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: pathname }),
        keepalive: true,
      }).catch(() => {
        /* 집계 실패는 사용자에게 아무 의미가 없다 — 조용히 넘어간다 */
      });
    } catch {
      /* 구형 브라우저에서 fetch 옵션이 막혀도 화면은 그대로 동작해야 한다 */
    }
  }, [pathname]);

  return null;
}
