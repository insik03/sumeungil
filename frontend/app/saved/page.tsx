import type { Metadata } from "next";
import Footer from "../../components/Footer";
import SavedContent from "../../components/SavedContent";

export const metadata: Metadata = {
  title: "저장한 코스 — 숨은길",
  description: "마음에 든 스팟을 모아두고 다시 확인해요.",
};

export default function SavedPage() {
  return (
    <div className="page">
      <main>
        <SavedContent />
      </main>
      <Footer />
    </div>
  );
}
