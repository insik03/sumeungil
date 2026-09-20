import type { Metadata } from "next";
import { Suspense } from "react";
import Footer from "../../components/Footer";
import FestivalsContent, { FestivalsLoadingSkeleton } from "../../components/FestivalsContent";

export const metadata: Metadata = {
  title: "전국 축제 — 숨은길",
  description: "전국에서 열리는 축제를 지역·시기별로 찾아보세요.",
};

export default function FestivalsPage() {
  return (
    <div className="page">
      <main>
        {/* 목록 상태(지역·월·상태·페이지)를 URL 로 옮기면서 useSearchParams 를 쓴다 —
            Next.js App Router 규약상 Suspense 경계가 필요하다(compare/page.tsx 와 동일). */}
        <Suspense fallback={<FestivalsLoadingSkeleton />}>
          <FestivalsContent />
        </Suspense>
      </main>
      <Footer />
    </div>
  );
}
