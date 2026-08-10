"use client";

import { FormEvent, useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ApiError, ConciergeAskResponse, OnboardingAxis, TagValue, askConcierge } from "../lib/api";
import { readRegionCode, withRegionCode } from "../lib/regionQuery";
import RecommendSpotCard from "./recommend/SpotCard";
import { FestivalCard } from "./FestivalBanner";
import { AXIS_LABEL_FALLBACK, RESULT_AXIS_ORDER } from "./onboarding/constants";
import { EXAMPLE_QUESTIONS, MAX_LEN, MIN_LEN } from "./concierge/constants";

type Status = "idle" | "loading" | "success" | "error";

/** AI 답변 라벨 옆 스파클 아이콘 — SpotDetailContent.tsx .ai-summary와 동일한 글리프 재사용. */
function SparkleIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z" fill="currentColor" />
    </svg>
  );
}

/** 지역 배지 핀 아이콘 — CongestionBoard.tsx .sample-tag와 동일한 글리프 재사용. */
function PinIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M12 2C7.58 2 4 5.58 4 10c0 5.25 6.72 11.34 7.06 11.64a1.5 1.5 0 0 0 1.88 0C13.28 21.34 20 15.25 20 10c0-4.42-3.58-8-8-8zm0 11a3 3 0 1 1 0-6 3 3 0 0 1 0 6z"
        fill="currentColor"
      />
    </svg>
  );
}

function validQuestion(q: string): boolean {
  const t = q.trim();
  return t.length >= MIN_LEN && t.length <= MAX_LEN;
}

/**
 * §33-3(2026-07-29, 03-design-spec.md) — AI 문답 전용 페이지(`/ask`)의 풀 경험. 기존
 * ConciergeSection.tsx(§32)에 있던 입력 폼+로딩+에러+결과 렌더 전체를 그대로 이 컴포넌트로
 * 옮겼다(재구현 아님, 이전) — 홈은 이제 컴팩트 진입창만 갖고(ConciergeSection.tsx §33-3),
 * 결과 렌더 책임은 이 컴포넌트 하나로만 존재한다(중복 구현 금지 원칙 준수).
 *
 * URL `?q=` 지원 — 값이 있고 길이 검증(2~200자)을 통과하면 마운트 시 자동으로 질문을 실행한다
 * (재공유·재진입 시 결과를 바로 보여주기 위함, 지시서 요구사항). 검증 실패 값은 입력창에만
 * 채우고 자동 제출하지 않는다(서버가 어차피 422를 낼 값을 굳이 왕복시키지 않는다).
 *
 * §35(2026-07-31, 03-design-spec.md — 지역 컨텍스트 전파, 백로그 D21) — URL `?region_code=`도
 * 함께 읽어 askConcierge의 region_code로 넘긴다(수동 제출·`?q=` 자동 실행 둘 다). 이 값은 폴백일
 * 뿐이며 질문 문장에 지역이 있으면 서버가 그쪽을 우선한다(부록 N §N.3②) — 프론트는 전달만 하고
 * 어느 쪽이 채택됐는지 재판정하지 않는다(채택 결과는 응답의 extracted.region 배지로 이미 보인다).
 * 형식이 어긋난 값은 readRegionCode가 걸러 null로 보낸다(쿼리 없을 때와 동일 동작).
 */
export default function AskContent() {
  const searchParams = useSearchParams();
  const initialQuestion = searchParams.get("q") ?? "";
  const regionCode = readRegionCode(searchParams.get("region_code"));

  const [question, setQuestion] = useState(initialQuestion);
  const [status, setStatus] = useState<Status>("idle");
  const [result, setResult] = useState<ConciergeAskResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const inputId = useId();

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const runAsk = (q: string) => {
    const trimmed = q.trim();
    if (!validQuestion(trimmed)) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setStatus("loading");
    setError(null);

    askConcierge(trimmed, regionCode, controller.signal)
      .then((res) => {
        setResult(res);
        setStatus("success");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          err instanceof ApiError
            ? err
            : new ApiError(0, "UNKNOWN", "질문에 답하지 못했어요. 잠시 후 다시 시도해주세요.")
        );
        setStatus("error");
      });
  };

  // ?q= 자동 실행 — q 파라미터 기준. ★ref 가드(마운트당 1회) 방식은 React StrictMode
  // 이중 마운트에서 ref가 true로 남아 두 번째 마운트의 실행을 막고, 첫 요청은 cleanup
  // abort로 죽어 로딩이 영원히 걸리는 버그가 있었다(네트워크 실측: 요청 전부 ERR_ABORTED).
  // 의존성 기반으로 바꿔 재마운트 시 자연히 재실행되게 한다.
  // §35 — regionCode도 의존성에 넣는다(지역만 다른 URL로 재진입하면 그 지역 기준으로 다시 묻는다).
  // 둘 다 URL 파생값이라 렌더마다 값이 흔들리지 않아 이중 마운트 패턴은 그대로 안전하다.
  useEffect(() => {
    if (initialQuestion && validQuestion(initialQuestion)) {
      runAsk(initialQuestion);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion, regionCode]);

  const trimmed = question.trim();
  const tooShort = trimmed.length > 0 && trimmed.length < MIN_LEN;
  const tooLong = trimmed.length > MAX_LEN;
  const canSubmit = trimmed.length >= MIN_LEN && trimmed.length <= MAX_LEN && status !== "loading";

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    runAsk(trimmed);
  };

  // §N.5-6/§C.7-4와 동일 원칙 — matched_tags(registry 코드)를 이번 응답 자체의 extracted.tags
  // 라벨로 치환한다(서버가 이미 검증한 라벨을 그대로 신뢰, 프론트 재매핑 없음).
  const tagLabelMap: Record<string, string> = {};
  if (result) {
    Object.values(result.extracted.tags).forEach((list) => {
      list?.forEach((t: TagValue) => {
        tagLabelMap[t.value] = t.label;
      });
    });
  }

  const understoodAxes: OnboardingAxis[] = result
    ? RESULT_AXIS_ORDER.filter((axis) => (result.extracted.tags[axis]?.length ?? 0) > 0)
    : [];

  return (
    <section className="section concierge" aria-labelledby="askHeading">
      <span className="eyebrow-pill eyebrow-pill--azure">AI 여행 문답</span>
      <h1 className="section__title" id="askHeading">
        말로 물어보면, AI가 조건에 맞는 곳을 찾아드려요
      </h1>
      <p className="concierge__lead">
        필터를 고르지 않아도 괜찮아요. &ldquo;비 오는 날 부모님 모시고 갈 조용한 곳&rdquo;처럼
        편하게 물어보세요.
      </p>

      <div className="concierge-card">
        <form className="concierge__form" onSubmit={handleSubmit}>
          <label className="onboard-label" htmlFor={inputId}>
            무엇이 궁금하세요?
          </label>
          <textarea
            id={inputId}
            className="onboard-textarea concierge__textarea"
            placeholder="예: 아이랑 갈만한 비 오는 날 실내 명소 있어?"
            value={question}
            maxLength={MAX_LEN}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={status === "loading"}
          />
          <p className="onboard-textarea__count" aria-live="off">
            {trimmed.length}/{MAX_LEN}
          </p>

          <div className="chip-row concierge__examples" role="group" aria-label="예시 질문">
            {EXAMPLE_QUESTIONS.map((q) => (
              <button
                key={q}
                type="button"
                className="onboard-chip"
                onClick={() => setQuestion(q)}
                disabled={status === "loading"}
              >
                {q}
              </button>
            ))}
          </div>

          {(tooShort || tooLong) && (
            <p className="onboard-validation" role="alert">
              질문은 {MIN_LEN}자 이상 {MAX_LEN}자 이하로 입력해주세요.
            </p>
          )}

          <div className="onboard-submit concierge__submit-row">
            <button type="submit" className="btn btn--coral btn--lg btn--block" disabled={!canSubmit}>
              {status === "loading" ? "AI가 답변하는 중…" : "AI에게 물어보기"}
            </button>
          </div>
        </form>

        {status === "loading" && (
          <div className="concierge__loading" role="status" aria-live="polite">
            <span className="concierge__loading-spinner" aria-hidden="true" />
            <p className="concierge__loading-text">
              AI가 조건을 읽고 있어요… 보통 5~10초 정도 걸려요.
            </p>
          </div>
        )}

        {status === "error" && (
          <div className="board-error" role="alert">
            <p className="board-error__msg">
              {error?.status === 422 || error?.status === 400
                ? "질문을 2자 이상 200자 이내로 다시 적어주세요."
                : error?.message ?? "질문에 답하지 못했어요. 잠시 후 다시 시도해주세요."}
            </p>
            <p className="board-error__hint">입력하신 질문은 그대로 남아 있어요. 다시 눌러보세요.</p>
          </div>
        )}

        {status === "success" && result && (
          <div className="concierge__result" aria-live="polite">
            <div className="ai-summary">
              <span className="ai-summary__label">
                <SparkleIcon />
                숨은길 AI
              </span>
              {/* answer는 항상 평문 문자열(부록 N §N.5-7) — 텍스트노드로만 렌더, HTML 주입 없음. */}
              <p className="ai-summary__text">{result.answer}</p>
            </div>
            <p className="concierge__footnote">AI 답변은 참고용이며 실제와 다를 수 있어요.</p>

            {result.extracted.region && (
              <span className="sample-tag concierge__region-badge">
                <PinIcon />
                {result.extracted.region.region_name} 기준으로 찾아봤어요
              </span>
            )}

            {understoodAxes.length > 0 && (
              <div className="concierge__understood">
                <h2 className="concierge__understood-title">이렇게 이해했어요</h2>
                {understoodAxes.map((axis) => (
                  <div className="onboard-axis-group" key={axis}>
                    <span className="onboard-axis-group__label">{AXIS_LABEL_FALLBACK[axis]}</span>
                    <div className="onboard-tag-row">
                      {result.extracted.tags[axis]!.map((tag) => (
                        <span key={tag.value} className="onboard-tag">
                          #{tag.label}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {result.meta.notice && <p className="dest-search__notice concierge__notice">{result.meta.notice}</p>}

            {result.spots.length > 0 && (
              <div className="concierge__spots">
                <h2 className="concierge__spots-heading">이런 곳은 어때요?</h2>
                <div className="spot-grid" role="list">
                  {result.spots.map((spot) => (
                    <div key={spot.id} role="listitem">
                      <Link
                        className="spot-card-link"
                        aria-label={`${spot.name} 상세 보기`}
                        href={`/spot/${spot.id}?region_code=${encodeURIComponent(spot.region_code)}`}
                      >
                        <RecommendSpotCard spot={spot} tagLabelMap={tagLabelMap} />
                      </Link>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* §N.6(2026-07-30) 축제 의도 — 축제 질문이면 스팟 대신 축제 카드를 보여준다
                (FestivalBanner.tsx의 FestivalCard 그대로 재사용, 중복 구현 금지 원칙). */}
            {(result.festivals?.length ?? 0) > 0 && (
              <div className="concierge__spots">
                <h2 className="concierge__spots-heading">이런 축제는 어때요?</h2>
                <div className="featured-scroll" role="list">
                  {result.festivals!.map((festival) => (
                    <FestivalCard key={festival.id} festival={festival} />
                  ))}
                </div>
              </div>
            )}

            {result.meta.intent === "festivals" ? (
              <Link href="/festivals" className="btn btn--coral btn--lg concierge__cta">
                전국 축제 모두 보기
              </Link>
            ) : (
              // §35 — 코스 화면으로도 지역을 이어준다. 서버가 실제로 채택한 지역
              // (extracted.region.region_code)을 먼저 쓰고, 없으면 이 화면이 받은 쿼리값을 쓴다
              // — 프론트가 지역을 지어내지 않고 이미 검증된 값만 넘긴다.
              <Link
                href={withRegionCode(
                  "/course",
                  result.extracted.region?.region_code ?? regionCode
                )}
                className="btn btn--coral btn--lg concierge__cta"
              >
                이 조건으로 코스 짜기
              </Link>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

/** app/ask/page.tsx의 Suspense fallback(useSearchParams 규약, CompareContent.tsx와 동일 패턴). */
export function AskLoadingSkeleton() {
  return (
    <section className="section concierge" aria-label="AI 여행 문답 불러오는 중">
      <div className="concierge-card" role="status" aria-live="polite">
        <div className="skeleton-bar" style={{ width: "40%", height: "14px" }} />
        <div className="skeleton-bar" style={{ width: "100%", height: "96px", marginTop: "16px" }} />
      </div>
    </section>
  );
}
