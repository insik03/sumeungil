"use client";

import { useEffect, useState } from "react";
import { LOADING_EXPECTED_SECONDS, LOADING_MESSAGES } from "./constants";

interface OnboardingLoadingProps {
  onCancel: () => void;
}

/**
 * §B.5-3 로딩 UX(필수) — 로컬 LLM 추론이 ~24초 걸린다(§B.0).
 * 스피너 + 순환 문구 + 체감 진행바로 "멈춘 게 아니라 진행 중"임을 계속 보여줘 이탈을 막는다.
 * 실제 서버 진행률을 알 방법이 없으므로(동기 응답, §B.6) 경과 시간 기반 근사치이며 100%를 스스로 채우지 않는다
 * — 응답이 오면 부모가 화면을 result/error로 전환한다.
 */
export default function OnboardingLoading({ onCancel }: OnboardingLoadingProps) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => setElapsed((t) => t + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  const progress = Math.min(92, Math.round((elapsed / LOADING_EXPECTED_SECONDS) * 92));
  const messageIndex = Math.min(
    LOADING_MESSAGES.length - 1,
    Math.floor(elapsed / (LOADING_EXPECTED_SECONDS / LOADING_MESSAGES.length))
  );

  return (
    <section className="onboard-section" aria-label="취향 분석 진행 중">
      <div className="onboard-card onboard-loading" role="status" aria-live="polite">
        <div className="onboard-loading__spinner" aria-hidden="true" />
        <h2 className="onboard-loading__title">취향을 분석하고 있어요…</h2>
        <p className="onboard-loading__msg">{LOADING_MESSAGES[messageIndex]}</p>
        <div className="onboard-loading__bar" aria-hidden="true">
          <div className="onboard-loading__bar-fill" style={{ width: `${progress}%` }} />
        </div>
        <p className="onboard-loading__elapsed">
          {elapsed}초 경과 · 보통 20~30초 정도 걸려요. 화면을 벗어나지 말고 잠시만 기다려주세요.
        </p>
        <button type="button" className="onboard-loading__cancel" onClick={onCancel}>
          취소하고 다시 입력하기
        </button>
      </div>
    </section>
  );
}
