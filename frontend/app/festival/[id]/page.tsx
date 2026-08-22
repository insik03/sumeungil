import type { Metadata } from "next";
import Footer from "../../../components/Footer";
import FestivalDetailContent from "../../../components/festival/FestivalDetailContent";

export const metadata: Metadata = {
  title: "축제 상세 — 숨은길",
  description: "축제 사진과 방문 타이밍, 날씨를 확인하고 이 지역 스팟도 함께 둘러보세요.",
};

export default async function FestivalDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <div className="page">
      <main>
        <FestivalDetailContent festivalId={id} />
      </main>
      <Footer />
    </div>
  );
}
