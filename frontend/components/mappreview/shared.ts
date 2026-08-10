/**
 * 전국 지도 시안 공용 상수 (2026-08-01, 대표 요청 "서울 시안처럼 전국 지도로")
 *
 * 색은 시안(SeoulTravel)의 범례 언어를 그대로 따른다 — 여유(파랑) / 보통(노랑) / 복잡(핑크).
 * `available=false`(데이터 없음)는 **회색**으로 따로 둔다. 한산함(파랑)과 섞으면 거짓말이 된다.
 */
export type Level = "low" | "mid" | "high" | null;

export const LEVEL_COLOR: Record<string, string> = {
  low: "#A9D8E8",
  mid: "#F8E3A3",
  high: "#F5A9A9",
  none: "#DDE3EA",
};

export const LEVEL_TEXT: Record<string, string> = {
  low: "여유",
  mid: "보통",
  high: "복잡",
  none: "정보 없음",
};

export function colorOf(available: boolean, level: Level): string {
  if (!available || !level) return LEVEL_COLOR.none;
  return LEVEL_COLOR[level];
}
