import type { Metadata } from "next";
import { Suspense } from "react";
import Footer from "../../components/Footer";
import RecommendContent, { RecommendLoadingSkeleton } from "../../components/RecommendContent";

export const metadata: Metadata = {
  title: "맞춤 스팟 추천 — 숨은길",
  description: "취향 분석 결과와 지역을 바탕으로 붐비지 않는 로컬 스팟을 추천해드려요.",
};

export default function RecommendPage() {
  return (
    <div className="page">
      <main>
        {/* §35(2026-07-31) — useSearchParams(?region_code=)를 쓰는 RecommendContent는 Suspense
            경계가 필요하다(Next.js App Router 규약, app/ask/page.tsx와 동일 패턴). */}
        <Suspense fallback={<RecommendLoadingSkeleton />}>
          <RecommendContent />
        </Suspense>
      </main>
      <Footer />
    </div>
  );
}
