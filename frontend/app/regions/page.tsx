import type { Metadata } from "next";
import { Suspense } from "react";
import Footer from "../../components/Footer";
import RegionsContent from "../../components/RegionsContent";

export const metadata: Metadata = {
  title: "지역별 여행 — 숨은길",
  description: "전국 17개 시도를 골라 지금 많이 찾는 곳과 아직 붐비지 않는 숨은 발견을 함께 둘러보세요.",
};

export default function RegionsPage() {
  return (
    <div className="page">
      <main>
        {/* RegionsContent 가 useSearchParams(?region_code=)를 쓰므로 App Router 규약상
            Suspense 경계가 필요하다(app/recommend·app/themes 와 동일 패턴). */}
        <Suspense fallback={null}>
          <RegionsContent />
        </Suspense>
      </main>
      <Footer />
    </div>
  );
}
