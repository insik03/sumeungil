import type { Metadata } from "next";
import { Suspense } from "react";
import Footer from "../../components/Footer";
import CourseContent, { CourseLoadingSkeleton } from "../../components/CourseContent";

export const metadata: Metadata = {
  title: "AI 추천 코스 — 숨은길",
  description: "취향과 지역을 바탕으로 아침부터 저녁까지 순서 있는 하루 코스와 이동 시간을 짜드려요.",
};

export default function CoursePage() {
  return (
    <div className="page">
      <main>
        {/* §35(2026-07-31) — useSearchParams(?region_code=)를 쓰는 CourseContent는 Suspense
            경계가 필요하다(Next.js App Router 규약, app/ask/page.tsx와 동일 패턴). */}
        <Suspense fallback={<CourseLoadingSkeleton />}>
          <CourseContent />
        </Suspense>
      </main>
      <Footer />
    </div>
  );
}
