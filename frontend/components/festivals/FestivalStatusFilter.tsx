export type FestivalStatusValue = "all" | "ongoing" | "upcoming";

const STATUS_META: { value: FestivalStatusValue; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "ongoing", label: "진행중" },
  { value: "upcoming", label: "예정" },
];

interface FestivalStatusFilterProps {
  selected: FestivalStatusValue;
  onSelect: (value: FestivalStatusValue) => void;
}

/**
 * §27 필터 ③ 진행중/예정/전체 — 클라이언트 전용 필터(서버 재요청 없음). 서버가 이미
 * "진행중(종료임박순) 먼저 → 예정(시작일순)"으로 정렬해 내려주므로, `festival.ongoing` 값만
 * 그대로 신뢰해 나눈다(FestivalBanner.computeBadge와 동일하게 값을 재판정하지 않는다).
 * SpotTypeFilter와 동일한 filter-chip 스타일을 재사용한다.
 */
export default function FestivalStatusFilter({ selected, onSelect }: FestivalStatusFilterProps) {
  return (
    <div className="spot-category-row" role="group" aria-label="진행 상태 필터">
      <span className="dest-search__quick-label">진행 상태</span>
      <div className="chip-row">
        {STATUS_META.map((s) => (
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
    </div>
  );
}
