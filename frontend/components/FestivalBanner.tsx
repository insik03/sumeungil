"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Festival,
  FestivalsResponse,
  ReviewSummary,
  fetchFestivals,
  fetchReviewsSummaryBulk,
} from "../lib/api";
import { withRegionCode } from "../lib/regionQuery";
import { FeaturedCardSkeleton } from "./FeaturedSpots";
import RatingBadge from "./RatingBadge";

const SKELETON_COUNT = 3;
const FETCH_LIMIT = 6;

/**
 * 아래 헬퍼 4종(FestivalGlyph/formatMonthDay/formatPeriod/computeBadge)과 FestivalCard는
 * §27(03-design-spec.md, /festivals 전국 축제 페이지)에서 그대로 재사용하기 위해 export한다 —
 * "FestivalBanner의 축제 카드 문법 재사용" 지시를 로직 중복 없이(단일 소스) 만족시킨다.
 * 동작 자체는 바뀌지 않는다(export 키워드만 추가).
 */

/** 축제/공연 자리표시자 아이콘 — 이모지 대신 인라인 SVG(깃발), ui-ux-pro-max 체크리스트 근거. */
export function FestivalGlyph() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6 3v18" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path
        d="M6 4.2l12.5 3.6L6 12"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
        fill="currentColor"
        fillOpacity="0.28"
      />
    </svg>
  );
}

/** "M.D" 포맷. 파싱 실패(예상 밖 날짜 형식)면 null — 값을 지어내지 않고 호출부가 원본 문자열로 폴백한다. */
export function formatMonthDay(iso: string): string | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return `${d.getMonth() + 1}.${d.getDate()}`;
}

export function formatPeriod(startDate: string, endDate: string): string {
  const s = formatMonthDay(startDate);
  const e = formatMonthDay(endDate);
  if (s && e) return s === e ? s : `${s} ~ ${e}`;
  return `${startDate} ~ ${endDate}`;
}

type BadgeTone = "live" | "upcoming";
interface FestivalBadge {
  label: string;
  tone: BadgeTone;
}

/**
 * ongoing(backend 권위값)을 그대로 신뢰하고, 아닌 경우에만 D-day를 클라이언트에서 계산한다.
 * 날짜 파싱 실패·이미 종료된 축제(days<0)는 배지 자체를 렌더하지 않는다 — 값을 지어내지 않는다.
 */
export function computeBadge(festival: Festival): FestivalBadge | null {
  if (festival.ongoing) return { label: "진행중", tone: "live" };

  const start = new Date(festival.start_date);
  if (Number.isNaN(start.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  start.setHours(0, 0, 0, 0);
  const days = Math.round((start.getTime() - today.getTime()) / 86_400_000);

  if (days > 0) return { label: `D-${days}`, tone: "upcoming" };
  if (days === 0) return { label: "D-DAY", tone: "upcoming" };
  return null;
}

/**
 * §36(신규) — 카드를 Link로 감싸 `/festival/{id}`(축제 상세) 이동을 붙인다. FestivalCard가
 * 홈 배너(FestivalBanner)·전국 축제 페이지(FestivalsContent) 공용 단일 소스라 여기 한 곳만
 * 고치면 두 화면 모두 자동 반영된다(지시서 근거). featured-card-link와 동일한 hover/focus
 * 상승 레시피를 재사용해 "카드가 눌리는 요소"라는 시각 언어를 사이트 전체에서 통일한다.
 */
interface FestivalCardProps {
  festival: Festival;
  /** §40(신규) — 별점·리뷰 자리. 요약이 없으면 RatingBadge가 "후기 없음"으로 표기한다. */
  rating?: number | null;
  reviewCount?: number;
}

export function FestivalCard({ festival, rating, reviewCount }: FestivalCardProps) {
  const [imgFailed, setImgFailed] = useState(false);
  const showImage = !!festival.image_url && !imgFailed;
  const badge = computeBadge(festival);
  const period = formatPeriod(festival.start_date, festival.end_date);

  return (
    <Link
      href={`/festival/${festival.id}`}
      className="festival-card-link"
      role="listitem"
      aria-label={`${festival.title}, ${period} — 자세히 보기`}
    >
      <article className="festival-card">
        <div className="festival-card__media">
          {showImage ? (
            <img
              src={festival.image_url as string}
              alt=""
              loading="lazy"
              className="festival-card__img"
              onError={() => setImgFailed(true)}
            />
          ) : (
            <div className="festival-card__placeholder">
              <FestivalGlyph />
            </div>
          )}
          {badge && (
            <span className={`festival-badge festival-badge--${badge.tone}`}>{badge.label}</span>
          )}
        </div>
        <div className="festival-card__body">
          <h3 className="festival-card__title">{festival.title}</h3>
          {/* §40(신규) — 축제 카드에는 "예상 혼잡도" 배지가 없어(축제 데이터 특성상 혼잡도 없음),
              그와 가장 가까운 배지형 메타 텍스트인 기간(period)과 같은 행에 별점·리뷰를 둔다
              (새 행 추가 금지). period는 이미 white-space:nowrap + ellipsis라 폭이 모자라면
              "..."로 줄어들 뿐 줄바꿈되지 않는다 — 카드 높이 불변이 보장된다(대표 지시). */}
          <div className="festival-card__meta-row">
            <p className="festival-card__period">{period}</p>
            <RatingBadge rating={rating} reviewCount={reviewCount} />
          </div>
          {/* 주소가 없어도 줄을 유지해(nbsp) 카드 높이가 주소 유무로 달라지지 않게 한다(대표 지시: 크기 통일). */}
          <p className="festival-card__address">{festival.address ?? " "}</p>
        </div>
      </article>
    </Link>
  );
}

type FetchStatus = "loading" | "success" | "error";

interface FestivalBannerProps {
  /** 선택된 지역(sigungu_cd). FeaturedSpots/ThemeCollections와 동일 원칙 — 없으면 백엔드 기본 지역. */
  regionCode?: string | null;
}

/**
 * 홈 "지금 이 지역 축제" 섹션. Phase 3(03-design-spec.md) — 이전엔 정적 카피 1건을 하드코딩해
 * 보여줬으나, 오케스트레이터가 확정한 백엔드 계약(GET /api/v1/festivals)으로 실데이터를 렌더한다.
 *
 * 빈 상태를 두 가지로 구분한다(R1 정직 표기 원칙과 동일 기조):
 * - festivals: [] (200 정상 응답) → "이 지역은 지금 진행 중인 축제가 없어요" 안내를 보여준다.
 *   축제는 계절성이 있어 "없음"이 실제로 흔한 정상 상태이므로, 조용히 숨기면 마치 이 기능이
 *   아예 없는 것처럼 보인다 — FeaturedSpots(순수 발견 콘텐츠)와 달리 명시적으로 알려준다.
 * - 404/네트워크 실패(엔드포인트 미배포 등 개발 단계 사정) → 섹션 전체를 조용히 숨긴다
 *   (FeaturedSpots/ThemeCollections와 동일 원칙, 홈이 깨지지 않게).
 */
export default function FestivalBanner({ regionCode }: FestivalBannerProps) {
  const [status, setStatus] = useState<FetchStatus>("loading");
  const [data, setData] = useState<FestivalsResponse | null>(null);
  // §41(신규) — 카드마다 개별 호출 금지 원칙(01-interface-contract.md 부록 R.5) — 1회만 조회한다.
  const [summaries, setSummaries] = useState<Record<string, ReviewSummary>>({});

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    fetchFestivals(regionCode ?? undefined, FETCH_LIMIT, controller.signal)
      .then((res) => {
        setData(res);
        setStatus("success");
        fetchReviewsSummaryBulk(
          "festival",
          res.festivals.map((f) => f.id),
          controller.signal
        )
          .then((s) => setSummaries(s))
          .catch(() => {
            // 실패해도 조용히 무시 — RatingBadge가 "후기 없음" 상태를 보여준다.
          });
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setStatus("error");
      });
    return () => controller.abort();
  }, [regionCode]);

  if (status === "error") return null;

  const festivals = data?.festivals ?? [];

  return (
    <section id="festival" className="section festival-section" aria-label="지금 이 지역 축제">
      <span className="eyebrow-pill eyebrow-pill--azure">지금 이 지역 축제</span>
      <h2 className="section__title">놓치면 아쉬운 축제 소식</h2>

      {status === "loading" && (
        <div className="featured-scroll" role="list" aria-label="축제 정보 불러오는 중" aria-busy="true">
          {Array.from({ length: SKELETON_COUNT }).map((_, i) => (
            <FeaturedCardSkeleton key={i} />
          ))}
        </div>
      )}

      {status === "success" && festivals.length === 0 && (
        <div className="festival-empty" role="status">
          <p className="festival-empty__msg">
            {data?.region?.region_name ? `${data.region.region_name}은(는) ` : "이 지역은 "}
            지금 진행 중인 축제 정보가 없어요.
          </p>
          <p className="festival-empty__hint">축제 소식이 들어오면 이 자리에서 바로 알려드릴게요.</p>
        </div>
      )}

      {status === "success" && festivals.length > 0 && (
        <>
          <div className="featured-scroll" role="list">
            {festivals.map((festival) => {
              const s = summaries[String(festival.id)];
              return (
                <FestivalCard
                  key={festival.id}
                  festival={festival}
                  rating={s?.average ?? null}
                  reviewCount={s?.count}
                />
              );
            })}
          </div>
          {/* §27(신규, 03-design-spec.md) — /festivals 전국 축제 페이지 진입점. 기존
              "이 지역 스팟 더 보기" 링크(변경 없음) 옆에 additive로 추가한 두 번째 CTA다. */}
          <div className="festival-section__cta-row">
            {/* §35(2026-07-31, 백로그 D21) — "이 지역"이라고 말하는 링크가 정작 지역을 안 넘기던
                단절을 없앤다. 이 섹션이 축제 조회에 쓰는 regionCode를 그대로 붙인다(미선택이면
                기존과 동일하게 쿼리 없음). */}
            <Link href={withRegionCode("/recommend", regionCode)} className="festival-section__cta">
              이 지역 스팟 더 보기
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
            <Link href="/festivals" className="festival-section__cta">
              전국 축제 모두 보기
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
          </div>
        </>
      )}
    </section>
  );
}
