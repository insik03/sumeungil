import Link from "next/link";

/**
 * §22(03-design-spec.md, 2026-07-29) — Acenda 레퍼런스의 "다크 푸터(링크 컬럼) + 뉴스레터형
 * CTA 카드" 문법을 흡수했다. 뉴스레터 자리는 숨은길에 이메일 수집 기능이 없으므로(스코프 밖)
 * 그대로 베끼지 않고 "취향 알려주고 맞춤 여행 받기" 온보딩 유도 카드로 재해석했다.
 * 링크 컬럼은 전부 Header.tsx의 NAV_ITEMS와 동일한 실제 존재하는 라우트만 쓴다 — 없는
 * 페이지(예: 고객센터·이용약관)는 만들지 않는다.
 */
const EXPLORE_LINKS = [
  { label: "홈", href: "/" },
  { label: "여행지 추천", href: "/recommend" },
  { label: "AI 여행 경로", href: "/course" },
];

const MY_TRIP_LINKS = [
  { label: "저장한 코스", href: "/saved" },
  { label: "여행 팁", href: "/tips" },
  { label: "취향 온보딩 시작", href: "/onboarding" },
];

export default function Footer() {
  return (
    <footer className="footer">
      <div className="footer__cta">
        <div>
          <p className="footer__cta-title">취향 알려주고 맞춤 여행 받기</p>
          <p className="footer__cta-sub">동행자와 분위기만 알려주면 AI가 숨은 코스를 찾아드려요.</p>
        </div>
        <Link className="btn btn--coral btn--lg" href="/onboarding">
          온보딩 시작하기
        </Link>
      </div>

      <div className="footer__columns">
        <div className="footer__col footer__col--brand">
          <div className="footer__logo">숨은길</div>
          <p className="footer__tag">사람 대신, 설렘을 만나는 여행</p>
        </div>
        <div className="footer__col">
          <span className="footer__col-title">탐색</span>
          <ul className="footer__links">
            {EXPLORE_LINKS.map((item) => (
              <li key={item.href}>
                <Link href={item.href}>{item.label}</Link>
              </li>
            ))}
          </ul>
        </div>
        <div className="footer__col">
          <span className="footer__col-title">내 여행</span>
          <ul className="footer__links">
            {MY_TRIP_LINKS.map((item) => (
              <li key={item.href}>
                <Link href={item.href}>{item.label}</Link>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <p className="footer__copyright">
        © 2026 숨은길 · 한국관광공사 공공데이터 기반 ·{" "}
        <Link href="/privacy" className="footer__privacy-link">
          개인정보처리방침
        </Link>
      </p>
    </footer>
  );
}
