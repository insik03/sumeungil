"use client";

import { ChangeEvent, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { readRegionCode } from "../lib/regionQuery";
import { loadLastRegion, saveLastRegion } from "../lib/lastRegionStorage";
import Link from "next/link";
import {
  FeaturedResponse,
  FestivalsResponse,
  RegionChild,
  fetchFeatured,
  fetchFestivals,
  fetchRegionChildren,
} from "../lib/api";
import { FeaturedCardSkeleton, FeaturedSpotCard } from "./FeaturedSpots";
import { FestivalCard } from "./FestivalBanner";
import SidoStrip from "./regions/SidoStrip";
import { DEFAULT_SIDO_CODE, SIDO_REGIONS } from "./regions/constants";

type FetchStatus = "loading" | "success" | "error";

/** "전체" 옵션의 select value. 실제 시군구 코드(숫자 5자리)와 절대 겹치지 않는다. */
const ALL_SIGUNGU_VALUE = "__all__";

/**
 * §47(신규, 지역 허브 A안, 오케스트레이터 지시서 2026-08-11 — 대표 승인) — children API의
 * "경기도 가평군" 같은 전체 명칭에서 시도 접두("경기도 ")를 떼고 "가평군"만 보여준다. 데이터를
 * 새로 짓지 않고 서버가 준 문자열을 가공만 한다 — 첫 공백 앞 토큰(시도명)만 제거, 공백이 없으면
 * (세종처럼 시군구가 없는 케이스) 원문 그대로 둔다.
 */
function shortenSigunguLabel(label: string): string {
  const idx = label.indexOf(" ");
  if (idx === -1) return label;
  return label.slice(idx + 1);
}

const FESTIVAL_LIMIT = 4;

/**
 * §45(신규, 2026-08-0X, 03-design-spec.md — 대표 지시 "지역별 여행지면 그 지역에 핫한 여행지나
 * 이런 것도 막 뜨고 더보기도 있고 축제도 뜨고 이래야 하는데 안 뜬다") — "지금 많이 찾는 곳"/
 * "숨은 발견" 더보기 단계. `GET /api/v1/places/featured`는 offset 페이지네이션 계약이 없다
 * (01-interface-contract.md 부록 H) — 그래서 ThemeCollections(offset 재조회)와 달리 **더 큰
 * limit으로 처음부터 다시 조회**한다(지시서 명시 방식). 8(기존 기본값과 동일, 화면 변화 없음)
 * →24→48(API 상한, featured_service.py LIMIT_MAX)로 3단계, 상한에 닿으면 버튼을 숨긴다.
 *
 * trending·hidden_picks는 **하나의 limit 파라미터를 공유**한다(featured_service.py:
 * `hidden_n = min(limit, HIDDEN_PICKS_MAX=6)`) — "숨은 발견" 축은 6개에서 이미 상한에 닿아 더
 * 늘지 않을 수 있지만, 두 섹션의 더보기/접기 버튼은 같은 상태(featuredTierIdx)를 공유한다.
 * 인기 축은 계속 늘어나므로 어느 쪽 버튼을 눌러도 항상 의미가 있다(죽은 버튼 없음).
 */
const FEATURED_TIERS = [8, 24, 48];

/**
 * `/regions` 지역 허브 — 구석구석 `/main/area.do`(D-1 시도 원형 스트립·D-2 인기 여행지 그리드·
 * D-3 시도별 브라우징) 흡수, 03-design-spec.md §29. Phase B(06-deep-audit-gap-plan.md).
 *
 * §45(신규) — 대표 지시로 "테마로 둘러보기" 축은 이 화면에서 뺐다("지역별 추천에 테마도 뜨는
 * 건 별로"). 테마는 이미 `/themes` 전용 페이지가 전담한다(ThemesContent.tsx, 지역 선택 포함) —
 * 중복 노출을 없애고, 대신 인기/숨은 스팟에 더보기·접기를 붙이고 축제 섹션을 강화했다.
 *
 * §47(개편, 지역 허브 A안, 오케스트레이터 지시서 2026-08-11 — 대표 승인) — 시도를 고르면
 * 대표 시군구 1곳이 아니라 **그 시도 전체**에서 집계한다. 시군구 드롭다운(기본 "전체")으로
 * 좁힐 수 있다. 신규 backend는 children 엔드포인트 1개뿐, featured/festivals는 기존 계약에
 * `area_cd`(시도 전체 조회) 파라미터만 additive로 더했다:
 * - fetchFeatured(regionCode, limit, signal, diverse, areaCd): "전체"면 areaCd만, 특정
 *   시군구면 regionCode만 넘긴다(계약상 regionCode 우선이라 동시에 보내지 않는다) —
 *   trending(지금 많이 찾는 곳) + hidden_picks(숨은 발견, ★우위 노출), limit을 8→24→48로
 *   키워가며 "더보기"(§45, FEATURED_TIERS 참고).
 * - fetchFestivals(regionCode, 4, signal, { areaCd }): 위와 동일 규약. 응답의 `total`은 이
 *   4건 미리보기와 무관하게 "필터를 통과한 전체 수"라(festival_service.py 주석) — 4건보다
 *   많으면 "전체 N건 보기" CTA로 지역명을 명시해 `/festivals`로 보낸다(그 페이지가 지역
 *   쿼리를 받지 않아 필터는 유지되지 않지만, 몇 건이 더 있는지는 지어내지 않고 정확히 알려준다).
 * - fetchRegionChildren(areaCd): 드롭다운 옵션(스팟 있는 시군구만, 가나다순).
 *
 * 우위 규율(§3, 06-deep-audit-gap-plan.md) — "숨은 발견" 섹션에 W2(예상 혼잡도 로드밸런싱)를
 * 문구로 명시해, 흡수 화면에도 구석구석에 없는 우리 축을 반드시 노출한다.
 *
 * §45 — 빈 상태 정직 표기(대표 지시 "안 뜬다"고 느끼는 원인 대응): trending/hidden_picks 중
 * 한쪽만 비어도(예: 혼잡도 원천 쿼터 소진으로 trending만 0건) 그 섹션이 조용히 사라지지 않고
 * "지금은 이 지역 OO 정보를 불러오지 못했어요" 안내가 그 자리에 남는다(값을 지어내지 않는다).
 * trending·hidden_picks가 **둘 다** 빈 지역(세종 선례)만 기존처럼 통합 안내 카드로 대체한다.
 * 축제 0건 지역도 동일 원칙(기존에 이미 구현돼 있었다, 유지).
 */
export default function RegionsContent() {
  // 2026-08-01(대표 지적 "경기권 보고 전체보기로 나갔는데 부산이 뜬다") — 이 화면이 URL 의
  // `?region_code=` 를 **아예 읽지 않아** 항상 기본 지역(부산)으로 시작했다. 다른 화면들이
  // 이미 쓰는 readRegionCode 규칙(숫자 5자리)을 그대로 써서 초기 시도/시군구를 정한다.
  // 전달된 시군구 코드는 **앞 2자리(시도)로 매칭**한다(예: 41820 경기 가평군 → 경기 41) —
  // §47(개편) 이후로는 SIDO_REGIONS의 하드코딩 대표값과 일치할 필요가 없다(임의의 실제 시군구
  // 코드를 그대로 드롭다운 선택값으로 쓴다). 매칭 실패 시에만 기본값(시도 26/전체)을 쓴다.
  const searchParams = useSearchParams();
  // URL 쿼리는 SSR에서도 동일하게 읽혀 서버/클라이언트 첫 렌더가 일치한다(하이드레이션
  // 안전) — 초기 state는 여기까지만 쓴다.
  const { initialSidoCode, initialSigunguCode } = (() => {
    const code = readRegionCode(searchParams.get("region_code"));
    if (code) {
      const bySido = SIDO_REGIONS.find((s) => s.sidoCode === code.slice(0, 2));
      if (bySido) return { initialSidoCode: bySido.sidoCode, initialSigunguCode: code };
    }
    return { initialSidoCode: DEFAULT_SIDO_CODE, initialSigunguCode: null as string | null };
  })();
  const [selectedSidoCode, setSelectedSidoCode] = useState(initialSidoCode);
  // null = "전체"(§47 기본값). 시도를 바꾸면 항상 "전체"로 리셋한다(handleSelectSido).
  const [selectedSigunguCode, setSelectedSigunguCode] = useState<string | null>(initialSigunguCode);
  // 대표 지시(2026-08-17) — URL 쿼리가 없을 때만 마지막으로 고른 지역(세션 기억)을 적용한다.
  // sessionStorage는 서버에서 못 읽으므로 mount 후 effect에서 반영해야 하이드레이션이
  // 깨지지 않는다(HomeContent.tsx와 동일 이유, 실측으로 확인된 버그 재발 방지).
  useEffect(() => {
    if (readRegionCode(searchParams.get("region_code"))) return; // URL이 이미 명시했다면 건드리지 않음
    const last = loadLastRegion();
    if (!last) return;
    const bySido = SIDO_REGIONS.find((s) => s.sidoCode === last.area_cd);
    if (!bySido) return;
    setSelectedSidoCode(bySido.sidoCode);
    setSelectedSigunguCode(last.sigungu_cd);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const selectedSido =
    SIDO_REGIONS.find((s) => s.sidoCode === selectedSidoCode) ?? SIDO_REGIONS[0];
  // "전체" 모드에서 /recommend·/course CTA에 실을 대표 시군구 — 그 두 화면은 여전히 구체적인
  // sigungu_cd 1개가 필요해(자체 계약, 이번 지시서 범위 밖) 기존 하드코딩 대표값을 그대로
  // 폴백으로 쓴다. 사용자가 시군구를 직접 골랐으면 그 값이 우선한다(더 구체적이니 더 정확하다).
  const ctaRegionCode = selectedSigunguCode ?? selectedSido.regionCode;

  // §47 — children(시군구 드롭다운) 옵션. 시도가 바뀔 때만 재조회한다.
  const [childrenStatus, setChildrenStatus] = useState<FetchStatus>("loading");
  const [sigunguChildren, setSigunguChildren] = useState<RegionChild[]>([]);

  const [featuredStatus, setFeaturedStatus] = useState<FetchStatus>("loading");
  const [featured, setFeatured] = useState<FeaturedResponse | null>(null);
  // §45 — "더보기" 단계 인덱스(FEATURED_TIERS). 인기/숨은 두 섹션이 공유(위 주석 참고).
  const [featuredTierIdx, setFeaturedTierIdx] = useState(0);
  const [featuredLoadingMore, setFeaturedLoadingMore] = useState(false);
  const [featuredMoreError, setFeaturedMoreError] = useState(false);

  const [festivalsStatus, setFestivalsStatus] = useState<FetchStatus>("loading");
  const [festivals, setFestivals] = useState<FestivalsResponse | null>(null);

  /** 시도 칩 클릭 핸들러 — 시도를 바꾸면 시군구 선택은 항상 "전체"로 리셋한다(지시서 요구사항).
   *  useEffect로 selectedSidoCode 변화를 감시해 리셋하면 한 프레임 동안 "새 시도 + 옛 시군구"라는
   *  잘못된 조합으로 API를 호출하게 돼, 클릭 핸들러에서 두 상태를 함께 갱신한다. */
  const handleSelectSido = (code: string) => {
    setSelectedSidoCode(code);
    setSelectedSigunguCode(null);
  };

  useEffect(() => {
    const controller = new AbortController();
    setChildrenStatus("loading");
    fetchRegionChildren(selectedSidoCode, controller.signal)
      .then((res) => {
        setSigunguChildren(res.items);
        setChildrenStatus("success");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        // 실패해도 "전체"는 계속 동작해야 한다(지시서 요구사항) — 드롭다운만 "전체" 단일 옵션으로 남는다.
        setSigunguChildren([]);
        setChildrenStatus("error");
      });
    return () => controller.abort();
  }, [selectedSidoCode]);

  useEffect(() => {
    const controller = new AbortController();
    setFeaturedStatus("loading");
    setFeaturedTierIdx(0);
    setFeaturedMoreError(false);
    fetchFeatured(
      selectedSigunguCode ?? undefined,
      FEATURED_TIERS[0],
      controller.signal,
      undefined,
      selectedSigunguCode ? undefined : selectedSidoCode
    )
      .then((res) => {
        setFeatured(res);
        setFeaturedStatus("success");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setFeaturedStatus("error");
      });
    return () => controller.abort();
  }, [selectedSidoCode, selectedSigunguCode]);

  useEffect(() => {
    const controller = new AbortController();
    setFestivalsStatus("loading");
    fetchFestivals(selectedSigunguCode ?? undefined, FESTIVAL_LIMIT, controller.signal, {
      areaCd: selectedSigunguCode ? undefined : selectedSidoCode,
    })
      .then((res) => {
        setFestivals(res);
        setFestivalsStatus("success");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setFestivalsStatus("error");
      });
    return () => controller.abort();
  }, [selectedSidoCode, selectedSigunguCode]);

  /** §47 — 드롭다운 표시용 라벨. children 목록에서 우선 찾고(정상 경로), 딥링크로 들어온
   *  코드가 그 시도의 children 목록에 없는 예외 상황(예: 서버 최소 스팟 기준 미달로 목록엔
   *  빠졌지만 개별 조회는 되는 코드)엔 featured/festivals 응답의 region.region_name으로
   *  보강한다(§H/§K 계약 — 둘 다 실제 서버 값, 지어내지 않는다). 그마저 없으면 코드 자체를
   *  보여줘 최소한 선택값이 사라지지는 않게 한다. */
  const selectedChild =
    sigunguChildren.find((c) => c.region_code === selectedSigunguCode) ?? null;
  const fallbackSigunguLabel =
    featured?.region?.region_code === selectedSigunguCode
      ? featured.region.region_name
      : festivals?.region?.region_code === selectedSigunguCode
        ? festivals.region.region_name
        : selectedSigunguCode;
  const selectedSigunguFullLabel = selectedChild?.label ?? fallbackSigunguLabel ?? "";

  // 대표 지시(2026-08-17) — 이 화면에서 고른 지역도 "마지막으로 고른 지역"으로 기억해 다른
  // 기본 화면(홈 등)의 기본값에 반영한다. 시군구 라벨이 아직 안 왔으면(children/featured
  // 로딩 중) 시도 대표 라벨로 우선 저장하고, 나중에 더 구체적인 라벨이 오면 갱신된다.
  useEffect(() => {
    saveLastRegion({
      region_id: selectedSigunguCode ? `sigungu-${selectedSigunguCode}` : `sido-${selectedSido.sidoCode}`,
      label: selectedSigunguCode ? selectedSigunguFullLabel || selectedSido.representativeLabel : selectedSido.representativeLabel,
      area_cd: selectedSido.sidoCode,
      sigungu_cd: ctaRegionCode,
    });
  }, [selectedSido.sidoCode, selectedSigunguCode, ctaRegionCode, selectedSigunguFullLabel, selectedSido.representativeLabel]);

  const handleSelectSigungu = (e: ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value;
    setSelectedSigunguCode(value === ALL_SIGUNGU_VALUE ? null : value);
  };

  const trending = featured?.trending ?? [];
  const hiddenPicks = featured?.hidden_picks ?? [];
  const bothFeaturedEmpty =
    featuredStatus === "success" && trending.length === 0 && hiddenPicks.length === 0;

  // 부록 H.6(2026-08-01) — 서버가 알려준 후보 총 수로 "더 있는지"를 판정한다.
  // 이게 없으면 단계만 남아 있으면 버튼을 보여주는데, 실제로는 그 지역 후보가 이미 소진돼
  // **눌러도 카드가 늘지 않는 죽은 버튼**이 된다(실측: 해운대 trending 총 8곳 = 이미 전량 노출).
  // total 이 null(구버전 백엔드/홈 diverse)이면 보수적으로 단계 기준만 쓴다.
  const trendingTotal = featured?.trending_total ?? null;
  const hiddenTotal = featured?.hidden_total ?? null;
  const tierHasNext = featuredTierIdx < FEATURED_TIERS.length - 1;
  const trendingHasMore =
    trendingTotal === null ? tierHasNext : trending.length < trendingTotal;
  const hiddenHasMore = hiddenTotal === null ? tierHasNext : hiddenPicks.length < hiddenTotal;
  // 두 섹션이 limit 을 공유하므로, 한쪽이라도 더 받을 게 있으면 재조회할 가치가 있다.
  const canLoadMoreFeatured = tierHasNext && (trendingHasMore || hiddenHasMore);
  const canCollapseFeatured = featuredTierIdx > 0;

  const handleLoadMoreFeatured = () => {
    if (featuredLoadingMore || !canLoadMoreFeatured) return;
    const nextIdx = featuredTierIdx + 1;
    const nextLimit = FEATURED_TIERS[nextIdx];
    setFeaturedLoadingMore(true);
    setFeaturedMoreError(false);
    fetchFeatured(
      selectedSigunguCode ?? undefined,
      nextLimit,
      undefined,
      undefined,
      selectedSigunguCode ? undefined : selectedSidoCode
    )
      .then((res) => {
        setFeatured(res);
        setFeaturedTierIdx(nextIdx);
      })
      .catch(() => {
        setFeaturedMoreError(true);
      })
      .finally(() => {
        setFeaturedLoadingMore(false);
      });
  };

  /** 접기(대표 지시, ThemeCollections.handleCollapse와 동일 원칙) — 재조회하지 않고 이미 받은
   *  배열을 초기 단계 개수로 잘라낸다(원천·사진 호출 0). 다시 "더보기"를 누르면 그 시점부터는
   *  실제로 재조회한다(캐시를 들고 있지 않음 — ThemeCollections와 동일하게 단순함을 우선). */
  const handleCollapseFeatured = () => {
    setFeatured((prev) =>
      prev
        ? {
            ...prev,
            trending: prev.trending.slice(0, FEATURED_TIERS[0]),
            hidden_picks: prev.hidden_picks.slice(0, FEATURED_TIERS[0]),
          }
        : prev
    );
    setFeaturedTierIdx(0);
    setFeaturedMoreError(false);
  };

  const festivalList = festivals?.festivals ?? [];
  // festivals.total은 이 4건 미리보기와 무관하게 "필터를 통과한 전체 수"(festival_service.py
  // 주석: "total = 필터를 통과한 전체 수(limit 절삭 전)") — 4건보다 많을 때만 지역명 CTA로 바꾼다.
  const hasMoreFestivals =
    typeof festivals?.total === "number" && festivals.total > festivalList.length;

  return (
    <>
      <section className="section regions-hero">
        <span className="eyebrow-pill eyebrow-pill--coral">전국 지역 허브</span>
        <h1 className="section__title">지역을 골라 숨은길을 둘러보세요</h1>

        <SidoStrip selected={selectedSidoCode} onSelect={handleSelectSido} />

        <div className="regions-current">
          <h2 className="regions-current__title">{selectedSido.shortName} 여행</h2>

          {/* §47(신규) — 시군구 드롭다운. 기본 "전체"(그 시도 전체 집계), 특정 시군구를 고르면
              기존 region_code 흐름 그대로 좁혀서 보여준다. children 실패 시에도 "전체" 단일
              옵션으로 계속 동작한다(지시서 요구사항). */}
          <div className="regions-sigungu-picker">
            <label htmlFor="regions-sigungu-select" className="regions-sigungu-picker__label">
              시군구로 좁혀보기
            </label>
            <select
              id="regions-sigungu-select"
              className="regions-sigungu-select"
              value={selectedSigunguCode ?? ALL_SIGUNGU_VALUE}
              onChange={handleSelectSigungu}
              disabled={childrenStatus === "loading"}
              aria-label={`${selectedSido.shortName} 시군구 선택`}
            >
              <option value={ALL_SIGUNGU_VALUE}>전체</option>
              {sigunguChildren.map((child) => (
                <option key={child.region_code} value={child.region_code}>
                  {shortenSigunguLabel(child.label)}
                </option>
              ))}
              {/* 딥링크로 들어온 코드가 이 시도의 children 목록에 없는 예외 상황에도 선택값을
                  잃지 않도록 폴백 옵션을 하나 더 둔다(위 selectedSigunguFullLabel 주석 참고). */}
              {selectedSigunguCode &&
                !sigunguChildren.some((c) => c.region_code === selectedSigunguCode) && (
                  <option value={selectedSigunguCode}>
                    {shortenSigunguLabel(selectedSigunguFullLabel)}
                  </option>
                )}
            </select>
            {childrenStatus === "error" && (
              <p className="regions-sigungu-picker__error" role="status">
                시군구 목록을 불러오지 못했어요 — 전체 보기는 계속 이용할 수 있어요.
              </p>
            )}
          </div>

          {/* §47 — "이 지역은 사실 ○○ 기준" 정직 캡션은 "전체"가 이제 진짜 시도 전체 집계라
              필요 없어져 뺐다. 특정 시군구를 골랐을 때만, 무엇을 보고 있는지 확인해준다. */}
          {selectedSigunguCode && (
            <p className="regions-current__caption">
              지금은 {selectedSigunguFullLabel} 스팟만 보여드려요.
            </p>
          )}
        </div>
      </section>

      {bothFeaturedEmpty && (
        <section className="section" aria-live="polite">
          <div className="regions-empty">
            <p className="regions-empty__msg">
              {selectedSido.shortName}은(는) 아직 채워진 스팟이 많지 않아요.
            </p>
            <p className="regions-empty__hint">
              곧 더 채워질게요 — 그동안 다른 시도를 먼저 둘러보시거나, 아래에서 맞춤 추천을
              받아보세요.
            </p>
          </div>
        </section>
      )}

      {/* §46(신규, 03-design-spec.md, 2026-08-10 — 대표 승인) — 공모전 지정과제 2번("숨은
          관광지 추천") 정체성에 맞춰 "숨은길 PICK"을 "지금 많이 찾는 곳"보다 먼저 렌더한다.
          fetch·더보기/접기 로직(featuredTierIdx 등)은 두 섹션이 그대로 공유 — 블록 순서와
          카피만 바꿨다. */}
      {!bothFeaturedEmpty && (
        <section className="section featured-section" aria-label="숨은 발견">
          <span className="eyebrow-pill eyebrow-pill--mint">숨은길 PICK</span>
          <div className="regions-section__head">
            <h2 className="section__title">
              AI가 찾은, 아직 붐비지 않는 {selectedSido.shortName}의 숨은 명소
            </h2>
            {featuredStatus === "success" && hiddenPicks.length > 0 && (
              <div className="regions-section__head-actions">
                {canCollapseFeatured && (
                  <button
                    type="button"
                    className="theme-collections__more-btn theme-collections__more-btn--collapse"
                    onClick={handleCollapseFeatured}
                    aria-label="숨은 발견 접기"
                  >
                    접기
                  </button>
                )}
                {canLoadMoreFeatured && hiddenHasMore && (
                  <button
                    type="button"
                    className="theme-collections__more-btn"
                    onClick={handleLoadMoreFeatured}
                    disabled={featuredLoadingMore}
                    aria-label="숨은 발견 더보기"
                  >
                    {featuredLoadingMore ? "불러오는 중…" : "더보기"}
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path
                        d="M9 5l7 7-7 7"
                        stroke="currentColor"
                        strokeWidth="2.2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                )}
              </div>
            )}
          </div>
          <p className="regions-advantage">
            예상 혼잡도가 낮은 곳을 AI가 먼저 찾아드려요 — 구석구석 같은 포털엔 없는 숨은길만의
            시선이에요.
          </p>
          {featuredStatus === "loading" ? (
            <div className="featured-scroll" role="list" aria-label="불러오는 중" aria-busy="true">
              {Array.from({ length: 4 }).map((_, i) => (
                <FeaturedCardSkeleton key={i} />
              ))}
            </div>
          ) : hiddenPicks.length > 0 ? (
            <div className="featured-scroll" role="list">
              {hiddenPicks.map((spot) => (
                <FeaturedSpotCard key={spot.id} spot={spot} />
              ))}
            </div>
          ) : (
            <div className="festival-empty" role="status">
              <p className="festival-empty__msg">
                지금은 이 지역의 숨은 스팟 정보를 불러오지 못했어요.
              </p>
              <p className="festival-empty__hint">잠시 후 다시 확인해 주세요.</p>
            </div>
          )}
          {featuredMoreError && (
            <p className="theme-collections__load-error" role="status">
              더 불러오지 못했어요. 잠시 후 다시 시도해주세요.
            </p>
          )}
        </section>
      )}

      {!bothFeaturedEmpty && (
        <section className="section featured-section" aria-label="지금 많이 찾는 곳">
          <span className="eyebrow-pill eyebrow-pill--coral">지금 많이 찾는 곳</span>
          <div className="regions-section__head">
            <h2 className="section__title">
              {selectedSido.shortName}에서 붐비는 곳도 확인해보세요
            </h2>
            {featuredStatus === "success" && trending.length > 0 && (
              <div className="regions-section__head-actions">
                {canCollapseFeatured && (
                  <button
                    type="button"
                    className="theme-collections__more-btn theme-collections__more-btn--collapse"
                    onClick={handleCollapseFeatured}
                    aria-label="지금 많이 찾는 곳 접기"
                  >
                    접기
                  </button>
                )}
                {canLoadMoreFeatured && trendingHasMore && (
                  <button
                    type="button"
                    className="theme-collections__more-btn"
                    onClick={handleLoadMoreFeatured}
                    disabled={featuredLoadingMore}
                    aria-label="지금 많이 찾는 곳 더보기"
                  >
                    {featuredLoadingMore ? "불러오는 중…" : "더보기"}
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path
                        d="M9 5l7 7-7 7"
                        stroke="currentColor"
                        strokeWidth="2.2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                )}
              </div>
            )}
          </div>
          {featuredStatus === "loading" ? (
            <div className="featured-scroll" role="list" aria-label="불러오는 중" aria-busy="true">
              {Array.from({ length: 4 }).map((_, i) => (
                <FeaturedCardSkeleton key={i} />
              ))}
            </div>
          ) : trending.length > 0 ? (
            <div className="featured-scroll" role="list">
              {trending.map((spot) => (
                <FeaturedSpotCard key={spot.id} spot={spot} />
              ))}
            </div>
          ) : (
            <div className="festival-empty" role="status">
              <p className="festival-empty__msg">
                지금은 이 지역 혼잡도 정보를 불러오지 못했어요.
              </p>
              <p className="festival-empty__hint">잠시 후 다시 확인해 주세요.</p>
            </div>
          )}
          {featuredMoreError && (
            <p className="theme-collections__load-error" role="status">
              더 불러오지 못했어요. 잠시 후 다시 시도해주세요.
            </p>
          )}
        </section>
      )}

      <section className="section featured-section" aria-label="진행중·예정 축제">
        <span className="eyebrow-pill eyebrow-pill--azure">진행중·예정 축제</span>
        <h2 className="section__title">{selectedSido.shortName}의 축제 소식</h2>
        {festivalsStatus === "loading" && (
          <div className="featured-scroll" role="list" aria-label="축제 불러오는 중" aria-busy="true">
            {Array.from({ length: 3 }).map((_, i) => (
              <FeaturedCardSkeleton key={i} />
            ))}
          </div>
        )}
        {festivalsStatus === "success" && festivalList.length === 0 && (
          <div className="festival-empty" role="status">
            <p className="festival-empty__msg">
              {selectedSido.shortName}은(는) 지금 진행 중인 축제가 없어요.
            </p>
            <p className="festival-empty__hint">축제 소식이 들어오면 이 자리에서 바로 알려드릴게요.</p>
          </div>
        )}
        {festivalsStatus === "success" && festivalList.length > 0 && (
          <>
            <div className="featured-scroll" role="list">
              {festivalList.map((festival) => (
                <FestivalCard key={festival.id} festival={festival} />
              ))}
            </div>
            <Link href="/festivals" className="festival-section__cta">
              {hasMoreFestivals
                ? `${selectedSido.shortName} 축제 ${festivals!.total}건 전체 보기`
                : "전국 축제 모두 보기"}
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M9 5l7 7-7 7"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </Link>
          </>
        )}
      </section>

      <section className="section regions-cta">
        <div className="regions-cta__box">
          <h2 className="regions-cta__title">{selectedSido.shortName} 여행, 이렇게 이어가보세요</h2>
          <div className="regions-cta__row">
            <Link
              href={`/recommend?region_code=${encodeURIComponent(ctaRegionCode)}`}
              className="btn btn--coral"
            >
              이 지역 맞춤 추천 받기
            </Link>
            <Link
              href={`/course?region_code=${encodeURIComponent(ctaRegionCode)}`}
              className="btn btn--outline"
            >
              이 지역 하루 코스 짜기
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
