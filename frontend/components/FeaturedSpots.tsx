"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  FeaturedResponse,
  FeaturedSpot,
  ReviewSummary,
  SpotCategory,
  fetchFeatured,
  fetchReviewsSummaryBulk,
} from "../lib/api";
import { CATEGORY_META } from "./recommend/constants";
import RatingBadge from "./RatingBadge";

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  CATEGORY_META.map((c) => [c.value, c.label])
);

/** 01-interface-contract.md §4.1과 동일한 레벨→배지 매핑(SpotCard.tsx·BoardCard.tsx와 동일 규약). */
const LEVEL_META: Record<string, { label: string; badgeClass: string }> = {
  high: { label: "혼잡", badgeClass: "badge--hot" },
  mid: { label: "보통", badgeClass: "badge--mid" },
  low: { label: "여유", badgeClass: "badge--calm" },
  unknown: { label: "정보없음", badgeClass: "badge--unknown" },
};

/**
 * 사진이 없을 때 플레이스홀더 색조 — 카테고리를 3개 톤(B안 기존 토큰)으로 묶어 시각적으로 구분한다.
 * §36(신규, 03-design-spec.md) — PhotoCarousel.tsx가 스팟 상세 사진 슬라이드에서 그대로 재사용한다
 * (export만 추가, 로직·값 변경 없음 — 단일 소스 원칙, FestivalBanner.tsx의 export 방식과 동일).
 */
export function placeholderTone(category: SpotCategory): "mint" | "sand" | "azure" {
  if (category === "attraction" || category === "nature" || category === "trail") return "mint";
  if (category === "restaurant" || category === "cafe" || category === "market") return "sand";
  return "azure"; // craft, etc
}

export function PlaceholderGlyph() {
  return (
    <svg width="30" height="30" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="2" y="4" width="20" height="16" rx="3" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="8" cy="10" r="1.8" fill="currentColor" />
      <path
        d="M3 17l5-5 4 4 3-3 6 6"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

interface FeaturedSpotCardProps {
  spot: FeaturedSpot;
  /** §40(신규) — 별점·리뷰 자리. 요약이 없으면 RatingBadge가 "후기 없음"으로 표기한다. */
  rating?: number | null;
  reviewCount?: number;
}

/** ThemeCollections.tsx(테마 컬렉션)가 동일한 사진 카드를 그대로 재사용한다(§03-design-spec.md 근거). */
export function FeaturedSpotCard({ spot, rating, reviewCount }: FeaturedSpotCardProps) {
  const [imgFailed, setImgFailed] = useState(false);
  const levelMeta = spot.congestion ? LEVEL_META[spot.congestion.level] ?? LEVEL_META.unknown : null;
  const showImage = !!spot.image_url && !imgFailed;

  return (
    <Link href={`/spot/${spot.id}`} className="featured-card-link" role="listitem">
      <article className="featured-card">
        <div className="featured-card__media">
          {showImage ? (
            // 외부 이미지 URL — next/image 도메인 설정 회피를 위해 plain img + lazy 사용(§작업 4).
            <img
              src={spot.image_url as string}
              alt=""
              loading="lazy"
              className="featured-card__img"
              onError={() => setImgFailed(true)}
            />
          ) : (
            <div
              className={`featured-card__placeholder featured-card__placeholder--${placeholderTone(spot.category)}`}
            >
              <PlaceholderGlyph />
            </div>
          )}
          {spot.is_hidden_gem && (
            <span className="badge badge--hidden-gem featured-card__badge">숨은 스팟</span>
          )}
          {/* §34(신규, 부록 H.3) — 사진이 실제로 뜰 때만, 우하단에 작게 출처를 표기한다(저작권 표기
              준수용). photo_credit이 없으면 아무것도 렌더하지 않는다(지어내지 않음). */}
          {showImage && spot.photo_credit && (
            <span className="featured-card__credit">{spot.photo_credit}</span>
          )}
        </div>
        <div className="featured-card__body">
          <span className="featured-card__category">
            {CATEGORY_LABEL[spot.category] ?? spot.category}
          </span>
          <h3 className="featured-card__name">{spot.name}</h3>
          <p className="featured-card__region">{spot.region_name}</p>
          {/* §40(신규) — 혼잡도 배지와 별점·리뷰 아이콘을 같은 행에 둔다(새 행 추가 금지, 대표
              지시: 카드 높이 불변). meta-row에서 두 아이템 모두 flex-shrink:0으로 고정해
              배지 내부 줄바꿈으로 카드가 늘어나는 일이 없게 한다(폭이 모자라면 잘림만 발생 —
              .featured-card의 overflow:hidden이 안전판, globals.css 근거 주석 참고). */}
          <div className="featured-card__meta-row">
            {/* 대표 지시(카드 크기 통일 + "정보없음" 문구는 신뢰성 저하라 미표기):
                혼잡도가 없으면 보이지 않는 고스트 뱃지로 같은 높이만 차지하게 한다. */}
            {levelMeta ? (
              <span className={`badge ${levelMeta.badgeClass} featured-card__congestion`}>
                <span className="badge__icon" aria-hidden="true"></span>
                {/* 대표 지시(2026-07-31): 혼잡/여유 라벨만으로는 정도를 알 수 없어 불편하다 →
                    수치(집중률 %)를 함께 보여준다. 판정은 여전히 서버 level 을 그대로 쓰고
                    index 로 재판정하지 않는다(§4.1 규약) — 표시만 추가한다.
                    recommend/SpotCard·CompareCard·BoardCard 와 동일한 표기 규칙. */}
                예상 혼잡도 {levelMeta.label}
                {spot.congestion?.index != null ? ` ${Math.round(spot.congestion.index)}%` : ""}
              </span>
            ) : (
              <span
                className="badge featured-card__congestion featured-card__congestion--ghost"
                aria-hidden="true"
              >
                <span className="badge__icon"></span>
                예상 혼잡도
              </span>
            )}
            <RatingBadge rating={rating} reviewCount={reviewCount} />
          </div>
        </div>
      </article>
    </Link>
  );
}

export function FeaturedCardSkeleton() {
  return (
    <div className="featured-card featured-card--skeleton" role="listitem" aria-hidden="true">
      <div className="skeleton-bar featured-card__media-skeleton" />
      <div className="featured-card__body">
        <div className="skeleton-bar" style={{ width: "50px", height: "10px" }} />
        <div className="skeleton-bar" style={{ width: "80%", height: "16px" }} />
        <div className="skeleton-bar" style={{ width: "60%", height: "12px" }} />
      </div>
    </div>
  );
}

const SKELETON_COUNT = 4;

interface FeaturedSectionProps {
  eyebrowClass: string;
  eyebrowLabel: string;
  title: string;
  /** null = 로딩 중(스켈레톤 표시). 빈 배열이면 섹션 자체를 렌더하지 않는다(조용히 숨김). */
  items: FeaturedSpot[] | null;
  /** §41(신규) — 일괄 조회한 별점 요약. id별로 없으면(호출 실패·아직 로딩 중) RatingBadge가
   * 조용히 "후기 없음"으로 폴백한다(카드 실패가 섹션 전체를 막지 않는다). */
  summaries?: Record<string, ReviewSummary>;
}

function FeaturedSection({ eyebrowClass, eyebrowLabel, title, items, summaries }: FeaturedSectionProps) {
  if (items !== null && items.length === 0) return null;

  return (
    <section className="section featured-section" aria-label={eyebrowLabel}>
      <span className={`eyebrow-pill ${eyebrowClass}`}>{eyebrowLabel}</span>
      <h2 className="section__title">{title}</h2>
      <div className="featured-scroll" role="list">
        {items === null
          ? Array.from({ length: SKELETON_COUNT }).map((_, i) => <FeaturedCardSkeleton key={i} />)
          : items.map((spot) => {
              const s = summaries?.[String(spot.id)];
              return (
                <FeaturedSpotCard key={spot.id} spot={spot} rating={s?.average ?? null} reviewCount={s?.count} />
              );
            })}
      </div>
    </section>
  );
}

type FetchStatus = "loading" | "success" | "error";

interface FeaturedSpotsProps {
  /** 선택된 지역(sigungu_cd). 없으면(null/undefined) 백엔드 기본 지역으로 호출한다(전광판과 동일 원칙). */
  regionCode?: string | null;
  /**
   * §37.4(신규, 03-design-spec.md, 2026-07-31) — 홈이 지역 미선택 상태일 때만 HomeContent가
   * true로 넘긴다. true면 fetchFeatured에 diverse=true를 실어 여러 지역이 섞여 오게 한다
   * ("홈에 부산만 많다" 대표 피드백 대응). regionCode가 있는 호출부(RegionsContent 등)는 이
   * prop 자체를 넘기지 않으므로 undefined→기존 동작(단일 지역) 그대로 유지된다.
   */
  diverse?: boolean;
}

/**
 * 홈 발견 섹션("오늘의 숨은 스팟" + "지금 뜨는 여행지") 오케스트레이터.
 * 한 번의 fetch(/api/v1/places/featured)로 두 섹션을 함께 채운다.
 * graceful: 404/네트워크 실패(백엔드 미배포 포함) 시 이 컴포넌트 전체가 조용히 사라진다(null 렌더) —
 * Hero·전광판·FestivalBanner는 이 컴포넌트와 무관하게 그대로 동작한다(작업 3).
 *
 * §46(신규, 03-design-spec.md, 2026-08-10 — 대표 승인) — 공모전 지정과제 2번("숨은 관광지
 * 추천") 정체성과 첫인상을 맞추기 위해 "숨은길 PICK"(hidden_picks)을 "지금 뜨는 여행지"
 * (trending)보다 먼저 렌더한다. API 계약(fetchFeatured)과 로직은 그대로, 렌더 순서와 카피만
 * 바꿨다 — trending은 보조 섹션으로 남는다.
 */
export default function FeaturedSpots({ regionCode, diverse }: FeaturedSpotsProps) {
  const [status, setStatus] = useState<FetchStatus>("loading");
  const [retryCount, setRetryCount] = useState(0);
  const [data, setData] = useState<FeaturedResponse | null>(null);
  // §41(신규) — 두 섹션(trending/hidden_picks)을 합쳐 reviews/summary를 1회만 호출한다
  // (지시서: "카드 목록은 반드시 이걸로 일괄 조회 — 카드마다 개별 호출 금지").
  const [summaries, setSummaries] = useState<Record<string, ReviewSummary>>({});

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    fetchFeatured(regionCode ?? undefined, undefined, controller.signal, diverse)
      .then((res) => {
        setData(res);
        setStatus("success");
        const ids = [...res.trending, ...res.hidden_picks].map((s) => s.id);
        fetchReviewsSummaryBulk("spot", ids, controller.signal)
          .then((s) => setSummaries(s))
          .catch(() => {
            // 실패해도 조용히 무시 — RatingBadge가 "후기 없음" 상태를 보여준다(화면 깨짐 금지).
          });
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        // 엔드포인트 미배포(404)든 네트워크 실패든 원인을 구분하지 않고 조용히 숨긴다 — 홈이 깨지지 않게.
        setStatus("error");
      });
    return () => controller.abort();
  }, [regionCode, diverse, retryCount]);

  if (status === "error") return (
    <section className="section featured-section featured-section--error" aria-label="여행지 추천 안내">
      <div role="status">
        <h2 className="section__title">여행지를 불러오지 못했어요</h2>
        <p>잠시 후 다시 시도해주세요. 지역별 여행에서도 여행지를 둘러볼 수 있어요.</p>
      </div>
      <div className="featured-section__actions">
        <button className="btn btn--mint" type="button" onClick={() => setRetryCount((count) => count + 1)}>다시 불러오기</button>
        <Link href="/regions">지역별 여행 보기 →</Link>
      </div>
    </section>
  );

  return (
    <>
      <FeaturedSection
        eyebrowClass="eyebrow-pill--mint"
        eyebrowLabel="숨은길 PICK"
        title="AI가 예상 혼잡도로 찾은, 오늘의 숨은 명소"
        items={status === "loading" ? null : data?.hidden_picks ?? []}
        summaries={summaries}
      />
      <FeaturedSection
        eyebrowClass="eyebrow-pill--coral"
        eyebrowLabel="지금 뜨는 여행지"
        title="사람들이 몰리는 곳도 확인해보세요"
        items={status === "loading" ? null : data?.trending ?? []}
        summaries={summaries}
      />
    </>
  );
}
