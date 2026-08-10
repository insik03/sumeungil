import { SORT_META, SortOption } from "./constants";

interface SortControlProps {
  selected: SortOption;
  onSelect: (value: SortOption) => void;
  /** "위치 권한이 필요해요" 등 거리순 선택 실패 안내. null이면 표시 안 함. */
  locationNotice: string | null;
}

/**
 * 정렬 선택(신규) — CategoryFilter/SpotTypeFilter와 동일한 filter-chip 스타일 재사용.
 * "거리순"의 geolocation 권한 처리·재정렬 로직은 호출부(RecommendContent)가 담당한다 —
 * 이 컴포넌트는 선택 UI와 위치 권한 안내 문구만 그린다.
 */
export default function SortControl({ selected, onSelect, locationNotice }: SortControlProps) {
  return (
    <div className="spot-category-row" role="group" aria-label="정렬">
      <span className="dest-search__quick-label">정렬</span>
      <div className="chip-row">
        {SORT_META.map((s) => (
          <button
            key={s.value}
            type="button"
            className={`filter-chip${selected === s.value ? " is-selected" : ""}`}
            aria-pressed={selected === s.value}
            onClick={() => onSelect(s.value)}
          >
            {s.label}
          </button>
        ))}
      </div>
      {locationNotice && (
        <p className="dest-search__notice" role="alert">
          {locationNotice}
        </p>
      )}
    </div>
  );
}
