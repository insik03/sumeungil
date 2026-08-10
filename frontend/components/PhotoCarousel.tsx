"use client";

import { useEffect, useRef, useState } from "react";
import { MediaImage } from "../lib/api";

/**
 * §36(신규, 03-design-spec.md) — 공용 사진 슬라이더. 스팟 상세 히어로 / 축제 상세 공용(단일 소스,
 * 지시서: "사진 슬라이더 공용 컴포넌트").
 *
 * 이미지 균일화 규칙(이 코드베이스 반복 버그, §33-4 승계): 컨테이너 aspect-ratio + overflow:hidden +
 * img position:absolute inset:0 object-fit:cover — 원본 비율이 무엇이든 슬라이드 비율이 밀리지 않는다.
 * 기본 비율은 4:3 — Hero.tsx의 .hero-carousel__card(몰입형 사진 카드)와 동일 비율을 재사용한다
 * (목록 크롭 8:5/2:1과 구분되는 "상세 히어로" 전용 비율을 새로 만들지 않고 이미 검증된 값을 그대로 씀).
 *
 * 0장: placeholder 정적 표시(컨트롤 없음). 1장: 사진 정적 표시(컨트롤 없음). 2장+: 좌우 화살표 +
 * 스와이프(가로 scroll-snap) + 하단 도트. Hero.tsx의 programmaticScrollRef 패턴을 그대로 승계해
 * "프로그램적 스크롤 도중 스크롤 이벤트가 인덱스를 되돌리는" StrictMode/자동 순환 버그를 예방한다
 * (이 캐러셀엔 자동 순환이 없지만, 화살표/도트 클릭도 동일한 프로그램적 스크롤이라 같은 문제가
 * 재현될 수 있다 — Hero.tsx 주석 근거 그대로 승계).
 */

export interface PhotoCarouselProps {
  images: MediaImage[];
  /** 사진 없음/개별 사진 로드 실패 시 보여줄 아이콘(예: PlaceholderGlyph, FestivalGlyph). */
  placeholderIcon: React.ReactNode;
  placeholderTone: "mint" | "sand" | "azure" | "festival";
  /** 캐러셀 영역 전체의 접근성 라벨(예: "경복궁 사진"). */
  ariaLabel: string;
  className?: string;
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function PrevIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M15 5l-7 7 7 7"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function NextIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M9 5l7 7-7 7"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function PhotoCarousel({
  images,
  placeholderIcon,
  placeholderTone,
  ariaLabel,
  className,
}: PhotoCarouselProps) {
  const count = images.length;
  const [activeIndex, setActiveIndex] = useState(0);
  const [failedIndices, setFailedIndices] = useState<Set<number>>(new Set());
  const trackRef = useRef<HTMLDivElement>(null);
  const scrollRafRef = useRef<number | null>(null);
  const programmaticScrollRef = useRef(false);
  const programmaticTimerRef = useRef<number>(0);

  // 이미지 배열 자체가 바뀌면(다른 스팟/축제로 이동) 인덱스·실패 기록을 초기화한다.
  useEffect(() => {
    setActiveIndex(0);
    setFailedIndices(new Set());
  }, [images]);

  // activeIndex가 바뀌면(화살표·도트 클릭) 트랙을 해당 슬라이드로 스크롤한다.
  // ★ scrollIntoView 금지(Hero.tsx와 동일 이유) — 트랙 자신만 scrollTo로 가로 이동시킨다.
  useEffect(() => {
    if (count < 2) return;
    const track = trackRef.current;
    const slide = track?.children[activeIndex] as HTMLElement | undefined;
    if (!track || !slide) return;
    const trackRect = track.getBoundingClientRect();
    const slideRect = slide.getBoundingClientRect();
    const left = track.scrollLeft + (slideRect.left - trackRect.left);
    // smooth 스크롤이 도착할 때까지 스와이프 동기화를 잠근다(도착 전 동기화가 인덱스를 되돌리는 것 방지).
    programmaticScrollRef.current = true;
    window.clearTimeout(programmaticTimerRef.current);
    track.scrollTo({ left, behavior: prefersReducedMotion() ? "auto" : "smooth" });
    programmaticTimerRef.current = window.setTimeout(
      () => {
        programmaticScrollRef.current = false;
      },
      prefersReducedMotion() ? 120 : 500
    );
    return () => window.clearTimeout(programmaticTimerRef.current);
  }, [activeIndex, count]);

  // 사용자가 직접 스와이프했을 때도 도트가 따라가도록 트랙 중앙에 가장 가까운 슬라이드를 찾는다.
  const handleTrackScroll = () => {
    if (programmaticScrollRef.current) return;
    if (scrollRafRef.current !== null) return;
    scrollRafRef.current = requestAnimationFrame(() => {
      scrollRafRef.current = null;
      const track = trackRef.current;
      if (!track) return;
      const trackRect = track.getBoundingClientRect();
      const centerX = trackRect.left + trackRect.width / 2;
      let closest = 0;
      let closestDist = Infinity;
      Array.from(track.children).forEach((child, i) => {
        const rect = (child as HTMLElement).getBoundingClientRect();
        const dist = Math.abs(rect.left + rect.width / 2 - centerX);
        if (dist < closestDist) {
          closestDist = dist;
          closest = i;
        }
      });
      setActiveIndex((prev) => (prev === closest ? prev : closest));
    });
  };

  useEffect(() => {
    return () => {
      if (scrollRafRef.current !== null) cancelAnimationFrame(scrollRafRef.current);
    };
  }, []);

  const goPrev = () => setActiveIndex((i) => (i - 1 + count) % count);
  const goNext = () => setActiveIndex((i) => (i + 1) % count);

  const markFailed = (i: number) =>
    setFailedIndices((prev) => {
      if (prev.has(i)) return prev;
      const next = new Set(prev);
      next.add(i);
      return next;
    });

  const placeholder = (
    <div className={`photo-carousel__placeholder photo-carousel__placeholder--${placeholderTone}`}>
      {placeholderIcon}
    </div>
  );

  const renderSlide = (img: MediaImage | null, index: number) => {
    const failed = img ? failedIndices.has(index) : false;
    const showImg = !!img && !failed;
    return (
      <div className="photo-carousel__slide" role={count > 1 ? "listitem" : undefined} key={img ? `${img.url}-${index}` : "placeholder"}>
        {showImg ? (
          <img
            src={(img as MediaImage).url}
            alt=""
            loading={index === 0 ? "eager" : "lazy"}
            className="photo-carousel__img"
            onError={() => markFailed(index)}
          />
        ) : (
          placeholder
        )}
        {showImg && img?.credit && <span className="photo-carousel__credit">{img.credit}</span>}
      </div>
    );
  };

  if (count === 0) {
    return (
      <div className={`photo-carousel photo-carousel--static ${className ?? ""}`.trim()} aria-label={ariaLabel}>
        {renderSlide(null, 0)}
      </div>
    );
  }

  if (count === 1) {
    return (
      <div className={`photo-carousel photo-carousel--static ${className ?? ""}`.trim()} aria-label={ariaLabel}>
        {renderSlide(images[0], 0)}
      </div>
    );
  }

  return (
    <div className={`photo-carousel ${className ?? ""}`.trim()} role="region" aria-label={ariaLabel}>
      <div className="photo-carousel__track" ref={trackRef} onScroll={handleTrackScroll} role="list">
        {images.map((img, i) => renderSlide(img, i))}
      </div>

      <button
        type="button"
        className="photo-carousel__arrow photo-carousel__arrow--prev"
        aria-label="이전 사진"
        onClick={goPrev}
      >
        <PrevIcon />
      </button>
      <button
        type="button"
        className="photo-carousel__arrow photo-carousel__arrow--next"
        aria-label="다음 사진"
        onClick={goNext}
      >
        <NextIcon />
      </button>

      <div className="photo-carousel__dots" role="tablist" aria-label="사진 선택">
        {images.map((_, i) => (
          <button
            key={i}
            type="button"
            role="tab"
            aria-selected={i === activeIndex}
            aria-label={`${i + 1}번째 사진`}
            className={`photo-carousel__dot${i === activeIndex ? " is-active" : ""}`}
            onClick={() => setActiveIndex(i)}
          />
        ))}
      </div>
    </div>
  );
}
