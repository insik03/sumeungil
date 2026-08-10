"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, PlaceSearchItem, fetchSpotSearch } from "../../lib/api";
import { CATEGORY_META } from "../recommend/constants";

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  CATEGORY_META.map((c) => [c.value, c.label])
);

const SEARCH_DEBOUNCE_MS = 200;

function isEndpointMissing(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 0);
}

interface SpotSearchBoxProps {
  /** 이미 코스에 추가된 스팟 id — 검색 결과에서 "담김" 표시 + 재추가 방지용. */
  existingIds: number[];
  /** MAX_CART_SIZE(8곳) 도달 시 검색창 자체를 비활성화하고 안내만 보여준다. */
  atMax: boolean;
  onAdd: (item: PlaceSearchItem) => void;
}

/**
 * §26(신규) — "내 코스 만들기" 검색창. RegionPicker.tsx의 전국 지역 검색 combobox 패턴
 * (디바운스 200ms, onMouseDown preventDefault로 클릭이 blur보다 먼저 처리되게, 동일한
 * dest-search__* 클래스)을 그대로 이식했다 — 지역 대신 스팟(가게·관광지)을 검색한다는 점만 다르다.
 * id/region_code 등 코드 값은 이 검색 응답에서만 가져오고 프론트가 지어내지 않는다(부록 A.1과
 * 동일 원칙, lib/api.ts fetchSpotSearch 주석 참고).
 */
export default function SpotSearchBox({ existingIds, atMax, onAdd }: SpotSearchBoxProps) {
  const [query, setQuery] = useState("");
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [results, setResults] = useState<PlaceSearchItem[]>([]);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const q = query.trim();
    if (q.length === 0) {
      setStatus("idle");
      setResults([]);
      return;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => {
      setStatus("loading");
      setErrorMsg(null);
      fetchSpotSearch(q, undefined, controller.signal)
        .then((res) => {
          setResults(res.items);
          setStatus("success");
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          setResults([]);
          setStatus("error");
          if (isEndpointMissing(err)) {
            setErrorMsg("검색 기능 준비 중이에요. 잠시 후 다시 시도해주세요.");
          } else {
            setErrorMsg(err instanceof ApiError ? err.message : "스팟 검색에 실패했습니다.");
          }
        });
    }, SEARCH_DEBOUNCE_MS);

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [query]);

  const clearQuery = () => {
    setQuery("");
    setDropdownOpen(false);
    setResults([]);
    setStatus("idle");
  };

  const handleAdd = (item: PlaceSearchItem) => {
    if (atMax || existingIds.includes(item.id)) return;
    onAdd(item);
    clearQuery();
    inputRef.current?.focus();
  };

  return (
    <div className="spot-search-box">
      <div className="dest-search__box">
        <svg className="dest-search__icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2.2" />
          <path d="M20 20l-3.5-3.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
        </svg>
        <input
          ref={inputRef}
          type="text"
          id="spotSearchInput"
          className="dest-search__input"
          placeholder="가게·관광지 이름으로 검색해 추가 (예: 반송187)"
          role="combobox"
          aria-expanded={dropdownOpen}
          aria-autocomplete="list"
          aria-controls="spotSearchListbox"
          autoComplete="off"
          value={query}
          disabled={atMax}
          onChange={(e) => {
            setQuery(e.target.value);
            setDropdownOpen(true);
          }}
          onFocus={() => {
            if (query.trim().length > 0) setDropdownOpen(true);
          }}
          onBlur={() => {
            // 드롭다운 항목 클릭(mousedown)이 blur보다 먼저 처리되도록 살짝 지연(RegionPicker와 동일)
            setTimeout(() => setDropdownOpen(false), 120);
          }}
        />
        {query && (
          <button type="button" className="dest-search__clear" aria-label="검색어 지우기" onClick={clearQuery}>
            &times;
          </button>
        )}
      </div>

      {dropdownOpen && query.trim().length > 0 && (
        <ul
          className="dest-search__dropdown"
          id="spotSearchListbox"
          role="listbox"
          aria-label="스팟 검색 결과"
        >
          {status === "loading" && (
            <li className="dest-search__dropdown-empty" aria-live="polite">
              검색 중…
            </li>
          )}
          {status === "success" && results.length === 0 && (
            <li className="dest-search__dropdown-empty">
              &quot;{query}&quot; 검색 결과가 없어요. 다른 이름으로 시도해보세요.
            </li>
          )}
          {status === "success" &&
            results.map((item) => {
              const already = existingIds.includes(item.id);
              return (
                <li key={item.id} role="option" aria-selected={already}>
                  <button
                    type="button"
                    className="dest-search__dropdown-item spot-search-box__item"
                    disabled={already}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => handleAdd(item)}
                  >
                    <span className="spot-search-box__item-main">
                      <span className="spot-search-box__item-category">
                        {CATEGORY_LABEL[item.category] ?? item.category}
                      </span>
                      <span className="spot-search-box__item-name">{item.name}</span>
                    </span>
                    <span className="spot-search-box__item-meta">
                      {item.is_hidden_gem && <span className="badge badge--hidden-gem">숨은 스팟</span>}
                      {item.region_name && (
                        <span className="spot-search-box__item-region">{item.region_name}</span>
                      )}
                      {already && <span className="spot-search-box__item-added">담김</span>}
                    </span>
                  </button>
                </li>
              );
            })}
          {status === "error" && (
            <li className="dest-search__dropdown-empty" role="alert">
              {errorMsg ?? "스팟 검색에 실패했습니다."}
            </li>
          )}
        </ul>
      )}

      {atMax && <p className="dest-search__notice">최대 8곳까지 담을 수 있어요.</p>}
    </div>
  );
}
