"use client";

import { useEffect, useState } from "react";
import {
  OnboardingResult,
  PersonalizedTip,
  fetchMyOnboardingProfile,
  fetchPersonalizedTips,
} from "../../lib/api";
import { loadLastRegion } from "../../lib/lastRegionStorage";
import { useLoggedInName } from "../../lib/useLoggedInName";

/** AI 라벨 아이콘 — CourseContent.tsx의 .ai-summary__label과 동일 글리프 재사용(신규 아이콘 없음). */
function SparkleIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z" fill="currentColor" />
    </svg>
  );
}

type Phase = "idle" | "checking" | "ready" | "none";

/**
 * §47.9(신규, 03-design-spec.md 부록 밖 — 08-interface-contract.md 부록 Z 계약, 2026-08-20)
 * `/tips` 개인화 팁 연동. 로그인 + 온보딩 프로필이 있을 때만 POST /api/v1/tips/personalized를
 * 호출한다(비로그인·프로필없음은 서버도 정적 폴백을 주지만, 불필요한 호출을 프론트에서 먼저
 * 거른다). 실패하거나 서버가 정적 폴백(generated_by:"static-v2")으로 응답하면 아무것도
 * 그리지 않는다 — TipsContent.tsx의 기존 정적 5건이 이미 항상 렌더되고 있으므로 additive로만
 * 얹는다(기존 화면을 대체하지 않는다).
 *
 * "AI가 만든 참고용" 표기(부록 Z.0-3): notice는 서버 상수 문자열이고 ai일 때만 온다 — 텍스트
 * 노드로만 렌더한다(HTML 주입 금지, 부록 R.8-2와 동일 원칙 승계).
 */
export default function PersonalizedTips() {
  const loggedIn = useLoggedInName();
  const [phase, setPhase] = useState<Phase>("idle");
  const [tips, setTips] = useState<PersonalizedTip[]>([]);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!loggedIn) {
      setPhase("none");
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    setPhase("checking");

    fetchMyOnboardingProfile(controller.signal)
      .then((profile: OnboardingResult | null) => {
        if (cancelled) return;
        if (!profile) {
          setPhase("none");
          return;
        }
        const regionCode = loadLastRegion()?.sigungu_cd ?? null;
        return fetchPersonalizedTips(regionCode, controller.signal).then((res) => {
          if (cancelled) return;
          if (res.generated_by === "ai-v1" && res.tips.length > 0) {
            setTips(res.tips);
            setNotice(res.notice);
            setPhase("ready");
          } else {
            setPhase("none"); // 서버 정적 폴백(static-v2) — 기존 정적 5건 그대로 두고 여긴 숨긴다
          }
        });
      })
      .catch(() => {
        if (cancelled) return;
        setPhase("none"); // 실패해도 기존 정적 5건은 그대로 보인다(이 컴포넌트만 조용히 숨음)
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [loggedIn]);

  if (phase !== "ready" || tips.length === 0) return null;

  return (
    <div className="tips-group tips-group--ai">
      <span className="tips-category-label tips-group__label">
        <SparkleIcon /> AI 맞춤 팁
      </span>
      <div className="tips-grid">
        {tips.map((tip) => (
          <article className="tip-card" key={tip.id}>
            <span className="tips-category-label">{tip.category}</span>
            <h2 className="tip-card__title">{tip.title}</h2>
            <p className="tip-card__body">{tip.body}</p>
          </article>
        ))}
      </div>
      {notice && (
        <p className="dest-search__notice tips-group__ai-notice" role="note">
          {notice}
        </p>
      )}
    </div>
  );
}
