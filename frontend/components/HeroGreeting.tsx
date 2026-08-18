"use client";

import { useEffect, useState } from "react";
import { loadOnboardingResult } from "../lib/onboardingStorage";
import { useLoggedInName } from "../lib/useLoggedInName";

/**
 * 로그인 사용자용 한 줄 인사("OO님, 둘이서 걷기 좋은 오늘의 코스를 아래에서 찾아보세요").
 * 2026-08-18(대표 지시) — 원래 Hero.tsx 맨 위(검색바보다도 먼저)에 있었는데, "카테고리 창
 * (ServiceQuickMenu) 밑, 추천 CTA 배너 밑"으로 옮겨달라는 요청에 따라 별도 컴포넌트로
 * 뽑아 HomeContent.tsx가 원하는 위치에 독립적으로 배치할 수 있게 했다. 로직·문구는 전혀
 * 바뀌지 않았다 — 위치만 옮겼다.
 *
 * 동행(companion) 태그 → 카피 분기 (대표 지시, 2026-07-29) — "아이와 함께 걷기 좋은"이
 * 하드코딩돼 있었는데 커플·혼자일 수도 있다는 지적. 온보딩에서 실제로 고른 동행 태그가
 * 있을 때만 그 문구를 쓰고, 없으면 중립 문구(회원가입에서 새 개인정보를 받지 않는다 —
 * 이미 있는 온보딩 취향만 사용, 법률 보류 방침 부합). 우선순위: 아이>반려동물>연인>부모님>
 * 친구>혼자>가족 — 더 구체적인 동행을 먼저 반영.
 */
const COMPANION_COPY: { value: string; walkWith: string }[] = [
  { value: "with_child", walkWith: "아이와 함께 걷기 좋은" },
  { value: "with_pet", walkWith: "반려견과 함께 걷기 좋은" },
  { value: "couple", walkWith: "둘이서 걷기 좋은" },
  { value: "with_parents", walkWith: "부모님과 함께 걷기 좋은" },
  { value: "friends", walkWith: "친구와 함께 걷기 좋은" },
  { value: "solo", walkWith: "혼자 사색하며 걷기 좋은" },
  { value: "family", walkWith: "가족과 함께 걷기 좋은" },
];
const NEUTRAL_WALK_WITH = "천천히 걷기 좋은";

export default function HeroGreeting() {
  const nickname = useLoggedInName();
  // SSR/첫 클라이언트 렌더는 중립값으로 맞춰 하이드레이션 경고를 막고, mount 후 실제값 반영
  // (기존 Hero.tsx와 동일 패턴 — 로그인 여부는 useLoggedInName이 이미 이 규칙을 지킨다).
  const [companionValues, setCompanionValues] = useState<string[]>([]);
  useEffect(() => {
    const stored = loadOnboardingResult()?.result;
    setCompanionValues(stored?.tags?.companion?.map((t) => t.value) ?? []);
  }, []);

  if (!nickname) return null;

  const companionCopy = COMPANION_COPY.find((c) => companionValues.includes(c.value)) ?? null;
  const walkWith = companionCopy?.walkWith ?? NEUTRAL_WALK_WITH;

  return (
    <p className="hero-greeting">
      {nickname}님, {walkWith} 오늘의 코스를 아래에서 찾아보세요
    </p>
  );
}
