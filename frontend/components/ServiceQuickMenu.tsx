"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { animate, stagger } from "animejs";
import { withRegionCode } from "../lib/regionQuery";

interface QuickMenuItem {
  key: string;
  label: string;
  href: string;
  /**
   * §35(2026-07-31, 백로그 D21) — 홈에서 고른 지역을 쿼리로 이어받는 목적지인지. 지역 쿼리를
   * 실제로 소비하는 화면(/recommend, /course)만 true다 — 소비하지 않는 화면에 파라미터를
   * 붙이면 아무 효과 없는 URL 노이즈만 남는다.
   */
  regionAware?: boolean;
}

/**
 * §24(03-design-spec.md, 2026-07-29) — 구석구석 포털의 "서비스 퀵메뉴" 문법을 재해석했다.
 * 8개 전부 기존 실재 라우트/앵커만 사용한다(신규 라우트·신규 API 없음):
 * - #board는 홈 내부 섹션 앵커. HomeContent.tsx가 CongestionBoard section에 id="board"를
 *   부여했다(globals.css가 scroll-margin-top으로 고정 GNB 높이만큼 여유를 둔다).
 * - "축제" 타일(§27, 신규)은 홈 내부 앵커(#festival) 대신 전용 페이지 `/festivals`로 바뀌었다 —
 *   전국 354건을 홈의 6개 미리보기 카드로는 다 보여줄 수 없어(§27 근거) 별도 라우트를 만들었다.
 *   홈의 #festival 섹션(FestivalBanner)은 그대로 남아 미리보기 역할을 하고, 그 안에도
 *   "전국 축제 모두 보기 →" 링크로 같은 목적지를 안내한다(additive, FestivalBanner.tsx 참고).
 *
 * §29(신규, 03-design-spec.md, /regions 지역 허브) — "핫플 비교" 타일을 "지역별 여행"으로
 * 교체했다(9개로 늘리지 않고 8개 유지 — grid-template-columns: repeat(4,1fr) 4×2 균형을
 * 그대로 보존, 5번째 행에 1개만 남는 불균형을 피함). 교체 근거: "핫플 비교" 타일은 href가
 * "/recommend"로 바로 위 "맞춤 추천" 타일과 목적지가 완전히 동일한 죽은 중복이었다(비교 기능
 * 자체는 스팟 상세 화면의 "핫플과 비교하기" 버튼으로만 진입하도록 이미 이관되어 있어 — 부록
 * D §D.7-1 — 이 타일이 안내하던 "/recommend"는 비교와 무관한 일반 추천 목록일 뿐이었다).
 * 따라서 제거해도 기능 손실이 없고(비교는 여전히 추천→상세 흐름으로 도달 가능), 대신 지금까지
 * 퀵메뉴에 없던 신규 목적지(/regions)를 넣어 8개 전부가 서로 다른 화면을 가리키게 됐다.
 */
const QUICK_MENU_ITEMS: QuickMenuItem[] = [
  { key: "onboarding", label: "AI 취향분석", href: "/onboarding" },
  { key: "recommend", label: "맞춤 추천", href: "/recommend", regionAware: true },
  { key: "course", label: "AI 코스", href: "/course", regionAware: true },
  { key: "regions", label: "지역별 여행", href: "/regions" },
  // §38(2026-07-31) — 홈에서 덜어낸 두 기능의 전용 페이지 진입점(대표 지시: 홈에 쌓지 말 것).
  { key: "plan", label: "출발일 플래너", href: "/plan" },
  { key: "seasonal", label: "계절 여행", href: "/seasonal" },
  { key: "board", label: "전국 혼잡 현황", href: "/congestion" },
  { key: "stamp", label: "방문 스탬프", href: "/saved" },
  { key: "festival", label: "축제", href: "/festivals" },
  { key: "tips", label: "여행 팁", href: "/tips" },
];

/**
 * 작은 원형 배지에서도 한 세트로 읽히도록 24px 좌표계, 1.75px 선, 둥근 끝을 공통 적용한다.
 * 완벽한 기하 도형보다 살짝 비대칭인 한두 개의 선과 점으로 여행 수첩에 그린 픽토그램처럼 정리했다.
 */
function QuickMenuSvg({ children }: { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

function QuickMenuIcon({ menuKey }: { menuKey: string }) {
  switch (menuKey) {
    case "onboarding":
      return (
        <QuickMenuSvg>
          <path d="M12 20v-4.2c0-2.2-1.5-3.3-3.4-4.5C7 10.3 6 8.8 6 6.5" />
          <path d="M12 15.8c0-2.2 1.3-3.4 3.2-4.6 1.6-1 2.8-2.3 2.8-4.5" />
          <circle cx="6" cy="5" r="1.35" fill="currentColor" stroke="none" />
          <circle cx="18" cy="5.2" r="1.35" fill="currentColor" stroke="none" />
          <circle cx="12" cy="20.2" r="1.35" fill="currentColor" stroke="none" />
        </QuickMenuSvg>
      );
    case "recommend":
      return (
        <QuickMenuSvg>
          <path d="M12 3.4c4.9 0 8.5 3.5 8.5 8.3 0 4.9-3.7 8.9-8.5 8.9s-8.5-4-8.5-8.9c0-4.8 3.6-8.3 8.5-8.3Z" />
          <path d="m15.8 7.7-2.2 5.8-5.4 2.8 2.1-6Z" />
          <circle cx="12" cy="12" r="1.15" fill="currentColor" stroke="none" />
        </QuickMenuSvg>
      );
    case "course":
      return (
        <QuickMenuSvg>
          <path d="M6.3 18.4c3.5-.7 2.1-5.7 5.7-6.1 3.4-.4 2.4-5.2 5.8-6.4" />
          <circle cx="4.8" cy="18.7" r="1.55" fill="currentColor" stroke="none" />
          <path d="m15.7 5.1 3.5.2-.5 3.5" />
          <path d="M9.2 20.4c2.6.5 5.6.3 8.2-1" strokeDasharray="1.2 2.4" />
        </QuickMenuSvg>
      );
    case "regions":
      return (
        <QuickMenuSvg>
          <path d="m3.5 6.7 5.3-2.5 6.3 2.3 5.4-2.3v13.5l-5.4 2.5-6.3-2.3-5.3 2.3Z" />
          <path d="M8.8 4.2v13.7M15.1 6.5v13.7" />
          <path d="M5.5 13.6c1.2-.9 2.1-1 3.3-.5 1.9.8 3.9.4 6.3-1.5 1.8-1.4 3.4-1.5 5.4-.7" />
        </QuickMenuSvg>
      );
    case "board":
      return (
        <QuickMenuSvg>
          <path d="M4 6.2h16" />
          <path d="M4 12c2.4-1.8 4.3 1.8 6.7 0s4.5 1.8 6.8 0c.9-.7 1.7-.8 2.5-.4" />
          <path d="M4 17.8h16" />
          <circle cx="7" cy="6.2" r="1.25" fill="currentColor" stroke="none" />
          <circle cx="12.2" cy="12" r="1.25" fill="currentColor" stroke="none" />
          <circle cx="17" cy="17.8" r="1.25" fill="currentColor" stroke="none" />
        </QuickMenuSvg>
      );
    case "stamp":
      return (
        <QuickMenuSvg>
          <path d="M9.2 13.5c.7-1.5 1-2.5.6-4.2-.6-2.8.5-4.7 2.2-4.7s2.8 1.9 2.2 4.7c-.4 1.7-.1 2.7.6 4.2" />
          <path d="M7.5 13.5h9l2.2 4.3H5.3Z" />
          <path d="M4.5 20.7c4.9-.8 10.1-.8 15 0" />
        </QuickMenuSvg>
      );
    case "festival":
      return (
        <QuickMenuSvg>
          <path d="M3.5 6.2c4 2.7 12.8 3 17 .1" />
          <path d="m6.2 7.5.6 4 2.6-2.9M11.2 8.6l1 4 2.2-3.8M16.2 8.4l1.1 3.6 2-4.4" />
          <path d="M5.5 18.6c2-2.1 4.1-2.2 6.2-.2 2.3 2.2 4.6 2 6.8-.4" strokeDasharray="1.2 2.3" />
        </QuickMenuSvg>
      );
    case "tips":
      return (
        <QuickMenuSvg>
          <path d="M6 3.5h9l3 3v14H6Z" />
          <path d="M15 3.5v3h3M9 10.3h6M9 13.8h5.2M9 17.3h3.5" />
          <path d="M6 6H4.5M6 10H4.5M6 14H4.5M6 18H4.5" />
        </QuickMenuSvg>
      );
    case "plan":
      return (
        <QuickMenuSvg>
          <path d="M5.4 5.7h13.2c1.1 0 1.9.8 1.9 1.9v11c0 1.1-.8 1.9-1.9 1.9H5.4c-1.1 0-1.9-.8-1.9-1.9v-11c0-1.1.8-1.9 1.9-1.9Z" />
          <path d="M3.5 9.6h17M8 3.5v4M16 3.5v4" />
          <path d="M7.5 16.8c1.5-2.4 3.1.5 4.6-1.7 1.1-1.6 2.5-1.9 4.4-1" />
          <circle cx="7.3" cy="17" r="1" fill="currentColor" stroke="none" />
        </QuickMenuSvg>
      );
    case "seasonal":
      return (
        <QuickMenuSvg>
          <path d="M12 11.9c-3.5-.3-5.7-2.5-5.8-6 3.5-.1 5.7 2.3 5.8 6Z" />
          <path d="M12.1 11.9c.4-3.5 2.7-5.6 6.1-5.6 0 3.5-2.4 5.6-6.1 5.6Z" />
          <path d="M12 12.1c3.5.3 5.7 2.5 5.8 6-3.5.1-5.7-2.3-5.8-6Z" />
          <path d="M11.9 12.1c-.4 3.5-2.7 5.6-6.1 5.6 0-3.5 2.4-5.6 6.1-5.6Z" />
          <circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none" />
        </QuickMenuSvg>
      );
    default:
      return null;
  }
}

interface ServiceQuickMenuProps {
  /** §35 — 홈에서 선택된 지역(sigungu_cd). null이면 쿼리를 붙이지 않는다(기존 동작 그대로). */
  regionCode?: string | null;
}

/** 각 타일이 살짝 떠오르며 순서대로 나타나는 입장 애니메이션(anime.js). Hero.tsx의
 * prefersReducedMotion 관례를 그대로 따라 모션 최소화 사용자에겐 아예 실행하지 않는다. */
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
                <QuickMenuIcon menuKey={item.key} />
              </span>
              <span className="quick-menu__label">{item.label}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
