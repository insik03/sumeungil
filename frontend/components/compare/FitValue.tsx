import { CompareSpot } from "../../lib/api";
import { matchTier } from "../../lib/matchTier";
import { SIGNAL_LABEL } from "../recommend/constants";

interface FitValueProps {
  spot: CompareSpot;
  /** 사용자 본인 OnboardingResult.tags에서 뽑은 value→label 맵(§C.7-4 승계). */
  tagLabelMap: Record<string, string>;
}

/**
 * 맞춤 적합도 축 값 1칸. match_score:null이면 "취향 정보 없음"(회색)으로 표기한다 —
 * §D.7-3 "핫플이 일률적임을 그대로 보여준다"는 의도적 정직 표시(재판정 금지).
 */
export default function FitValue({ spot, tagLabelMap }: FitValueProps) {
  if (spot.match_score == null) {
    return <span className="compare-value compare-value--empty">취향 정보 없음</span>;
  }

  const tier = matchTier(spot.match_score);
  const matchedTagLabels = spot.match_reasons?.matched_tags.map((v) => tagLabelMap[v] ?? v) ?? [];
  const signalLabels = spot.match_reasons?.signals.map((s) => SIGNAL_LABEL[s] ?? s) ?? [];

  return (
    <div className="compare-value">
      <div className="compare-value__fit-bar">
        <div style={{ width: `${tier.fill}%` }} />
      </div>
      <span className="compare-value__fit-pct">{tier.label}</span>
      {(matchedTagLabels.length > 0 || signalLabels.length > 0) && (
        <div className="compare-value__reason-tags">
          {signalLabels.map((label, i) => (
            <span key={`signal-${i}`} className="reason-chip reason-chip--signal">
              {label}
            </span>
          ))}
          {matchedTagLabels.map((label, i) => (
            <span key={`tag-${i}`} className="reason-chip">
              #{label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
