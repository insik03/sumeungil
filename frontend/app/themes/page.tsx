import type { Metadata } from "next";
import { Suspense } from "react";
import Footer from "../../components/Footer";
import ThemesContent, { ThemesLoadingSkeleton } from "../../components/ThemesContent";

export const metadata: Metadata = {
  title: "테마별 여행 — 숨은길",
  description: "분위기와 목적으로 골라보는 여행지 테마 모음.",
};

export default function ThemesPage() {
  return (
    <div className="page">
      <main>
        {/* §44(2026-08-0X) — useSearchParams(?region_code=)를 쓰는 ThemesContent는 Suspense
            경계가 필요하다(Next.js App Router 규약, app/recommend/page.tsx §35와 동일 패턴). */}
        <Suspense fallback={<ThemesLoadingSkeleton />}>
          <ThemesContent />
        </Suspense>
      </main>
      <Footer />
    </div>
  );
}
