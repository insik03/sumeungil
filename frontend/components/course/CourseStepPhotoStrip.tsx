"use client";

import { useState } from "react";
import { CourseSpot, SpotCategory } from "../../lib/api";

/** CourseStepCard.tsx와 동일한 플레이스홀더 톤 규칙(작은 헬퍼 재복제 — 위 파일 주석 참고). */
function placeholderTone(category: SpotCategory): "mint" | "sand" | "azure" {
  if (category === "attraction" || category === "nature" || category === "trail") return "mint";
  if (category === "restaurant" || category === "cafe" || category === "market") return "sand";
  return "azure";
}

function StripThumb({ spot }: { spot: CourseSpot }) {
  const [imgFailed, setImgFailed] = useState(false);
  const showImage = !!spot.image_url && !imgFailed;
  return showImage ? (
    <img
      src={spot.image_url as string}
      alt=""
      loading="lazy"
      className="course-photo-strip__img"
      onError={() => setImgFailed(true)}
    />
  ) : (
    <div
      className={`course-photo-strip__placeholder featured-card__placeholder--${placeholderTone(spot.category)}`}
      aria-hidden="true"
    />
  );
}

interface CourseStepPhotoStripProps {
  spots: CourseSpot[];
  /** 각 스텝의 앵커 id(course-timeline__item과 동일 규칙, CourseTimelinePanel이 생성해 넘긴다). */
  stepIds: string[];
}

/**
 * §28(신규, 06-deep-audit-gap-plan §2-B B-9 대응) — "코스 전체를 사진으로 훑는" 가로 스트립.
 * 순번 배지 + 썸네일 + 스팟명을 <a href="#course-step-N">으로 감싼다 — 클릭하면 네이티브 앵커
 * 이동으로 해당 타임라인 항목까지 스크롤된다(전역 html { scroll-behavior: smooth } +
 * .course-timeline__item { scroll-margin-top } 재사용, 별도 스크롤 JS 없음 — globals.css §28 참고).
 * 지도(CourseMap)의 번호 마커와 같은 순번 규칙(1부터)을 쓰지만 이 스트립은 지도가 실패해도
 * (SDK 로드 실패) 항상 동작한다 — 타임라인이 정본이라는 사이트 원칙을 사진 훑기에도 적용.
 */
export default function CourseStepPhotoStrip({ spots, stepIds }: CourseStepPhotoStripProps) {
  if (spots.length < 2) return null;

  return (
    <nav className="course-photo-strip" aria-label="코스 스텝 사진으로 훑어보기">
      {spots.map((spot, i) => (
        <a key={spot.id} href={`#${stepIds[i]}`} className="course-photo-strip__item">
          <span className="course-photo-strip__num" aria-hidden="true">
            {i + 1}
          </span>
          <span className="course-photo-strip__thumb">
            <StripThumb spot={spot} />
          </span>
          <span className="course-photo-strip__name">{spot.name}</span>
        </a>
      ))}
    </nav>
  );
}
