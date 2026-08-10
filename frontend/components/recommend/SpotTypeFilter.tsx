import { SPOT_TYPE_META, SpotTypeFilterValue } from "./constants";

interface SpotTypeFilterProps {
  selected: SpotTypeFilterValue;
  onSelect: (value: SpotTypeFilterValue) => void;
}

/**
 * 유형 필터(신규) — 전체/숨은 명소/인기 명소. CategoryFilter와 동일한 filter-chip 스타일을 재사용한다.
 * `spot_type` 파라미터로 backend에 그대로 전달한다 — is_hidden_gem 재판정은 하지 않는다.
 */
export default function SpotTypeFilter({ selected, onSelect }: SpotTypeFilterProps) {
  return (
    <div className="spot-category-row" role="group" aria-label="유형 필터">
      <span className="dest-search__quick-label">유형</span>
      <div className="chip-row">
        {SPOT_TYPE_META.map((t) => (
          <button
            key={t.value}
            type="button"
            className={`filter-chip${selected === t.value ? " is-selected" : ""}`}
            aria-pressed={selected === t.value}
            onClick={() => onSelect(t.value)}
          >
            {t.label}
          </button>
        ))}
      </div>
    </div>
  );
}
