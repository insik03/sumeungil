import { SpotCategory } from "../../lib/api";
import { CATEGORY_META } from "./constants";

interface CategoryFilterProps {
  selected: SpotCategory | null;
  onSelect: (category: SpotCategory | null) => void;
}

/** §C.2.1 카테고리 enum 필터. null = 전체(카테고리 파라미터 생략). */
export default function CategoryFilter({ selected, onSelect }: CategoryFilterProps) {
  return (
    <div className="spot-category-row" role="group" aria-label="카테고리 필터">
      <span className="dest-search__quick-label">카테고리</span>
      <div className="chip-row">
        <button
          type="button"
          className={`filter-chip${selected === null ? " is-selected" : ""}`}
          aria-pressed={selected === null}
          onClick={() => onSelect(null)}
        >
          전체
        </button>
        {CATEGORY_META.map((c) => (
          <button
            key={c.value}
            type="button"
            className={`filter-chip${selected === c.value ? " is-selected" : ""}`}
            aria-pressed={selected === c.value}
            onClick={() => onSelect(c.value)}
          >
            {c.label}
          </button>
        ))}
      </div>
    </div>
  );
}
