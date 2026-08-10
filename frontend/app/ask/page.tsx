import type { Metadata } from "next";
import { Suspense } from "react";
import Footer from "../../components/Footer";
import AskContent, { AskLoadingSkeleton } from "../../components/AskContent";

export const metadata: Metadata = {
  title: "AI 여행 문답 — 숨은길",
  description: "말로 물어보면 AI가 조건에 맞는 여행지를 찾아드려요. 필터를 고르지 않아도 괜찮아요.",
};

export default function AskPage() {
  return (
    <div className="page">
      <main>
        {/* useSearchParams(?q= 자동 실행)를 쓰는 AskContent는 Suspense 경계가 필요하다
            (Next.js App Router 규약, CompareContent.tsx와 동일 패턴). */}
        <Suspense fallback={<AskLoadingSkeleton />}>
          <AskContent />
        </Suspense>
      </main>
      <Footer />
    </div>
  );
}
