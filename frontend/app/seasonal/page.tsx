import type { Metadata } from "next";
import Footer from "../../components/Footer";
import SeasonalSection from "../../components/SeasonalSection";

export const metadata: Metadata = {
  title: "계절 여행 — 숨은길",
  description: "봄·여름·가을·겨울, 계절마다 사람이 몰리는 곳과 아직 붐비지 않는 곳을 나눠 보여드려요.",
};

/**
 * §38(2026-07-31, 대표 지시 "홈에 자꾸 다 추가하지 말고 따로 만들라") — 계절 여행 전용
 * 페이지. 이전엔 홈(HomeContent) 안의 한 섹션이었으나 독립 화면으로 분리했다.
 * regionCode 는 넘기지 않는다 — 이 화면은 전국 기준으로 계절을 보여준다.
 */
export default function SeasonalPage() {
  return (
    <div className="page">
      <main>
        <SeasonalSection headingLevel="h1" />
      </main>
      <Footer />
    </div>
  );
}
