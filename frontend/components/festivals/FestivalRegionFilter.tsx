"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, RegionSearchItem, fetchRegionSearch } from "../../lib/api";
import { REGION_BLOCKS, RegionBlock } from "../regions/blocks";
import ChipScrollRow from "../ChipScrollRow";

/**
 * 선택된 지역. 2026-09-20 대표 지시로 "지역 바로가기"가 시도 17칩 → **9권역 칩**이 되면서
 * 두 가지 모양을 갖는다. 서버 필터가 서로 다른 파라미터라 어느 쪽인지 구분해 들고 있어야 한다.
 *   - 권역 칩: blockKey 로 `region_block` 을 보낸다(권역에 속한 시도 전체 축제).
 *   - 검색 선택: sigunguCd 로 `region_code` 를 보낸다(그 시군구 축제만). 검색은 그대로 둔다 —
 *     "여수 축제"처럼 좁게 보려는 동선을 권역으로 뭉개면 오히려 쓰기 어려워진다.
 */
export interface FestivalRegion {
  /** 권역 칩으로 고른 경우 REGION_BLOCKS.key, 검색으로 고른 경우 null. */
  blockKey: string | null;
  /** 검색으로 고른 시군구 코드. 권역 칩이면 null. */
  sigunguCd: string | null;
  label: string;
  /** 다른 화면에 "마지막 선택 지역"으로 넘길 대표 시군구 코드(권역이면 대표 시군구). */
  representativeCode: string;
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
 * 2026-09-20(대표 지시 "축제 지역 바로가기도 전국 N도로 묶어줘") — 시도 17칩을 **9권역 칩**으로
 * 바꿨다. 권역 정의는 새로 만들지 않고 이미 있는 REGION_BLOCKS(components/regions/blocks.ts ↔
 * backend app/regions/nationwide.py 1:1 미러)를 그대로 쓴다. 광역시를 소속 도에 흡수한 정의라
 * 한 권역이 여러 시도를 품고(경기·서울 = 11+41+28), 서버는 그 시도 전체를 훑어 축제를 준다
 * (`region_block` 파라미터). 칩마다 대표 시군구 1곳으로 좁히면 "전남·광주"를 눌렀는데 여수
 * 축제만 나오는 문제가 생겨서, 시군구 코드가 아니라 권역 key 를 보내는 게 핵심이다.
 *
 * 검색 combobox 는 그대로 둔다 — "여수 축제"처럼 좁게 보려는 동선까지 권역으로 뭉개면 오히려
 * 쓰기 어려워진다. 검색으로 고르면 종전대로 `region_code`(시군구)로 필터한다.
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
    onSelect({
      blockKey: null,
      sigunguCd: item.sigungu_cd,
      label: item.label,
      representativeCode: item.sigungu_cd,
    });
  };

  // 권역 칩 — 검증된 key 를 그대로 넘긴다(검색 API 왕복 없음). 라벨은 blocks.ts 소유.
  const selectBlock = (b: RegionBlock) => {
    setQuery("");
    setDropdownOpen(false);
    onSelect({
      blockKey: b.key,
      sigunguCd: null,
      label: b.label,
      representativeCode: b.regionCode,
    });
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

  const isChipActive = (b: RegionBlock) => selected?.blockKey === b.key;

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
        {REGION_BLOCKS.map((b) => {
          const active = isChipActive(b);
          return (
            <button
              key={b.key}
              type="button"
              className={`chip chip--all${active ? " is-active" : ""}`}
              aria-pressed={active}
              onClick={() => selectBlock(b)}
            >
              {b.label}
            </button>
          );
        })}
      </ChipScrollRow>
      <p className="dest-search__status" aria-live="polite">
        {selected ? `${selected.label} 축제를 보고 있어요` : "전국 축제를 보고 있어요"}
      </p>
    </div>
  );
}
