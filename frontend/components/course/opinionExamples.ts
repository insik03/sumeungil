/**
 * AI 코스짜기 선택지(2026-09-20 대표 지시 — "직접 입력 대신 실내/실외·동행·액티비티 같은 걸 고르게").
 * 고른 조합을 `composeCourseWish` 가 한 문장으로 만들어 기존 자유서술 경로(analyzeOnboarding → 코스
 * 선택기 wish)에 그대로 넘긴다 — 서버·프롬프트 무변경. 개인정보가 들어갈 자리가 없다.
 */
export interface CourseChoiceOption {
  value: string;
  label: string;
  /** 문장 조각 — composeCourseWish 가 이어 붙인다. */
  phrase: string;
}
export interface CourseChoice {
  key: "who" | "place" | "activity";
  label: string;
  options: CourseChoiceOption[];
}

export const COURSE_CHOICES: CourseChoice[] = [
  {
    key: "who",
    label: "누구와 가나요?",
    options: [
      { value: "solo", label: "혼자", phrase: "혼자 여행" },
      { value: "couple", label: "연인", phrase: "연인과 함께" },
      { value: "friends", label: "친구", phrase: "친구들과 함께" },
      { value: "family", label: "아이와 가족", phrase: "아이와 가족이 함께" },
      { value: "parents", label: "부모님", phrase: "부모님을 모시고" },
      { value: "pet", label: "반려동물", phrase: "반려동물과 함께" },
    ],
  },
  {
    key: "place",
    label: "실내 · 실외",
    options: [
      { value: "indoor", label: "실내 위주", phrase: "실내 위주로" },
      { value: "outdoor", label: "실외 위주", phrase: "야외 위주로" },
      { value: "any", label: "상관없음", phrase: "실내·실외 상관없이" },
    ],
  },
  {
    key: "activity",
    label: "어떤 하루?",
    options: [
      { value: "active", label: "활동적인 체험", phrase: "활동적인 체험이 있는" },
      { value: "slow", label: "느긋한 산책", phrase: "느긋하게 걷는" },
      { value: "food", label: "맛집·카페 위주", phrase: "맛집과 카페 위주의" },
      { value: "photo", label: "사진 찍기 좋은", phrase: "사진 찍기 좋은" },
    ],
  },
];

/** 고른 조합 → "연인과 함께, 실내 위주로, 느긋하게 걷는 코스". 아무것도 안 골랐으면 빈 문자열. */
export function composeCourseWish(choices: Record<string, string>): string {
  const parts = COURSE_CHOICES.map((g) => g.options.find((o) => o.value === choices[g.key])?.phrase).filter(
    (p): p is string => Boolean(p)
  );
  return parts.length ? `${parts.join(", ")} 코스` : "";
}
