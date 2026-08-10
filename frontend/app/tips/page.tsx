import type { Metadata } from "next";
import Footer from "../../components/Footer";
import TipsContent from "../../components/TipsContent";

export const metadata: Metadata = {
  title: "여행 팁 — 숨은길",
  description: "혼잡을 피하고 더 편안하게 여행하는 법을 정리했어요.",
};

export default function TipsPage() {
  return (
    <div className="page">
      <main>
        <TipsContent />
      </main>
      <Footer />
    </div>
  );
}
