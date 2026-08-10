import type { Metadata } from "next";
import "../styles/globals.css";
import Header from "../components/Header";
import LoginGateProvider from "../components/LoginGateProvider";
import VisitBeacon from "../components/VisitBeacon";

export const metadata: Metadata = {
  title: "숨은길 — 설렘 가득한 우리 가족만의 숨은 루트",
  description:
    "AI가 찾아주는 한적한 여행 코스와 예상 혼잡도 전광판. 숨은길과 함께 붐비지 않는 오늘의 여행을 계획하세요.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        {/* §40(신규) — 하트/찜·코스 담기·방문 스탬프 등 로그인 필요 동작을 전역에서 게이트한다. */}
        <LoginGateProvider>
          {/* 부록 X: 페이지 조회 집계 비콘. 렌더 결과가 없고 화면을 막지 않는다. */}
          <VisitBeacon />
          <Header />
          {children}
        </LoginGateProvider>
      </body>
    </html>
  );
}
