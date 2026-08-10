import { OnboardingAxis } from "../../lib/api";

/**
 * 결과 화면 표시 순서. JSON 객체 키 순서에 의존하지 않고 프론트가 고정한다.
 * companion/mobility/mood/spot_pref/accessibility는 01-interface-contract.md 부록 B §B.1 예시 순서,
 * flag(파생값)·congestion_pref는 그 다음에 보조로 노출한다.
 */
export const RESULT_AXIS_ORDER: OnboardingAxis[] = [
  "companion",
  "mobility",
  "mood",
  "spot_pref",
  "accessibility",
  "flag",
  "congestion_pref",
];

/**
 * 축 한국어 라벨의 최후 폴백. tag-schema(§B.2)가 준 axes[].label을 항상 우선 사용하고,
 * 스키마 호출이 실패했을 때만 이 상수를 쓴다. 값은 계약 문서 §B.2가 명시한 6개 축 라벨
 * (동행/이동수단/분위기/스팟 선호/접근성/혼잡 선호) 그대로이며, flag만 화면 표시를 위해
 * 별도로 보강했다(§B.2: flag는 칩이 없어 tag-schema 축 목록에서 제외됨).
 */
export const AXIS_LABEL_FALLBACK: Record<OnboardingAxis, string> = {
  companion: "동행",
  flag: "특이사항",
  mobility: "이동수단",
  mood: "분위기",
  spot_pref: "스팟 선호",
  accessibility: "접근성",
  congestion_pref: "혼잡 선호",
};

/** 로딩 화면에서 순환 표시할 진행 문구. ~24초 추론 동안 사용자가 멈춘 줄 알고 이탈하지 않도록. */
export const LOADING_MESSAGES = [
  "AI가 취향을 읽고 있어요…",
  "동행·이동수단을 살피는 중…",
  "분위기와 선호 스팟을 정리하는 중…",
  "거의 다 됐어요, 조금만 기다려주세요…",
];

/** 체감 진행률 계산 기준 시간(초). 실제 추론은 ~24초(§B.0) — 이보다 넉넉히 잡아 끝에 멈추지 않게 한다. */
export const LOADING_EXPECTED_SECONDS = 24;
