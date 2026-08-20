import { OnboardingAxis, OnboardingResult } from "../../lib/api";
import { RESULT_AXIS_ORDER } from "./constants";

const LOW_CONFIDENCE_THRESHOLD = 0.5; // §B.5-4 — 표시 전용 재량. 스코어링에는 쓰지 않는다(§B.1 confidence 규칙).

interface OnboardingResultViewProps {
  result: OnboardingResult;
  axisLabels: Partial<Record<OnboardingAxis, string>>;
  displayName: string | null;
  onEdit: () => void;
  onConfirm: () => void;
  onGoMypage: () => void;
}

/**
 * §B.5-4 결과 화면 — tags만으로 렌더한다. tag_vector/scoring_weights는 서버 전용 수치라
 * 화면에 노출하거나 재계산하지 않는다(§B.5-6). "이렇게 이해했어요" 톤으로 사용자가 확인/정정하게 한다.
 *
 * `displayName`은 OnboardingContent가 이미 들고 있는 `useLoggedInName()` 값을 그대로
 * 내려받는다(2026-08-17 — 하드코딩된 "서연님" 수정). 이 화면은 로그인 게이트를 통과해야만
 * 렌더되므로 실사용 시 null이 될 일은 없지만, 타입상 null이 오면 이름 없이 문구를 보여준다.
 */
export default function OnboardingResultView({
  result,
  axisLabels,
  displayName,
  onEdit,
  onConfirm,
  onGoMypage,
}: OnboardingResultViewProps) {
  const visibleAxes = RESULT_AXIS_ORDER.filter((axis) => (result.tags[axis]?.length ?? 0) > 0);

  return (
    <section className="onboard-section" aria-label="취향 분석 결과">
      <div className="onboard-card">
        <div className="onboard-result__head">
          <h2 className="onboard-result__title">이렇게 이해했어요</h2>
          <p className="onboard-result__sub">
            {displayName ? `${displayName}님이 알려주신 내용을` : "알려주신 내용을"} AI가 이렇게
            정리했어요. 다르면 다시 입력해도 괜찮아요.
          </p>
        </div>

        {result.fallback_used && (
          <p className="onboard-result__fallback">
            간편 분석 모드로 정리했어요. 칩으로 골라주신 취향은 그대로 반영됐어요.
          </p>
        )}

        {visibleAxes.length === 0 && (
          <p className="onboard-notice">
            아직 뚜렷하게 읽어낸 취향이 없어요. 조금 더 자세히 적거나 키워드를 선택해보세요.
          </p>
        )}

        {visibleAxes.map((axis) => (
          <div className="onboard-axis-group" key={axis}>
            <span className="onboard-axis-group__label">{axisLabels[axis] ?? axis}</span>
            <div className="onboard-tag-row">
              {result.tags[axis]!.map((tag) => (
                <span
                  key={tag.value}
                  className={`onboard-tag${tag.confidence < LOW_CONFIDENCE_THRESHOLD ? " onboard-tag--low-confidence" : ""}`}
                >
                  #{tag.label}
                </span>
              ))}
            </div>
          </div>
        ))}

        <div className="onboard-result__actions">
          {/* PRD §4-1-③ — "코스 짜러 가기"(/course)를 1순위 주 CTA로, "마이페이지로"(/mypage)를
              2순위 보조 CTA로 둔다. 보조 CTA는 /regions에서 확립한 2차 CTA 톤(.btn--outline,
              "화면당 주요 CTA 하나" 원칙)을 그대로 재사용한다(신규 스타일 없음). */}
          <button type="button" className="btn btn--mint btn--block btn--lg" onClick={onConfirm}>
            코스 짜러 가기
          </button>
          <button
            type="button"
            className="btn btn--outline btn--block btn--lg"
            onClick={onGoMypage}
          >
            마이페이지로
          </button>
          <button type="button" className="btn btn--ghost-text" onClick={onEdit}>
            다시 입력할게요
          </button>
        </div>
      </div>
    </section>
  );
}
