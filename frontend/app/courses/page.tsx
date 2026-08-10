import type { Metadata } from "next";
import Footer from "../../components/Footer";
import CoursesFeedContent from "../../components/CoursesFeedContent";

export const metadata: Metadata = {
  title: "다른 사람 코스 — 숨은길",
  description: "다른 여행자가 공유한 코스를 구경해요.",
};

export default function CoursesPage() {
  return (
    <div className="page">
      <main>
        <CoursesFeedContent />
      </main>
      <Footer />
    </div>
  );
}
