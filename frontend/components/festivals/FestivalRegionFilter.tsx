"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, RegionSearchItem, fetchRegionSearch } from "../../lib/api";
import { QUICK_REGIONS, QuickRegionChip } from "../recommend/constants";
import ChipScrollRow from "../ChipScrollRow";

export interface FestivalRegion {
  sigunguCd: string;
  label: string;
}

interface FestivalRegionFilterProps {
  /** null = 전국(지역 필터 없음, 페이지 기본값). §27 요구사항: "전국=기본". */
  selected: FestivalRegion | null;
  onSelect: (region: FestivalRegion | null) => void;
}

function isEndpointMissing(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 0);
}

const SEARCH_DEBOUNCE_MS = 200;

/**
 * §27(03-design-spec.md, /festivals) — RegionPicker.tsx(components/recommend/)의 검색 combobox +
 * 자주 찾는 지역 칩 "패턴"을 재사용하되 별도 컴포넌트로 새로 짰다(직접 import하지 않음).
 * 이유: RegionPicker는 recommend 화면 전용으로 (a) 지역이 항상 필수 선택 상태(전국 개념 없음),
 * (b) 상태 문구가 "OO 추천을 보고 있어요"로 recommend 맥락에 고정돼 있다 — 지시서가 명시한
 * "전국=기본" 요구를 그 컴포넌트에 억지로 얹으면 recommend 화면까지 건드리게 되어(불변 원칙 밖의
 * 파일 변경 위험) 패턴만 이식한 새 컴포넌트로 분리했다. 코드 값(sigungu_cd 등)은 RegionPicker와
 * 동일하게 /regions/search 응답에서만 가져온다 — 프론트가 지어내지 않는다.
 *
 * §30(03-design-spec.md, 2026-07-29) — QUICK_REGIONS(recommend/constants.ts)가 4개→17개(시도
 * 1곳씩)로 확장되면서 이 컴포넌트가 공유해 쓰던 칩도 자동으로 17개가 됐다. 예전 방식(칩마다
 * /regions/search 사전조회)을 그대로 뒀다면 17회 왕복이 되어 §30이 recommend 쪽에서 없앤 낭비가
 * 여기서 되살아난다 — 그래서 RegionPicker.tsx와 동일하게 이 컴포넌트도 사전조회를 없애고
 * QUICK_REGIONS가 이미 들고 있는 검증된 sigunguCd를 직접 선택한다(이 파일은 지시서의 명시적
 * 수정 대상은 아니지만, 공유 상수 변경의 직접 결과로 깨지는 걸 막기 위한 최소 동형 수정이다).
 */
export default function FestivalRegionFilter({ selected, onSelect }: FestivalRegionFilterProps) {
  const [query, setQuery] = useState("");
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [searchStatus, setSearchStatus] = useState<"idle" | "loading" | "success" | "error">(
    "idle"
  );
  const [searchResults, setSearchResults] = useState<RegionSearchItem[]>([]);
  const [searchErrorMsg, setSearchErrorMsg] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const q = query.trim();
    if (q.length === 0) {
      setSearchStatus("idle");
      setSearchResults([]);
      return;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => {
      setSearchStatus("loading");
      setSearchErrorMsg(null);
      fetchRegionSearch(q, 8, controller.signal)
        .then((res) => {
          setSearchResults(res.items);
          setSearchStatus("success");
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          setSearchResults([]);
          setSearchStatus("error");
          setSearchErrorMsg(
            isEndpointMissing(err)
              ? "검색 기능 준비 중이에요. 아래 추천 지역을 이용해주세요."
              : err instanceof ApiError
              ? err.message
              : "지역 검색에 실패했습니다."
          );
        });
    }, SEARCH_DEBOUNCE_MS);

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [query]);

  const selectRegion = (item: RegionSearchItem, label: string) => {
    setQuery(label);
    setDropdownOpen(false);
    onSelect({ sigunguCd: item.sigungu_cd, label: item.label });
  };

  // §30 — 칩 선택 경로. QUICK_REGIONS의 검증된 sigunguCd를 그대로 onSelect에 넘긴다(검색 API 왕복 없음).
  const selectQuickRegion = (r: QuickRegionChip) => {
    setQuery(r.label);
    setDropdownOpen(false);
    onSelect({ sigunguCd: r.sigunguCd, label: r.label });
  };

  const selectNationwide = () => {
    setQuery("");
    setDropdownOpen(false);
    setSearchResults([]);
    setSearchStatus("idle");
    onSelect(null);
  };

  const clearQuery = () => {
    setQuery("");
    setDropdownOpen(false);
    setSearchResults([]);
    setSearchStatus("idle");
  };

  const isChipActive = (r: QuickRegionChip) => !!selected && r.sigunguCd === selected.sigunguCd;

  return (
    <div className="spot-region-row">
      <span className="dest-search__quick-label">지역 선택</span>

      <div className="dest-search__box">
        <svg className="dest-search__icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2.2" />
          <path d="M20 20l-3.5-3.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
        </svg>
        <input
          ref={inputRef}
          type="text"
          id="festivalRegionSearchInput"
          className="dest-search__input"
          placeholder="전국 지역 이름으로 검색 (예: 제주, 여수)"
          role="combobox"
          aria-expanded={dropdownOpen}
          aria-autocomplete="list"
          aria-controls="festivalRegionSearchListbox"
          autoComplete="off"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setDropdownOpen(true);
          }}
          onFocus={() => {
            if (query.trim().length > 0) setDropdownOpen(true);
          }}
          onBlur={() => {
            setTimeout(() => setDropdownOpen(false), 120);
          }}
        />
        {query && (
          <button
            type="button"
            className="dest-search__clear"
            aria-label="지역 검색어 지우기"
            onClick={clearQuery}
          >
            &times;
          </button>
        )}
      </div>

      {dropdownOpen && query.trim().length > 0 && (
        <ul
          className="dest-search__dropdown"
          id="festivalRegionSearchListbox"
          role="listbox"
          aria-label="지역 검색 결과"
        >
          {searchStatus === "loading" && (
            <li className="dest-search__dropdown-empty" aria-live="polite">
              검색 중…
            </li>
          )}
          {searchStatus === "success" && searchResults.length === 0 && (
            <li className="dest-search__dropdown-empty">
              &quot;{query}&quot; 검색 결과가 없어요. 다른 지역명으로 시도해보세요.
            </li>
          )}
          {searchStatus === "success" &&
            searchResults.map((item) => (
              <li
                key={item.region_id}
                role="option"
                aria-selected={selected?.sigunguCd === item.sigungu_cd}
              >
                <button
                  type="button"
                  className="dest-search__dropdown-item"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => selectRegion(item, item.label)}
                >
                  {item.label}
                </button>
              </li>
            ))}
          {searchStatus === "error" && (
            <li className="dest-search__dropdown-empty" role="alert">
              {searchErrorMsg ?? "지역 검색에 실패했습니다."}
            </li>
          )}
        </ul>
      )}

      <span className="dest-search__quick-label spot-region-row__quick-label">지역 바로가기</span>
      <ChipScrollRow>
        <button
          type="button"
          className={`chip chip--all${selected === null ? " is-active" : ""}`}
          aria-pressed={selected === null}
          onClick={selectNationwide}
        >
          전국
        </button>
        {QUICK_REGIONS.map((r) => {
          const active = isChipActive(r);
          return (
            <button
              key={r.sigunguCd}
              type="button"
              className={`chip chip--all${active ? " is-active" : ""}`}
              aria-pressed={active}
              title={r.label}
              onClick={() => selectQuickRegion(r)}
            >
              {r.name}
            </button>
          );
        })}
      </ChipScrollRow>
      <p className="dest-search__status" aria-live="polite">
        {selected ? `${selected.label} 축제만 보고 있어요` : "전국 축제를 보고 있어요"}
      </p>
    </div>
  );
}
