"use client";

import { SIDO_REGIONS } from "./constants";

interface SidoStripProps {
  selected: string;
  onSelect: (sidoCode: string) => void;
}

/**
 * 시도 원형 스트립(D-1 흡수, 03-design-spec.md §29). 구석구석 원본은 시도마다 별도 아이콘을
 * 쓰지만, 17개 커스텀 SVG를 새로 그리면 유지보수 부담이 크고 자칫 지역을 상투적 이미지(예:
 * 특정 랜드마크)로 단순화해 부정확할 위험이 있다 — 대신 "이니셜(짧은 시도명의 첫 글자)" +
 * 색은 선택 상태에만 부여(브랜드 그린 1색)해 "혼잡도 배지 색과 헷갈리지 않는" 안전한 조합을 쓴다.
 * 이모지는 쓰지 않는다(ui-ux-pro-max 체크리스트).
 */
export default function SidoStrip({ selected, onSelect }: SidoStripProps) {
  return (
    <nav className="region-strip" aria-label="시도 선택">
      <ul className="region-strip__list" role="list">
        {SIDO_REGIONS.map((sido) => {
          const active = sido.sidoCode === selected;
          return (
            <li key={sido.sidoCode}>
              <button
                type="button"
                className={`region-chip${active ? " is-active" : ""}`}
                aria-pressed={active}
                onClick={() => onSelect(sido.sidoCode)}
              >
                <span className="region-chip__circle" aria-hidden="true">
                  {sido.initial}
                </span>
                <span className="region-chip__label">{sido.shortName}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
