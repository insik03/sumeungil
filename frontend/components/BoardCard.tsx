import type { CongestionItem, CongestionLevel } from "../lib/api";

/**
 * 01-interface-contract.md §4.1 레벨 → 배지 매핑.
 * congestion_level만으로 색/라벨을 결정한다 — rate로 재판정하지 않는다.
 */
const LEVEL_META: Record<
  CongestionLevel,
  { label: string; badgeClass: string }
> = {
  high: { label: "혼잡", badgeClass: "badge--hot" },
  mid: { label: "보통", badgeClass: "badge--mid" },
  low: { label: "여유", badgeClass: "badge--calm" },
  unknown: { label: "정보없음", badgeClass: "badge--unknown" },
};

function formatRate(rate: number | null): string | null {
  if (rate === null || rate === undefined) return null;
  return `${Math.round(rate)}%`;
}

export default function BoardCard({ item }: { item: CongestionItem }) {
  const meta = LEVEL_META[item.congestion_level] ?? LEVEL_META.unknown;
  const rateLabel = formatRate(item.congestion_rate);
  const rankLabel = String(item.rank).padStart(2, "0");

  return (
    <div className="board-card" role="listitem">
      <span className="board-card__ranknum" aria-hidden="true">
        {rankLabel}
      </span>
      <span className="board-card__rank">TOP {item.rank}</span>
      <div className="board-card__name">{item.spot_name}</div>
      <span className={`badge ${meta.badgeClass}`}>
        <span className="badge__icon"></span>
        {meta.label}
        {rateLabel ? ` ${rateLabel}` : ""}
      </span>
      {item.base_date && <span className="board-card__date">기준 {item.base_date}</span>}
    </div>
  );
}

export function BoardCardSkeleton() {
  return (
    <div className="board-card board-card--skeleton" role="listitem" aria-hidden="true">
      <div className="skeleton-bar" style={{ width: "36px", height: "12px" }} />
      <div className="skeleton-bar" style={{ width: "88px", height: "18px" }} />
      <div className="skeleton-bar" style={{ width: "64px", height: "24px", borderRadius: "999px" }} />
    </div>
  );
}
