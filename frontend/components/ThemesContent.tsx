"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { FeaturedCardSkeleton } from "./FeaturedSpots";
import RegionDropdown from "./regions/RegionDropdown";
import { SIDO_REGIONS, SidoRegion } from "./regions/constants";
import { readRegionCode } from "../lib/regionQuery";
import ThemeCollections from "./ThemeCollections";

/**
 * "전국" 선택을 나타내는 프론트 전용 sentinel — 실제 법정동 코드가 아니며 절대 backend로
 * 전송하지 않는다(region_code 자체를 생략하고 diverse=true로 대체한다, handleSelectRegion
 * 참고). `SidoRegion` 타입 모양만 그대로 빌려 RegionDropdown(§42, 03-design-spec.md)에
 * 코드 변경 없이 꽂기 위한 값이다.
 */
const ALL_REGION_SENTINEL = "ALL";
const ALL_OPTION: SidoRegion = {
  sidoCode: "00",
  shortName: "전국",
  initial: "전",
  regionCode: ALL_REGION_SENTINEL,
  representativeLabel: "전국 — 여러 권역을 섞어서 보여드려요",
};
/** "전국"을 맨 앞에 두고 기존 17개 시도(SIDO_REGIONS, regions/constants.ts)를 그대로 잇는다. */
const REGION_OPTIONS: SidoRegion[] = [ALL_OPTION, ...SIDO_REGIONS];

/**
 * `/themes` 전용 페이지 — §44(2026-08-0X, 03-design-spec.md, 대표 지시: "테마별 여행은
 * 테마별로 몇 가지만 나오는데 전체를 다 볼 수 있도록 더보기가 있으면 좋겠고, 처음엔 전국
 * 테마별 여행이었다가 각 지역별로 선택할 수 있게").
 *
 * 지역 선택 상태는 이 페이지가 소유한다 — 테마 컬렉션 여러 줄이 같은 지역 조건을 공유해야
 * 하므로 ThemeCollections 내부가 아니라 여기서 한 번만 관리하고 `regionCode`/`diverse` prop으로
 * 내려준다. URL `?region_code=`에 반영해 공유·새로고침에 살아남게 한다 — RecommendContent.tsx
 * §35(지연 초기화 + 쿼리 동기화)와 동일한 패턴. 기본값은 "전국"(diverse=true, region_code
 * 미전송) — 대표 지시 원문 "처음엔 전국 테마별 여행이었다가"를 그대로 반영.
 *
 * "더보기"(테마별 독립 페이지네이션·seed 재사용)는 이 페이지가 아니라 ThemeCollections가
 * 소유한다(§44, ThemeCollections.tsx 주석 참고) — 지역이 바뀌면 이 페이지는 새 regionCode/
 * diverse만 내려주고, ThemeCollections의 fetch effect가 처음부터 다시 돌아 새 seed로 초기화된다.
 *
 * §A(2026-08-01, 03-design-spec.md §43) 원본 판단(지역 필터 없이 diverse 고정)을 이번 대표
 * 지시로 대체한다 — API 호출·정렬·404 처리 로직은 여전히 ThemeCollections가 그대로 소유한다
 * (변경 없음), 이 파일은 지역 선택 UI와 레이아웃 배치만 담당한다.
 */
export default function ThemesContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const paramRegionCode = readRegionCode(searchParams.get("region_code"));

  // 지연 초기화 — 첫 렌더부터 쿼리 지역으로 시작한다(기본 지역으로 한 번 조회한 뒤 다시 조회하는
  // 이중 호출을 피하기 위함). 쿼리가 없거나 형식이 틀리면 null(전국)로 시작한다.
  const [regionCode, setRegionCode] = useState<string | null>(() => paramRegionCode);

  // 뒤로가기 등으로 쿼리만 바뀌는 경우를 위한 동기화(RecommendContent.tsx §35와 동일 원칙).
  // 의존성이 paramRegionCode뿐이라, 드롭다운으로 사용자가 고른 선택은 쿼리가 바뀌기 전까지
  // 덮어써지지 않는다.
  useEffect(() => {
    setRegionCode((prev) => (prev === paramRegionCode ? prev : paramRegionCode));
  }, [paramRegionCode]);

  const handleSelectRegion = (option: SidoRegion) => {
    const next = option.regionCode === ALL_REGION_SENTINEL ? null : option.regionCode;
    setRegionCode(next);
    // URL에 반영 — 이미 있는 다른 쿼리(있다면)는 보존하고 region_code만 갱신/제거한다.
    const params = new URLSearchParams(searchParams.toString());
    if (next) params.set("region_code", next);
    else params.delete("region_code");
    const qs = params.toString();
    router.replace(qs ? `/themes?${qs}` : "/themes", { scroll: false });
  };

  const matchedOption = REGION_OPTIONS.find(
    (r) => r.regionCode === (regionCode ?? ALL_REGION_SENTINEL)
  );
  // 쿼리로 들어온 지역이 17개 대표 시군구 밖이면(이론상 다른 화면에서 온 링크) 체크 표시는
  // 없지만 "선택한 지역"으로 정직하게 표시한다 — 지어낸 지역명을 채우지 않는다(§42 폴백과 동일 원칙).
  const triggerLabel = matchedOption?.shortName ?? (regionCode ? "선택한 지역" : "전국");

  return (
    <section className="section" aria-labelledby="themesHeading">
      <span className="eyebrow-pill eyebrow-pill--mint">저혼잡 · 숨은 테마</span>
      <h1 className="section__title" id="themesHeading">
        테마별 여행
      </h1>
      <div className="board-header-row">
        <RegionDropdown
          options={REGION_OPTIONS}
          selectedCode={regionCode ?? ALL_REGION_SENTINEL}
          triggerLabel={triggerLabel}
          onSelect={handleSelectRegion}
          ariaLabel="테마별 여행 지역 선택"
        />
      </div>
      <ThemeCollections regionCode={regionCode} diverse={regionCode === null} limit={Infinity} bare />
    </section>
  );
}

/** app/themes/page.tsx의 Suspense fallback. useSearchParams를 쓰는 클라이언트 컴포넌트는
 *  Next.js App Router 규약상 Suspense 경계가 필요하다(app/recommend/page.tsx §35와 동일 패턴). */
export function ThemesLoadingSkeleton() {
  return (
    <section className="section" aria-label="테마별 여행 불러오는 중">
      <div className="theme-collections__group">
        <div className="featured-scroll" role="list" aria-busy="true">
          {Array.from({ length: 4 }).map((_, i) => (
            <FeaturedCardSkeleton key={i} />
          ))}
        </div>
      </div>
    </section>
  );
}
