"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ApiError,
  FeaturedSpot,
  RegionSearchItem,
  fetchFeatured,
  fetchRegionSearch,
} from "../lib/api";
import { AUTH_CHANGED_EVENT, getNickname } from "../lib/authStorage";
import { loadOnboardingResult } from "../lib/onboardingStorage";
import { PROVINCE_REGIONS, SIDO_REGIONS, SidoRegion } from "./regions/constants";
import ChipScrollRow from "./ChipScrollRow";

/**
 * 동행(companion) 태그 → 히어로 카피 분기 (대표 지시, 2026-07-29).
 * "아이와 함께 걷기 좋은"이 하드코딩돼 있었는데 커플·혼자일 수도 있다는 지적 —
 * 온보딩에서 실제로 고른 동행 태그가 있을 때만 그 문구를 쓰고, 없으면 중립 문구.
 * (회원가입에서 새 개인정보를 받지 않는다 — 이미 있는 온보딩 취향만 사용, 법률 보류 방침 부합.)
 * 우선순위: 아이>반려동물>연인>부모님>친구>혼자>가족 — 더 구체적인 동행을 먼저 반영.
 *
 * §43(2026-08-01, 03-design-spec.md, 대표 지시 4건 — 레이아웃 재설계) — 마케팅 헤드라인/서브카피
 * ("혼잡한 관광 대신…")를 통째로 없애면서 routeOwner(코스 소유격 문구, 옛 h1 전용)는 더 이상
 * 쓰이지 않아 제거했다. walkWith(동행 문구)만 남겨 로그인 사용자용 한 줄 인사에 재사용한다
 * (아래 hero-greeting, 스킬 근거는 컴포넌트 하단 §43 주석 참고).
 */
const COMPANION_COPY: { value: string; walkWith: string }[] = [
  { value: "with_child", walkWith: "아이와 함께 걷기 좋은" },
  { value: "with_pet", walkWith: "반려견과 함께 걷기 좋은" },
  { value: "couple", walkWith: "둘이서 걷기 좋은" },
  { value: "with_parents", walkWith: "부모님과 함께 걷기 좋은" },
  { value: "friends", walkWith: "친구와 함께 걷기 좋은" },
  { value: "solo", walkWith: "혼자 사색하며 걷기 좋은" },
  { value: "family", walkWith: "가족과 함께 걷기 좋은" },
];
const NEUTRAL_WALK_WITH = "천천히 걷기 좋은";

/**
 * §30(03-design-spec.md, 2026-07-29) — "빠른 추천 여행지" 칩을 4개(경주·전주·강릉·부산)에서 17개
 * 시도 각 1곳으로 확장한다(대표 지시: "각 도마다 여행지 하나씩 추천에 떠야 한다"). 새 코드를 지어
 * 내지 않고 components/regions/constants.ts의 검증된 SIDO_REGIONS(§29, Phase B 산출물 — /regions
 * 페이지 SidoStrip.tsx가 이미 쓰는 동일 소스)를 그대로 쓴다.
 *
 * 라벨은 "부산 해운대"처럼 [시도+대표지] 합성 대신 시도명만 쓴다: SidoStrip.tsx도 같은 이유로
 * 이니셜/짧은 시도명만 쓰는 관례를 세워뒀고, 대표지가 구 단위인 시도(대구 중구→"중", 광주 동구→
 * "동")는 문자열을 잘라 만들면 검증 안 된 한 글자 애칭이 나와 오히려 부정확·산만하다("코드/지명을
 * 지어내지 않는다" 원칙과 같은 이유). 대표 시군구 전체 명칭(representativeLabel)은 title 툴팁과
 * 선택 후 상태문구("OO 전광판을 보고 있어요")에 그대로 노출해 "이 지역은 사실 어디 기준인지"
 * 정직하게 알린다.
 *
 * region_code가 이미 검증돼 있으므로 예전처럼 칩마다 /regions/search를 사전조회(prefetch)하지
 * 않는다 — 4회면 몰라도 17회 왕복은 낭비다. 자유 텍스트 검색창만 계속 /regions/search를 쓴다.
 */
function sidoToRegionItem(sido: SidoRegion): RegionSearchItem {
  return {
    region_id: `sido-${sido.regionCode}`,
    label: sido.representativeLabel,
    area_cd: sido.sidoCode,
    sigungu_cd: sido.regionCode,
  };
}

const SEARCH_DEBOUNCE_MS = 200;
const CAROUSEL_LIMIT = 6;
const AUTO_ROTATE_MS = 5000;

function isEndpointMissing(err: unknown): boolean {
  // regions/search가 아직 없는 백엔드(MVP-1 상태)이면 404, 아예 미기동이면 네트워크 실패(status 0)로 온다.
  return err instanceof ApiError && (err.status === 404 || err.status === 0);
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * 대표 지시(2026-08-16) — 지역 미선택(첫 진입) 상태의 히어로 캐러셀은 "도" 9곳의 대표 스팟을
 * 한 곳씩만 가져와 채운다. limit=1로 그 도의 trending 1위를 쓰고, trending이 비면(도에 따라
 * congestion 랭킹 후보가 없을 수 있음) hidden_picks로 폴백한다. 실패한 도는 조용히 빠진다
 * (지어내지 않는다 — 9개를 억지로 채우지 않고 성공한 만큼만 보여준다).
 */
async function fetchProvinceRepresentative(
  regionCode: string,
  signal: AbortSignal
): Promise<FeaturedSpot | null> {
  try {
    const res = await fetchFeatured(regionCode, 1, signal);
    return res.trending[0] ?? res.hidden_picks[0] ?? null;
  } catch {
    return null;
  }
}

interface HeroProps {
  /** 현재 선택된 지역(칩/검색으로 선택). null이면 기본 지역(해운대) */
  selectedRegion: RegionSearchItem | null;
  onSelectRegion: (region: RegionSearchItem | null) => void;
}

/**
 * §24(03-design-spec.md, 2026-07-29) — 구석구석(한국관광공사 공식 포털) 템플릿 재구성.
 * 기존 "부킹형 풀블리드 히어로 + 겹쳐 뜨는 검색 카드"(§22 Acenda 재스킨)를 "컨테인드 라운드
 * 사진 카드 캐러셀 + 컴팩트 검색바"로 교체한다 — 대표 피드백("너무 커머스적") 반영.
 *
 * 데이터: fetchFeatured(기존 API, 신규 엔드포인트 없음)를 limit=6으로 호출해 trending 배열을
 * 그대로 캐러셀 슬라이드로 쓴다(§FeaturedSpots.tsx와 동일 호출 패턴). 목적지 자유 텍스트 검색
 * 로직(디바운스 /regions/search, 드롭다운)은 전혀 손대지 않고 그대로 재사용한다 — 바뀐 것은
 * 이 로직을 감싸는 마크업(부킹형 큰 카드 → 컴팩트 인라인 바)뿐이다. 빠른 추천 칩은 §30에서
 * 4→17개로 확장하며 사전조회(prefetch) 방식을 버렸다(위 sidoToRegionItem 주석 참고).
 */
export default function Hero({ selectedRegion, onSelectRegion }: HeroProps) {
  const [value, setValue] = useState("");

  // ---- 개인화 카피(대표 지시) ----
  // SSR/첫 클라이언트 렌더는 중립값으로 맞춰 하이드레이션 경고를 막고, mount 후 실제값 반영
  // (RegionPicker·SaveToggle과 동일 패턴). 닉네임=데모 로그인, 동행=온보딩 태그.
  const [nickname, setNickname] = useState<string | null>(null);
  const [companionValues, setCompanionValues] = useState<string[]>([]);
  useEffect(() => {
    const syncAuth = () => setNickname(getNickname());
    syncAuth();
    window.addEventListener(AUTH_CHANGED_EVENT, syncAuth);
    window.addEventListener("storage", syncAuth);
    const stored = loadOnboardingResult()?.result;
    setCompanionValues(stored?.tags?.companion?.map((t) => t.value) ?? []);
    return () => {
      window.removeEventListener(AUTH_CHANGED_EVENT, syncAuth);
      window.removeEventListener("storage", syncAuth);
    };
  }, []);
  const companionCopy =
    COMPANION_COPY.find((c) => companionValues.includes(c.value)) ?? null;
  const walkWith = companionCopy?.walkWith ?? NEUTRAL_WALK_WITH;

  // ---- 캐러셀 슬라이드 ----
  const [slides, setSlides] = useState<FeaturedSpot[]>([]);
  const [slidesStatus, setSlidesStatus] = useState<"loading" | "success" | "error">("loading");
  const [activeIndex, setActiveIndex] = useState(0);
  const trackRef = useRef<HTMLDivElement>(null);
  const scrollRafRef = useRef<number | null>(null);
  // 프로그램적(자동순환·인디케이터) 스크롤 진행 중 플래그. 이게 켜져 있는 동안 handleTrackScroll의
  // 인덱스 동기화를 건너뛴다 — 안 그러면 smooth 스크롤 시작 직후(아직 이전 카드가 중앙) 동기화가
  // 인덱스를 도로 되돌려 자동순환이 영원히 1번 카드에 묶인다(실측으로 확인된 버그).
  const programmaticScrollRef = useRef(false);
  const programmaticTimerRef = useRef<number>(0);

  useEffect(() => {
    const controller = new AbortController();
    setSlidesStatus("loading");
    if (selectedRegion) {
      fetchFeatured(selectedRegion.sigungu_cd, CAROUSEL_LIMIT, controller.signal)
        .then((res) => {
          setSlides(res.trending);
          setSlidesStatus("success");
          setActiveIndex(0);
        })
        .catch(() => {
          if (controller.signal.aborted) return;
          setSlides([]);
          setSlidesStatus("error");
        });
    } else {
      // 지역 미선택(첫 진입) — 특정 지역에 쏠리지 않게 도 9곳의 대표 사진 한 장씩(9개 병렬 호출,
      // 순차 왕복 아님 — 체감 지연은 가장 느린 1건 수준).
      Promise.all(
        PROVINCE_REGIONS.map((p) => fetchProvinceRepresentative(p.regionCode, controller.signal))
      )
        .then((results) => {
          if (controller.signal.aborted) return;
          setSlides(results.filter((s): s is FeaturedSpot => s !== null));
          setSlidesStatus("success");
          setActiveIndex(0);
        })
        .catch(() => {
          if (controller.signal.aborted) return;
          setSlides([]);
          setSlidesStatus("error");
        });
    }
    return () => controller.abort();
  }, [selectedRegion]);

  // 5초 자동 순환 — 슬라이드 2개 이상 + prefers-reduced-motion 아닐 때만.
  useEffect(() => {
    if (slides.length < 2 || prefersReducedMotion()) return;
    const timer = setInterval(() => {
      setActiveIndex((i) => (i + 1) % slides.length);
    }, AUTO_ROTATE_MS);
    return () => clearInterval(timer);
  }, [slides.length]);

  // activeIndex가 바뀌면(자동 순환·인디케이터 클릭 공통) 트랙을 해당 카드로 스크롤.
  // ★ scrollIntoView 금지: 모든 스크롤 조상(페이지 세로 포함)을 움직여 5초마다 화면이
  //   캐러셀로 끌려가는 버그가 있었고, scroll-snap mandatory와 충돌해 정작 가로 이동은
  //   씹혔다(대표 리포트 2건의 공통 원인). 트랙 자신만 scrollTo로 가로 이동시킨다.
  useEffect(() => {
    const track = trackRef.current;
    const card = track?.children[activeIndex] as HTMLElement | undefined;
    if (!track || !card) return;
    const trackRect = track.getBoundingClientRect();
    const cardRect = card.getBoundingClientRect();
    const left =
      track.scrollLeft + (cardRect.left - trackRect.left) - (trackRect.width - cardRect.width) / 2;
    // smooth 스크롤이 도착할 때까지 스와이프 동기화를 잠근다(도착 전 동기화가 인덱스를 되돌리는 것 방지).
    programmaticScrollRef.current = true;
    window.clearTimeout(programmaticTimerRef.current);
    track.scrollTo({
      left,
      behavior: prefersReducedMotion() ? "auto" : "smooth",
    });
    programmaticTimerRef.current = window.setTimeout(
      () => {
        programmaticScrollRef.current = false;
      },
      prefersReducedMotion() ? 120 : 800
    );
    return () => window.clearTimeout(programmaticTimerRef.current);
  }, [activeIndex]);

  // 사용자가 직접 스와이프했을 때도 인디케이터가 따라가도록 트랙 중앙에 가장 가까운 카드를 찾는다.
  const handleTrackScroll = () => {
    // 프로그램적 스크롤 진행 중이면 동기화 생략 — 사용자 스와이프일 때만 인덱스를 따라간다.
    if (programmaticScrollRef.current) return;
    if (scrollRafRef.current !== null) return;
    scrollRafRef.current = requestAnimationFrame(() => {
      scrollRafRef.current = null;
      const track = trackRef.current;
      if (!track) return;
      const trackRect = track.getBoundingClientRect();
      const centerX = trackRect.left + trackRect.width / 2;
      let closest = 0;
      let closestDist = Infinity;
      Array.from(track.children).forEach((child, i) => {
        const rect = (child as HTMLElement).getBoundingClientRect();
        const dist = Math.abs(rect.left + rect.width / 2 - centerX);
        if (dist < closestDist) {
          closestDist = dist;
          closest = i;
        }
      });
      setActiveIndex((prev) => (prev === closest ? prev : closest));
    });
  };

  useEffect(() => {
    return () => {
      if (scrollRafRef.current !== null) cancelAnimationFrame(scrollRafRef.current);
    };
  }, []);

  // ---- 목적지 자유 텍스트 검색(부록 A.3) — 로직 무변경, Acenda 라운드부터 그대로 재사용 ----
  // §30 — 빠른 추천 칩은 더 이상 이 API를 사전조회하지 않는다(SIDO_REGIONS 직접 선택). 이 상태들은
  // 순수하게 입력창 자유 검색만 담당한다.
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [searchStatus, setSearchStatus] = useState<"idle" | "loading" | "success" | "error">(
    "idle"
  );
  const [searchResults, setSearchResults] = useState<RegionSearchItem[]>([]);
  const [searchErrorMsg, setSearchErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    const q = value.trim();
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
          if (isEndpointMissing(err)) {
            setSearchErrorMsg("검색 기능 준비 중이에요. 아래 추천 지역을 이용해주세요.");
          } else {
            setSearchErrorMsg(
              err instanceof ApiError ? err.message : "지역 검색에 실패했습니다."
            );
          }
        });
    }, SEARCH_DEBOUNCE_MS);

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [value]);

  const selectRegion = (region: RegionSearchItem, label: string) => {
    setValue(label);
    setDropdownOpen(false);
    onSelectRegion(region);
  };

  // §30 — SIDO_REGIONS의 검증된 코드를 그대로 선택한다(검색 API 왕복 없음).
  const selectSido = (sido: SidoRegion) => {
    selectRegion(sidoToRegionItem(sido), sido.shortName);
  };

  const clearDestination = () => {
    setValue("");
    setDropdownOpen(false);
    setSearchResults([]);
    setSearchStatus("idle");
    onSelectRegion(null);
  };

  const isChipActive = (sido: SidoRegion) =>
    !!selectedRegion && selectedRegion.sigungu_cd === sido.regionCode;

  const inputRef = useRef<HTMLInputElement>(null);

  const status = selectedRegion
    ? `${selectedRegion.label} 전광판을 보고 있어요`
    : value
    ? `"${value}" 검색 중`
    : "";

  return (
    <>
      {/* §43(2026-08-01, 03-design-spec.md — 대표 지시 4건 레이아웃 재설계) — 마케팅 카피 블록
          (이유브로우+헤드라인+서브카피 3단)을 통째로 없앴다("혼잡한 관광 대신…" 멘트, 대표 지시
          원문 2 그대로 반영). 확보된 세로 공간은 전부 아래 히어로 캐러셀(사진) 확대에 쓴다.
          단, 페이지에는 h1이 정확히 하나 있어야 한다는 접근성 규칙(이 코드베이스의 다른 모든
          화면이 지키는 관례 — FestivalsContent/RegionsContent 등 h1=section__title 패턴)을
          깨지 않기 위해 시각적으로는 숨기되(sr-only) 의미상 h1은 유지한다. 로그인 사용자에게는
          그 자리에 마케팅 문장 대신 사실 기반 한 줄 인사만 남긴다(아래 hero-greeting) —
          design-taste-frontend 스킬 §4.7 "히어로 텍스트 요소는 최소한으로, 하나의 작은 텍스트
          요소만" 원칙과 redesign-skill "Missing whitespace — 밀도를 낮추고 여백을 늘려라" 원칙을
          함께 적용한 선택. 비로그인 사용자는 이 자리에 아무 텍스트도 없다(추측 카피로 채우지
          않는다 — 이 코드베이스의 기존 "정직" 원칙과 동일선상). */}
      <h1 className="sr-only">숨은길 — 혼잡한 명소 대신 숨은 코스를 추천하는 AI 여행 서비스</h1>
      {nickname && (
        <p className="hero-greeting">
          {nickname}님, {walkWith} 오늘의 코스를 아래에서 찾아보세요
        </p>
      )}

      {/* §24 — 부킹형 큰 검색 카드(라벨+박스+칩+CTA 버튼, shadow-lg, 히어로 위 겹침)를 없애고
          인라인 컴팩트 바로 축소했다. CTA 버튼은 아래 서비스 퀵메뉴의 "AI 코스" 타일과 의도가
          겹쳐(동일 CTA 중복) 제거했다 — 검색/지역 선택 기능만 남긴다. */}
      <div className="home-search-bar">
        <label className="home-search-bar__label" htmlFor="destInput">
          어디로 떠나시나요?
        </label>
        <div className="dest-search__box">
          <svg className="dest-search__icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2.2" />
            <path d="M20 20l-3.5-3.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            id="destInput"
            className="dest-search__input"
            placeholder="지역/관광지 이름으로 검색 (예: 경주, 전주)"
            role="combobox"
            aria-expanded={dropdownOpen}
            aria-autocomplete="list"
            aria-controls="destSearchListbox"
            autoComplete="off"
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setDropdownOpen(true);
            }}
            onFocus={() => {
              if (value.trim().length > 0) setDropdownOpen(true);
            }}
            onBlur={() => {
              setTimeout(() => setDropdownOpen(false), 120);
            }}
          />
          {value && (
            <button
              type="button"
              className="dest-search__clear"
              aria-label="목적지 검색어 지우기"
              onClick={clearDestination}
            >
              &times;
            </button>
          )}
        </div>

        {dropdownOpen && value.trim().length > 0 && (
          <ul
            className="dest-search__dropdown"
            id="destSearchListbox"
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
                &quot;{value}&quot; 검색 결과가 없어요. 다른 지역명으로 시도해보세요.
              </li>
            )}
            {searchStatus === "success" &&
              searchResults.map((item) => (
                <li key={item.region_id} role="option" aria-selected="false">
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

        <div className="dest-search__quick">
          <span className="dest-search__quick-label">자주 찾는 지역</span>
          <ChipScrollRow>
            {SIDO_REGIONS.map((sido) => {
              const active = isChipActive(sido);
              return (
                <button
                  key={sido.sidoCode}
                  type="button"
                  className={`chip chip--all${active ? " is-active" : ""}`}
                  onClick={() => selectSido(sido)}
                  aria-pressed={active}
                  title={sido.representativeLabel}
                >
                  {sido.shortName}
                </button>
              );
            })}
          </ChipScrollRow>
        </div>
        <div className="dest-search__status" aria-live="polite">
          {status}
        </div>
      </div>

      {/* §24 — 구석구석 히어로 문법: 컨테인드 라운드 사진 카드 캐러셀(풀블리드 아님).
          가운데 큰 카드 + 양옆 이웃 카드가 살짝 보이도록 트랙 좌우 여백을 남기고
          scroll-snap-align:center로 정렬한다. 5초 자동 순환 + 일시정지 버튼(접근성),
          prefers-reduced-motion이면 자동 순환을 아예 켜지 않는다(위 useEffect). */}
      <div className="hero-carousel" role="region" aria-label="지금 뜨는 여행지 사진">
        <div className="hero-carousel__track" ref={trackRef} onScroll={handleTrackScroll} role="list">
          {slidesStatus === "loading" &&
            Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="hero-carousel__card hero-carousel__card--skeleton" aria-hidden="true" />
            ))}

          {slidesStatus !== "loading" && slides.length === 0 && (
            <div className="hero-carousel__card hero-carousel__card--fallback" role="listitem">
              <span className="hero-carousel__overlay">
                <strong className="hero-carousel__title">사람 대신, 설렘이 가득한 여행</strong>
                <span className="hero-carousel__meta">AI가 찾은 오늘의 숨은 코스를 만나보세요</span>
              </span>
            </div>
          )}

          {slidesStatus !== "loading" &&
            slides.map((spot) => {
              const hasPhoto = !!spot.image_url;
              return (
                <Link
                  key={spot.id}
                  href={`/spot/${spot.id}`}
                  role="listitem"
                  className={`hero-carousel__card${hasPhoto ? "" : " hero-carousel__card--noimg"}`}
                  style={
                    hasPhoto
                      ? ({ "--slide-photo": `url("${spot.image_url}")` } as React.CSSProperties)
                      : undefined
                  }
                  aria-label={`${spot.name}, ${spot.region_name} — 자세히 보기`}
                >
                  <span className="hero-carousel__overlay">
                    <strong className="hero-carousel__title">{spot.name}</strong>
                    <span className="hero-carousel__meta">{spot.region_name}</span>
                  </span>
                </Link>
              );
            })}
        </div>

        {slidesStatus === "success" && slides.length > 1 && (
          <div className="hero-carousel__controls">
            <div className="hero-carousel__dots" role="tablist" aria-label="추천 스팟 슬라이드 선택">
              {slides.map((spot, i) => (
                <button
                  key={spot.id}
                  type="button"
                  role="tab"
                  aria-selected={i === activeIndex}
                  aria-label={`${i + 1}번째 슬라이드: ${spot.name}`}
                  className={`hero-carousel__dot${i === activeIndex ? " is-active" : ""}`}
                  onClick={() => setActiveIndex(i)}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
