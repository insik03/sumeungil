"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, RegionSearchItem, fetchRegionSearch } from "../../lib/api";
import { useHotRegions } from "../../lib/useHotRegions";
import { QUICK_REGIONS, QuickRegionChip } from "./constants";
import ChipScrollRow from "../ChipScrollRow";

export interface SelectedRegion {
  sigunguCd: string;
  label: string;
}

interface RegionPickerProps {
  selected: SelectedRegion;
  onSelect: (region: SelectedRegion) => void;
}

function isEndpointMissing(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 0);
}

const SEARCH_DEBOUNCE_MS = 200;

/**
 * 지역 선택 UI. 전국 검색(Hero.tsx의 목적지 검색 combobox와 동일 패턴 이식) + 자주 찾는 지역 칩.
 * §30(03-design-spec.md, 2026-07-29) — 칩을 4개(경주·전주·강릉·부산)에서 17개(시도 1곳씩)로
 * 확장하면서, 예전처럼 칩마다 /regions/search를 사전조회(prefetch)하던 방식은 왕복이 4→17회로
 * 늘어 낭비다. QUICK_REGIONS(recommend/constants.ts)가 이미 components/regions/constants.ts의
 * 검증된 SIDO_REGIONS에서 뽑은 region_code를 들고 있으므로, 칩은 검색 API 없이 그 코드를 바로
 * 선택한다(자유 텍스트 검색창만 계속 /regions/search를 쓴다). 코드 값은 여전히 프론트가 지어내지
 * 않는다 — SIDO_REGIONS가 이미 검증한 값을 그대로 옮겨 쓸 뿐이다.
 */
export default function RegionPicker({ selected, onSelect }: RegionPickerProps) {
  // 전국 지역 검색(Hero.tsx §A.3 패턴 이식) — 17개 칩 밖의 지역도 고를 수 있게 한다.
  const [query, setQuery] = useState("");
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [searchStatus, setSearchStatus] = useState<"idle" | "loading" | "success" | "error">(
    "idle"
  );
  const [searchResults, setSearchResults] = useState<RegionSearchItem[]>([]);
  const [searchErrorMsg, setSearchErrorMsg] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // 2026-09-20 대표 지시 — "자주 찾는 지역"을 고정 17개가 아니라 **지금 사람들이 많이 찾는 지역**으로.
  // 순위 계산은 useHotRegions 가 맡는다(홈 Hero 와 같은 훅 — 두 화면의 순서가 갈리지 않게).
  const hotRegions = useHotRegions();
  const quickRegions: QuickRegionChip[] = hotRegions
    ? hotRegions.map((h) => ({ name: h.shortName, sigunguCd: h.regionCode, label: h.basisLabel ?? h.shortName }))
    : QUICK_REGIONS;

  // 검색창 타이핑 디바운스(200ms) → /regions/search 호출. Hero.tsx §A.3와 동일 패턴.
  // §30 — 칩은 더 이상 이 API를 사전조회하지 않으므로, 이 효과는 순수하게 자유 텍스트 검색만 맡는다.
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

  // §30 — 칩은 SIDO_REGIONS의 검증된 sigunguCd를 직접 들고 있어 검색 API 응답과 무관하게 비교한다.
  const isChipActive = (r: QuickRegionChip) => r.sigunguCd === selected.sigunguCd;

  // 검색 결과 선택 경로. Hero.tsx의 selectRegion과 동일하게 입력창 값도 함께 맞춰 현재 선택 지역이
  // 항상 입력창에 보이게 한다.
  const selectRegion = (item: RegionSearchItem, label: string) => {
    setQuery(label);
    setDropdownOpen(false);
    onSelect({ sigunguCd: item.sigungu_cd, label: item.label });
  };

  // §30 — 칩 선택 경로. SIDO_REGIONS에서 이미 검증된 코드를 그대로 onSelect에 넘긴다(검색 API 왕복 없음).
  const selectQuickRegion = (r: QuickRegionChip) => {
    setQuery(r.label);
    setDropdownOpen(false);
    onSelect({ sigunguCd: r.sigunguCd, label: r.label });
  };

  const clearQuery = () => {
    setQuery("");
    setDropdownOpen(false);
    setSearchResults([]);
    setSearchStatus("idle");
  };

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
          id="regionSearchInput"
          className="dest-search__input"
          placeholder="전국 지역 이름으로 검색 (예: 제주, 여수)"
          role="combobox"
          aria-expanded={dropdownOpen}
          aria-autocomplete="list"
          aria-controls="regionSearchListbox"
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
            // 드롭다운 항목 클릭(mousedown)이 blur보다 먼저 처리되도록 살짝 지연
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
        <ul className="dest-search__dropdown" id="regionSearchListbox" role="listbox" aria-label="지역 검색 결과">
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
              <li key={item.region_id} role="option" aria-selected={item.sigungu_cd === selected.sigunguCd}>
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

      <span className="dest-search__quick-label spot-region-row__quick-label">
        {hotRegions ? "지금 많이 찾는 지역 · 예상 방문 집중도 높은 순" : "자주 찾는 지역"}
      </span>
      <ChipScrollRow>
        {quickRegions.map((r) => {
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
        {selected.label} 추천을 보고 있어요
      </p>
    </div>
  );
}
