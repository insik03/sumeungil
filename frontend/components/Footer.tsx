import Link from "next/link";

/**
 * 2026-09-16 대표 지시 — "대한민국 구석구석처럼". 종전의 링크 컬럼(탐색/내 여행)은 GNB 와 겹쳐 의미가
 * 없어 걷어내고, 구석구석 푸터의 구성(관광안내 전화 띠 → 기관·데이터 정보 → 약관 링크 줄 → 출처 마크 →
 * 저작권)을 숨은길 규모에 맞게 옮겼다. 사업자번호·주소처럼 우리에게 없는 정보는 적지 않는다.
 * 1330 은 한국관광공사 관광안내전화(공개 번호, 24시간). 관련 사이트는 실제로 데이터를 받아오는 곳만.
 */
const RELATED_SITES = [
  { label: "대한민국 구석구석", href: "https://korean.visitkorea.or.kr" },
  { label: "한국관광 데이터랩", href: "https://datalab.visitkorea.or.kr" },
  { label: "공공데이터포털", href: "https://www.data.go.kr" },
  { label: "기상청 날씨누리", href: "https://www.weather.go.kr" },
];

const POLICY_LINKS = [
  { label: "이용약관", href: "/terms" },
  { label: "개인정보처리방침", href: "/privacy" },
  { label: "위치정보 이용 안내", href: "/privacy" },
  { label: "고객문의", href: "/mypage" },
];

export default function Footer() {
  return (
    <footer className="footer">
      <div className="footer__inner">
        <div className="footer__help">
          <div className="footer__help-item">
            <span className="footer__help-label">관광안내</span>
            <a className="footer__help-phone" href="tel:1330">
              1330
            </a>
            <span className="footer__help-note">한국관광공사 관광안내전화 · 24시간</span>
          </div>
          <div className="footer__help-item">
            <span className="footer__help-label">정보 수정·문의</span>
            <Link className="footer__help-link" href="/mypage">
              마이페이지 › 고객문의
            </Link>
            <span className="footer__help-note">잘못된 관광 정보, 서비스 문의</span>
          </div>
          <div className="footer__help-item footer__help-item--sites">
            <span className="footer__help-label">관련 사이트</span>
            <ul className="footer__sites">
              {RELATED_SITES.map((s) => (
                <li key={s.href}>
                  <a href={s.href} target="_blank" rel="noopener noreferrer">
                    {s.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* 2026-09-20 대표 지시 — 브랜드·슬로건·목적 문단·데이터 출처 블록 제거. 출처는 아래 마크 3개가 대신한다. */}
        <ul className="footer__policy" aria-label="약관과 안내">
          {POLICY_LINKS.map((p) => (
            <li key={p.label}>
              <Link href={p.href}>{p.label}</Link>
            </li>
          ))}
        </ul>

        <div className="footer__bottom">
          <div className="footer__marks" aria-label="출처 표시">
            <span className="footer__mark">한국관광공사 공공데이터</span>
            <span className="footer__mark">TourAPI 4.0</span>
            <span className="footer__mark">공공데이터포털</span>
          </div>
          <p className="footer__copyright">© 2026 숨은길</p>
        </div>
      </div>
    </footer>
  );
}
