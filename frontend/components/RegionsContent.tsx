"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { readRegionCode } from "../lib/regionQuery";
import Link from "next/link";
import { FeaturedResponse, FestivalsResponse, fetchFeatured, fetchFestivals } from "../lib/api";
import { FeaturedCardSkeleton, FeaturedSpotCard } from "./FeaturedSpots";
import { FestivalCard } from "./FestivalBanner";
import SidoStrip from "./regions/SidoStrip";
import { DEFAULT_SIDO_CODE, SIDO_REGIONS } from "./regions/constants";

type FetchStatus = "loading" | "success" | "error";

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
 * 신규 backend 0 원칙 — 전부 기존 계약 재사용:
 * - fetchFeatured(regionCode, limit): trending(지금 많이 찾는 곳) + hidden_picks(숨은 발견,
 *   ★우위 노출) — limit을 8→24→48로 키워가며 "더보기"(§45, FEATURED_TIERS 참고).
 * - fetchFestivals(regionCode, 4): 진행중·예정 축제 프리뷰. 응답의 `total`은 이 4건 미리보기와
 *   무관하게 "필터를 통과한 전체 수"라(festival_service.py 주석) — 4건보다 많으면 "전체 N건
 *   보기" CTA로 지역명을 명시해 `/festivals`로 보낸다(그 페이지가 지역 쿼리를 받지 않아 필터는
 *   유지되지 않지만, 몇 건이 더 있는지는 지어내지 않고 정확히 알려준다).
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
  // 이미 쓰는 readRegionCode 규칙(숫자 5자리)을 그대로 써서 초기 시도를 정한다.
  // 전달된 시군구 코드가 SIDO_REGIONS 대표값과 달라도 **앞 2자리(시도)로 매칭**한다
  // (예: 41111 수원 장안 → 경기 41). 매칭 실패 시에만 기본값을 쓴다(지어내지 않는다).
  const searchParams = useSearchParams();
  const initialSido = (() => {
    const code = readRegionCode(searchParams.get("region_code"));
    if (!code) return DEFAULT_SIDO_CODE;
    const exact = SIDO_REGIONS.find((s) => s.regionCode === code);
    if (exact) return exact.sidoCode;
    const bySido = SIDO_REGIONS.find((s) => s.sidoCode === code.slice(0, 2));
    return bySido ? bySido.sidoCode : DEFAULT_SIDO_CODE;
  })();
  const [selectedSidoCode, setSelectedSidoCode] = useState(initialSido);
  const selectedSido =
    SIDO_REGIONS.find((s) => s.sidoCode === selectedSidoCode) ?? SIDO_REGIONS[0];
  const regionCode = selectedSido.regionCode;

  const [featuredStatus, setFeaturedStatus] = useState<FetchStatus>("loading");
  const [featured, setFeatured] = useState<FeaturedResponse | null>(null);
  // §45 — "더보기" 단계 인덱스(FEATURED_TIERS). 인기/숨은 두 섹션이 공유(위 주석 참고).
  const [featuredTierIdx, setFeaturedTierIdx] = useState(0);
  const [featuredLoadingMore, setFeaturedLoadingMore] = useState(false);
  const [featuredMoreError, setFeaturedMoreError] = useState(false);

  const [festivalsStatus, setFestivalsStatus] = useState<FetchStatus>("loading");
  const [festivals, setFestivals] = useState<FestivalsResponse | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setFeaturedStatus("loading");
    setFeaturedTierIdx(0);
    setFeaturedMoreError(false);
    fetchFeatured(regionCode, FEATURED_TIERS[0], controller.signal)
      .then((res) => {
        setFeatured(res);
        setFeaturedStatus("success");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setFeaturedStatus("error");
      });
    return () => controller.abort();
  }, [regionCode]);

  useEffect(() => {
    const controller = new AbortController();
    setFestivalsStatus("loading");
    fetchFestivals(regionCode, FESTIVAL_LIMIT, controller.signal)
      .then((res) => {
        setFestivals(res);
        setFestivalsStatus("success");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setFestivalsStatus("error");
      });
    return () => controller.abort();
  }, [regionCode]);

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
    fetchFeatured(regionCode, nextLimit)
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
        <p className="regions-hero__sub">
          전국 17개 시도를 골라보세요. 사람이 몰리는 곳뿐 아니라, AI가 예상 혼잡도를 살펴 찾아낸
          한적한 곳까지 함께 보여드려요.
        </p>

        <SidoStrip selected={selectedSidoCode} onSelect={setSelectedSidoCode} />

        <div className="regions-current">
          <h2 className="regions-current__title">{selectedSido.shortName} 여행</h2>
          <p className="regions-current__caption">
            지금은 {selectedSido.representativeLabel} 스팟을 중심으로 보여드려요.
          </p>
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
              href={`/recommend?region_code=${encodeURIComponent(regionCode)}`}
              className="btn btn--coral"
            >
              이 지역 맞춤 추천 받기
            </Link>
            <Link
              href={`/course?region_code=${encodeURIComponent(regionCode)}`}
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
