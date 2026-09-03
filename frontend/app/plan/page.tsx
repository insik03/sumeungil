import type { Metadata } from "next";
import Footer from "../../components/Footer";
import DeparturePlanner from "../../components/DeparturePlanner";

export const metadata: Metadata = {
  title: "출발일 플래너 — 숨은길",
  description: "가려는 날짜와 권역을 고르면 그날의 예상 혼잡도와 날씨를 알려드려요.",
};

/**
 * §38(2026-07-31, 대표 지시 "홈에 자꾸 다 추가하지 말고 따로 만들라") — 출발일 플래너 전용
 * 페이지. 이전엔 홈(HomeContent) 안의 한 섹션이었으나, 홈이 번잡해진다는 지적에 따라
 * 독립 화면으로 분리했다(ServiceQuickMenu 타일에서 진입).
 */
export default function PlanPage() {
  return (
    <div className="page">
      <main>
        <DeparturePlanner headingLevel="h1" />
      </main>
      <Footer />
    </div>
  );
}
