"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { animate, stagger } from "animejs";
import { withRegionCode } from "../lib/regionQuery";

interface QuickMenuItem {
  key: string;
  label: string;
  href: string;
  /** 홈에서 고른 지역을 실제로 소비하는 목적지에만 지역 쿼리를 이어준다. */
  regionAware?: boolean;
}

/**
 * 홈의 10개 핵심 기능을 서로 다른 실제 화면으로 연결한다.
 * 아이콘 파일 이름은 key 와 1:1 이다(`public/quick-menu/<key>.gif`) — 항목을 추가하면
 * 같은 이름의 GIF·정지 프레임 PNG 를 같이 넣어야 한다.
 */
const QUICK_MENU_ITEMS: QuickMenuItem[] = [
  { key: "board", label: "혼잡 현황", href: "/congestion" },
  { key: "compare", label: "붐비는 곳 대신", href: "/compare", regionAware: true },
  { key: "course", label: "AI 코스", href: "/course", regionAware: true },
  { key: "recommend", label: "맞춤 추천", href: "/recommend", regionAware: true },
  { key: "onboarding", label: "AI 취향분석", href: "/onboarding" },
  { key: "regions", label: "지역별 여행", href: "/regions" },
  { key: "seasonal", label: "계절 여행", href: "/seasonal" },
  { key: "festival", label: "축제", href: "/festivals" },
  { key: "stamp", label: "방문 스탬프", href: "/saved" },
  { key: "tips", label: "여행 팁", href: "/tips" },
];

/**
 * 2026-09-20 대표 지시 — lucide 선 아이콘에서 GIF 로 교체했다. 에셋이 둥근 타일 배경까지
 * 품고 있어서 컨테이너(.quick-menu__icon)의 배경·테두리는 CSS 에서 걷어냈고, 이미지가 타일
 * 자리를 그대로 채운다.
 *
 * GIF 는 2초 무한 반복이고 CSS·JS 로 재생을 멈출 수단이 없다. 모션 최소화 설정에서는
 * <picture> 의 media 쿼리로 **정지 프레임 PNG** 를 대신 내보낸다(WCAG 2.2.2 "정지·중지·숨기기").
 * 정지 프레임은 첫 프레임이 아니라 그림이 가장 많이 그려진 프레임을 골라 뽑았다 — 축제·여행팁은
 * 첫 프레임이 거의 비어 있어서 그대로 쓰면 빈 타일이 된다.
 *
 * 라벨(.quick-menu__label)이 바로 옆에 같은 뜻으로 있으므로 이미지는 장식이다(alt="").
 */
function QuickMenuIcon({ itemKey }: { itemKey: string }) {
  return (
    <picture>
      <source media="(prefers-reduced-motion: reduce)" srcSet={`/quick-menu/${itemKey}-still.png`} />
      <img src={`/quick-menu/${itemKey}.gif`} alt="" aria-hidden="true" width={96} height={96} decoding="async" />
    </picture>
  );
}

interface ServiceQuickMenuProps {
  /** 홈에서 선택된 지역(sigungu_cd). null이면 쿼리를 붙이지 않는다. */
  regionCode?: string | null;
}

/**
 * 각 타일이 살짝 떠오르며 순서대로 나타난다.
 * 모션 최소화 사용자에게는 실행하지 않는다.
 */
function useQuickMenuEnterAnimation(gridRef: React.RefObject<HTMLUListElement>) {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const items = gridRef.current?.querySelectorAll("li");
    if (!items || items.length === 0) return;
    const animation = animate(items, {
      opacity: [0, 1],
      translateY: [12, 0],
      delay: stagger(35),
      duration: 420,
      ease: "outQuad",
    });
    return () => { animation.revert(); };
  }, [gridRef]);
}

// 2026-09-20 회의(모바일 단순화) — 모바일 첫 화면엔 핵심 4개만: 전국 혼잡 현황 · 붐비는 곳 대신 · AI 코스 · 맞춤 추천.
// 나머지는 "전체 메뉴 보기"로 펼친다. 데스크톱은 10개 전부 한 줄.
const CORE_KEYS = new Set(["board", "compare", "course", "recommend"]);

export default function ServiceQuickMenu({ regionCode = null }: ServiceQuickMenuProps) {
  const gridRef = useRef<HTMLUListElement>(null);
  useQuickMenuEnterAnimation(gridRef);
  const [expanded, setExpanded] = useState(false);

  return (
    <nav className={`quick-menu${expanded ? " is-expanded" : ""}`} aria-label="숨은길 서비스 바로가기">
      <h2 className="quick-menu__title">숨은길 서비스</h2>
      <ul className="quick-menu__grid" ref={gridRef}>
        {QUICK_MENU_ITEMS.map((item) => (
          <li key={item.key} data-core={CORE_KEYS.has(item.key) ? "" : undefined}>
            <Link
              href={item.regionAware ? withRegionCode(item.href, regionCode) : item.href}
              className="quick-menu__item"
            >
              <span className="quick-menu__icon">
                <QuickMenuIcon itemKey={item.key} />
              </span>
              <span className="quick-menu__label">{item.label}</span>
            </Link>
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="quick-menu__more"
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
      >
        {expanded ? "메뉴 접기" : "전체 메뉴 보기"}
      </button>
    </nav>
  );
}
