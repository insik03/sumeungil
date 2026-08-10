import type { Metadata } from "next";
import Footer from "../../../../components/Footer";
import SharedCourseDetailContent from "../../../../components/course/SharedCourseDetailContent";

export const metadata: Metadata = {
  title: "공유 코스 — 숨은길",
  description: "다른 여행자가 공유한 코스를 확인해요.",
};

export default function SharedCoursePage({ params }: { params: { code: string } }) {
  return (
    <div className="page">
      <main>
        <SharedCourseDetailContent code={params.code} />
      </main>
      <Footer />
    </div>
  );
}
