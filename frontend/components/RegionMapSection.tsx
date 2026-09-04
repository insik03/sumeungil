"use client";

import { useEffect, useMemo, useState } from "react";
import { FeaturedSpot, fetchFeatured } from "../lib/api";
import { DEFAULT_SIDO_CODE, SIDO_REGIONS } from "./regions/constants";
import RegionRouteMap, { RouteSpot } from "./demo-home/RegionRouteMap";

interface RegionMapSectionProps {
  /** 선택된 지역(sigungu_cd). FeaturedSpots/CoursePromo와 동일 원칙. */
  regionCode?: string | null;
  /**
   * 2026-09-03(대표: "지도 크기를 naver map 크기랑 똑같이 해서 그 밑에 붙여줄 수 있어?") —
   * true면 제목·설명이 있는 독립 섹션 대신 **지도 카드만** 그린다. /recommend의 지도 칸
   * 안에서 NAVER 지도(SpotMap) 바로 아래에 같은 크기로 쌓기 위한 모드. 크기는 부모
   * (.recommend-layout__map--stacked)가 정한다 — 여기서는 높이를 강제하지 않는다.
   */
  inline?: boolean;
  /**
   * 2026-09-04(대표: "추천 경로도 네이버맵이랑 연동해서 AI 코스랑 같이") — 이 값을 주면 featured
   * 픽을 받아오지 않고 이 스팟들(예: AI 코스 결과)을 순서대로 잇는다. NAVER CourseMap 과 같은
   * 데이터를 쓰므로 두 지도가 같은 경로를 보여준다.
   */
  spots?: RouteSpot[];
  /** spots 를 줄 때의 로딩 상태(코스 생성 중이면 true). */
  spotsLoading?: boolean;
  /** 경로로 이을 최대 스팟 수 — 기본 3. spots 를 준 코스 화면은 코스 길이만큼. */
  maxStops?: number;
  routeLabel?: string;
}

// RegionRouteMap용 후보 풀 크기. 시/도 전체에서 좌표 있는 스팟을 걸러 최대 3곳만
// 코스선으로 잇는다(demo-home/DemoHome.tsx와 동일 관례) — 넉넉히 받아야 결측 후에도 남는다.
const MAP_SPOTS_LIMIT = 12;

/**
 * 홈의 독립 지역 지도 섹션 (2026-08-29, 대표 지시).
 *
 * 처음엔 이 지도를 Hero.tsx 검색창 옆에 나란히 넣었으나(2026-08-29 1차), 대표가 두 차례에
 * 걸쳐 "부자연스럽다"고 재지적했다 — 카드 장식·높이를 맞춰도 근본적으로 "히어로 안에
 * 검색과 지도를 욱여넣은 배치" 자체가 문제였다("애초에 위치 자체부터가 글러먹었다"). 히어로는
 * 원래대로(검색+캐러셀만) 되돌리고, 지도는 이 파일로 옮겨 홈 안의 독립 섹션으로 만든다 —
 * 제목·설명을 갖춘 자기 자리를 주고, 카드 하나 크기에 맞출 필요가 없어 넉넉하게 보여준다.
 *
 * regionCode(sigungu_cd)에서 시/도 코드만 뽑아(앞 2자리 — SIDO_REGIONS 코드 체계와 동일,
 * DEFAULT_SIDO_CODE 등 기존 상수 그대로 재사용) RegionRouteMap에 넘긴다. 이 화면엔 이미
 * Hero.tsx의 검색/칩이 지역 선택 UI를 갖고 있으므로 지도 자체 도시 선택 칩은 계속 숨긴다
 * (hidePicker) — 지도는 선택된 지역을 그대로 반영하는 동반 콘텐츠다.
 */
export default function RegionMapSection({
  regionCode,
  inline = false,
  spots: givenSpots,
  spotsLoading: givenLoading,
  maxStops,
  routeLabel,
}: RegionMapSectionProps) {
  const selectedSido = useMemo(() => {
    const sidoCode = regionCode?.slice(0, 2);
    return (
      SIDO_REGIONS.find((sido) => sido.sidoCode === sidoCode) ??
      SIDO_REGIONS.find((sido) => sido.sidoCode === DEFAULT_SIDO_CODE) ??
      SIDO_REGIONS[0]
    );
  }, [regionCode]);

  const [fetchedSpots, setFetchedSpots] = useState<FeaturedSpot[]>([]);
  const [fetchedLoading, setFetchedLoading] = useState(true);
  const useGiven = givenSpots !== undefined;
  const spots: RouteSpot[] = useGiven ? givenSpots : fetchedSpots;
  const spotsLoading = useGiven ? !!givenLoading : fetchedLoading;

  useEffect(() => {
    if (useGiven) return; // 코스 스팟을 직접 받은 경우 featured 조회는 하지 않는다
    const controller = new AbortController();
    setFetchedLoading(true);
    // areaCd(시/도 전체 풀)로 받는다 — regionCode(구 단위)를 쓰면 지도가 커버하는 범위보다
    // 좁아져 코스선을 그릴 좌표가 쉽게 바닥난다.
    fetchFeatured(undefined, MAP_SPOTS_LIMIT, controller.signal, false, selectedSido.sidoCode)
      .then((res) => {
        if (controller.signal.aborted) return;
        setFetchedSpots([...res.hidden_picks, ...res.trending].filter((s) => !!s.image_url));
        setFetchedLoading(false);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setFetchedSpots([]);
        setFetchedLoading(false);
      });
    return () => controller.abort();
  }, [selectedSido.sidoCode, useGiven]);

  if (inline) {
    return (
      <div className="home-region-map region-map-inline" aria-label={`${selectedSido.shortName} 지역 지도`}>
        <RegionRouteMap
          selectedSido={selectedSido}
          spots={spots}
          spotsLoading={spotsLoading}
          onSelectSido={() => {}}
          hidePicker
          maxStops={maxStops}
          routeLabel={routeLabel}
        />
      </div>
    );
  }

  return (
    <section className="section region-map-section" aria-labelledby="regionMapHeading">
      <span className="eyebrow-pill eyebrow-pill--coral">지역 지도</span>
      <h2 className="section__title" id="regionMapHeading">
        {selectedSido.shortName}의 실제 경계 안에서
      </h2>
      <p className="region-map-section__sub">
        시/군/구 행정 경계와 추천 스팟 좌표를 그대로 얹었어요 — 지어낸 위치가 아니라 실제
        데이터로 그린 지도예요.
      </p>
      <div className="region-map-section__card home-region-map">
        <RegionRouteMap
          selectedSido={selectedSido}
          spots={spots}
          spotsLoading={spotsLoading}
          onSelectSido={() => {}}
          hidePicker
        />
      </div>
    </section>
  );
}
