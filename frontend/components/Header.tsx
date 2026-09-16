"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import ConsentModal from "./ConsentModal";
import LoginModal from "./LoginModal";
import { logout, syncSessionFromServer } from "../lib/authStorage";
import { useLoggedInName } from "../lib/useLoggedInName";

/**
 * 헤더 네비게이션 — GNB 개편(§39, 대표 지시: "키워드가 겹치는 건 하위 목록, 안 겹치면 새 메뉴").
 * 상단 항목 자체도 실제 라우트로 연결되고, 겹치는 항목은 hover/focus 시 드롭다운으로 하위 화면을
 * 노출한다. children이 없는 항목은 기존과 동일하게 단일 링크로 렌더된다.
 *
 * 지역 컨텍스트(§35 withRegionCode)는 헤더가 전역이라 붙이지 않는다(기존 결정 유지).
 *
 * §A-2(2026-08-01, 03-design-spec.md §43) — "여행지 추천" 드롭다운에 "테마별 여행"(`/themes`)을
 * 추가했다. 홈에서 뺀 ThemeCollections(§A, HomeContent.tsx)의 새 진입점 — "지역별 여행" 바로
 * 옆에 둬 "지역으로 고르기 / 테마로 고르기"가 대칭을 이루게 했다. 퀵메뉴(ServiceQuickMenu, 10개)
 * 는 지시서 제약대로 개수를 유지하며 건드리지 않았다.
 */
interface NavChild {
  label: string;
  href: string;
}
interface NavItem {
  label: string;
  href: string;
  children?: NavChild[];
}

const NAV_ITEMS: NavItem[] = [
  { label: "홈", href: "/" },
  {
    label: "여행지 추천",
    href: "/recommend",
    children: [
      { label: "맞춤 추천", href: "/recommend" },
      // 2026-08-24(대표 지시) — "여행지 추천" 드롭다운에서 "AI 취향분석"(/onboarding) 항목 제거.
      // §47.7과 같은 패턴: 라우트 자체(/onboarding)는 그대로 두고(코스짜기 의견입력에서 재사용
      // 중) 이 메뉴 진입점만 뺀다.
      { label: "지역별 여행", href: "/regions" },
      { label: "테마별 여행", href: "/themes" },
      { label: "계절 여행", href: "/seasonal" },
    ],
  },
  {
    label: "AI 여행 경로",
    href: "/course",
    children: [
      { label: "AI 코스 짜기", href: "/course" },
      // §47.7(2026-08-20) — "AI 여행 문답"(/ask) 항목 제거. 컨시어지 화면이 삭제되고 같은 니즈는
      // /course AI 모드 상단 의견 입력으로 흡수됐다(§47.3).
      // §41(신규) — 다른 사람이 공유한 코스 피드(/courses). 퀵메뉴(ServiceQuickMenu, 10개 유지)는
      // 건드리지 않고 GNB 드롭다운에만 추가한다(지시서 요구사항).
      { label: "다른 사람 코스", href: "/courses" },
    ],
  },
  {
    label: "혼잡도·시기",
    href: "/congestion",
    children: [
      { label: "전국 혼잡 현황", href: "/congestion" },
      // 부록 D.7(2026-08-01) — 지정과제2("쏠림 완화")에 가장 직결되는 기능인데 GNB·퀵메뉴 어디에도
      // 진입점이 없어 스팟 상세를 통해서만 닿을 수 있었다. 독립 목적지로 승격한다.
      { label: "붐비는 곳 대신", href: "/compare" },
      // 2026-09-05(대표) — 출발일 플래너는 메뉴에서 뺀다. /plan 페이지는 남긴다(혼잡현황이 임베드).
    ],
  },
  { label: "축제", href: "/festivals" },
  { label: "저장한 코스", href: "/saved" },
  { label: "여행 팁", href: "/tips" },
];

/** href에서 해시(#board 등)를 뗀 순수 경로. 앵커만 있는 값("")은 별도 라우트가 아니므로 매칭 대상에서 뺀다. */
function pathOf(href: string): string {
  const idx = href.indexOf("#");
  return idx === -1 ? href : href.slice(0, idx);
}

/**
 * 현재 경로 강조 여부. "/"는 홈 항목만 매칭하고("혼잡도·시기"의 "/#board"처럼 pathOf가 "/"로
 * 뭉개지는 앵커 링크는 홈과 동시에 강조되지 않도록 별도 취급), 나머지는 정확히 일치할 때만 켠다.
 */
function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  const p = pathOf(href);
  if (!p || p === "/") return false;
  return pathname === p;
}

/**
 * 붐비는 큰길(잉크색)에서 한적한 샛길(브랜드 그린)이 갈라지는 모습을 한 획처럼 단순화한 심볼.
 * currentColor를 함께 써서 흰 GNB와 짙은 모바일 메뉴 양쪽에서 외곽선이 자연스럽게 반전된다.
 */
function BrandMark() {
  return (
    <svg
      width="30"
      height="30"
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      focusable="false"
      style={{ flex: "0 0 auto" }}
    >
      <circle cx="6.2" cy="26.2" r="1.8" fill="currentColor" />
      <path
        d="M6.4 24.2c.8-3.7 5.6-4.8 5.8-8.3.2-3.2-3.5-4.2-2.7-7 .5-1.9 2.5-3.5 5.5-4.1"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      <path
        d="M12.1 16.1c3.6-.1 5.1-1.8 4.7-4.5-.4-3.1 1.7-5.7 6.6-6.1"
        stroke="var(--g-500)"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      <path
        d="m20.8 4.3 3.2.7-.9 3"
        stroke="var(--g-500)"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function Header() {
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const [navOpen, setNavOpen] = useState(false);
  const [openLabel, setOpenLabel] = useState<string | null>(null);
  const nickname = useLoggedInName();
  const [loginOpen, setLoginOpen] = useState(false);
  // 2026-09-14 — 서버가 "현재 약관 버전 미동의"라고 하면 한 번 동의 모달을 띄운다(ConsentModal.tsx).
  const [consentOpen, setConsentOpen] = useState(false);
  const triggerRefs = useRef<Record<string, HTMLAnchorElement | null>>({});
  // Esc 로 닫은 직후 포커스를 트리거로 되돌리면 onFocus 가 즉시 다시 열어버린다(실측 확인).
  // "이 항목은 방금 Esc 로 닫았다"를 기억해 두고, 포커스가 그룹 밖으로 나가거나 마우스가
  // 다시 들어올 때 해제한다 — 그래야 Esc 가 실제로 닫힌 상태로 남는다.
  const escDismissedRef = useRef<string | null>(null);

  // 로그인 상태 자체는 useLoggedInName()이 읽는다(authStorage 실시간 반영). 여기서는
  // 부팅 시 서버 세션 동기화만 1회 튼다. "계정 삭제" 버튼(과 그 2단계 확인 상태)은
  // 2026-08-17 대표 지시로 /mypage(MyPageContent.tsx)로 옮겨서 여기엔 더 없다.
  useEffect(() => {
    void syncSessionFromServer().then((info) => {
      // QA M-2 — 부팅 시 1회, 서버 세션 진실과 로컬 캐시를 맞춘다. 2026-09-14: 약관 미동의면 동의 모달.
      if (info?.authenticated && info.terms_agreed === false) setConsentOpen(true);
    });
  }, []);

  // 관리자 콘솔은 일반 서비스 셸을 공유하지 않는다(03-admin-console-design.md §4).
  //   - 운영 화면인 줄 모르고 조작하는 사고를 막으려면 시각적으로 확실히 갈라져야 한다.
  //   - GNB 의 로그인 모달·닉네임 상태는 **일반 사용자용**이라 관리자 세션과 개념이 다르다.
  //     한 화면에 둘 다 있으면 "어느 쪽으로 로그인한 건지" 혼동이 생긴다.
  // app/<경로>/layout.tsx 로는 이걸 못 한다 — 중첩 레이아웃은 부모를 감쌀 뿐 제거하지 못한다.
  // 기존 페이지를 전부 route group 으로 옮기는 대공사 대신, 여기서 스스로 빠지게 했다.
  // 훅은 전부 위에서 호출된 뒤이므로 훅 순서 규칙을 어기지 않는다.
  // 경로 자체가 무작위 문자열이다(2026-08-18, app/ops-37878f1b71/page.tsx 주석 참고) —
  // 바뀌면 이 상수도 같이 바꿔야 한다.
  const ADMIN_PATH = "/ops-37878f1b71";
  if (pathname === ADMIN_PATH || pathname.startsWith(`${ADMIN_PATH}/`)) return null;

  return (
    <>
      <div className="gnb">
        <div className="gnb__inner">
          <Link className="gnb__logo" href="/" aria-label="숨은길 홈으로">
            <BrandMark />
            <span>숨은길</span>
          </Link>
          <nav className="gnb__menu" aria-label="주요 메뉴">
            {NAV_ITEMS.map((item) => {
              if (!item.children?.length) {
                const active = isActive(pathname, item.href);
                return (
                  <Link
                    key={item.label}
                    href={item.href}
                    className={active ? "is-active" : undefined}
                    aria-current={active ? "page" : undefined}
                  >
                    {item.label}
                  </Link>
                );
              }

              const childActive = item.children.some((c) => isActive(pathname, c.href));
              const selfActive = isActive(pathname, item.href) || childActive;
              const isOpen = openLabel === item.label;

              return (
                <div
                  key={item.label}
                  className={`gnb__dropdown${isOpen ? " is-open" : ""}`}
                  onMouseEnter={() => {
                    escDismissedRef.current = null;
                    setOpenLabel(item.label);
                  }}
                  onMouseLeave={() => setOpenLabel((cur) => (cur === item.label ? null : cur))}
                  onFocus={() => {
                    if (escDismissedRef.current === item.label) return;
                    setOpenLabel(item.label);
                  }}
                  onBlur={(e) => {
                    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                      escDismissedRef.current = null; // 그룹을 벗어나면 Esc 기억을 푼다
                      setOpenLabel((cur) => (cur === item.label ? null : cur));
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") {
                      escDismissedRef.current = item.label;
                      setOpenLabel(null);
                      triggerRefs.current[item.label]?.focus();
                    }
                  }}
                >
                  <Link
                    href={item.href}
                    className={`gnb__dropdown-trigger${selfActive ? " is-active" : ""}`}
                    aria-haspopup="true"
                    aria-expanded={isOpen}
                    ref={(el) => {
                      triggerRefs.current[item.label] = el;
                    }}
                  >
                    {item.label}
                  </Link>
                  <ul className="gnb__dropdown-panel">
                    {item.children.map((child) => {
                      const active = isActive(pathname, child.href);
                      return (
                        <li key={child.label}>
                          <Link
                            href={child.href}
                            className={active ? "is-active" : undefined}
                            aria-current={active ? "page" : undefined}
                            onClick={() => setOpenLabel(null)}
                          >
                            {child.label}
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              );
            })}
          </nav>
          <div className="gnb__actions">
            {nickname ? (
              <>
                <Link className="gnb__greeting" href="/mypage">
                  {nickname}님
                </Link>
                <button
                  className="btn btn--ghost-text"
                  type="button"
                  onClick={() => logout()}
                >
                  로그아웃
                </button>
              </>
            ) : (
              <button
                className="btn btn--ghost-text"
                type="button"
                onClick={() => setLoginOpen(true)}
              >
                로그인
              </button>
            )}
            {/* 2026-08-18(대표 지시) — 로그인한 사용자에게는 이 CTA가 불필요하다(이미
                시작한 사용자라 "시작하기"라는 문구 자체가 안 맞는다). 비로그인일 때만. */}
            {!nickname && (
              <Link className="btn btn--mint" href="/onboarding">
                시작하기
              </Link>
            )}
            <button
              className="gnb__burger"
              aria-label="메뉴 열기"
              onClick={() => setNavOpen(true)}
            >
              <i></i>
              <i></i>
              <i></i>
            </button>
          </div>
        </div>
      </div>

      <div className={`mobile-nav${navOpen ? " is-open" : ""}`}>
        <div className="mobile-nav__top">
          <div className="gnb__logo">
            <BrandMark />
            <span>숨은길</span>
          </div>
          <button
            className="mobile-nav__close"
            aria-label="메뉴 닫기"
            onClick={() => setNavOpen(false)}
          >
            &times;
          </button>
        </div>
        <nav className="mobile-nav__list" aria-label="모바일 메뉴">
          {NAV_ITEMS.map((item) => {
            if (!item.children?.length) {
              const active = isActive(pathname, item.href);
              return (
                <Link
                  key={item.label}
                  href={item.href}
                  className={active ? "is-active" : undefined}
                  aria-current={active ? "page" : undefined}
                  onClick={() => setNavOpen(false)}
                >
                  {item.label}
                </Link>
              );
            }

            const childActive = item.children.some((c) => isActive(pathname, c.href));
            const selfActive = isActive(pathname, item.href) || childActive;

            return (
              <div key={item.label} className="mobile-nav__group">
                <Link
                  href={item.href}
                  className={`mobile-nav__group-top${selfActive ? " is-active" : ""}`}
                  aria-current={selfActive ? "page" : undefined}
                  onClick={() => setNavOpen(false)}
                >
                  {item.label}
                </Link>
                <div className="mobile-nav__group-children">
                  {item.children.map((child) => {
                    const active = isActive(pathname, child.href);
                    return (
                      <Link
                        key={child.label}
                        href={child.href}
                        className={`mobile-nav__group-child${active ? " is-active" : ""}`}
                        aria-current={active ? "page" : undefined}
                        onClick={() => setNavOpen(false)}
                      >
                        {child.label}
                      </Link>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </nav>
        <div className="mobile-nav__cta">
          {nickname ? (
            <>
              <Link
                className="btn btn--outline btn--block btn--lg"
                href="/mypage"
                onClick={() => setNavOpen(false)}
              >
                {nickname}님 · 마이페이지
              </Link>
              <button
                className="btn btn--ghost-text btn--block"
                type="button"
                onClick={() => {
                  logout();
                  setNavOpen(false);
                }}
              >
                로그아웃
              </button>
            </>
          ) : (
            <button
              className="btn btn--outline btn--block btn--lg"
              type="button"
              onClick={() => {
                setNavOpen(false);
                setLoginOpen(true);
              }}
            >
              로그인
            </button>
          )}
          {!nickname && (
            <Link
              className="btn btn--coral btn--block btn--lg"
              href="/onboarding"
              onClick={() => setNavOpen(false)}
            >
              시작하기
            </Link>
          )}
        </div>
      </div>

      {/* onLoggedIn: nickname은 이제 useLoggedInName()이 AUTH_CHANGED_EVENT로 자동 반영한다
          (LoginModal이 로그인 성공 시 setLoggedInName()을 이미 호출) — 여기선 이동만 한다.
          §47.2(2026-08-20) — 헤더 로그인 버튼 경로에서 로그인 성공 시 마이페이지로 이동.
          데스크톱·모바일 메뉴가 이 LoginModal 인스턴스를 공유하므로 이 한 곳만 고치면 된다.
          LoginGateProvider/LoginRequiredGate의 별도 로그인 흐름은 건드리지 않는다(§47.2). */}
      <ConsentModal open={consentOpen} onDone={() => setConsentOpen(false)} />
      <LoginModal
        open={loginOpen}
        onClose={() => setLoginOpen(false)}
        onLoggedIn={() => router.push("/mypage")}
      />
    </>
  );
}
