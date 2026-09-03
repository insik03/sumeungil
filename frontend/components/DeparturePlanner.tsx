"use client";

import { FormEvent, useId, useMemo, useState } from "react";
import {
  ApiError,
  CongestionLevel,
  PlanCongestionBasis,
  PlanOutlookResponse,
  PlanWeatherBasis,
  fetchPlanOutlook,
} from "../lib/api";
import { DEFAULT_BLOCK_KEY, REGION_BLOCKS } from "./regions/blocks";

type Status = "idle" | "loading" | "success" | "error";

/** BoardCard.tsx·FeaturedSpots.tsx와 동일한 레벨→배지 매핑(재판정 금지, 그대로 표시). */
const LEVEL_META: Record<CongestionLevel, { label: string; badgeClass: string }> = {
  high: { label: "혼잡 예상", badgeClass: "badge--hot" },
  mid: { label: "보통", badgeClass: "badge--mid" },
  low: { label: "여유 예상", badgeClass: "badge--calm" },
  unknown: { label: "정보없음", badgeClass: "badge--unknown" },
};

/** §37.2 — 날씨/혼잡도 "정보 출처(basis)" 배지. 사용자가 예보와 통계를 혼동하면 안 된다는
 * 원칙(대표 지시, 가장 중요한 요구사항)에 따라 반드시 시각적으로 구분한다. */
const WEATHER_BASIS_META: Record<PlanWeatherBasis, { label: string; className: string }> = {
  forecast: { label: "예보", className: "basis-badge--forecast" },
  none: { label: "정보 없음", className: "basis-badge--none" },
};
const CONGESTION_BASIS_META: Record<PlanCongestionBasis, { label: string; className: string }> = {
  forecast: { label: "예보", className: "basis-badge--forecast" },
  last_year: { label: "작년 같은 시기 기준", className: "basis-badge--stat" },
  none: { label: "정보 없음", className: "basis-badge--none" },
};

function toDateInputValue(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/**
 * §37.2(신규, 03-design-spec.md, 2026-07-31) — 출발일 플래너. 지역+날짜를 고르면 그 시기의
 * 날씨·혼잡도를 basis(예보/통계 기준)를 구분해 보여준다.
 *
 * 2026-07-31 대표 지시(작업 중 계약 축소) 반영 — 날씨는 예보 커버(원천 실측 3일) 밖이면
 * `weather.available:false`로 오고 이때도 혼잡도는 계속 정상 표시된다(원천 실측 커버는
 * 29일이며 basis는 forecast — "작년 같은 시기"(last_year)는 원천 부재로 현재 미동작). 그래서 결과 레이아웃은 혼잡도 카드를 더 넓게·먼저
 * 배치해 "주인공"으로 두고, 날씨 카드는 예보 밖일 때 조용한 보조 상태(축소된 muted 카드)로
 * 접어 화면이 비어 보이지 않게 했다.
 *
 * 지역 선택은 **전국 9권역**(components/regions/blocks.ts, backend REGION_BLOCKS 미러)이다.
 * 대표 지시(2026-07-31): "광역시까지 다 포함하라는 게 아니고 서울도 경기도로 포함시켜 9도로."
 * 각 권역의 대표 시군구 코드가 그대로 region_code 계약값으로 나간다(프론트가 코드를 지어내지 않음).
 */
/** 혼잡도 예측 원천(KTO)의 실측 커버 상한. 이 범위 밖은 서버가 available:false 를 준다. */
const PLANNER_MAX_DAYS_AHEAD = 29;

interface DeparturePlannerProps {
  headingLevel?: "h1" | "h2";
}

export default function DeparturePlanner({ headingLevel = "h2" }: DeparturePlannerProps) {
  const Heading = headingLevel;
  const [today] = useState(() => new Date());
  const minDate = useMemo(() => toDateInputValue(today), [today]);
  // QA 약식(2026-07-31) M-1: 상한이 180일이었으나 원천 실측 커버는 혼잡도 29일·날씨 3일이라
  // 181일 중 151일(83%)이 "정보 없음"으로 나왔다 — 고를 수 있는데 답을 못 주는 건 나쁜 약속이다.
  // 실제로 답할 수 있는 범위(+29일)로 상한을 맞춘다. 원천(데이터랩 등)이 열리면 되돌린다.
  const maxDate = useMemo(() => {
    const d = new Date(today);
    d.setDate(d.getDate() + PLANNER_MAX_DAYS_AHEAD);
    return toDateInputValue(d);
  }, [today]);

  const [blockKey, setBlockKey] = useState(DEFAULT_BLOCK_KEY);
  const [date, setDate] = useState(minDate);
  const [status, setStatus] = useState<Status>("idle");
  const [data, setData] = useState<PlanOutlookResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const dateInputId = useId();

  const selectedBlock = REGION_BLOCKS.find((b) => b.key === blockKey) ?? REGION_BLOCKS[0];

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!date) return;
    setStatus("loading");
    setError(null);
    fetchPlanOutlook(selectedBlock.regionCode, date)
      .then((res) => {
        setData(res);
        setStatus("success");
      })
      .catch((err: unknown) => {
        setError(
          err instanceof ApiError
            ? err
            : new ApiError(0, "UNKNOWN", "여행 시기 정보를 불러오지 못했습니다.")
        );
        setStatus("error");
      });
  };

  const weatherMeta = data
    ? WEATHER_BASIS_META[data.weather.basis] ?? WEATHER_BASIS_META.none
    : null;
  const congestionMeta = data
    ? CONGESTION_BASIS_META[data.congestion.basis] ?? CONGESTION_BASIS_META.none
    : null;
  const congestionLevelMeta =
    data?.congestion.available && data.congestion.level ? LEVEL_META[data.congestion.level] : null;

  return (
    <section className="section planner" aria-labelledby="plannerHeading">
      <span className="eyebrow-pill eyebrow-pill--mint">출발일 플래너</span>
      <Heading className="section__title" id="plannerHeading">
        언제 떠나세요?
      </Heading>
      <p className="planner__lead">
        지역과 앞으로 한 달 안의 날짜를 고르면 그날 예상 혼잡도를 보여드려요. 날짜가 앞으로
        사흘 안이면 날씨 예보도 함께 확인할 수 있어요.
      </p>

      <form className="planner-form" onSubmit={handleSubmit}>
        <div className="planner-form__region">
          <span className="onboard-label">어느 지역으로 가시나요?</span>
          {/* 대표 지시(2026-07-31): 광역시를 따로 두지 않고 **전국 9도**만 고르게 한다
              (서울→경기, 대전·세종→충남, 부산·울산→경남 …). 17개 시도 칩(SidoStrip)은
              지역 탐색 화면 전용이며 여기서는 쓰지 않는다. */}
          <div className="chip-row planner-form__blocks" role="group" aria-label="권역 선택">
            {REGION_BLOCKS.map((b) => (
              <button
                key={b.key}
                type="button"
                className={`onboard-chip${b.key === blockKey ? " onboard-chip--on" : ""}`}
                aria-pressed={b.key === blockKey}
                onClick={() => setBlockKey(b.key)}
              >
                {b.label}
              </button>
            ))}
          </div>
        </div>

        <div className="planner-form__date">
          <label className="onboard-label" htmlFor={dateInputId}>
            출발 예정일
          </label>
          <input
            id={dateInputId}
            type="date"
            className="date-input"
            value={date}
            min={minDate}
            max={maxDate}
            onChange={(e) => setDate(e.target.value)}
          />
        </div>

        <button
          type="submit"
          className="btn btn--coral planner-form__submit"
          disabled={status === "loading" || !date}
        >
          {status === "loading" ? "확인하는 중…" : `${selectedBlock.label} 여행 정보 보기`}
        </button>
      </form>

      {status === "error" && (
        <div className="board-error" role="alert">
          <p className="board-error__msg">
            {error?.message ?? "여행 시기 정보를 불러오지 못했습니다."}
          </p>
        </div>
      )}

      {status === "success" && data && (
        <div className="plan-result">
          {/* 혼잡도 카드 — 항상 주인공(먼저·더 넓게). 180일 전 구간까지 계속 채워지는 값이라
              날씨가 없는 먼 날짜에도 화면이 비어 보이지 않게 한다. */}
          <article className="plan-card plan-card--congestion">
            <div className="plan-card__head">
              <h3 className="plan-card__title">예상 혼잡도</h3>
              {data.congestion.available && congestionMeta && (
                <span className={`basis-badge ${congestionMeta.className}`}>
                  {congestionMeta.label}
                </span>
              )}
            </div>
            {data.congestion.available && congestionLevelMeta ? (
              <>
                <span className={`badge ${congestionLevelMeta.badgeClass}`}>
                  <span className="badge__icon" aria-hidden="true"></span>
                  {congestionLevelMeta.label}
                  {/* 대표 지시(2026-07-31) — 라벨 옆에 수치(집중률 %)도 함께. 다른 화면
                      (홈 카드·추천·비교·전광판)과 같은 표기 규칙을 쓴다. */}
                  {data.congestion.index != null ? ` ${Math.round(data.congestion.index)}%` : ""}
                </span>
                {data.congestion.summary && (
                  <p className="plan-card__summary">{data.congestion.summary}</p>
                )}
              </>
            ) : (
              <p className="plan-card__empty">
                {data.congestion.notice ?? "이 시기 혼잡도 정보가 아직 없어요."}
              </p>
            )}
          </article>

          {/* 날씨 카드 — 예보 범위 밖(사흘 초과)이면 muted 보조 카드로 접혀 옆 혼잡도 카드보다
              작게 보인다(2026-07-31 대표 지시 반영). */}
          <article
            className={`plan-card plan-card--weather${
              !data.weather.available ? " plan-card--muted" : ""
            }`}
          >
            <div className="plan-card__head">
              <h3 className="plan-card__title">날씨</h3>
              {data.weather.available && weatherMeta && (
                <span className={`basis-badge ${weatherMeta.className}`}>{weatherMeta.label}</span>
              )}
            </div>
            {data.weather.available ? (
              <>
                <p className="plan-card__metrics">
                  {[
                    data.weather.temp_c !== null ? `${Math.round(data.weather.temp_c)}°C` : null,
                    data.weather.pop !== null ? `강수확률 ${data.weather.pop}%` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
                {data.weather.summary && <p className="plan-card__summary">{data.weather.summary}</p>}
              </>
            ) : (
              <p className="plan-card__empty">
                {data.weather.notice ??
                  "이 날짜는 예보 범위 밖이라 날씨를 알려드릴 수 없어요 — 사흘 이내 날짜만 예보를 볼 수 있어요."}
              </p>
            )}
          </article>
        </div>
      )}
    </section>
  );
}
