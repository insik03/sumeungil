import { CongestionLevel } from "../../lib/api";

/**
 * 01-interface-contract.md §1.4/§4.1과 동일한 레벨→배지 매핑(BoardCard·recommend/SpotCard와 동일 규약).
 * congestion_level만으로 색·라벨을 결정한다 — index(rate)로 재판정하지 않는다.
 */
export const LEVEL_META: Record<CongestionLevel, { label: string; badgeClass: string }> = {
  high: { label: "혼잡", badgeClass: "badge--hot" },
  mid: { label: "보통", badgeClass: "badge--mid" },
  low: { label: "여유", badgeClass: "badge--calm" },
  unknown: { label: "정보없음", badgeClass: "badge--unknown" },
};

/** §D.7-3 tier 배지 라벨(08 tier 매핑) — 데이터 신뢰등급. backend 판정을 그대로 라벨만 붙인다. */
export const TIER_LABEL: Record<"A" | "B" | "C" | "none", string> = {
  A: "실측",
  B: "추정",
  C: "추정(저신뢰)",
  none: "데이터없음",
};
