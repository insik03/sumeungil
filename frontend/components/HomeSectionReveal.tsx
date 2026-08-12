"use client";

import { useEffect, useLayoutEffect } from "react";
import { animate, onScroll } from "animejs";

/**
 * 홈의 각 섹션(컨시어지·발견 카드 2종·AI 코스 배너·축제 배너)이 스크롤로 화면에 들어올 때
 * 살짝 떠오르며 나타나는 입장 연출. 각 컴포넌트의 기존 클래스명만 셀렉터로 찾아 붙이는
 * 방식이라 5개 컴포넌트 내부는 전혀 건드리지 않는다(단일 소스, 추가 전용).
 *
 * ServiceQuickMenu는 자체 stagger 애니메이션(마운트 시 즉시 실행)이 이미 있어 여기서 제외한다
 * — 같이 넣으면 두 애니메이션이 겹쳐 어색해진다.
 *
 * useLayoutEffect를 쓰는 이유: useEffect(페인트 후 실행)면 SSR로 이미 그려진 섹션이 잠깐
 * 다 보였다가 갑자기 숨는 깜빡임(FOUC)이 생긴다. 페인트 전에 동기 실행해 처음부터 숨김
 * 상태로 그려지게 한다(SSR 경고 방지를 위해 서버에선 useEffect로 폴백).
 */
const useIsomorphicLayoutEffect = typeof window !== "undefined" ? useLayoutEffect : useEffect;

const REVEAL_SELECTOR = ".concierge, .featured-section, .course-promo, .festival-section";

export default function HomeSectionReveal() {
  useIsomorphicLayoutEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const sections = document.querySelectorAll<HTMLElement>(REVEAL_SELECTOR);
    if (sections.length === 0) return;

    const animations = Array.from(sections).map((el) =>
      animate(el, {
        opacity: [0, 1],
        translateY: [28, 0],
        duration: 600,
        ease: "outQuad",
        autoplay: onScroll({
          target: el,
          enter: "bottom-=5% top",
          sync: false,
          repeat: false,
        }),
      })
    );

    return () => {
      animations.forEach((a) => a.revert());
    };
  }, []);

  return null;
}
