import HomeContent from "../components/HomeContent";
import Footer from "../components/Footer";

/**
 * FestivalBanner는 더 이상 여기서 직접 렌더하지 않는다 — 실데이터 연동(Phase 3)을 위해
 * HomeContent가 소유한 지역 선택 상태(selectedRegion)를 공유해야 해서 HomeContent 내부로
 * 옮겼다(components/HomeContent.tsx 참고, 화면상 위치는 그대로 맨 아래).
 */
export default function HomePage() {
  return (
    <div className="page page--home">
      <main>
        <HomeContent />
      </main>
      <Footer />
    </div>
  );
}
