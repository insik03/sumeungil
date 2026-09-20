"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ApiError, FestivalDetailResponse, FestivalTiming, fetchFestivalDetail } from "../../lib/api";
import { withRegionCode } from "../../lib/regionQuery";
import BackLink from "../BackLink";
import { FestivalGlyph, computeBadge, formatPeriod } from "../FestivalBanner";
import PhotoCarousel from "../PhotoCarousel";
import ReviewSection from "../reviews/ReviewSection";

import LiveWeatherLine from "../weather/LiveWeatherLine";
type Status = "loading" | "success" | "notfound" | "error";

interface FestivalDetailContentProps {
  festivalId: string;
}

/**
 * §36(신규, 03-design-spec.md) — 축제 상세 화면. 홈 배너·전국 축제 페이지의 FestivalCard 클릭으로
 * 진입한다. 진행 배지는 FestivalCard와 완전히 동일한 값을 보여줘야 하므로 computeBadge/formatPeriod를
 * 재계산 없이 그대로 재사용한다(단일 소스, 지시서 근거). timing/weather는 이 화면 전용 backend
 * 권위값을 그대로 표시하고 재판정하지 않는다(§31 visit_tip과 동일 원칙).
 *
 * useSearchParams를 쓰지 않아 Next.js App Router가 요구하는 Suspense 경계가 필요 없다
 * (app/ask/page.tsx가 Suspense를 쓰는 이유는 그 반대 — 이 페이지는 SpotDetailContent와 동일하게
 * params.id만 쓰는 클라이언트 fetch 패턴이라 그 구조를 그대로 따른다).
 */
export default function FestivalDetailContent({ festivalId }: FestivalDetailContentProps) {
  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<FestivalDetailResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [retryTick, setRetryTick] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    setError(null);

    fetchFestivalDetail(festivalId, controller.signal)
      .then((res) => {
        setData(res);
        setStatus("success");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const apiErr =
          err instanceof ApiError ? err : new ApiError(0, "UNKNOWN", "축제 정보를 불러오지 못했습니다.");
        if (apiErr.status === 404) {
          setError(apiErr);
          setStatus("notfound");
          return;
        }
        setError(apiErr);
        setStatus("error");
      });

    return () => controller.abort();
  }, [festivalId, retryTick]);

  const retry = () => setRetryTick((t) => t + 1);

  if (status === "loading") {
    return <FestivalDetailSkeleton />;
  }

  if (status === "notfound") {
    return (
      <section className="section festival-detail" aria-labelledby="festivalDetailHeading">
        <BackLink href="/festivals" className="compare-back">
          ← 축제 목록으로
        </BackLink>
        <h1 className="section__title" id="festivalDetailHeading">
          축제 상세
        </h1>
        <div className="board-error" role="status">
          <p className="board-error__msg">축제를 찾을 수 없어요.</p>
          <p className="board-error__hint">종료됐거나 삭제된 축제일 수 있어요.</p>
          <Link className="btn btn--mint" href="/festivals">
            축제 목록으로 돌아가기
          </Link>
        </div>
      </section>
    );
  }

  if (status === "error") {
    return (
      <section className="section festival-detail" aria-labelledby="festivalDetailHeading">
        <BackLink href="/festivals" className="compare-back">
          ← 축제 목록으로
        </BackLink>
        <h1 className="section__title" id="festivalDetailHeading">
          축제 상세
        </h1>
        <div className="board-error" role="alert">
          <p className="board-error__msg">{error?.message ?? "축제 정보를 불러오지 못했습니다."}</p>
          <p className="board-error__hint">
            {error?.status === 0
              ? "백엔드 서버가 켜져 있는지 확인해주세요 (localhost:8000). 잠시 후 다시 시도해주세요."
              : "잠시 후 다시 시도해주세요."}
          </p>
          <button className="btn btn--coral" type="button" onClick={retry}>
            다시 시도
          </button>
        </div>
      </section>
    );
  }

  if (!data) return null;

  const { festival, region, images, timing, weather, description } = data;
  const badge = computeBadge(festival);
  const period = formatPeriod(festival.start_date, festival.end_date);

  return (
    <section className="section festival-detail" aria-labelledby="festivalDetailHeading">
      <BackLink href="/festivals" className="compare-back">
        ← 축제 목록으로
      </BackLink>

      <div className="festival-detail__photo">
        <PhotoCarousel
          images={images}
          placeholderIcon={<FestivalGlyph />}
          placeholderTone="festival"
          ariaLabel={`${festival.title} 사진`}
        />
      </div>

      <div className="festival-detail__head">
        {badge && (
          <div className="festival-detail__badges">
            <span className={`festival-detail__badge festival-badge--${badge.tone}`}>{badge.label}</span>
          </div>
        )}
        <h1 className="spot-detail__title" id="festivalDetailHeading">
          {festival.title}
        </h1>
        <div className="festival-detail__meta">
          <span className="spot-card__address">{period}</span>
          {festival.address && <span className="spot-card__address">{festival.address}</span>}
        </div>
      </div>

      {/* §36.8(신규, 대표 피드백 후속) — description이 null/undefined면(구버전 백엔드 포함) 빈
          껍데기를 그리지 않고 섹션 자체를 생략한다(지어내지 않음). */}
      {data.ai_summary && data.ai_provider === "ollama" && (
        <section className="festival-section" aria-label="축제 핵심 요약">
          <h2>AI 축제 핵심 요약</h2>
          <p>{data.ai_summary}</p>
        </section>
      )}
      {(description || data.ai_summary) && <FestivalDescription description={description || data.ai_summary!} />}

      <div className="festival-timing-card">
        <span className="festival-timing-card__eyebrow">방문 타이밍</span>
        <div className="festival-timing-card__status">
          <span className={`festival-timing-card__dday festival-timing-card__dday--${timing.status}`}>
            {timingLabel(timing)}
          </span>
        </div>
        <p className="festival-timing-card__tip">{timing.tip}</p>
      </div>

      <div className="festival-weather-card">
        <span className="festival-weather-card__eyebrow">날씨</span>
        {/* 2026-09-20 — 두 줄은 서로 다른 질문이다. 위: 이 지역에 **지금** 비가 오는가(초단기실황,
            5km 격자). 아래: 축제 **기간에** 비가 올 확률(관광코스 날씨 D18, 시도 해상도). */}
        <LiveWeatherLine weather={data.live_weather} />
        {weather.available && weather.summary ? (
          <p className="festival-weather-card__text">{weather.summary}</p>
        ) : (
          <p className="festival-weather-card__text festival-weather-card__text--muted">
            {weather.notice ?? "축제 기간 강수 예보는 아직 확인할 수 없어요."}
          </p>
        )}
      </div>

      {region && (
        <Link href={withRegionCode("/recommend", region.region_code)} className="festival-section__cta">
          {region.region_name ?? "이 지역"} 스팟 더 보기
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
      )}

      {/* §41(신규) — 후기 섹션. 스팟 상세(SpotDetailContent)와 공유하는 단일 컴포넌트다. */}
      <ReviewSection targetType="festival" targetId={festival.id} />
    </section>
  );
}

/**
 * timing(status/d_day/days_left)은 backend 권위값을 그대로 문구로 옮기기만 한다(재계산 금지).
 * status==="ongoing"인데 days_left가 없으면(축제 종료일 미상 등) "진행중"만 표기 — 값을 지어내지 않는다.
 */
function timingLabel(timing: FestivalTiming): string {
  if (timing.status === "ongoing") {
    return timing.days_left != null ? `진행중 · 종료까지 ${timing.days_left}일` : "진행중";
  }
  if (timing.status === "upcoming") {
    if (timing.d_day === 0) return "D-DAY";
    return timing.d_day != null ? `D-${timing.d_day}` : "예정";
  }
  return "종료";
}

/**
 * §36.8(신규) — "축제 소개". 6줄 클램프(spot-detail__overview의 white-space:pre-line·text-lg
 * 레시피를 그대로 재사용, 신규 시각 언어 없음) + "더보기/접기" 토글. 토글 버튼은 실제로 텍스트가
 * 잘렸을 때만 보여준다 — scrollHeight(전체 높이) vs clientHeight(클램프된 보이는 높이)를
 * 마운트 직후 1회 비교한다(description이 바뀌지 않는 한 재측정하지 않음 — expand/collapse로
 * clientHeight가 달라져도 "원래 잘렸었는지" 판정이 흔들리지 않게).
 */
function FestivalDescription({ description }: { description: string }) {
  const [expanded, setExpanded] = useState(false);
  const [clamped, setClamped] = useState(false);
  const textRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    const el = textRef.current;
    if (!el) return;
    setClamped(el.scrollHeight > el.clientHeight + 1);
  }, [description]);

  return (
    <div className="spot-detail__block">
      <h2 className="spot-detail__block-title">축제 소개</h2>
      <p
        ref={textRef}
        className={`spot-detail__overview${
          !expanded ? " festival-description__text--clamped" : ""
        }`}
      >
        {description}
      </p>
      {clamped && (
        <button
          type="button"
          className="festival-description__toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((e) => !e)}
        >
          {expanded ? "접기" : "더보기"}
        </button>
      )}
    </div>
  );
}

export function FestivalDetailSkeleton() {
  return (
    <section className="section festival-detail" aria-label="축제 정보 불러오는 중" aria-busy="true">
      <div className="skeleton-bar" style={{ width: "120px", height: "16px" }} />
      <div className="skeleton-bar" style={{ width: "100%", aspectRatio: "4 / 3", marginTop: "16px" }} />
      <div className="skeleton-bar" style={{ width: "70%", height: "30px", marginTop: "16px" }} />
      <div className="skeleton-bar" style={{ width: "50%", height: "16px", marginTop: "10px" }} />
      <div className="skeleton-bar" style={{ width: "100%", height: "100px", marginTop: "var(--sp-6)" }} />
    </section>
  );
}
