"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { SavedSpot, loadSavedSpots, removeSavedSpot } from "../lib/savedSpotsStorage";
import SavedSpotCard from "./saved/SavedSpotCard";
import VisitStampsSection from "./saved/VisitStampsSection";
import SharedCoursesSection from "./saved/SharedCoursesSection";

/**
 * 부록 F 파트2(F.2-6-2) 저장 화면. 서버 호출 0(F.2-2) — localStorage만 읽는다.
 * 서버 렌더/첫 클라이언트 렌더는 항상 null(로딩 아님, 그냥 "아직 안 읽음")로 맞춰
 * 하이드레이션 경고를 막고, mount 후에만 localStorage 값을 반영한다(onboardingStorage 소비 패턴).
 *
 * Phase 4(신규) — "내 방문 스탬프" 섹션(VisitStampsSection)을 이 화면 아래에 추가했다(additive,
 * 위 저장한 스팟 렌더 로직·마크업은 무변경). 하나의 화면에 두 섹션(각자 own <section>)을 쌓는
 * HomeContent.tsx의 기존 관례를 그대로 따른다 — 탭 대신 섹션을 선택한 이유는 03-design-spec.md §21 참고.
 * §41(신규) — "내가 공유한 코스" 섹션(SharedCoursesSection)을 그 아래에 추가했다(additive, 공유한
 * 적이 없으면 섹션 자체가 렌더되지 않는다).
 */
export default function SavedContent() {
  const [spots, setSpots] = useState<SavedSpot[] | null>(null);

  useEffect(() => {
    setSpots(loadSavedSpots());
  }, []);

  const handleRemove = (id: number) => {
    removeSavedSpot(id);
    setSpots((prev) => (prev ?? []).filter((s) => s.id !== id));
  };

  const sorted = spots
    ? [...spots].sort((a, b) => new Date(b.saved_at).getTime() - new Date(a.saved_at).getTime())
    : [];

  return (
    <>
      <section className="section" aria-labelledby="savedHeading">
        <span className="eyebrow-pill eyebrow-pill--azure">저장한 코스</span>
        <h1 className="section__title" id="savedHeading">
          내가 저장한 스팟
        </h1>
        <p className="saved-content__intro">
          이 기기에만 저장돼요 — 다른 기기·브라우저에서는 보이지 않아요(F.2-2, 서버 저장 없음).
        </p>

        {spots !== null && sorted.length === 0 && (
          <div className="board-error" role="status">
            <p className="board-error__msg">아직 저장한 스팟이 없어요.</p>
            <p className="board-error__hint">추천 화면에서 마음에 드는 스팟을 하트로 저장해보세요.</p>
            <Link className="btn btn--mint" href="/recommend">
              추천 보러가기
            </Link>
          </div>
        )}

        {sorted.length > 0 && (
          <div className="spot-grid" role="list">
            {sorted.map((spot) => (
              <SavedSpotCard key={spot.id} spot={spot} onRemove={() => handleRemove(spot.id)} />
            ))}
          </div>
        )}
      </section>

      <VisitStampsSection />
      <SharedCoursesSection />
    </>
  );
}
