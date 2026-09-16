import Link from "next/link";
import tipsData from "../content/travel-tips.ko.json";
import WeatherBoard from "./WeatherBoard";
import PersonalizedTips from "./tips/PersonalizedTips";

interface Tip {
  id: string;
  category: string;
  title: string;
  body: string;
  icon?: string;
}

/** Phase 4(신규) — "숨은길 이용 가이드" 정적 스텝. content/travel-tips.ko.json에 함께 둔다
 * (route href를 포함한 순서 있는 안내 콘텐츠라 tips와 동일하게 데이터 파일에서 관리하는 편이
 * content-marketer 등 후속 문구 교체 작업에도 일관적이다). */
interface GuideStep {
  id: string;
  step: number;
  title: string;
  body: string;
  href: string;
  cta: string;
}

/**
 * 부록 F 파트3(F.3-6). 정적 JSON(content/travel-tips.ko.json, F.3-3 shape)을 category별로 묶어 렌더한다.
 * 외부 API·백엔드 호출 없음(F.3-2). body는 항상 텍스트 노드로만 렌더한다 — 정적 콘텐츠라도
 * HTML 주입 경로를 만들지 않는다(F.3-6-2).
 * 문구는 2026-09-14 정식 교체(v3: 혼잡·교통·날씨·반려동물·무장애·안전·예절 8건) — 실제 기능(혼잡 예측·Tmap 소요·동반/무장애 표시)에 근거한 안내만 쓰고 의학/법률 단정은 없다.
 *
 * Phase 4(신규) — 기존 팁 카드 유지 + "숨은길 이용 가이드" 섹션을 아래에 추가했다(additive, tips-group
 * 렌더 로직은 무변경). 가이드는 온보딩→추천→코스→저장·스탬프 4단계를 <ol>(순서 있는 목록)로 표시해
 * 스크린리더에서도 순서가 그대로 전달되도록 했다 — 카드 그리드가 아니라 세로 스텝 목록을 쓴 이유다.
 *
 * §37.1(신규, 03-design-spec.md, 2026-07-31) — `/tips` 최상단에 `<WeatherBoard />`(전국 날씨 보드)를
 * 얹었다(확장, 대체 아님) — 기존 정적 팁 카드·가이드는 그대로 두고 실시간성 콘텐츠를 그 위에 새로
 * 추가했다(홈에는 "여행 팁"에 대응하는 별도 섹션이 없어 이 페이지가 유일한 확장 지점이었다).
 *
 * §47.9(신규, 08-interface-contract.md 부록 Z, 2026-08-20) — 로그인+온보딩 프로필이 있으면
 * `<PersonalizedTips />`가 AI 맞춤 팁을 인트로 문단 아래에 additive로 얹는다. 비로그인·
 * 프로필없음·API 실패·서버 정적 폴백이면 그 컴포넌트가 스스로 null을 반환해 아무것도 안 그리고,
 * 아래 기존 정적 5건 카테고리 그룹은 무조건 그대로 렌더된다(이 컴포넌트 로직 무변경).
 */
export default function TipsContent() {
  const data = tipsData as { version: number; tips: Tip[]; guideSteps: GuideStep[] };
  const tips = data.tips;
  const guideSteps = data.guideSteps;

  const grouped = tips.reduce<Record<string, Tip[]>>((acc, tip) => {
    if (!acc[tip.category]) acc[tip.category] = [];
    acc[tip.category].push(tip);
    return acc;
  }, {});

  return (
    <>
      <WeatherBoard />
      <section className="section" aria-labelledby="tipsHeading">
        <span className="eyebrow-pill eyebrow-pill--coral">여행 팁</span>
        <h1 className="section__title" id="tipsHeading">
          더 편안한 여행을 위한 팁
        </h1>
        <p className="tips-intro">
          숨은길이 정리한 일반적인 여행 정보예요. 상황에 따라 다를 수 있으니 참고용으로 봐주세요.
        </p>

        <PersonalizedTips />

        {Object.entries(grouped).map(([category, categoryTips]) => (
          <div className="tips-group" key={category}>
            {/* §23(2026-07-29) — 카테고리마다 색을 바꿔 칠하던 eyebrow-pill 대신 중립 라벨로 통일
                (globals.css .tips-category-label 근거 주석 참고). */}
            <span className="tips-category-label tips-group__label">{category}</span>
            <div className="tips-grid">
              {categoryTips.map((tip) => (
                <article className="tip-card" key={tip.id}>
                  <h2 className="tip-card__title">{tip.title}</h2>
                  <p className="tip-card__body">{tip.body}</p>
                </article>
              ))}
            </div>
          </div>
        ))}

        {guideSteps.length > 0 && (
          <div className="guide-section">
            {/* §23(2026-07-29) — eyebrow-pill 제거. border-top 구분선 + 고유 헤딩만으로 이미
                "여행 팁" 목록과 다른 블록임이 드러나 칩 라벨이 중복이었다. */}
            <h2 className="section__title" id="guideHeading">
              숨은길 이렇게 써보세요
            </h2>
            <p className="guide-intro">
              취향 입력부터 저장·방문 기록까지, 숨은길이 처음이라면 이 순서를 따라가 보세요.
            </p>
            <ol className="guide-steps">
              {guideSteps.map((step) => (
                <li className="guide-step" key={step.id}>
                  <span className="guide-step__num" aria-hidden="true">
                    {step.step}
                  </span>
                  <div className="guide-step__body">
                    <h3 className="guide-step__title">{step.title}</h3>
                    <p className="guide-step__body-text">{step.body}</p>
                    <Link className="guide-step__cta" href={step.href}>
                      {step.cta}
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                      >
                        <path d="M5 12h14M13 6l6 6-6 6" />
                      </svg>
                    </Link>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        )}
      </section>
    </>
  );
}
