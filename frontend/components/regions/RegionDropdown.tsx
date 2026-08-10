"use client";

import { useEffect, useId, useRef, useState } from "react";
import { SidoRegion } from "./constants";

interface RegionDropdownProps {
  /** 목록 — 호출부가 SIDO_REGIONS를 그대로 넘긴다(코드를 지어내지 않음). */
  options: SidoRegion[];
  /** 현재 선택된 항목의 regionCode(sigungu_cd). 목록에 없는 값(예: 자유 검색으로 고른 지역)이면
   *  null을 넘긴다 — 목록에서 체크 표시는 빠지고, 트리거 라벨은 호출부가 별도로 계산해 넘긴다. */
  selectedCode: string | null;
  /** 트리거 버튼에 보일 텍스트. 미매칭 시 폴백 라벨 계산은 호출부 책임(이 컴포넌트는 지어내지 않음). */
  triggerLabel: string;
  onSelect: (option: SidoRegion) => void;
  /** 패널의 스크린리더 라벨. 기본값 "지역 선택". */
  ariaLabel?: string;
}

/**
 * 재사용 가능한 지역 드롭다운(03-design-spec.md §42, 대표 지시: "지역 선택은 클릭하면
 * 지역들이 팝업으로 밑으로 쫙 뜨는 형식"). 트리거를 클릭하면 바로 아래로 목록(listbox)이 펼쳐진다.
 *
 * Header.tsx의 GNB 드롭다운(hover/focus 트리거)과 달리 이건 클릭으로만 열린다 — 그래서 Header.tsx가
 * 필요로 했던 escDismissedRef("Esc로 닫은 직후 포커스가 되돌아오며 다시 열어버리는 문제") 자체가
 * 구조적으로 발생하지 않는다: 트리거에 포커스가 돌아와도 onFocus로 열지 않으므로, Esc로 닫고
 * 포커스를 트리거로 복귀시켜도 재오픈되지 않는다.
 *
 * ui-ux-pro-max ux 도메인에 "dropdown select region"·"listbox accessibility"·"select menu
 * combobox"로 조회했으나 DB 매치 0건(공지: 폴백) — 대신 WAI-ARIA APG의 listbox 패턴(트리거
 * aria-haspopup="listbox"/aria-expanded, 패널 role="listbox"+항목 role="option", Esc 닫기+포커스
 * 복귀, 바깥 클릭 닫힘, 44px 터치 타겟)을 따랐고, 이미 코드베이스의 RegionPicker.tsx
 * (dest-search__dropdown)가 같은 리스트박스 CSS 레시피를 쓰고 있어 시각적 일관성도 있다.
 */
export default function RegionDropdown({
  options,
  selectedCode,
  triggerLabel,
  onSelect,
  ariaLabel = "지역 선택",
}: RegionDropdownProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  // 바깥 클릭 시 닫힘.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  // Esc로 닫고 트리거로 포커스 복귀.
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  return (
    <div className="region-dropdown" ref={containerRef}>
      <button
        type="button"
        ref={triggerRef}
        className={`region-dropdown__trigger${open ? " is-open" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
      >
        <svg
          className="region-dropdown__pin"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            fillRule="evenodd"
            clipRule="evenodd"
            d="M12 2C7.58 2 4 5.58 4 10c0 5.25 6.72 11.34 7.06 11.64a1.5 1.5 0 0 0 1.88 0C13.28 21.34 20 15.25 20 10c0-4.42-3.58-8-8-8zm0 11a3 3 0 1 1 0-6 3 3 0 0 1 0 6z"
            fill="currentColor"
          />
        </svg>
        <span>{triggerLabel}</span>
        <span className="region-dropdown__chevron" aria-hidden="true" />
      </button>

      {open && (
        <ul id={panelId} className="region-dropdown__panel" role="listbox" aria-label={ariaLabel}>
          {options.map((sido) => {
            const active = sido.regionCode === selectedCode;
            return (
              <li key={sido.sidoCode} role="option" aria-selected={active}>
                <button
                  type="button"
                  className={`region-dropdown__item${active ? " is-active" : ""}`}
                  aria-current={active ? "true" : undefined}
                  onClick={() => {
                    onSelect(sido);
                    setOpen(false);
                    triggerRef.current?.focus();
                  }}
                >
                  <span>{sido.shortName}</span>
                  {active && (
                    <svg
                      className="region-dropdown__check"
                      width="16"
                      height="16"
                      viewBox="0 0 24 24"
                      aria-hidden="true"
                    >
                      <path
                        d="M5 13l4 4L19 7"
                        stroke="currentColor"
                        strokeWidth="2.4"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        fill="none"
                      />
                    </svg>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
