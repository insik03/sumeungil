import Link from "next/link";
import Footer from "../components/Footer";

export default function NotFound() {
  return (
    <div className="page">
      <main>
        <section className="section legal-content" aria-labelledby="notFoundHeading">
          <span className="eyebrow-pill eyebrow-pill--mint">404</span>
          <h1 className="section__title" id="notFoundHeading">
            길을 잠깐 잃었어요
          </h1>
          <p>요청한 페이지가 없거나 주소가 바뀌었습니다. 홈에서 다른 숨은길을 찾아보세요.</p>
          <p>
            <Link className="btn btn--mint" href="/">
              홈으로 돌아가기
            </Link>
          </p>
        </section>
      </main>
      <Footer />
    </div>
  );
}
