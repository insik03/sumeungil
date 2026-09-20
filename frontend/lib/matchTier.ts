/**
 * 매칭도 표시 등급 (2026-09-20).
 *
 * 서버 match_score(0~1)는 스팟 태그가 적어(72%가 1개) 몇 가지 값에 몰린다. "37%"처럼 정밀해 보이는
 * 숫자는 그 정밀도를 실제로 갖고 있지 않으므로, 3단계 등급 + 겹친 취향 태그로 보여준다. 값을 다시
 * 계산하지 않고 구간만 나눈다(서버 점수·정렬은 그대로).
 */
export interface MatchTier {
  key: "high" | "mid" | "low";
  label: string;
  /** 막대 채움(%) — 등급별 고정 3단계. 점수 자체를 정밀하게 그리지 않는다. */
  fill: number;
}

const TIERS: Record<MatchTier["key"], MatchTier> = {
  high: { key: "high", label: "잘 맞아요", fill: 100 },
  mid: { key: "mid", label: "무난해요", fill: 62 },
  low: { key: "low", label: "참고용", fill: 28 },
};

export function matchTier(score: number): MatchTier {
  if (score >= 0.55) return TIERS.high;
  if (score >= 0.3) return TIERS.mid;
  return TIERS.low;
}
