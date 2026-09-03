"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { animate, stagger } from "animejs";
import {
  BookOpenText,
  CalendarDays,
  Compass,
  Flower2,
  Gauge,
  Luggage,
  MapPinned,
  PartyPopper,
  Route,
  Stamp,
  type LucideIcon,
} from "lucide-react";
import { withRegionCode } from "../lib/regionQuery";

interface QuickMenuItem {
  key: string;
  label: string;
  href: string;
  icon: LucideIcon;
  /** 홈에서 고른 지역을 실제로 소비하는 목적지에만 지역 쿼리를 이어준다. */
  regionAware?: boolean;
}

/**
 * 홈의 10개 핵심 기능을 서로 다른 실제 화면으로 연결한다.
 * 아이콘은 여행 안내소의 픽토그램처럼 목적지를 즉시 연상할 수 있는 상징으로 통일했다.
 */
const QUICK_MENU_ITEMS: QuickMenuItem[] = [
  { key: "onboarding", label: "AI 취향분석", href: "/onboarding", icon: Luggage },
  {
    key: "recommend",
    label: "맞춤 추천",
    href: "/recommend",
    icon: Compass,
    regionAware: true,
  },
  { key: "course", label: "AI 코스", href: "/course", icon: Route, regionAware: true },
  { key: "regions", label: "지역별 여행", href: "/regions", icon: MapPinned },
  { key: "plan", label: "출발일 플래너", href: "/plan", icon: CalendarDays },
  { key: "seasonal", label: "계절 여행", href: "/seasonal", icon: Flower2 },
  { key: "board", label: "전국 혼잡 현황", href: "/congestion", icon: Gauge },
  { key: "stamp", label: "방문 스탬프", href: "/saved", icon: Stamp },
  { key: "festival", label: "축제", href: "/festivals", icon: PartyPopper },
  { key: "tips", label: "여행 팁", href: "/tips", icon: BookOpenText },
];

/** 같은 굵기와 비율을 유지하는 관광 안내형 퀵메뉴 아이콘. */
function QuickMenuIcon({ icon: Icon }: { icon: LucideIcon }) {
  return <Icon aria-hidden="true" focusable="false" strokeWidth={2.1} />;
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
    animate(items, {
      opacity: [0, 1],
      translateY: [12, 0],
      delay: stagger(35),
      duration: 420,
      ease: "outQuad",
    });
  }, [gridRef]);
}

export default function ServiceQuickMenu({ regionCode = null }: ServiceQuickMenuProps) {
  const gridRef = useRef<HTMLUListElement>(null);
  useQuickMenuEnterAnimation(gridRef);

  return (
    <nav className="quick-menu" aria-label="숨은길 서비스 바로가기">
      <h2 className="quick-menu__title">숨은길 서비스</h2>
      <ul className="quick-menu__grid" ref={gridRef}>
        {QUICK_MENU_ITEMS.map((item) => (
          <li key={item.key}>
            <Link
              href={item.regionAware ? withRegionCode(item.href, regionCode) : item.href}
              className="quick-menu__item"
            >
              <span className="quick-menu__icon">
                <QuickMenuIcon icon={item.icon} />
              </span>
              <span className="quick-menu__label">{item.label}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
