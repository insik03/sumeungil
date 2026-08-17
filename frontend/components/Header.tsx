"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import LoginModal from "./LoginModal";
import {
  AUTH_CHANGED_EVENT,
  deleteAccount,
  getNickname,
  logout,
  syncSessionFromServer,
} from "../lib/authStorage";

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
      { label: "AI 취향분석", href: "/onboarding" },
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
      { label: "AI 여행 문답", href: "/ask" },
      // §41(신규) — 다른 사람이 공유한 코스 피드(/courses). 퀵메뉴(ServiceQuickMenu, 10개 유지)는
      // 건드리지 않고 GNB 드롭다운에만 추가한다(지시서 요구사항).
      { label: "다른 사람 코스", href: "/courses" },
    ],
  },
  {
    label: "혼잡도·시기",
    href: "/congestion",
    children: [
      { label: "전국 혼잡 지도", href: "/congestion" },
      // 부록 D.7(2026-08-01) — 지정과제2("쏠림 완화")에 가장 직결되는 기능인데 GNB·퀵메뉴 어디에도
      // 진입점이 없어 스팟 상세를 통해서만 닿을 수 있었다. 독립 목적지로 승격한다.
      { label: "붐비는 곳 대신", href: "/compare" },
      { label: "출발일 플래너", href: "/plan" },
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

export default function Header() {
  const pathname = usePathname() ?? "/";
  const [navOpen, setNavOpen] = useState(false);
  const [openLabel, setOpenLabel] = useState<string | null>(null);
  const [nickname, setNickname] = useState<string | null>(null);
  const [loginOpen, setLoginOpen] = useState(false);
  // 계정 삭제 2단계 확인(QA C-4, 2026-08-17) — 새 모달 없이 버튼 텍스트만 바꿔 "정말?"을
  // 한 번 더 묻는다. 5초 안에 다시 누르지 않으면 원상태로 되돌려 실수 클릭을 막는다.
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const deleteConfirmTimerRef = useRef<number | null>(null);
  const triggerRefs = useRef<Record<string, HTMLAnchorElement | null>>({});
  // Esc 로 닫은 직후 포커스를 트리거로 되돌리면 onFocus 가 즉시 다시 열어버린다(실측 확인).
  // "이 항목은 방금 Esc 로 닫았다"를 기억해 두고, 포커스가 그룹 밖으로 나가거나 마우스가
  // 다시 들어올 때 해제한다 — 그래야 Esc 가 실제로 닫힌 상태로 남는다.
  const escDismissedRef = useRef<string | null>(null);

  // 데모 로그인 상태는 localStorage(authStorage)에서 읽는다. 다른 탭/컴포넌트 변화도 즉시 반영.
  useEffect(() => {
    setNickname(getNickname());
    const sync = () => {
      setNickname(getNickname());
      setDeleteConfirm(false);
    };
    window.addEventListener(AUTH_CHANGED_EVENT, sync);
    window.addEventListener("storage", sync);
    void syncSessionFromServer(); // QA M-2 — 부팅 시 1회, 서버 세션 진실과 로컬 캐시를 맞춘다.
    return () => {
      window.removeEventListener(AUTH_CHANGED_EVENT, sync);
      window.removeEventListener("storage", sync);
      if (deleteConfirmTimerRef.current) window.clearTimeout(deleteConfirmTimerRef.current);
    };
  }, []);

  const handleDeleteAccount = () => {
    if (!deleteConfirm) {
      setDeleteConfirm(true);
      deleteConfirmTimerRef.current = window.setTimeout(() => setDeleteConfirm(false), 5000);
      return;
    }
    if (deleteConfirmTimerRef.current) window.clearTimeout(deleteConfirmTimerRef.current);
    setDeleteConfirm(false);
    void deleteAccount();
  };

  // 관리자 콘솔(/admin)은 일반 서비스 셸을 공유하지 않는다(03-admin-console-design.md §4).
  //   - 운영 화면인 줄 모르고 조작하는 사고를 막으려면 시각적으로 확실히 갈라져야 한다.
  //   - GNB 의 로그인 모달·닉네임 상태는 **일반 사용자용**이라 관리자 세션과 개념이 다르다.
  //     한 화면에 둘 다 있으면 "어느 쪽으로 로그인한 건지" 혼동이 생긴다.
  // app/admin/layout.tsx 로는 이걸 못 한다 — 중첩 레이아웃은 부모를 감쌀 뿐 제거하지 못한다.
  // 기존 페이지를 전부 route group 으로 옮기는 대공사 대신, 여기서 스스로 빠지게 했다.
  // 훅은 전부 위에서 호출된 뒤이므로 훅 순서 규칙을 어기지 않는다.
  if (pathname === "/admin" || pathname.startsWith("/admin/")) return null;

  return (
    <>
      <div className="gnb">
        <div className="gnb__inner">
          <Link className="gnb__logo" href="/" aria-label="숨은길 홈으로">
            <span>숨은</span>
            <span className="gnb__logo-badge">길</span>
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
                <span className="gnb__greeting">{nickname}님</span>
                <button
                  className="btn btn--ghost-text"
                  type="button"
                  onClick={() => logout()}
                >
                  로그아웃
                </button>
                <button
                  className="btn btn--ghost-text gnb__delete-account"
                  type="button"
                  onClick={handleDeleteAccount}
                >
                  {deleteConfirm ? "정말 삭제할까요? 다시 누르면 삭제돼요" : "계정 삭제"}
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
            <Link className="btn btn--mint" href="/onboarding">
              시작하기
            </Link>
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
          <div className="gnb__logo" style={{ color: "#fff" }}>
            <span>숨은</span>
            <span className="gnb__logo-badge">길</span>
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
              <button
                className="btn btn--white btn--block btn--lg"
                type="button"
                onClick={() => {
                  logout();
                  setNavOpen(false);
                }}
              >
                {nickname}님 · 로그아웃
              </button>
              <button
                className="btn btn--ghost-text btn--block"
                type="button"
                onClick={handleDeleteAccount}
              >
                {deleteConfirm ? "정말 삭제할까요? 다시 누르면 삭제돼요" : "계정 삭제"}
              </button>
            </>
          ) : (
            <button
              className="btn btn--white btn--block btn--lg"
              type="button"
              onClick={() => {
                setNavOpen(false);
                setLoginOpen(true);
              }}
            >
              로그인
            </button>
          )}
          <Link
            className="btn btn--coral btn--block btn--lg"
            href="/onboarding"
            onClick={() => setNavOpen(false)}
          >
            시작하기
          </Link>
        </div>
      </div>

      <LoginModal open={loginOpen} onClose={() => setLoginOpen(false)} onLoggedIn={setNickname} />
    </>
  );
}
