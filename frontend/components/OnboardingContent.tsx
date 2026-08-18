"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  OnboardingAxis,
  OnboardingResult,
  TagSchemaAxis,
  analyzeOnboarding,
  fetchOnboardingTagSchema,
} from "../lib/api";
import { logout } from "../lib/authStorage";
import { saveOnboardingResult } from "../lib/onboardingStorage";
import { useLoggedInName } from "../lib/useLoggedInName";
import LoginRequiredGate from "./LoginRequiredGate";
import OnboardingForm, { SchemaStatus } from "./onboarding/OnboardingForm";
import OnboardingLoading from "./onboarding/OnboardingLoading";
import OnboardingResultView from "./onboarding/OnboardingResultView";
import { AXIS_LABEL_FALLBACK } from "./onboarding/constants";

type Step = "form" | "loading" | "result" | "error";

interface LastSubmission {
  text?: string;
  chips?: string[];
}

/**
 * 온보딩(M1) 화면 오케스트레이터. 01-interface-contract.md 부록 B(§B.1~B.7)를 그대로 따른다.
 * - 진입 시 tag-schema 1회 호출(§B.5-1), 제출은 analyze(§B.5-2), 응답은 sessionStorage에만 보관(§B.5-7).
 * - LLM 실패는 서버가 200 + fallback_used:true로 흡수하므로(§B.3) 여기서는 4xx/5xx/타임아웃/네트워크만 에러로 다룬다.
 */
export default function OnboardingContent() {
  const router = useRouter();
  // 2026-08-17(대표 지시) — 온보딩(취향분석)은 로그인 필수. "시작하기가 사실상 회원가입"
  // 이라는 지적대로, 비로그인이면 폼 대신 로그인 게이트만 보여준다.
  const loggedIn = useLoggedInName();

  const [text, setText] = useState("");
  const [selected, setSelected] = useState<Record<string, Set<string>>>({});
  const [validationMessage, setValidationMessage] = useState<string | null>(null);

  const [schemaStatus, setSchemaStatus] = useState<SchemaStatus>("loading");
  const [axes, setAxes] = useState<TagSchemaAxis[]>([]);
  const [schemaRetryTick, setSchemaRetryTick] = useState(0);

  const [step, setStep] = useState<Step>("form");
  const [result, setResult] = useState<OnboardingResult | null>(null);
  const [errorInfo, setErrorInfo] = useState<ApiError | null>(null);
  const [lastSubmission, setLastSubmission] = useState<LastSubmission | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  // §B.5-1: 진입 시 tag-schema 1회 호출 — 칩 목록은 이 응답으로만 구성한다.
  // 2026-08-17: 로그인 전에는 폼 자체를 안 보여주므로(아래 return문) 이 호출도 미룬다.
  useEffect(() => {
    if (!loggedIn) return;
    let cancelled = false;
    const controller = new AbortController();
    setSchemaStatus("loading");
    fetchOnboardingTagSchema(controller.signal)
      .then((res) => {
        if (cancelled) return;
        setAxes(res.axes);
        setSchemaStatus("success");
      })
      .catch((err: unknown) => {
        if (cancelled || controller.signal.aborted) return;
        // 백엔드가 아직 MVP-3 전이면(엔드포인트 없음) 404, 미기동이면 네트워크 실패(status 0) — 화면은 죽지 않고 "준비 중" 처리.
        if (err instanceof ApiError && (err.status === 404 || err.status === 0)) {
          setSchemaStatus("unavailable");
        } else {
          setSchemaStatus("error");
        }
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [schemaRetryTick, loggedIn]);

  const axisLabels = useMemo(() => {
    const map: Partial<Record<OnboardingAxis, string>> = { ...AXIS_LABEL_FALLBACK };
    axes.forEach((a) => {
      map[a.axis as OnboardingAxis] = a.label;
    });
    return map;
  }, [axes]);

  const toggleChip = useCallback((axis: TagSchemaAxis, value: string) => {
    setValidationMessage(null);
    setSelected((prev) => {
      const next: Record<string, Set<string>> = { ...prev };
      const current = new Set(next[axis.axis] ?? []);
      if (current.has(value)) {
        current.delete(value);
      } else {
        if (axis.select === "single") current.clear();
        current.add(value);
      }
      next[axis.axis] = current;
      return next;
    });
  }, []);

  const handleTextChange = useCallback((value: string) => {
    setValidationMessage(null);
    setText(value);
  }, []);

  const runAnalyze = useCallback((payload: LastSubmission) => {
    setLastSubmission(payload);
    setStep("loading");
    setErrorInfo(null);

    const controller = new AbortController();
    abortRef.current = controller;

    analyzeOnboarding(payload, controller.signal)
      .then((res) => {
        // §B.5-7: 서버 저장 없이 sessionStorage에만 보관. 다음 단계(추천)가 여기서 읽는다.
        saveOnboardingResult(res);
        setResult(res);
        setStep("result");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return; // 사용자가 직접 취소 — 이미 폼으로 돌아가 있음
        if (err instanceof ApiError && err.status === 401) {
          // 세션이 도중에 만료됐다 — 로컬 로그인 캐시를 정리하면 useLoggedInName()이
          // null로 바뀌어 이 화면이 자동으로 로그인 게이트로 돌아간다(아래 return문).
          logout();
          setStep("form");
          return;
        }
        setErrorInfo(
          err instanceof ApiError ? err : new ApiError(0, "UNKNOWN", "취향 분석에 실패했습니다.")
        );
        setStep("error");
      });
  }, []);

  const handleSubmit = useCallback(() => {
    const trimmed = text.trim();
    const chips = Object.values(selected).flatMap((s) => Array.from(s));
    if (!trimmed && chips.length === 0) {
      // §B.1 EMPTY_INPUT과 동일한 문구로 미리 안내 — 24초를 기다렸다 실패하지 않게 클라이언트에서 먼저 막는다.
      setValidationMessage("취향을 입력하거나 키워드를 선택해 주세요.");
      return;
    }
    setValidationMessage(null);
    runAnalyze({ text: trimmed || undefined, chips: chips.length > 0 ? chips : undefined });
  }, [text, selected, runAnalyze]);

  const handleCancelLoading = useCallback(() => {
    abortRef.current?.abort();
    setStep("form");
  }, []);

  const handleRetry = useCallback(() => {
    if (lastSubmission) runAnalyze(lastSubmission);
  }, [lastSubmission, runAnalyze]);

  const handleEditAfterError = useCallback(() => {
    setStep("form");
  }, []);

  const handleEditAfterResult = useCallback(() => {
    setStep("form");
  }, []);

  const handleConfirmResult = useCallback(() => {
    // 2026-08-17(대표 지시) — 예전엔 여기서 바로 /recommend로 보냈다(MVP-4, 부록 C: 추천
    // 화면이 이 결과를 sessionStorage에서 그대로 소비). 이제 홈으로 보내고, 홈이 방금
    // 만든 추천을 배너로 안내한다(HomeContent.tsx의 hasFreshOnboardingResult 참고) —
    // sessionStorage는 그대로 두므로 recommend가 여전히 이 결과를 소비할 수 있다.
    router.push("/");
  }, [router]);

  return (
    <>
      <section className="onboard-hero" aria-label="온보딩 소개">
        <span className="hero__eyebrow">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M12 2l2.2 6.8H21l-5.6 4.1 2.2 6.9L12 15.8 6.4 19.8l2.2-6.9L3 8.8h6.8L12 2z"
              fill="currentColor"
            />
          </svg>
          두근두근 취향 찾기
        </span>
        <h1 className="onboard-hero__title">
          우리만 아는 코스를 위해
          <br />
          취향을 살짝 알려주세요
        </h1>
        <p className="onboard-hero__sub">
          동행, 이동 방법, 좋아하는 분위기까지 — AI가 자유 서술과 키워드를 함께 읽고 정리해드려요.
        </p>
      </section>

      {!loggedIn ? (
        <LoginRequiredGate
          title="로그인이 필요해요"
          message="로그인하면 취향 분석 결과가 계정에 저장돼 다음에 다시 온보딩하지 않아도 돼요."
        />
      ) : step === "form" && (
        <OnboardingForm
          text={text}
          onTextChange={handleTextChange}
          schemaStatus={schemaStatus}
          axes={axes}
          selected={selected}
          onToggleChip={toggleChip}
          onSubmit={handleSubmit}
          canSubmit={true}
          validationMessage={validationMessage}
          onRetrySchema={() => setSchemaRetryTick((t) => t + 1)}
        />
      )}

      {step === "loading" && <OnboardingLoading onCancel={handleCancelLoading} />}

      {step === "result" && result && (
        <OnboardingResultView
          result={result}
          axisLabels={axisLabels}
          displayName={loggedIn}
          onEdit={handleEditAfterResult}
          onConfirm={handleConfirmResult}
        />
      )}

      {step === "error" && (
        <section className="onboard-section" aria-label="취향 분석 오류">
          <div className="board-error" role="alert">
            <p className="board-error__msg">
              {errorInfo?.message ?? "취향 분석에 실패했습니다."}
            </p>
            <p className="board-error__hint">
              {errorInfo?.code === "TIMEOUT"
                ? "AI 분석이 평소보다 오래 걸리고 있어요. 잠시 후 다시 시도해주세요."
                : "백엔드 서버가 켜져 있는지 확인해주세요 (localhost:8000). 잠시 후 다시 시도해주세요."}
            </p>
            <div style={{ display: "flex", gap: "var(--sp-2)" }}>
              <button className="btn btn--coral" type="button" onClick={handleRetry}>
                다시 시도
              </button>
              <button className="btn btn--ghost-text" type="button" onClick={handleEditAfterError}>
                입력 수정하기
              </button>
            </div>
          </div>
        </section>
      )}
    </>
  );
}
