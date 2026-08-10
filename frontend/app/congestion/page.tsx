import type { Metadata } from "next";
import Footer from "../../components/Footer";
import MapPreviewContent from "../../components/mappreview/MapPreviewContent";

export const metadata: Metadata = {
  title: "전국 예상 혼잡 지도 — 숨은길",
  description:
    "전국 시·도의 예상 혼잡도를 지도 한 장으로 보고, 지역을 고르면 그 지역 관광지의 예상 혼잡 현황을 확인해요.",
};

/**
 * 부록 U.3(2026-08-01, 대표 지시) — 종전 홈의 "예상 혼잡 전광판(#board)" 자리를 대신하는 화면.
 * 위: 전국 지도(시·도별 예상 혼잡도 + 랜드마크) / 아래: 고른 지역의 예상 혼잡 현황판(가로 순환).
 */
export default function CongestionPage() {
  return (
    <div className="page">
      <main>
        <MapPreviewContent />
      </main>
      <Footer />
    </div>
  );
}
