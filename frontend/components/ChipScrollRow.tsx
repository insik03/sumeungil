"use client";

import { useEffect, useRef, useState } from "react";

interface ChipScrollRowProps {
  children: React.ReactNode;
}

/**
 * §33-2(2026-07-29, 03-design-spec.md) — 칩 가로 스크롤 "더 있음" 시각 신호.
 *
 * 진단: `.chip-row--scroll`(§30) 자체는 이미 `overflow-x:auto`로 정상 스크롤된다 — 실측 결과
 * 문제는 스크롤이 "안 되는" 게 아니라, 끝나는 지점에 아무 시각 신호가 없어 "칩 목록이 거기서
 * 잘려 끝났다"고 오인되는 것(대표 리포트 원인)이었다.
 *
 * 수정: 스크롤 컨테이너의 scrollLeft/scrollWidth를 추적해 시작/끝이 아닐 때만 해당 방향의
 * 흰색 그라데이션 페이드를 보여준다(오른쪽 끝이 아니면 항상 오른쪽 페이드가 보인다 — "더 있음"
 * 신호). Hero.tsx(홈)·RegionPicker.tsx(추천)·FestivalRegionFilter.tsx(축제) 3곳이 동일 규약
 * (`.chip-row--scroll`)을 공유하므로 이 컴포넌트 하나로 로직을 재사용한다(중복 구현 금지).
 * 나머지 두 신호(마지막 칩 반쯤 걸치기·데스크톱 hover 스크롤바)는 순수 CSS(globals.css §33-2)다.
 */
export default function ChipScrollRow({ children }: ChipScrollRowProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [atStart, setAtStart] = useState(true);
  const [atEnd, setAtEnd] = useState(true);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const update = () => {
      setAtStart(el.scrollLeft <= 1);
      setAtEnd(el.scrollLeft + el.clientWidth >= el.scrollWidth - 1);
    };
    update();

    el.addEventListener("scroll", update, { passive: true });
    // 뷰포트 리사이즈 등으로 clientWidth/scrollWidth가 바뀌는 경우까지 커버한다.
    const ro = new ResizeObserver(update);
    ro.observe(el);

    return () => {
      el.removeEventListener("scroll", update);
      ro.disconnect();
    };
  }, []);

  const wrapClassName = `chip-row-fade${atStart ? "" : " chip-row-fade--start"}${
    atEnd ? "" : " chip-row-fade--end"
  }`;

  return (
    <div className={wrapClassName}>
      <div className="chip-row chip-row--scroll" ref={scrollRef}>
        {children}
      </div>
    </div>
  );
}
