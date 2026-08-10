import { CompareSpot } from "../../lib/api";
import { LEVEL_META, TIER_LABEL } from "./constants";

interface CongestionValueProps {
  spot: CompareSpot;
}

/**
 * 혼잡도 축 값 1칸. 모바일 지표행 셀 · 데스크톱 대칭 카드 양쪽에서 그대로 재사용한다(마크업만 다르고 로직은 공유).
 * congestion:null이면 §D.7-3 규약대로 처리한다:
 *  - hidden(숨은길)이고 is_hidden_gem이면 "한적함(숨은 곳)" 정성 라벨
 *  - 그 외(주로 hotspot)는 "정보없음" 회색 — 값을 지어내지 않는다.
 */
export default function CongestionValue({ spot }: CongestionValueProps) {
  if (!spot.congestion) {
    if (spot.role === "hidden" && spot.is_hidden_gem) {
      return <span className="compare-value compare-value--calm-text">한적함(숨은 곳)</span>;
    }
    return <span className="compare-value compare-value--empty">정보없음</span>;
  }

  const { level, index, tier } = spot.congestion;
  const levelMeta = LEVEL_META[level] ?? LEVEL_META.unknown;

  return (
    <div className="compare-value">
      <span className={`badge ${levelMeta.badgeClass}`}>
        <span className="badge__icon" aria-hidden="true"></span>
        {levelMeta.label}
        {index != null ? ` ${Math.round(index)}%` : ""}
      </span>
      <span className="compare-value__tier">데이터 {TIER_LABEL[tier] ?? TIER_LABEL.none}</span>
    </div>
  );
}
