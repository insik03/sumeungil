import type { Metadata } from "next";
import { Suspense } from "react";
import Footer from "../../components/Footer";
import CompareContent, { CompareLoadingSkeleton } from "../../components/compare/CompareContent";

export const metadata: Metadata = {
  title: "핫플 vs 숨은길 비교 — 숨은길",
  description: "붐비는 유명 스팟과 AI가 찾은 한적한 숨은길을 예상 혼잡도·맞춤 적합도로 1:1 비교해요.",
};

export default function ComparePage() {
  return (
    <div className="page">
      <main>
        {/* useSearchParams를 쓰는 CompareContent는 Suspense 경계가 필요하다(Next.js App Router 규약). */}
        <Suspense fallback={<CompareLoadingSkeleton />}>
          <CompareContent />
        </Suspense>
      </main>
      <Footer />
    </div>
  );
}
