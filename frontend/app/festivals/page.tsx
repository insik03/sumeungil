import type { Metadata } from "next";
import Footer from "../../components/Footer";
import FestivalsContent from "../../components/FestivalsContent";

export const metadata: Metadata = {
  title: "전국 축제 — 숨은길",
  description: "전국에서 열리는 축제를 지역·시기별로 찾아보세요.",
};

export default function FestivalsPage() {
  return (
    <div className="page">
      <main>
        <FestivalsContent />
      </main>
      <Footer />
    </div>
  );
}
