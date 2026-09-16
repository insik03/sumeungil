import type { Metadata } from "next";
import Footer from "../../components/Footer";
import MapPreviewContent from "../../components/mappreview/MapPreviewContent";
import DeparturePlanner from "../../components/DeparturePlanner";

export const metadata: Metadata = {
  title: "전국 예상 혼잡 현황 — 숨은길",
  description:
    "전국 시·도의 예상 혼잡도를 한눈에 보고, 지역을 고르면 그 지역 관광지의 예상 혼잡 현황을 확인해요.",
};

/**
 * 부록 U.3(2026-08-01, 대표 지시) — 종전 홈의 "예상 혼잡 전광판(#board)" 자리를 대신하는 화면.
 * 위: 전국 지도(시·도별 예상 혼잡도 + 랜드마크) / 아래: 고른 지역의 예상 혼잡 현황판(가로 순환).
 *
 * §52(2026-08-12, 대표 지시 "전국 혼잡도 지도 안에 출발일 플래너를 붙여") — 같은 혼잡도 데이터를
 * 공간(지도)으로 보여주던 화면에 시간(출발일 플래너, "언제 갈까") 관점을 이어 붙인다.
 * DeparturePlanner는 자체 상태만 갖는 독립 섹션이라(§37.2, /plan 전용 페이지) props 없이
 * 그대로 아래에 이어 붙이기만 하면 된다 — 내부 로직·API 호출 무변경, /plan 페이지도 그대로 유지
 * (기존 진입 경로 보존, 필요 시 정리는 대표 지시로 별도 진행).
 *
 * 2026-09-15(대표 지시) — 순서 반전: 출발일 플래너를 맨 위, 전국 혼잡 현황을 아래로. 두 섹션의
 * 좌우 폭은 globals.css `.planner`(max-width 1560)로 맞췄고, 두 섹션 사이 간격은 `.congestion-stack`으로 좁혔다.
 */
export default function CongestionPage() {
  return (
    <div className="page">
      <main className="congestion-stack">
        <DeparturePlanner />
        <MapPreviewContent />
      </main>
      <Footer />
    </div>
  );
}
