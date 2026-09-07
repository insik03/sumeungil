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
import { PROVINCE_REGIONS, SIDO_REGIONS, SidoRegion } from "./regions/constants";
import ChipScrollRow from "./ChipScrollRow";

/**
 * §43(2026-08-01, 03-design-spec.md, 대표 지시 4건 — 레이아웃 재설계) — 마케팅 헤드라인/서브카피
 * ("혼잡한 관광 대신…")를 통째로 없애면서 routeOwner(코스 소유격 문구, 옛 h1 전용)는 더 이상
 * 쓰이지 않아 제거했다.
 *
 * 2026-08-18(대표 지시) — 로그인 사용자용 한 줄 인사("OO님, 둘이서 걷기 좋은…")는 이 파일에
 * 있었지만 HeroGreeting.tsx로 옮겼다("카테고리 창 밑, 추천 배너 밑"으로 위치를 옮겨달라는
 * 요청 — HomeContent.tsx가 원하는 자리에 독립 렌더).
 */

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

/** 사진이 없는 스팟(빈 카드/폴백 카드) 후보 목록에서 사진 있는 첫 번째를 고른다. */
const PROVINCE_CANDIDATE_LIMIT = 10;

/**
 * 대표 지시(2026-08-16) — 지역 미선택(첫 진입) 상태의 히어로 캐러셀은 "도" 9곳의 대표 스팟을
 * 한 곳씩만 가져와 채운다. trending 1위를 우선하고, trending이 비면(도에 따라 congestion 랭킹
 * 후보가 없을 수 있음) hidden_picks로 폴백한다. 실패한 도는 조용히 빠진다(지어내지 않는다 —
 * 9개를 억지로 채우지 않고 성공한 만큼만 보여준다).
 *
 * 대표 지적(2026-08-17) — "사진 없는 스팟이 캐러셀에 들어가니 어색함". limit=1로 순위 1위만
 * 가져오면 그 스팟이 사진이 없어도 그대로 쓸 수밖에 없었다. limit을 넉넉히 올려 후보 풀을
 * 받아온 뒤(trending 우선, 부족하면 hidden_picks) image_url이 있는 첫 후보를 고른다 — 순위
 * 자체를 재판정하지 않고(§4.1 규약 준수) "사진 있는 것 중 1등"으로 좁히기만 한다.
 */
async function fetchProvinceRepresentative(
  regionCode: string,
  signal: AbortSignal
): Promise<FeaturedSpot | null> {
  try {
    const res = await fetchFeatured(regionCode, PROVINCE_CANDIDATE_LIMIT, signal);
    const candidates = [...res.trending, ...res.hidden_picks];
    return candidates.find((s) => !!s.image_url) ?? candidates[0] ?? null;
  } catch {
    return null;
  }
}

interface HeroProps {
  /** 현재 선택된 지역(칩/검색으로 선택). null이면 기본 지역(해운대) */
  selectedRegion: RegionSearchItem | null;
  onSelectRegion: (region: RegionSearchItem | null) => void;
  /**
   * 2026-09-03 — 부모(HomeContent)가 기억해둔 지역을 sessionStorage에서 복원했는지. false면
   * 캐러셀 데이터 요청을 미룬다. 첫 렌더의 null을 "지역 미선택"으로 오해해 전국 9개 도 병렬
   * 호출을 쏜 뒤 곧바로 지역이 복원되며 전부 취소·재요청하던 이중 호출을 막는다(렉 원인).
   * 다른 호출자가 없어 기본값은 true(즉시 요청).
   */
  regionResolved?: boolean;
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
export default function Hero({ selectedRegion, onSelectRegion, regionResolved = true }: HeroProps) {
  const [value, setValue] = useState("");

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
    if (!regionResolved) return; // 지역 복원 전 — 요청하지 않고 loading 상태로 대기
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
  }, [selectedRegion, regionResolved]);

  // 5초 자동 순환 — 슬라이드 2개 이상 + prefers-reduced-motion 아닐 때만.
  useEffect(() => {
    if (slides.length < 2 || prefersReducedMotion()) return;
    const timer = setInterval(() => {
      // 2026-09-04(대표: "마지막에서 첫 번째로 되돌아가는 게 어색하다") — n 은 트랙 끝에 붙인
      // "첫 장의 복제"라, 마지막→첫 장도 앞으로 미끄러진다. 도착 후 아래 effect 가 소리 없이 실제
      // 첫 장(0)으로 점프해 다음 바퀴를 잇는다(무한 순환).
      setActiveIndex((i) => (i >= slides.length ? 1 : i + 1));
    }, AUTO_ROTATE_MS);
    return () => clearInterval(timer);
  }, [slides.length]);

  // activeIndex가 바뀌면(자동 순환·인디케이터 클릭 공통) 트랙을 해당 카드로 스크롤.
  // ★ scrollIntoView 금지: 모든 스크롤 조상(페이지 세로 포함)을 움직여 5초마다 화면이
  //   캐러셀로 끌려가는 버그가 있었고, scroll-snap mandatory와 충돌해 정작 가로 이동은
  //   씹혔다(대표 리포트 2건의 공통 원인). 트랙 자신만 scrollTo로 가로 이동시킨다.
  // 무한 순환(2026-09-04): 슬라이드가 2장 이상이면 트랙을 [마지막 복제, s0..s(n-1), 첫 복제] 로
  // 그린다. activeIndex 는 -1(마지막 복제)~n(첫 복제) 범위를 잠깐 가질 수 있고, 그 두 위치에
  // 부드럽게 도착한 뒤에는 애니메이션 없이 실제 장으로 점프한다 — 사용자 눈엔 끊김 없이 계속
  // 앞으로 도는 것으로 보인다. 점(dots)은 항상 실제 인덱스((activeIndex+n)%n)로 표시한다.
  const looped = slides.length > 1;
  // 2026-09-05 대표 3차 지적("6→1이 여전히 어색") — 실측 원인: 복제를 한 장씩만 붙이면 끝 복제가
  // 트랙의 **맨 끝 자식**이라 가운데로 스크롤할 수 없다(필요 위치 5044px > 최대 4842px). 브라우저가
  // 끝에서 멈춘 뒤 실제 1장으로 점프하니 카드가 200px 옆으로 튀었다(1→6 역방향도 같은 이유).
  // 양쪽에 **두 장씩** 복제해 끝 복제 뒤에도 카드 한 장 분량의 공간을 두면 항상 가운데에 도착한다.
  const CLONES = 2;
  const trackChildIndex = (logical: number) => (looped ? logical + CLONES : logical);
  // 슬라이드가 새로 들어오면 트랙의 첫 자식은 "마지막 장 복제"라, 애니메이션 없이 실제 첫 장으로
  // 맞춰 둔다(안 하면 첫 화면이 마지막 장으로 보인다). activeIndex 는 이미 0 이라 아래 effect 가
  // 다시 돌지 않으므로 여기서 직접 한다.
  useEffect(() => {
    if (!looped) return;
    const track = trackRef.current;
    const card = track?.children[CLONES] as HTMLElement | undefined;
    if (!track || !card) return;
    const trackRect = track.getBoundingClientRect();
    const cardRect = card.getBoundingClientRect();
    track.scrollTo({
      left: track.scrollLeft + (cardRect.left - trackRect.left) - (trackRect.width - cardRect.width) / 2,
      behavior: "instant",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slides]);
  const scrollTrackTo = (childIdx: number, behavior: ScrollBehavior) => {
    const track = trackRef.current;
    const card = track?.children[childIdx] as HTMLElement | undefined;
    if (!track || !card) return false;
    const trackRect = track.getBoundingClientRect();
    const cardRect = card.getBoundingClientRect();
    const left =
      track.scrollLeft + (cardRect.left - trackRect.left) - (trackRect.width - cardRect.width) / 2;
    track.scrollTo({ left, behavior });
    return true;
  };

  useEffect(() => {
    if (!scrollTrackTo(trackChildIndex(activeIndex), prefersReducedMotion() ? "auto" : "smooth")) return;
    // smooth 스크롤이 도착할 때까지 스와이프 동기화를 잠근다(도착 전 동기화가 인덱스를 되돌리는 것 방지).
    programmaticScrollRef.current = true;
    window.clearTimeout(programmaticTimerRef.current);
    const settleMs = prefersReducedMotion() ? 120 : 800;
    const track = trackRef.current;
    let settled = false;
    const settle = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(programmaticTimerRef.current);
      track?.removeEventListener("scrollend", settle);
      const n = slides.length;
      if (looped && (activeIndex >= n || activeIndex < 0)) {
        // 복제 장에 도착 — 같은 그림의 실제 장으로 소리 없이 점프한 뒤 인덱스를 정규화.
        // 2026-09-04 대표 재지적("6 다음에 1이 오른쪽에서 나와야") — 원인: 트랙 CSS 가
        // scroll-behavior:smooth 라 behavior:"auto" 는 CSS 값을 따라 **부드럽게 되감겼다**.
        // 그래서 마지막 장 뒤에 1로 "쭉 돌아가는" 게 보였다. "instant" 는 CSS 를 무시한다.
        const real = ((activeIndex % n) + n) % n;
        scrollTrackTo(trackChildIndex(real), "instant");
        setActiveIndex(real);
        // 점프 직후 발생하는 scroll 이벤트가 인덱스를 되돌리지 않게 한 프레임 더 잠근다.
        window.setTimeout(() => {
          programmaticScrollRef.current = false;
        }, 60);
        return;
      }
      programmaticScrollRef.current = false;
    };
    // scrollend 는 도착 즉시(Chrome 114+/Firefox 109+/Safari 18.4+), 타이머는 미지원 브라우저 폴백.
    track?.addEventListener("scrollend", settle, { once: true });
    programmaticTimerRef.current = window.setTimeout(settle, settleMs);
    return () => {
      window.clearTimeout(programmaticTimerRef.current);
      track?.removeEventListener("scrollend", settle);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      const logical = looped ? closest - CLONES : closest;
      setActiveIndex((prev) => (prev === logical ? prev : logical));
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
          깨지 않기 위해 시각적으로는 숨기되(sr-only) 의미상 h1은 유지한다. 로그인 사용자용
          한 줄 인사(hero-greeting)는 2026-08-18부터 HeroGreeting.tsx로 옮겨 HomeContent.tsx가
          더 아래(카테고리 창 밑)에 따로 배치한다 — design-taste-frontend 스킬 §4.7 "히어로
          텍스트 요소는 최소한으로" 원칙과 redesign-skill "Missing whitespace" 원칙은 이 h1
          자리에 여전히 적용된다. 비로그인 사용자는 이 자리에 아무 텍스트도 없다(추측 카피로
          채우지 않는다 — 이 코드베이스의 기존 "정직" 원칙과 동일선상).
          2026-08-29 — 대표 지시로 "숨은 길" 헤드라인+지역지도를 이 자리(히어로, 검색바 옆)에
          한 번 넣었다가, 재지적("애초에 위치 자체가 글러먹었다")으로 되돌렸다. 지도는
          RegionMapSection.tsx로 옮겨 홈 안의 독립 섹션이 됐다 — 자리를 옮긴 것뿐 기능은
          그대로다. 여기 h1도 그 되돌림의 일부로 원래(sr-only)로 복귀. */}
      <h1 className="sr-only">숨은길 — 혼잡한 명소 대신 숨은 코스를 추천하는 AI 여행 서비스</h1>

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
            (looped ? [...slides.slice(-CLONES), ...slides, ...slides.slice(0, CLONES)] : slides).map((spot, idx, arr) => {
              const hasPhoto = !!spot.image_url;
              // 양끝 CLONES 장은 순환용 복제 — 화면엔 보이지만 접근성 트리·탭 순서에서는 뺀다.
              const isClone = looped && (idx < CLONES || idx >= arr.length - CLONES);
              return (
                <Link
                  key={isClone ? `clone-${idx}-${spot.id}` : spot.id}
                  href={`/spot/${spot.id}`}
                  role="listitem"
                  aria-hidden={isClone || undefined}
                  tabIndex={isClone ? -1 : undefined}
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
                  aria-selected={i === ((activeIndex % slides.length) + slides.length) % slides.length}
                  aria-label={`${i + 1}번째 슬라이드: ${spot.name}`}
                  className={`hero-carousel__dot${i === ((activeIndex % slides.length) + slides.length) % slides.length ? " is-active" : ""}`}
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
