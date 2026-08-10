"use client";

import { FormEvent, useId, useState } from "react";
import { useRouter } from "next/navigation";
import { withRegionCode } from "../lib/regionQuery";
import { EXAMPLE_QUESTIONS, MAX_LEN, MIN_LEN } from "./concierge/constants";

/** 전송 아이콘 — 이모지 대신 인라인 SVG(ui-ux-pro-max 체크리스트 근거). */
function SendIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M4 12l16-8-6 8 6 8-16-8z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * §33-3(2026-07-29, 03-design-spec.md, 대표 피드백 하이브리드안) — 홈 AI 여행 문답 섹션을
 * "컴팩트 진입"으로 슬림화했다. 예전(§32)엔 여기서 질문을 받아 결과까지 전부 렌더했지만, 그
 * 풀 경험은 이제 `/ask`(AskContent.tsx)로 전부 옮겼다 — 이 컴포넌트는 한 줄 입력창 + 예시
 * 칩만 남기고, 제출 시 `/ask?q={질문}`으로 이동한다(홈에서 결과를 렌더하지 않아 홈 스크롤
 * 길이가 줄어든다, 지시서 요구사항). 로딩·에러·결과 상태를 이 컴포넌트가 더는 갖지 않는다.
 *
 * §35(2026-07-31, 백로그 D21 — 지역 컨텍스트 전파) — 홈에서 고른 지역을 `&region_code=`로 함께
 * 넘긴다. 이 값은 폴백일 뿐이고 질문 문장에 지역이 있으면 서버가 그쪽을 우선한다(부록 N §N.3②) —
 * 프론트는 전달만 하고 어느 쪽이 이겼는지 재판정하지 않는다. §33-3에서 regionCode prop을 뗐던
 * 이유(라우트 간 전달 수단이 없었음)가 이번에 해소돼 다시 받는다.
 */
interface ConciergeSectionProps {
  /** 홈에서 선택된 지역(sigungu_cd). null이면 쿼리를 붙이지 않는다(기존 동작 그대로). */
  regionCode?: string | null;
}

export default function ConciergeSection({ regionCode = null }: ConciergeSectionProps) {
  const [question, setQuestion] = useState("");
  const inputId = useId();
  const router = useRouter();

  const trimmed = question.trim();
  const tooShort = trimmed.length > 0 && trimmed.length < MIN_LEN;
  const tooLong = trimmed.length > MAX_LEN;
  const canSubmit = trimmed.length >= MIN_LEN && trimmed.length <= MAX_LEN;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    router.push(withRegionCode(`/ask?q=${encodeURIComponent(trimmed)}`, regionCode));
  };

  return (
    <section className="section concierge" aria-labelledby="conciergeHeading">
      <span className="eyebrow-pill eyebrow-pill--azure">AI 여행 문답</span>
      <h2 className="section__title" id="conciergeHeading">
        말로 물어보면, AI가 조건에 맞는 곳을 찾아드려요
      </h2>
      <p className="concierge__lead">
        필터를 고르지 않아도 괜찮아요. &ldquo;비 오는 날 부모님 모시고 갈 조용한 곳&rdquo;처럼
        편하게 물어보세요.
      </p>

      <form className="concierge-quick" onSubmit={handleSubmit}>
        <label className="onboard-label" htmlFor={inputId}>
          무엇이 궁금하세요?
        </label>
        <div className="dest-search__box concierge-quick__box">
          <svg className="dest-search__icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z" fill="currentColor" />
          </svg>
          <input
            id={inputId}
            type="text"
            className="dest-search__input"
            placeholder="예: 아이랑 갈만한 비 오는 날 실내 명소 있어?"
            value={question}
            maxLength={MAX_LEN}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <button
            type="submit"
            className="concierge-quick__submit"
            aria-label="AI에게 물어보기"
            disabled={!canSubmit}
          >
            <SendIcon />
          </button>
        </div>

        {(tooShort || tooLong) && (
          <p className="onboard-validation" role="alert">
            질문은 {MIN_LEN}자 이상 {MAX_LEN}자 이하로 입력해주세요.
          </p>
        )}

        <div className="chip-row concierge__examples" role="group" aria-label="예시 질문">
          {EXAMPLE_QUESTIONS.map((q) => (
            <button key={q} type="button" className="onboard-chip" onClick={() => setQuestion(q)}>
              {q}
            </button>
          ))}
        </div>
      </form>
    </section>
  );
}
