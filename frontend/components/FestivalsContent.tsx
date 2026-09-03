"use client";

import { useEffect, useMemo, useState } from "react";
import { ApiError, FestivalsResponse, ReviewSummary, fetchFestivals, fetchReviewsSummaryBulk } from "../lib/api";
import { saveLastRegion } from "../lib/lastRegionStorage";
import { FestivalCard } from "./FestivalBanner";
import { FeaturedCardSkeleton } from "./FeaturedSpots";
import FestivalRegionFilter, { FestivalRegion } from "./festivals/FestivalRegionFilter";
import FestivalMonthFilter from "./festivals/FestivalMonthFilter";
import FestivalStatusFilter, { FestivalStatusValue } from "./festivals/FestivalStatusFilter";

type FetchStatus = "loading" | "success" | "error";

const SKELETON_COUNT = 8;
const FETCH_LIMIT = 200; // 지시서 한도("최대200")를 그대로 요청 상한으로 쓴다.
/** 월 필터를 쓰지 않는 기본 뷰의 조회 기간. 지시서: "기본 뷰는 90 유지". */
const DEFAULT_WINDOW_DAYS = 90;
/** 월 필터 선택 시 — 가을 축제 등 먼 시점도 놓치지 않도록 넉넉히 요청(지시서 근거). */
const MONTH_FILTER_WINDOW_DAYS = 365;

/**
 * `/festivals` 전국 축제 페이지 — §27(03-design-spec.md). 오케스트레이터 지시서의 병렬 확장
 * 백엔드 계약(GET /api/v1/festivals?region_code=&limit=&month=&window_days=)을 그대로 쓴다.
 *
 * - 지역/월 필터는 서버에 다시 요청한다(region_code/month/window_days 파라미터).
 * - 진행중/예정/전체 토글은 클라이언트 전용(FestivalStatusFilter) — 서버가 이미 정렬해 내려준
 *   `festival.ongoing` 값을 그대로 신뢰해 나눈다(재판정하지 않는다).
 * - total은 optional(§K/§27 하위호환) — 백엔드가 아직 안 내려주면 건수 표기를 생략한다
 *   (지어내지 않는다, R1과 동일 원칙).
 * - 404/네트워크 실패(엔드포인트 미배포 등)는 홈 FestivalBanner처럼 조용히 숨기지 않고 에러
 *   카드 + 재시도 버튼으로 안내한다 — 이 페이지는 "축제 전용" 페이지라 실패를 숨기면 사용자가
 *   기능이 아예 없다고 오해할 수 있다(RecommendContent의 에러 처리와 동일 원칙).
 */
export default function FestivalsContent() {
  // §27 "전국=기본" 요구사항은 그대로 유지(이 화면 자체의 기본값은 여전히 미선택/전국) — 대표
  // 지시(2026-08-17, 마지막 선택 지역을 기본 화면 기준으로)는 여기서 "고르면 기억한다" 쪽만
  // 적용한다. 다른 화면(홈 등)이 그 기억을 기본값으로 쓴다.
  const [selectedRegion, setSelectedRegionState] = useState<FestivalRegion | null>(null);
  const setSelectedRegion = (region: FestivalRegion | null) => {
    setSelectedRegionState(region);
    if (region) {
      saveLastRegion({
        region_id: `sigungu-${region.sigunguCd}`,
        label: region.label,
        area_cd: region.sigunguCd.slice(0, 2),
        sigungu_cd: region.sigunguCd,
      });
    }
  };
  const [month, setMonth] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<FestivalStatusValue>("all");

  const [status, setStatus] = useState<FetchStatus>("loading");
  const [data, setData] = useState<FestivalsResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  // §41(신규) — 카드마다 개별 호출 금지(01-interface-contract.md 부록 R.5) — 필터로 바뀐 목록마다 1회.
  const [summaries, setSummaries] = useState<Record<string, ReviewSummary>>({});

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    setError(null);

    fetchFestivals(selectedRegion?.sigunguCd, FETCH_LIMIT, controller.signal, {
      month: month ?? undefined,
      windowDays: month ? MONTH_FILTER_WINDOW_DAYS : DEFAULT_WINDOW_DAYS,
    })
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
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          err instanceof ApiError ? err : new ApiError(0, "UNKNOWN", "축제 정보를 불러오지 못했습니다.")
        );
        setStatus("error");
      });

    return () => controller.abort();
  }, [selectedRegion, month, retryTick]);

  // 진행중/예정/전체는 서버 재요청 없이 클라이언트에서만 나눈다(서버가 이미 정렬한 ongoing 값을 그대로 신뢰).
  const filteredFestivals = useMemo(() => {
    const festivals = data?.festivals ?? [];
    if (statusFilter === "ongoing") return festivals.filter((f) => f.ongoing);
    if (statusFilter === "upcoming") return festivals.filter((f) => !f.ongoing);
    return festivals;
  }, [data?.festivals, statusFilter]);

  const retry = () => setRetryTick((t) => t + 1);

  return (
    <section className="section" aria-labelledby="festivalsHeading">
      <span className="eyebrow-pill eyebrow-pill--azure">전국 축제</span>
      <div className="festivals-page__head">
        <h1 className="section__title" id="festivalsHeading">
          전국 축제
        </h1>
        {/* total 미배포(구버전 백엔드) 시 건수를 지어내지 않고 생략한다 — R1과 동일 원칙. */}
        {status === "success" && typeof data?.total === "number" && (
          <span className="festivals-page__count">전체 {data.total}건</span>
        )}
      </div>
      <p className="tips-intro">지역과 시기를 골라 전국의 축제 소식을 확인해보세요.</p>

      <div className="festivals-filter-bar">
        <FestivalRegionFilter selected={selectedRegion} onSelect={setSelectedRegion} />
        <FestivalMonthFilter selected={month} onSelect={setMonth} />
        <FestivalStatusFilter selected={statusFilter} onSelect={setStatusFilter} />
      </div>

      {status === "loading" && (
        <div
          className="festivals-grid"
          role="list"
          aria-label="축제 정보 불러오는 중"
          aria-busy="true"
        >
          {Array.from({ length: SKELETON_COUNT }).map((_, i) => (
            <FeaturedCardSkeleton key={i} />
          ))}
        </div>
      )}

      {status === "success" && filteredFestivals.length === 0 && (
        <div className="festival-empty" role="status">
          <p className="festival-empty__msg">이 조건의 축제가 아직 없어요.</p>
          <p className="festival-empty__hint">지역·월·진행 상태를 다르게 선택해보세요.</p>
        </div>
      )}

      {status === "success" && filteredFestivals.length > 0 && (
        <div className="festivals-grid" role="list">
          {filteredFestivals.map((festival) => {
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
      )}

      {status === "error" && (
        <div className="board-error" role="alert">
          <p className="board-error__msg">{error?.message ?? "축제 정보를 불러오지 못했습니다."}</p>
          <p className="board-error__hint">
            {error?.status === 404
              ? "축제 페이지가 아직 준비 중이에요(백엔드 연동이 필요해요)."
              : "백엔드 서버가 켜져 있는지 확인해주세요 (localhost:8000). 잠시 후 다시 시도해주세요."}
          </p>
          <button className="btn btn--coral" type="button" onClick={retry}>
            다시 시도
          </button>
        </div>
      )}
    </section>
  );
}
