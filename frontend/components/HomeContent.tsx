"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { RegionSearchItem } from "../lib/api";
import { clearLastRegion, loadLastRegion, saveLastRegion } from "../lib/lastRegionStorage";
import { loadOnboardingResult } from "../lib/onboardingStorage";
import Hero from "./Hero";
import HeroGreeting from "./HeroGreeting";
import ServiceQuickMenu from "./ServiceQuickMenu";
import FeaturedSpots from "./FeaturedSpots";
import CoursePromo from "./CoursePromo";
import FestivalBanner from "./FestivalBanner";

/**
 * 부록 A.3 — 지역 칩/검색 선택과 전광판을 이어주는 상태 소유자.
 * Hero(검색·칩)에서 지역을 선택하면 CongestionBoard·FeaturedSpots·ThemeCollections·FestivalBanner가
 * 해당 지역으로 재호출된다. 선택이 없으면(null) 기존대로 백엔드 기본 지역(해운대)을 유지한다.
 *
 * 홈 발견 화면 — Hero(검색) 바로 아래에 사진 위주 발견 섹션(FeaturedSpots: "숨은길 PICK" +
 * "지금 뜨는 여행지"(§46에서 순서 반전), ThemeCollections: "테마별로 골라보는 여행")을 먼저 배치하고, 수치 중심의
 * 전광판(CongestionBoard)을 그 아래로 뒀다 — "둘러보기(발견) → 숫자로 확인(혼잡도)" 순서가
 * 발견형 홈의 자연스러운 시선 흐름이라는 판단(03-design-spec.md 근거). ThemeCollections를
 * FeaturedSpots 바로 다음(CongestionBoard보다 앞)에 둔 것도 같은 이유 — 둘 다 사진 카드 기반
 * 발견 콘텐츠라 같은 클러스터에 묶는 편이 시선 흐름을 끊지 않는다(Phase 2, 핸드오프 참고).
 * region_code는 recommend/compare 화면과 동일하게 sigungu_cd를 그대로 재사용한다
 * (§RecommendContent.tsx 패턴과 일관).
 *
 * Phase 3(신규, 03-design-spec.md 근거) — FestivalBanner를 전광판 다음(맨 아래)에 두고 여기로
 * 옮겨왔다. 이전엔 app/page.tsx가 정적 데이터로 별도 렌더했지만, 실데이터 연동을 위해 지역
 * 선택 상태를 공유해야 해서 이 컴포넌트가 소유한 selectedRegion을 그대로 재사용한다(다른
 * 섹션과 동일 패턴). 화면상 위치는 이전과 동일(맨 아래) — 섹션 순서 자체는 재배치하지 않았다.
 *
 * §22(2026-07-29, 03-design-spec.md) — Acenda 재스킨: CoursePromo(다크 풀블리드 AI 코스 홍보)를
 * ThemeCollections(사진 카드 그리드) 다음·CongestionBoard(수치 중심) 이전에 추가했다. Acenda의
 * "그리드 → 다크 사진 배너 → 다음 콘텐츠" 리듬과 동일한 위치 — "둘러보기 → 이거 어때 → 숫자로
 * 확인" 순서로 자연스럽게 이어진다. 기존 5개 섹션의 순서·로직은 그대로 두고 1개만 삽입했다.
 *
 * §24(2026-07-29, 03-design-spec.md) — 구석구석 포털 재구성: Hero 바로 아래 ServiceQuickMenu(8개
 * 핵심 기능 퀵메뉴)를 추가해 "모든 기능이 첫 화면에서 한눈에" 보이게 했다. 섹션 순서도 지시서
 * 명세("지금 뜨는 → 오늘의 발견 → 테마 → 예상 혼잡 전광판 → AI 코스 밴드 → 축제")에 맞춰
 * CongestionBoard를 CoursePromo보다 앞으로 옮겼다 — §22가 만든 CoursePromo/CongestionBoard
 * 컴포넌트 자체(로직·API 호출)는 그대로이고 렌더 순서만 바뀐다. CongestionBoard·FestivalBanner
 * section에는 각각 id="board"/id="festival"을 부여해(각 컴포넌트 내부에서 처리) 퀵메뉴 앵커
 * 이동의 대상이 되게 했다.
 *
 * §32(2026-07-29, 03-design-spec.md) — ConciergeSection(AI 여행 문답)을 ServiceQuickMenu 바로
 * 아래에 얹었다. 지시서 권고 위치("퀵메뉴 아래")를 그대로 따른 것 — 이 기능이 구석구석류 필터
 * UI와 다른 숨은길만의 차별화 진입점이라, 사진 위주 발견 섹션(FeaturedSpots)보다 먼저 눈에 띄어야
 * "필터 대신 문장으로 물어봐도 된다"는 걸 첫 스크롤에서 바로 알 수 있다.
 *
 * §33-3(2026-07-29, 03-design-spec.md, 대표 피드백) — ConciergeSection이 결과 렌더를 더 이상
 * 하지 않고 `/ask`로 이동만 시키는 컴팩트 진입창으로 슬림화되면서, regionCode prop도 함께
 * 없앴다(질문 텍스트에서 지역이 감지되거나 서버 기본 지역으로 `/ask`가 처리한다, 부록 N §N.3②
 * — 홈 selectedRegion을 라우트 간 전달하지 않는 이유는 03-design-spec.md §33.3 핸드오프 참고).
 *
 * §35(2026-07-31, 03-design-spec.md — 지역 컨텍스트 전파, 백로그 D21) — 위 §33-3의 "라우트 간
 * 전달하지 않는다"를 뒤집는다. 홈에서 고른 지역이 다른 화면으로 이어지지 않는 단절이 실사용에서
 * 문제였고, 전달 수단(URL 쿼리 `?region_code=`)을 이번에 세웠다. 이 컴포넌트가 이미 소유하고 있는
 * selectedRegion을 홈의 링크 생산자(ServiceQuickMenu·ConciergeSection·CoursePromo·FestivalBanner)
 * 에도 그대로 내려주기만 하면 되고, 새로운 상태·저장소·API는 없다. 미선택(null)이면 각 컴포넌트가
 * 쿼리를 붙이지 않아 기존 URL과 완전히 동일하다.
 *
 * §37.4(신규, 03-design-spec.md, 2026-07-31) — 홈 지역 다양성: 지역 미선택 상태(selectedRegion
 * === null)일 때만 `<FeaturedSpots diverse />`를 켠다("홈에 부산만 많다" 대표 피드백 대응).
 * 지역을 고르면 기존대로(diverse 꺼짐, 해당 지역 결과만) 동작한다 — 다른 섹션(테마 컬렉션·
 * 전광판 등)은 지시서 스코프 밖이라 건드리지 않는다.
 *
 * §37.5(2026-08-01, 대표 재보고 "테마별 여행은 새로고침해도 같은 곳만 / 인생샷도 부산만") —
 * 위 §37.4의 "테마 컬렉션은 스코프 밖"을 해제하고 `<ThemeCollections diverse />`도 같은
 * 조건(지역 미선택)으로 켠다. 테마 컬렉션은 단일 지역 후보가 테마당 7~15개뿐이라 섞을 여지가
 * 없었다(backend 실측) — diverse면 9권역 합산 풀에서 시군구당 최대 2곳으로 뽑아 온다.
 *
 * §38(2026-07-31, 대표 지시 "홈에 자꾸 다 추가하는데 너무 번잡스러워 따로 만들라") —
 * 계절 여행(SeasonalSection)·출발일 플래너(DeparturePlanner)를 홈에서 **덜어내** 각각
 * `/seasonal`·`/plan` 전용 페이지로 옮겼다. 홈은 발견(히어로·추천·전광판·코스·축제)까지만
 * 담고, 도구성 기능은 ServiceQuickMenu 타일로 진입한다. **앞으로 홈에 새 섹션을 얹기 전에
 * 전용 페이지로 만들 수 있는지부터 검토할 것**(대표 반복 지적).
 *
 * §A(2026-08-01, 03-design-spec.md §43 — 대표 지시 4건 레이아웃 재설계 원문 1: "테마별로 골라보는
 * 여행은 홈페이지가 난잡해지니 없애고 카테고리로 넘겨라") — ThemeCollections를 §38과 동일한
 * 이유로 홈에서 뺐다(§38이 "번잡" 사유로 덜어낸 두 섹션과 같은 판단). `/themes` 전용 페이지로
 * 옮기고 GNB "여행지 추천" 드롭다운에 진입점을 추가했다(Header.tsx, ThemeCollections.tsx §A
 * 참고) — 퀵메뉴(10개)는 지시서 제약대로 개수를 유지하며 건드리지 않았다.
 *
 * §47.7(2026-08-20, 03-design-spec.md — AI 여행 문답 삭제) — ConciergeSection(퀵메뉴 바로 아래
 * 있던 컴팩트 진입창)을 제거했다. `/ask`는 리다이렉트만 남기고, 같은 니즈는 `/course` AI 모드
 * 상단의 "어떤 여행을 원하세요?" 의견 입력(CourseContent.tsx)으로 흡수됐다(§47.3).
 */
export default function HomeContent() {
  // 대표 지시(2026-08-17) — "모든 기본 화면의 기준 지역은 마지막으로 고른 지역"을 기준으로.
  // SSR/첫 클라이언트 렌더는 항상 중립값(null)으로 맞춘다 — sessionStorage는 서버에서
  // 읽을 수 없어(Hero.tsx의 닉네임/동행 태그 처리와 동일 이유) 초기 state에서 바로 쓰면
  // 서버 HTML과 클라이언트 첫 렌더가 달라져 하이드레이션 에러가 난다(실측으로 확인).
  // mount 후 effect에서 반영한다.
  const [selectedRegion, setSelectedRegionState] = useState<RegionSearchItem | null>(null);
  // 2026-09-03(대표 "렉 걸리는 이유") — 기억해둔 지역을 mount 후에야 알 수 있다 보니, 첫 렌더가
  // null(지역 미선택)로 나가면서 Hero가 전국 9개 도 병렬 호출을 쏘고 FeaturedSpots·CoursePromo·
  // FestivalBanner도 전국 기준으로 한 번 요청한 뒤, 바로 지역이 복원되면 전부 abort하고 다시
  // 요청했다(네트워크 탭에 featured 12건 취소 → 재요청으로 실측). worker 1개짜리 백엔드에
  // 홈 한 번 열 때마다 요청이 두 배로 몰려 각 호출이 700ms대로 늘어지는 게 체감 렉의 원인.
  // 그래서 "지역 복원이 끝났다"는 신호가 서기 전엔 데이터 섹션을 아예 그리지 않는다 —
  // SSR과 첫 클라이언트 렌더는 둘 다 false라 하이드레이션은 그대로 안전하다.
  const [regionResolved, setRegionResolved] = useState(false);
  useEffect(() => {
    const last = loadLastRegion();
    if (last) setSelectedRegionState(last);
    setRegionResolved(true);
  }, []);

  // 2026-08-17(대표 지시) — 온보딩 결과 확인("이 취향으로 계속하기")은 이제 /recommend로
  // 바로 넘기지 않고 홈으로 보낸다(OnboardingContent.tsx handleConfirmResult 참고). 대신
  // 방금 만든 결과가 sessionStorage에 있으면 여기서 배너로 안내한다 — RecommendContent
  // 등이 이미 쓰는 .recommend-cta-banner를 그대로 재사용(새 컴포넌트를 만들지 않음, §38
  // "홈에 새 섹션 추가 전 전용 페이지부터 검토"와 별개로 이건 조건부 배너라 상시 섹션이
  // 아니다). 같은 이유로 서버/첫 클라이언트 렌더는 항상 false — mount 후에만 반영.
  const [hasFreshOnboardingResult, setHasFreshOnboardingResult] = useState(false);
  useEffect(() => {
    setHasFreshOnboardingResult(loadOnboardingResult() !== null);
  }, []);
  const handleSelectRegion = (region: RegionSearchItem | null) => {
    setSelectedRegionState(region);
    // 검색창 지우기(대표: destInput의 × 버튼)로 명시적으로 지역을 비운 것도 하나의 선택이다
    // — 기억해둔 지역도 함께 지워야 다음 방문에서 도로 튀어나오지 않는다.
    if (region) saveLastRegion(region);
    else clearLastRegion();
  };
  // 다른 섹션들이 쓰는 값과 동일한 sigungu_cd를 링크 쿼리에도 그대로 쓴다(별도 변환 없음).
  const regionCode = selectedRegion?.sigungu_cd ?? null;

  return (
    <>
      {/* 2026-08-18(대표 지시) — 배너·인사말을 페이지 맨 위, Hero(검색바 "어디로 떠나시나요")
          보다도 위로. 한 번 카테고리 창(ServiceQuickMenu) 밑으로 옮겼다가 "맨 위로, 검색바
          위로" 재지시받아 되돌렸다. hero-greeting은 HeroGreeting.tsx로 분리했다(Hero.tsx
          주석 참고) — 여기서 Hero보다 먼저 렌더하면 그게 곧 "검색바 위"가 된다. */}
      {hasFreshOnboardingResult && (
        <div className="recommend-cta-banner">
          <p className="recommend-cta-banner__text">방금 알려주신 취향으로 맞춤 추천을 만들어뒀어요.</p>
          <Link className="btn btn--mint" href="/recommend">
            방금 만든 추천 보러가기
          </Link>
        </div>
      )}
      <HeroGreeting />
      <Hero selectedRegion={selectedRegion} onSelectRegion={handleSelectRegion} regionResolved={regionResolved}>
        <ServiceQuickMenu regionCode={regionCode} />
      </Hero>
      {/* 2026-08-29(대표 지시) — 지역 지도(RegionMapSection)를 홈에서 뺐다. 히어로 옆(1차) →
          히어로 밖 독립 섹션(2차)을 거쳐 결국 "홈에는 없어도 된다"로 정리 — /course(로그인
          후)에만 남는다(CourseContent.tsx). 컴포넌트 자체는 지우지 않았다, 거기서 재사용 중. */}
      {regionResolved && (
        <>
          {/* 2026-09-03 회의 액션 — 축제 섹션을 추천보다 위로(시의성 높은 정보 먼저). */}
          <FeaturedSpots regionCode={regionCode} diverse={!selectedRegion} />
          {/* 부록 U.3(2026-08-01, 대표 지시) — 예상 혼잡 전광판은 congestion 화면으로 옮겼다.
              그 화면이 전국 지도 아래에 같은 전광판을 두므로, 홈에 남겨두면 두 번 나온다. */}
          <CoursePromo regionCode={regionCode} />
          <FestivalBanner regionCode={regionCode} />
        </>
      )}
    </>
  );
}
