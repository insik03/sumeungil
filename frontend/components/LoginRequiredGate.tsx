"use client";

/**
 * 로그인 필수 기능(온보딩·AI 문답·AI 코스짜기, 2026-08-17 대표 지시)의 공통 게이트 UI.
 * 세 페이지가 똑같은 모양이라 컴포넌트로 뺐다 — `LoginGateProvider.tsx`의 `requireLogin`은
 * 원래 "버튼 클릭 하나를 감싸는" 액션 래퍼였는데(하트·저장 등 기존 6곳), 여기서는 action을
 * 빈 함수로 넘긴다 — 로그인 성공 시 `LoginModal`이 `setLoggedInName()`으로
 * `AUTH_CHANGED_EVENT`를 쏘면 각 페이지의 `useLoggedInName()`이 그걸 받아 자동으로
 * 리렌더되어 실제 컨텐츠로 바뀐다. 즉 "로그인 후 이걸 실행해줘"가 아니라 "로그인 모달만
 * 띄워줘"가 목적이라 action이 할 일이 없다.
 */
import { useLoginGate } from "./LoginGateProvider";

interface LoginRequiredGateProps {
  title: string;
  message: string;
  ctaLabel?: string;
}

export default function LoginRequiredGate({
  title,
  message,
  ctaLabel = "로그인하고 시작하기",
}: LoginRequiredGateProps) {
  const { requireLogin } = useLoginGate();
  return (
    <section className="onboard-section" aria-label={title}>
      <div className="board-error" role="status">
        <h1 className="board-error__msg">{title}</h1>
        <p className="board-error__hint">{message}</p>
        <button
          className="btn btn--coral"
          type="button"
          onClick={() => requireLogin(() => {}, message)}
        >
          {ctaLabel}
        </button>
      </div>
    </section>
  );
}
