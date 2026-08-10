"use client";

import { KeyboardEvent, useState } from "react";

/** RatingBadge.tsx와 같은 별 path(이모지 대신 인라인 SVG, 사이트 전역 관례)를 크게 그린 버전. */
function StarIcon() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M12 3.5l2.47 5.06 5.58.74-4.06 3.9.99 5.55L12 16.9l-4.98 2.85.99-5.55-4.06-3.9 5.58-.74L12 3.5z"
        fill="currentColor"
      />
    </svg>
  );
}

interface StarRatingInputProps {
  /** 0 = 아직 선택 안 함(제출 막음). 1~5 = 선택된 별점. */
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
  /** 필드 자체의 접근성 이름. 후기 작성/수정 폼에서 문구를 다르게 줄 수 있다. */
  label?: string;
}

/**
 * §41(신규) — 별점 선택 입력. ARIA APG "Radio Group" 패턴(roving tabindex)으로 구현한 접근 가능한
 * 라디오 그룹이다 — 네이티브 `<input type="radio">` 5개 대신 `role="radio"` 버튼 5개를 쓴 이유는
 * 별 모양 아이콘이 라디오 점보다 큰 히트영역(--touch-min)을 가져야 해서다(터치 타겟 크기 원칙).
 * 방향키(←/→, ↓/↑)로 이동, 클릭/Enter/Space로 선택 — 탭은 그룹당 1개 정지점만 갖는다(roving
 * tabIndex). 마우스 호버 시 미리보기(hoverValue)만 보여주고 실제 선택(onChange)은 클릭 시에만
 * 일어난다 — 미리보기와 실제 선택을 착각하지 않게 구분한다.
 */
export default function StarRatingInput({
  value,
  onChange,
  disabled,
  label = "별점 선택 (1점에서 5점)",
}: StarRatingInputProps) {
  const [hoverValue, setHoverValue] = useState<number | null>(null);
  const displayValue = hoverValue ?? value;
  const stars = [1, 2, 3, 4, 5];

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    const current = value || 0;
    if (e.key === "ArrowRight" || e.key === "ArrowUp") {
      e.preventDefault();
      onChange(Math.min(5, current + 1 || 1));
    } else if (e.key === "ArrowLeft" || e.key === "ArrowDown") {
      e.preventDefault();
      onChange(Math.max(1, current - 1 || 1));
    } else if (e.key === "Home") {
      e.preventDefault();
      onChange(1);
    } else if (e.key === "End") {
      e.preventDefault();
      onChange(5);
    }
  };

  return (
    <div
      className="star-rating-input"
      role="radiogroup"
      aria-label={label}
      onKeyDown={handleKeyDown}
      onMouseLeave={() => setHoverValue(null)}
    >
      {stars.map((n) => {
        const selected = value === n;
        // 탭 정지점은 선택된 별(없으면 1번) 하나뿐 — roving tabIndex.
        const isTabStop = value > 0 ? selected : n === 1;
        return (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={`${n}점`}
            tabIndex={isTabStop ? 0 : -1}
            disabled={disabled}
            className={`star-rating-input__star${n <= displayValue ? " is-filled" : ""}`}
            onClick={() => onChange(n)}
            onMouseEnter={() => setHoverValue(n)}
          >
            <StarIcon />
          </button>
        );
      })}
    </div>
  );
}
