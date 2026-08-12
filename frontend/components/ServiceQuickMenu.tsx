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
  { key: "board", label: "전국 혼잡 지도", href: "/congestion" },
  { key: "stamp", label: "방문 스탬프", href: "/saved" },
  { key: "festival", label: "축제", href: "/festivals" },
  { key: "tips", label: "여행 팁", href: "/tips" },
];

/** 이모지 대신 인라인 SVG(ui-ux-pro-max 체크리스트 근거) — 코드베이스 전역의 기존 관례(FestivalGlyph 등)와 동일. */
function QuickMenuIcon({ menuKey }: { menuKey: string }) {
  switch (menuKey) {
    case "onboarding":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M12 3l1.8 5.6H20l-4.8 3.5 1.8 5.6L12 14.2 7 17.7l1.8-5.6L4 8.6h6.2L12 3z"
            fill="currentColor"
          />
        </svg>
      );
    case "recommend":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M12 20.2S3.8 15 3.8 9.4C3.8 6.4 6.1 4.5 8.6 4.5c1.5 0 2.9.8 3.4 2 .5-1.2 1.9-2 3.4-2 2.5 0 4.8 1.9 4.8 4.9 0 5.6-8.2 10.8-8.2 10.8z"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "course":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M4 19c3.5-1 4.2-6.2 8-6.2s4.5 5.2 8 6.2"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
          <circle cx="4" cy="19" r="1.7" fill="currentColor" />
          <circle cx="20" cy="19" r="1.7" fill="currentColor" />
          <path d="M12 5v4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          <circle cx="12" cy="3.4" r="1.6" fill="currentColor" />
        </svg>
      );
    case "regions":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M12 21.5S5 15 5 9.8a7 7 0 0114 0c0 5.2-7 11.7-7 11.7z"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinejoin="round"
          />
          <circle cx="12" cy="9.6" r="2.4" fill="currentColor" />
        </svg>
      );
    case "board":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M4 20V11M10 20V4M16 20v-6.5M3 20h18"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "stamp":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="8.5" stroke="currentColor" strokeWidth="1.8" />
          <path
            d="M8.2 12.4l2.4 2.4 5.2-5.4"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "festival":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M6 3v18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          <path
            d="M6 4.3l12 3.5L6 11.3"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinejoin="round"
            fill="currentColor"
            fillOpacity="0.22"
          />
        </svg>
      );
    case "tips":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M12 3.5a5.8 5.8 0 00-2.9 10.8c.6.4 1 1.1 1 1.9v.4h3.8v-.4c0-.8.4-1.5 1-1.9A5.8 5.8 0 0012 3.5z"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinejoin="round"
          />
          <path d="M10.1 19.5h3.8M10.8 22h2.4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
        </svg>
      );
    case "plan":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3.5" y="5" width="17" height="15.5" rx="2.4" stroke="currentColor" strokeWidth="1.7" />
          <path d="M3.5 9.5h17" stroke="currentColor" strokeWidth="1.7" />
          <path d="M8 3.5v3M16 3.5v3" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
          <circle cx="12" cy="14.5" r="1.8" fill="currentColor" />
        </svg>
      );
    case "seasonal":
      return (
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M12 3v18M3 12h18" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
          <path
            d="M12 3c2.4 2.2 2.4 6.6 0 9-2.4-2.4-2.4-6.8 0-9zM21 12c-2.2 2.4-6.6 2.4-9 0 2.4-2.4 6.8-2.4 9 0z"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinejoin="round"
            fill="currentColor"
            fillOpacity="0.2"
          />
        </svg>
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
