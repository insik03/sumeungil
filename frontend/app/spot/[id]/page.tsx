import type { Metadata } from "next";
import Footer from "../../../components/Footer";
import SpotDetailContent from "../../../components/spot/SpotDetailContent";

export const metadata: Metadata = {
  title: "스팟 상세 — 숨은길",
  description: "숨은 스팟의 소개와 이런 분께 추천하는 이유, 예상 혼잡도를 확인해요.",
};

export default async function SpotDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <div className="page">
      <main>
        <SpotDetailContent contentId={id} />
      </main>
      <Footer />
    </div>
  );
}
