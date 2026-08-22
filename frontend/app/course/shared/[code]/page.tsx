import type { Metadata } from "next";
import Footer from "../../../../components/Footer";
import SharedCourseDetailContent from "../../../../components/course/SharedCourseDetailContent";

export const metadata: Metadata = {
  title: "공유 코스 — 숨은길",
  description: "다른 여행자가 공유한 코스를 확인해요.",
};

export default async function SharedCoursePage({
  params,
}: {
  params: Promise<{ code: string }>;
}) {
  const { code } = await params;
  return (
    <div className="page">
      <main>
        <SharedCourseDetailContent code={code} />
      </main>
      <Footer />
    </div>
  );
}
