"use client";

import { useEffect, useState } from "react";
import { Season, SeasonalPlacesResponse, fetchSeasonalPlaces } from "../lib/api";
import { FeaturedCardSkeleton, FeaturedSpotCard } from "./FeaturedSpots";
import { REGION_BLOCKS } from "./regions/blocks";
import type { SidoRegion } from "./regions/constants";
import RegionDropdown from "./regions/RegionDropdown";

type Status = "loading" | "success" | "error";

/**
 * §46(2026-08-01, 대표 지시: "계절여행에 지역 선택할 수 있게 해줘야할 거 같음 전국부터 9도까지").
 *
 * 옵션은 **전국 + 9권역**이다(17개 시도가 아니다) — 대표가 앞서 확정한 "광역시는 소속 도에
 * 흡수한 9도" 기준 그대로이고, 백엔드 REGION_BLOCKS 와 1:1이다(components/regions/blocks.ts).
 *
 * ThemesContent.tsx 와 같은 방식으로 `SidoRegion` **타입 모양만 빌려** RegionDropdown 에 꽂는다
 * (드롭다운 컴포넌트를 고치지 않기 위한 어댑터). 다만 여기서 `regionCode` 자리에 들어가는 값은
 * 시군구 코드가 아니라 **권역 key** 이고, 백엔드에는 `region_code` 가 아니라 `region_block`
 * 파라미터로 나간다 — 두 계약을 섞지 않는다(fetchSeasonalPlaces 주석 참고).
 */
const ALL_BLOCK_SENTINEL = "ALL";
const REGION_OPTIONS: SidoRegion[] = [
  {
    sidoCode: "00",
    shortName: "전국",
    initial: "전",
    regionCode: ALL_BLOCK_SENTINEL,
    representativeLabel: "전국 — 9권역을 섞어서 보여드려요",
  },
  ...REGION_BLOCKS.map((b) => ({
    sidoCode: b.key,
    shortName: b.label,
    initial: b.label.slice(0, 1),
    regionCode: b.key, // ← 권역 key(= region_block 값). 시군구 코드가 아니다.
    representativeLabel: b.label,
  })),
];

const SEASON_TABS: { value: Season; label: string }[] = [
  { value: "spring", label: "봄" },
  { value: "summer", label: "여름" },
  { value: "autumn", label: "가을" },
  { value: "winter", label: "겨울" },
];

/** 오늘 날짜 기준 현재 계절(월 기준 3구간). §37.3 근거 — 기본 탭 = 현재 계절. */
function currentSeason(): Season {
  const month = new Date().getMonth() + 1;
  if (month >= 3 && month <= 5) return "spring";
  if (month >= 6 && month <= 8) return "summer";
  if (month >= 9 && month <= 11) return "autumn";
  return "winter";
}

const SKELETON_COUNT = 4;

interface SeasonalSectionProps {
  /** 선택된 지역(sigungu_cd). FeaturedSpots·ThemeCollections와 동일 원칙 — 없으면 백엔드
   * 기본 지역으로 호출한다. */
  regionCode?: string | null;
}

/**
 * §37.3(신규, 03-design-spec.md, 2026-07-31) — 홈 "계절 여행" 섹션. 계절 탭(봄/여름/가을/겨울,
 * 기본=현재 계절) + "이 계절 인기"/"이 계절 숨은 명소" 2줄 카드행.
 *
 * 탭은 `.onboard-chip`(온보딩 축 단일 선택 칩)을 그대로 재사용한다 — 새 탭 컴포넌트를 만들지
 * 않는다(지시서 원칙: 신규 시각 언어 금지). 카드는 지시서가 명시한 대로 FeaturedSpotCard를
 * 재사용한다(응답 형태 해석은 lib/api.ts §R 주석 참고).
 *
 * graceful: 404/네트워크 실패 시 섹션 전체가 조용히 사라진다(ThemeCollections.tsx와 동일 원칙).
 */
export default function SeasonalSection({ regionCode }: SeasonalSectionProps) {
  const [season, setSeason] = useState<Season>(() => currentSeason());
  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<SeasonalPlacesResponse | null>(null);
  // §46 — 선택된 권역 key. null 이면 전국(파라미터 미전송).
  const [blockKey, setBlockKey] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    fetchSeasonalPlaces(
      season,
      regionCode ?? undefined,
      undefined,
      controller.signal,
      blockKey ?? undefined
    )
      .then((res) => {
        setData(res);
        setStatus("success");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        // 엔드포인트 미배포(404)든 네트워크 실패든 원인을 구분하지 않고 조용히 숨긴다.
        setStatus("error");
      });
    return () => controller.abort();
  }, [season, regionCode, blockKey]);

  if (status === "error") return null;

  const popular = data?.popular ?? [];
  const hidden = data?.hidden ?? [];
  const bothEmpty = status === "success" && popular.length === 0 && hidden.length === 0;

  return (
    <section className="section featured-section" aria-labelledby="seasonalHeading">
      <span className="eyebrow-pill eyebrow-pill--mint">계절 여행</span>
      <h2 className="section__title" id="seasonalHeading">
        지금 이 계절에 가기 좋은 곳
      </h2>

      {/* §46 — 지역 선택(전국 + 9권역). 이 섹션이 홈에 박혀 있던 시절엔 지역이 고정이었으나,
          전용 페이지가 된 뒤 대표 지시로 지역을 고를 수 있게 했다. regionCode prop 으로 지역이
          이미 지정된 호출부(홈 등)에서는 백엔드가 그쪽을 우선하므로 선택기를 띄우지 않는다. */}
      {!regionCode && (
        <div className="board-header-row">
          <RegionDropdown
            options={REGION_OPTIONS}
            selectedCode={blockKey ?? ALL_BLOCK_SENTINEL}
            triggerLabel={
              REGION_OPTIONS.find((o) => o.regionCode === (blockKey ?? ALL_BLOCK_SENTINEL))
                ?.shortName ?? "전국"
            }
            onSelect={(option) =>
              setBlockKey(option.regionCode === ALL_BLOCK_SENTINEL ? null : option.regionCode)
            }
            ariaLabel="계절 여행 지역 선택"
          />
        </div>
      )}

      <div className="chip-row season-tabs" role="tablist" aria-label="계절 선택">
        {SEASON_TABS.map((tab) => (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={season === tab.value}
            className={`onboard-chip${season === tab.value ? " is-selected" : ""}`}
            onClick={() => setSeason(tab.value)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* §37.3 — meta.notice("작년 같은 계절 기준" 류)는 항상 노출한다(지시서 필수 요구사항). */}
      {data?.meta.notice && <p className="seasonal__notice">{data.meta.notice}</p>}

      {bothEmpty ? (
        <p className="seasonal__empty">이 계절 추천을 아직 준비 중이에요.</p>
      ) : (
        <>
          {(status === "loading" || popular.length > 0) && (
            <div className="theme-collections__group">
              <h3 className="theme-collections__group-title">이 계절 인기</h3>
              <div className="featured-scroll" role="list" aria-label="이 계절 인기">
                {status === "loading"
                  ? Array.from({ length: SKELETON_COUNT }).map((_, i) => (
                      <FeaturedCardSkeleton key={i} />
                    ))
                  : popular.map((spot) => <FeaturedSpotCard key={spot.id} spot={spot} />)}
              </div>
            </div>
          )}
          {(status === "loading" || hidden.length > 0) && (
            <div className="theme-collections__group">
              <h3 className="theme-collections__group-title">이 계절 숨은 명소</h3>
              <div className="featured-scroll" role="list" aria-label="이 계절 숨은 명소">
                {status === "loading"
                  ? Array.from({ length: SKELETON_COUNT }).map((_, i) => (
                      <FeaturedCardSkeleton key={i} />
                    ))
                  : hidden.map((spot) => <FeaturedSpotCard key={spot.id} spot={spot} />)}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
