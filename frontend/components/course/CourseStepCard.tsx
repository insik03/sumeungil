"use client";

import { useState } from "react";
import { CourseSpot, SpotCategory } from "../../lib/api";
import RecommendSpotCard from "../recommend/SpotCard";

/**
 * §28(신규, 06-deep-audit-gap-plan §2-B B-9/B-10 대응) — 스텝 카드에 사진 + 발췌를 얹는다.
 * RecommendSpotCard(추천 화면과 공유하는 배지/매칭도 렌더)는 건드리지 않고, 그 위에 미디어를
 * 얹고 아래에 blurb 문단을 붙이는 합성 컴포넌트만 course/* 안에 새로 둔다 — 공유 컴포넌트를
 * 코스 전용으로 변형하면 /recommend 화면까지 영향을 받기 때문(스코프 지시 "course/* 파일만").
 * 플레이스홀더 톤 로직(placeholderTone/PlaceholderGlyph)은 FeaturedSpots.tsx와 동일 규칙을
 * 이 파일 안에서 재구현했다(그 파일은 이번 스코프의 편집 대상이 아니라 export를 늘리지 않음 —
 * LEVEL_META가 CourseMap.tsx/SpotCard.tsx/FeaturedSpots.tsx에 이미 3중 복제돼 있는 것과
 * 같은 관례를 따른다).
 */
function placeholderTone(category: SpotCategory): "mint" | "sand" | "azure" {
  if (category === "attraction" || category === "nature" || category === "trail") return "mint";
  if (category === "restaurant" || category === "cafe" || category === "market") return "sand";
  return "azure";
}

function PlaceholderGlyph() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="2" y="4" width="20" height="16" rx="3" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="8" cy="10" r="1.8" fill="currentColor" />
      <path
        d="M3 17l5-5 4 4 3-3 6 6"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

interface CourseStepCardProps {
  spot: CourseSpot;
  tagLabelMap: Record<string, string>;
}

/**
 * 타임라인 항목 1개 = [사진(또는 플레이스홀더)] + [기존 RecommendSpotCard: 이름·혼잡도·숨은/인기
 * 뱃지·매칭도] + [blurb 2줄 발췌]. image_url/blurb는 둘 다 null이면 조용히 생략한다(지어내지 않음,
 * 부록 I.12-2). 이미지 로드 실패(깨진 링크)도 플레이스홀더로 전환한다(FeaturedSpotCard와 동일 원칙).
 */
export default function CourseStepCard({ spot, tagLabelMap }: CourseStepCardProps) {
  const [imgFailed, setImgFailed] = useState(false);
  const showImage = !!spot.image_url && !imgFailed;

  return (
    <div className="course-step-card">
      <div className="course-step-card__media">
        {showImage ? (
          <img
            src={spot.image_url as string}
            alt=""
            loading="lazy"
            className="course-step-card__img"
            onError={() => setImgFailed(true)}
          />
        ) : (
          <div
            className={`featured-card__placeholder course-step-card__placeholder featured-card__placeholder--${placeholderTone(
              spot.category
            )}`}
          >
            <PlaceholderGlyph />
          </div>
        )}
      </div>
      {/* §34(신규, 부록 H.3) — 사진이 실제로 뜰 때만 사진 바로 아래에 작게 출처를 표기한다(저작권
          표기 준수용). FeaturedSpotCard는 사진 위 오버레이를 쓰지만, 이 카드는 사진 바로 아래
          바디(RecommendSpotCard)가 이어지는 리스트형 레이아웃이라 오버레이보다 사진 아래 캡션이
          "읽는 흐름"에 자연스럽다(03-design-spec.md §34 판단 근거). photo_credit이 없으면
          아무것도 렌더하지 않는다. */}
      {showImage && spot.photo_credit && (
        <p className="course-step-card__credit">{spot.photo_credit}</p>
      )}
      <div className="course-step-card__body">
        <RecommendSpotCard spot={spot} tagLabelMap={tagLabelMap} />
        {spot.blurb && <p className="course-step-card__blurb">{spot.blurb}</p>}
      </div>
    </div>
  );
}
