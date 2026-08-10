"use client";

import { useEffect, useState } from "react";
import {
  NationwideWeatherRegion,
  NationwideWeatherResponse,
  WeatherVerdict,
  fetchNationwideWeather,
} from "../lib/api";

type Status = "loading" | "success" | "error";

/** verdict → 배지 매핑. 기존 혼잡도 배지 톤(badge--calm/mid/hot)을 그대로 재사용한다
 * (지시서 원칙 — 신규 시각 언어 금지, 03-design-spec.md §37.1 근거). */
const VERDICT_META: Record<WeatherVerdict, { label: string; badgeClass: string }> = {
  good: { label: "여행 좋음", badgeClass: "badge--calm" },
  fair: { label: "보통", badgeClass: "badge--mid" },
  poor: { label: "주의", badgeClass: "badge--hot" },
};

const SKELETON_COUNT = 9;

function WeatherCardSkeleton() {
  return (
    <div className="weather-card weather-card--skeleton" aria-hidden="true">
      <div className="skeleton-bar" style={{ width: "44%", height: "14px" }} />
      <div className="skeleton-bar" style={{ width: "64px", height: "22px", borderRadius: "999px" }} />
      <div className="skeleton-bar" style={{ width: "90%", height: "12px" }} />
      <div className="skeleton-bar" style={{ width: "70%", height: "12px" }} />
    </div>
  );
}

function WeatherCard({ region }: { region: NationwideWeatherRegion }) {
  const meta = region.available && region.verdict ? VERDICT_META[region.verdict] : null;
  const metrics: string[] = [];
  if (region.available) {
    if (region.temp_c !== null) metrics.push(`${Math.round(region.temp_c)}°C`);
    if (region.pop !== null) metrics.push(`강수 ${region.pop}%`);
  }

  return (
    <article
      className={`weather-card${!region.available ? " weather-card--unavailable" : ""}`}
      role="listitem"
    >
      <div className="weather-card__head">
        <span className="weather-card__label">{region.label}</span>
      </div>

      {metrics.length > 0 && <p className="weather-card__metrics">{metrics.join(" · ")}</p>}

      {meta ? (
        <span className={`badge ${meta.badgeClass}`}>
          <span className="badge__icon" aria-hidden="true"></span>
          {meta.label}
        </span>
      ) : (
        <span className="badge badge--unknown">
          <span className="badge__icon" aria-hidden="true"></span>
          정보 없음
        </span>
      )}

      {region.available && region.tip ? (
        <p className="weather-card__tip">{region.tip}</p>
      ) : (
        <p className="weather-card__tip weather-card__tip--notice">
          {region.notice ?? "이 지역은 아직 날씨 정보가 없어요."}
        </p>
      )}
    </article>
  );
}

/**
 * §37.1(신규, 03-design-spec.md, 2026-07-31) — 전국 날씨 보드. `/tips`(여행 팁) 상단에
 * 얹는다 — 이 사이트에 "홈 팁 섹션"은 별도로 없고(TipsContent.tsx만 정적 팁·가이드를
 * 렌더), `/tips`가 "여행 전 실용 정보"를 모아두는 유일한 자리라 가장 자연스러운 확장
 * 지점이다(대체가 아니라 확장 — 기존 카테고리별 팁 카드·가이드는 그대로 두고 그 위에
 * 실시간성 콘텐츠를 새로 얹는다).
 *
 * graceful: 404/네트워크 실패 시 섹션 전체가 조용히 사라진다(FeaturedSpots.tsx와 동일 원칙) —
 * /tips 나머지 콘텐츠는 그대로 보인다.
 */
export default function WeatherBoard() {
  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<NationwideWeatherResponse | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    fetchNationwideWeather(controller.signal)
      .then((res) => {
        setData(res);
        setStatus("success");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setStatus("error");
      });
    return () => controller.abort();
  }, []);

  if (status === "error") return null;
  if (status === "success" && (data?.regions.length ?? 0) === 0) return null;

  return (
    <section className="section weather-board" aria-labelledby="weatherBoardHeading">
      <span className="eyebrow-pill eyebrow-pill--azure">전국 날씨</span>
      <h2 className="section__title" id="weatherBoardHeading">
        떠나기 전, 전국 날씨부터 확인하세요
      </h2>
      {status === "success" && data?.as_of && (
        <p className="weather-board__asof">{data.as_of} 기준 · 지역별 예상 강수확률·기온</p>
      )}

      <div className="weather-board-grid" role="list" aria-label="권역별 날씨">
        {status === "loading"
          ? Array.from({ length: SKELETON_COUNT }).map((_, i) => <WeatherCardSkeleton key={i} />)
          : (data?.regions ?? []).map((region) => <WeatherCard key={region.key} region={region} />)}
      </div>
    </section>
  );
}
