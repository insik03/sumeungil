import Link from "next/link";
import { TagSchemaAxis } from "../../lib/api";

const TEXT_MAX_LENGTH = 300; // §B.1 — 서버가 300자 초과분을 절단. 프론트도 같은 상한을 안내.
const CHIP_SKELETON_AXES = 3;
const CHIP_SKELETON_PER_AXIS = 4;

export type SchemaStatus = "loading" | "success" | "unavailable" | "error";

interface OnboardingFormProps {
  text: string;
  onTextChange: (value: string) => void;
  /** 자유 서술 사용 동의(체크). true 여야 입력 칸이 열린다. */
  consent: boolean;
  onConsentChange: (checked: boolean) => void;
  schemaStatus: SchemaStatus;
  axes: TagSchemaAxis[];
  selected: Record<string, Set<string>>;
  onToggleChip: (axis: TagSchemaAxis, value: string) => void;
  onSubmit: () => void;
  canSubmit: boolean;
  validationMessage: string | null;
  onRetrySchema: () => void;
}

/**
 * 온보딩 1단계 입력 화면. 칩 목록은 반드시 tag-schema 응답(axes)에서만 구성한다(하드코딩 금지, §B.5-1).
 * 칩 값은 영문 코드(value)로 선택 상태를 관리하고, 제출 시에도 value 배열로만 보낸다(§B.1).
 */
export default function OnboardingForm({
  text,
  onTextChange,
  consent,
  onConsentChange,
  schemaStatus,
  axes,
  selected,
  onToggleChip,
  onSubmit,
  canSubmit,
  validationMessage,
  onRetrySchema,
}: OnboardingFormProps) {
  return (
    <section className="onboard-section" aria-label="여행 취향 입력">
      <div className="onboard-card">
        <span className="onboard-label">어떤 여행을 꿈꾸시나요?</span>
        <p className="onboard-hint">
          아래 키워드만 골라도 돼요. 내 상황을 직접 적고 싶다면(예: 휠체어 이용, 아이 동반) 자유 서술을 켜 주세요.
        </p>
        {/* 2026-09-20 — 자유 서술은 선택. 동의해야 입력 칸이 열린다(동의 없이는 문장이 저장·전송되지 않는다). */}
        <label className="consent-check">
          <input type="checkbox" checked={consent} onChange={(e) => onConsentChange(e.target.checked)} />
          <span>
            <strong>[선택] 자유 서술로 직접 적기.</strong> 취향 분석은 서비스 서버에서만 처리되고, AI 코스 생성을
            요청하면 입력한 문장이 <strong>Google LLC(미국 등 해외)의 Gemini로 전송</strong>되는 것에 동의합니다.
            이름·연락처·주소는 적지 마세요. <Link href="/privacy">자세히</Link>
          </span>
        </label>
        {consent && (
          <>
            <textarea
              id="onboardText"
              className="onboard-textarea"
              aria-label="자유 서술"
              placeholder="예: 6세 아이랑 반려견이 함께 걷기 편하고 주차 넉넉한 곳"
              value={text}
              maxLength={TEXT_MAX_LENGTH}
              onChange={(e) => onTextChange(e.target.value)}
            />
            <div className="onboard-textarea__count" aria-live="off">
              {text.length}/{TEXT_MAX_LENGTH}
            </div>
          </>
        )}

        {schemaStatus === "loading" &&
          Array.from({ length: CHIP_SKELETON_AXES }).map((_, i) => (
            <div className="onboard-axis" key={i} aria-hidden="true">
              <div className="skeleton-bar" style={{ width: "72px", height: "12px", marginBottom: "10px" }} />
              <div className="onboard-axis__chips">
                {Array.from({ length: CHIP_SKELETON_PER_AXIS }).map((_, j) => (
                  <div
                    key={j}
                    className="skeleton-bar"
                    style={{ width: "76px", height: "40px", borderRadius: "999px" }}
                  />
                ))}
              </div>
            </div>
          ))}

        {schemaStatus === "success" &&
          axes.map((axis) => (
            <div className="onboard-axis" key={axis.axis}>
              <span className="onboard-axis__label">
                #{axis.label}
                {axis.select === "multi" ? " · 복수 선택" : ""}
              </span>
              <div className="onboard-axis__chips" role="group" aria-label={axis.label}>
                {axis.chips.map((chip) => {
                  const isSelected = selected[axis.axis]?.has(chip.value) ?? false;
                  return (
                    <button
                      key={chip.value}
                      type="button"
                      className={`onboard-chip${isSelected ? " is-selected" : ""}`}
                      aria-pressed={isSelected}
                      onClick={() => onToggleChip(axis, chip.value)}
                    >
                      #{chip.label}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}

        {(schemaStatus === "unavailable" || schemaStatus === "error") && (
          <div className="onboard-axis">
            <p className="onboard-notice">
              {schemaStatus === "unavailable"
                ? "빠른 키워드 선택 기능을 준비 중이에요. 자유 서술(선택 동의)로도 분석할 수 있어요."
                : "키워드 목록을 불러오지 못했어요. 자유 서술(선택 동의)로 진행하거나 다시 시도해주세요."}
            </p>
            {schemaStatus === "error" && (
              <button type="button" className="btn btn--ghost-text" onClick={onRetrySchema}>
                키워드 다시 불러오기
              </button>
            )}
          </div>
        )}

        <div className="onboard-submit">
          <button
            type="button"
            className="btn btn--coral btn--block btn--lg"
            onClick={onSubmit}
            disabled={!canSubmit}
          >
            취향 분석하기
          </button>
          {!canSubmit && !validationMessage && (
            <p className="onboard-hint">
              키워드를 고르거나, 자유 서술에 동의하고 내용을 적으면 분석할 수 있어요.
            </p>
          )}
          {validationMessage && <p className="onboard-validation" role="alert">{validationMessage}</p>}
        </div>
      </div>
    </section>
  );
}
