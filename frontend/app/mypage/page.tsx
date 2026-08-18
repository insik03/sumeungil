import type { Metadata } from "next";
import Footer from "../../components/Footer";
import MyPageContent from "../../components/MyPageContent";

export const metadata: Metadata = {
  title: "마이페이지 — 숨은길",
  description: "내 계정 정보를 확인하고 관리해요.",
};

export default function MyPage() {
  return (
    <div className="page">
      <main>
        <MyPageContent />
      </main>
      <Footer />
    </div>
  );
}
