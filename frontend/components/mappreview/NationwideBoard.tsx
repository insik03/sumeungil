"use client";

import { NationwideCongestionItem } from "../../lib/api";
import { LANDMARKS } from "./landmarks";
import { LEVEL_TEXT } from "./shared";

/** 레벨 → 기존 전광판과 **같은 배지 클래스**(BoardCard.tsx 매핑을 그대로 따른다). */
const BADGE: Record<string, string> = {
  high: "badge--hot",
  mid: "badge--mid",
  low: "badge--calm",
  none: "badge--unknown",
};

/**
 * 부록 U.3(2026-08-01, 대표 지시) — 지역을 **고르기 전** 기본 현황판.
 *
 * 특정 지역 전광판 대신 **지도에 떠 있는 시·도(랜드마크) 전체의 예상 혼잡도**를 나열한다.
 * "처음 들어오면 전국이 한눈에, 지역을 고르면 그 지역만" 이라는 흐름을 맞추기 위한 것.
 *
 * 카드 마크업은 기존 `BoardCard` 의 클래스를 그대로 써서 두 모드의 생김새가 어긋나지 않게 했다.
 * 정렬은 **붐비는 순**이다(순위가 곧 정보인 화면). 데이터 없는 지역은 뒤로 보내고 "정보없음"으로
 * 표기한다 — 0% 로 적어 한산한 척하지 않는다.
 *
 * §47.4(신규, 03-design-spec.md, 2026-08-20) — `/congestion`에서 지도(KoreaSvgMap)를 없애고
 * 이 보드를 지역 선택 자리로 승격하면서 `selected` prop을 추가했다. 일치하는 카드에
 * `is-active`를 얹어 현재 선택된 시·도를 시각적으로 표시한다(선택 없으면 전부 비활성).
 */
export default function NationwideBoard({
  items,
  selected,
  onSelect,
}: {
  items: NationwideCongestionItem[];
  selected?: string | null;
  onSelect: (sidoCode: string) => void;
}) {
  const ordered = [...items].sort((a, b) => {
    if (a.available !== b.available) return a.available ? -1 : 1;
    return (b.index ?? -1) - (a.index ?? -1);
  });

  const cards = ordered.map((it, idx) => {
    const key = it.available ? it.level ?? "none" : "none";
    const lm = LANDMARKS[it.sido_code];
    return (
      <button
        key={`${it.sido_code}-${idx}`}
        type="button"
        className={`board-card board-card--clickable${it.sido_code === selected ? " is-active" : ""}`}
        onClick={() => onSelect(it.sido_code)}
        aria-pressed={it.sido_code === selected}
        aria-label={`${it.short_name} ${
          it.available ? `${LEVEL_TEXT[key]} ${Math.round(it.index ?? 0)}퍼센트` : "정보 없음"
        } — 이 지역 보기`}
      >
        {lm && (
          <img
            src={`/landmarks/${it.sido_code}.png`}
            alt=""
            width={38}
            height={38}
            style={{ alignSelf: "center" }}
          />
        )}
        <div className="board-card__name">{it.short_name}</div>
        <span className={`badge ${BADGE[key]}`}>
          <span className="badge__icon"></span>
          {LEVEL_TEXT[key]}
          {it.available ? ` ${Math.round(it.index ?? 0)}%` : ""}
        </span>
        {lm && <span className="board-card__date">{lm.name}</span>}
      </button>
    );
  });

  return (
    <div className="board-marquee" role="list" aria-label="전국 시·도 예상 혼잡도 순환 목록">
      <div
        className="board-marquee__track"
        // 카드 수에 비례해 재생 시간을 정해 개수가 달라도 흐르는 속도가 일정하다(카드당 3.2초).
        style={{ animationDuration: `${Math.max(12, ordered.length * 3.2)}s` }}
      >
        {/* 두 벌 이어 붙여야 -50% 지점에서 이음매 없이 반복된다. */}
        {cards}
        {cards.map((c, i) => (
          <div key={`dup-${i}`} aria-hidden="true">
            {c}
          </div>
        ))}
      </div>
    </div>
  );
}
