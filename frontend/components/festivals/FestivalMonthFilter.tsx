"use client";

import { useEffect, useState } from "react";

export interface MonthOption {
  /** "YYYY-MM" — 서버 계약(month 파라미터) 형식 그대로. */
  value: string;
  label: string;
}

const MONTH_COUNT = 8; // §27 지시 범위(6~12개월) 중간값.

/** 이번달부터 count개월 옵션을 만든다. 연도가 바뀌는 달은 "M월(YYYY)"로 표기해 혼동을 막는다. */
export function buildMonthOptions(count = MONTH_COUNT, base = new Date()): MonthOption[] {
  const startYear = base.getFullYear();
  const options: MonthOption[] = [];
  for (let i = 0; i < count; i++) {
    const d = new Date(base.getFullYear(), base.getMonth() + i, 1);
    const y = d.getFullYear();
    const m = d.getMonth() + 1;
    options.push({
      value: `${y}-${String(m).padStart(2, "0")}`,
      label: y === startYear ? `${m}월` : `${m}월(${y})`,
    });
  }
  return options;
}

interface FestivalMonthFilterProps {
  /** null = 전체 기간(기본값, window_days=90). */
  selected: string | null;
  onSelect: (month: string | null) => void;
}

/**
 * §27 필터 ② 월 선택 — 이번달부터 6~12개월 칩. "전체 기간"이 기본(month 파라미터 미전송,
 * window_days=90 유지)이고, 특정 달을 고르면 호출부(FestivalsContent)가 month + window_days=365로
 * 다시 요청한다(가을 축제처럼 먼 시점도 놓치지 않기 위함 — §27 지시 근거).
 *
 * 월 목록은 "오늘" 기준이라 서버·클라이언트 렌더 시점이 달(주로 자정 근처)라져 하이드레이션 경고가
 * 날 수 있다 — RegionPicker의 isDesktop(matchMedia) 패턴과 동일하게 mount 이후에만 채운다
 * (첫 렌더는 "전체 기간" 칩만 보이고, 곧바로 나머지 칩이 붙는다).
 */
export default function FestivalMonthFilter({ selected, onSelect }: FestivalMonthFilterProps) {
  const [months, setMonths] = useState<MonthOption[]>([]);

  useEffect(() => {
    setMonths(buildMonthOptions());
  }, []);

  return (
    <div className="spot-category-row" role="group" aria-label="월 선택">
      <span className="dest-search__quick-label">월 선택</span>
      <div className="chip-row">
        <button
          type="button"
          className={`filter-chip${selected === null ? " is-selected" : ""}`}
          aria-pressed={selected === null}
          onClick={() => onSelect(null)}
        >
          전체 기간
        </button>
        {months.map((m) => (
          <button
            key={m.value}
            type="button"
            className={`filter-chip${selected === m.value ? " is-selected" : ""}`}
            aria-pressed={selected === m.value}
            onClick={() => onSelect(m.value)}
          >
            {m.label}
          </button>
        ))}
      </div>
    </div>
  );
}
