"use client";

import { useEffect, useState } from "react";
import { ForecastDay, VisitTip, fetchForecast } from "../../lib/api";

/**
 * §31 — "방문 타이밍" 카드 (SpotDetailContent 전용, 예상 혼잡도 뱃지 바로 아래).
 * visit_tip은 SpotDetail이 이미 갖고 온 값을 그대로 표시하고(재판정 금지), 주간 미니 차트만
 * fetchForecast(regionCode, spotName)를 별도 호출해 그린다. 차트 로드 실패/빈 daily여도
 * "방문 타이밍" 카드(best/worst) 자체는 그대로 유지한다 — 차트 섹션만 조용히 생략한다.
 *
 * "실시간/실측" 표현을 쓰지 않는다 — "예상/예측/참고용"만 쓴다(부록 M 계약, notice 문구 그대로 노출).
 */

const WEEKDAY_KO = ["일", "월", "화", "수", "목", "금", "토"];

/** "YYYY-MM-DD" → "8/10(월)". 서버가 준 date 문자열의 표기만 바꾼다(요일을 지어내지 않고 계산). */
function formatDayLabel(dateStr: string): string {
  const d = new Date(`${dateStr}T00:00:00+09:00`);
  if (Number.isNaN(d.getTime())) return dateStr;
  return `${d.getMonth() + 1}/${d.getDate()}(${WEEKDAY_KO[d.getDay()]})`;
}

/** 차트 x축용 짧은 표기("10일"). */
function formatDayShort(dateStr: string): string {
  const d = new Date(`${dateStr}T00:00:00+09:00`);
  if (Number.isNaN(d.getTime())) return "";
  return String(d.getDate());
}

const LEVEL_LABEL: Record<string, string> = {
  high: "혼잡",
  mid: "보통",
  low: "여유",
  unknown: "정보없음",
};

interface VisitTipCardProps {
  visitTip: VisitTip;
  regionCode: string;
  spotName: string;
}

type ChartStatus = "loading" | "success" | "empty";

export default function VisitTipCard({ visitTip, regionCode, spotName }: VisitTipCardProps) {
  const [chartStatus, setChartStatus] = useState<ChartStatus>("loading");
  const [daily, setDaily] = useState<ForecastDay[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    setChartStatus("loading");

    fetchForecast(regionCode, spotName, undefined, controller.signal)
      .then((res) => {
        const rows = res.spots[0]?.daily ?? [];
        setDaily(rows);
        setChartStatus(rows.length > 0 ? "success" : "empty");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        // §31 — 차트는 실패해도 조용히 생략한다(visit_tip 카드는 이미 값을 갖고 있어 그대로 유지).
        setDaily([]);
        setChartStatus("empty");
      });

    return () => controller.abort();
  }, [regionCode, spotName]);

  return (
    <div className="visit-tip-card">
      <span className="visit-tip-card__eyebrow">방문 타이밍</span>

      <div className="visit-tip-card__stats">
        <div className="visit-tip-card__stat visit-tip-card__stat--best">
          <span className="visit-tip-card__stat-icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="visit-tip-card__stat-label">가장 한적할 날</span>
          <span className="visit-tip-card__stat-value">
            {formatDayLabel(visitTip.best_day.date)} 예상 {Math.round(visitTip.best_day.index)}%
          </span>
        </div>

        <div className="visit-tip-card__stat visit-tip-card__stat--worst">
          <span className="visit-tip-card__stat-icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 3l8 15H4l8-15z" stroke="currentColor" strokeWidth="2.4" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="visit-tip-card__stat-label">가장 붐빌 날</span>
          <span className="visit-tip-card__stat-value">
            {formatDayLabel(visitTip.worst_day.date)} 예상 {Math.round(visitTip.worst_day.index)}%
          </span>
        </div>
      </div>

      <p className="visit-tip-card__footnote">
        {visitTip.days}일 예측 기준 · KT 이동통신 데이터로 만든 예측치예요(실측 아님, 실제와 다를 수
        있어요)
      </p>

      {chartStatus === "loading" && (
        <div className="visit-tip-chart visit-tip-chart--skeleton" aria-hidden="true">
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="skeleton-bar visit-tip-chart__skeletonbar" />
          ))}
        </div>
      )}

      {chartStatus === "success" && (
        <ForecastMiniChart
          daily={daily}
          bestDate={visitTip.best_day.date}
          worstDate={visitTip.worst_day.date}
        />
      )}
    </div>
  );
}

function ForecastMiniChart({
  daily,
  bestDate,
  worstDate,
}: {
  daily: ForecastDay[];
  bestDate: string;
  worstDate: string;
}) {
  return (
    <div
      className="visit-tip-chart"
      role="group"
      aria-label={`${daily.length}일 혼잡도 예보 미니 차트 (예측치, 참고용)`}
    >
      {daily.map((day) => {
        const heightPct = Math.max(day.index, 4);
        const levelLabel = LEVEL_LABEL[day.level] ?? LEVEL_LABEL.unknown;
        const isBest = day.date === bestDate;
        const isWorst = day.date === worstDate;
        return (
          <div className="visit-tip-chart__col" key={day.date}>
            {isBest && (
              <span className="visit-tip-chart__marker visit-tip-chart__marker--best" aria-hidden="true">
                ●
              </span>
            )}
            {isWorst && (
              <span className="visit-tip-chart__marker visit-tip-chart__marker--worst" aria-hidden="true">
                ▲
              </span>
            )}
            <div
              className={`visit-tip-chart__bar visit-tip-chart__bar--${day.level}`}
              style={{ height: `${heightPct}%` }}
              title={`${formatDayLabel(day.date)} 예상 혼잡도 ${levelLabel} ${Math.round(day.index)}%`}
              aria-label={`${formatDayLabel(day.date)} 예상 혼잡도 ${levelLabel} ${Math.round(day.index)}%`}
              role="img"
            />
            <span className="visit-tip-chart__daylabel" aria-hidden="true">
              {formatDayShort(day.date)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
