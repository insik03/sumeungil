import type { Metadata } from "next";
import Footer from "../../components/Footer";
import OnboardingContent from "../../components/OnboardingContent";

export const metadata: Metadata = {
  title: "취향 찾기 — 숨은길",
  description: "자유 서술과 키워드로 여행 취향을 알려주시면 AI가 태그로 정리해드려요.",
};

export default function OnboardingPage() {
  return (
    <div className="page">
      <main>
        <OnboardingContent />
      </main>
      <Footer />
    </div>
  );
}
