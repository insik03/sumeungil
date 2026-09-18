"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  ApiError,
  OnboardingResult,
  RecommendRequest,
  RecommendResponse,
  ReviewSummary,
  SpotCategory,
  fetchRecommendedPlaces,
  fetchReviewsSummaryBulk,
} from "../lib/api";
import { clearOnboardingResult } from "../lib/onboardingStorage";
import { resolveOnboardingProfile } from "../lib/onboardingProfile";
import { loadLastRegion, saveLastRegion } from "../lib/lastRegionStorage";
import { safeDistanceKm } from "../lib/geo";
import CategoryFilter from "./recommend/CategoryFilter";
import type { SelectedRegion } from "./recommend/RegionPicker";
import RegionBlockPicker from "./recommend/RegionBlockPicker";
import RecommendSpotCard, { SpotCardSkeleton } from "./recommend/SpotCard";
import SaveToggleButton from "./recommend/SaveToggleButton";
import RerankBanners from "./recommend/RerankBanners";
import SpotMap from "./recommend/SpotMap";
import { useLoggedInName } from "../lib/useLoggedInName";
import SpotTypeFilter from "./recommend/SpotTypeFilter";
import SortControl from "./recommend/SortControl";
import {
  DEFAULT_REGION,
  SortOption,
  SpotTypeFilterValue,
  regionSelectionFromCode,
} from "./recommend/constants";

type Status = "loading" | "success" | "error";
/** undefined = sessionStorage 확인 전(SSR와 값이 갈리지 않게 첫 렌더는 항상 undefined). */
type ProfileState = OnboardingResult | null | undefined;

const SKELETON_COUNT = 6;

/**
 * 추천 화면(MVP-4, 01-interface-contract.md 부록 C) 오케스트레이터.
 * - sessionStorage의 OnboardingResult(부록 B 산출물)를 읽어 그대로 재전송한다. 조작·재계산 금지(§C.7-7).
 * - 프로필이 없어도 화면을 막지 않는다 — 비개인화 목록 + 온보딩 유도 배너로 처리한다(§C.7-1, DoD).
 * - 개인화 여부는 항상 backend 응답의 `personalized`를 신뢰한다(§C.7-1) — 로컬 프로필 유무로 재판정하지 않는다.
 *
 * §35(2026-07-31, 03-design-spec.md — 지역 컨텍스트 전파, 백로그 D21) — URL `?region_code=`를
 * 초기 지역으로 소비한다. 그동안 홈·/regions가 이 쿼리를 붙여 보내도 이 화면이 읽지 않아 항상
 * 기본 지역(해운대)으로 열리던 단절을 없앤다. 규칙:
 *   ① 형식(숫자 5자리)이 아니면 무시하고 기존 기본 지역을 그대로 쓴다(regionSelectionFromCode).
 *   ② 쿼리는 "초기값 주입"일 뿐이라, 이후 RegionPicker로 사용자가 고른 지역이 항상 우선한다
 *      (아래 동기화 effect가 paramCode가 바뀔 때만 돌기 때문에 사용자의 선택을 덮지 않는다).
 */
export default function RecommendContent() {
  const searchParams = useSearchParams();
  const loggedIn = useLoggedInName();
  const paramRegionCode = searchParams.get("region_code");

  // 지역 지도는 /course와 같이 로그인한 사용자에게만(대표: "공개 화면에 둘 거 아님 로그인에 넣으셈").
  const [profile, setProfile] = useState<ProfileState>(undefined);
  // 지연 초기화 — 첫 렌더부터 쿼리 지역으로 시작한다(기본 지역으로 한 번 조회한 뒤 다시 조회하는
  // 이중 호출을 피하기 위함). URL 쿼리는 SSR에서도 동일하게 읽혀 하이드레이션이 안전하다 —
  // 마지막으로 고른 지역(세션 기억)은 sessionStorage라 서버에서 못 읽으므로 초기 state에
  // 넣지 않는다(넣으면 서버/클라이언트 첫 렌더가 갈려 하이드레이션 에러, 실측으로 확인된
  // 버그 재발 방지) — 아래 effect에서 mount 후 반영한다.
  const [selectedRegion, setSelectedRegionState] = useState<SelectedRegion>(
    () =>
      regionSelectionFromCode(paramRegionCode) ?? {
        sigunguCd: DEFAULT_REGION.sigunguCd,
        label: DEFAULT_REGION.label,
      }
  );
  useEffect(() => {
    if (regionSelectionFromCode(paramRegionCode)) return; // URL이 이미 명시했다면 건드리지 않음
    const last = loadLastRegion();
    if (last) setSelectedRegionState({ sigunguCd: last.sigungu_cd, label: last.label });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // useState 세터와 동일한 시그니처(값 또는 함수형 업데이터)를 유지해 기존 호출부(§35 동기화
  // effect의 함수형 업데이터 포함)를 그대로 쓸 수 있게 한다 — 실제로 바뀔 때만 기억해둔다.
  const setSelectedRegion = (value: SelectedRegion | ((prev: SelectedRegion) => SelectedRegion)) => {
    setSelectedRegionState((prev) => {
      const next = typeof value === "function" ? value(prev) : value;
      if (next !== prev) {
        saveLastRegion({
          region_id: `sigungu-${next.sigunguCd}`,
          label: next.label,
          area_cd: next.sigunguCd.slice(0, 2),
          sigungu_cd: next.sigunguCd,
        });
      }
      return next;
    });
  };

  // 이미 열려 있는 화면으로 다른 region_code가 들어오는 경우(홈 → 추천 → 뒤로 → 다른 지역 선택 →
  // 추천)를 위한 동기화. 의존성이 paramCode뿐이라 사용자가 RegionPicker로 바꾼 선택은 건드리지
  // 않고, 값이 같으면 setState가 이전 객체를 그대로 반환해 재조회도 일어나지 않는다.
  useEffect(() => {
    const fromQuery = regionSelectionFromCode(paramRegionCode);
    if (!fromQuery) return;
    setSelectedRegion((prev) => (prev.sigunguCd === fromQuery.sigunguCd ? prev : fromQuery));
  }, [paramRegionCode]);
  const [category, setCategory] = useState<SpotCategory | null>(null);
  // 유형 필터(신규) — spot_type 파라미터. "all"이면 backend 필터 없음과 동일 의미.
  const [spotType, setSpotType] = useState<SpotTypeFilterValue>("all");
  // 정렬(신규). "distance"는 클라이언트 전용 — backend에는 항상 recommended로 보낸다(아래 backendSort).
  const [sortOption, setSortOption] = useState<SortOption>("recommended");
  const [userCoords, setUserCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [locationNotice, setLocationNotice] = useState<string | null>(null);

  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<RecommendResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  // §41(신규) — 카드마다 개별 호출 금지(01-interface-contract.md 부록 R.5) — 목록이 바뀔 때 1회.
  const [ratingSummaries, setRatingSummaries] = useState<Record<string, ReviewSummary>>({});

  // MVP-6(부록 E): 모바일은 지도가 기본 접힘(리스트가 정본, 데이터 절약) — 토글로 편다.
  const [mapOpen, setMapOpen] = useState(false);
  // 1024px+는 항상 지도를 보여준다. 서버 렌더와 첫 클라이언트 렌더는 항상 false로 맞춰
  // 하이드레이션 경고를 막고, mount 후 matchMedia로 실제 폭을 반영한다(RegionPicker 패턴과 동일 원칙).
  const [isDesktop, setIsDesktop] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const update = () => setIsDesktop(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  const showMap = isDesktop || mapOpen;

  // 2026-09-18 — 로컬(sessionStorage) → 없으면 계정 프로필(/onboarding/me). 클라이언트에서만(하이드레이션 안전).
  useEffect(() => {
    let alive = true;
    void resolveOnboardingProfile(loggedIn !== null).then((p) => {
      if (alive) setProfile(p);
    });
    return () => {
      alive = false;
    };
  }, [loggedIn]);

  // "distance"는 backend sort 값이 아니다(클라이언트 전용) — backend에는 recommended로 요청한다.
  const backendSort: "recommended" | "popular" | "calm" =
    sortOption === "distance" ? "recommended" : sortOption;

  useEffect(() => {
    if (profile === undefined) return; // 프로필 확인 전엔 대기(깜빡임 방지)

    const controller = new AbortController();
    setStatus("loading");
    setError(null);

    const payload: RecommendRequest = {
      region_code: selectedRegion.sigunguCd,
      // §C.3: sessionStorage 프로필을 그대로 body에 싣는다. 값을 만들거나 다시 계산하지 않는다.
      profile: profile
        ? {
            tag_vector: profile.tag_vector,
            vector_version: profile.vector_version,
            scoring_weights: profile.scoring_weights,
            tags: profile.tags,
          }
        : null,
      ...(category ? { category } : {}),
      spot_type: spotType,
      sort: backendSort,
      // 부록 F.1-3/F.4-3: 분산·날씨 rerank를 opt-in한다. 백엔드가 아직 rerank를 모르면
      // 필드를 무시하고 기존 MVP-4~6 응답을 그대로 준다(하위호환, 요청 additive).
      // sort가 recommended가 아니면 backend가 balance rerank를 끄므로 popular/calm에서는 빼고 보낸다(weather는 유지).
      rerank: backendSort === "recommended" ? { balance: true, weather: true } : { weather: true },
    };

    fetchRecommendedPlaces(payload, controller.signal)
      .then((res) => {
        setData(res);
        setStatus("success");
        fetchReviewsSummaryBulk(
          "spot",
          res.items.map((s) => s.id),
          controller.signal
        )
          .then((s) => setRatingSummaries(s))
          .catch(() => {
            // 실패해도 조용히 무시 — RatingBadge가 "후기 없음" 상태를 보여준다.
          });
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        // 부록 C.4a — 서버가 프로필 구조 위반으로 400 INVALID_PROFILE 을 주면 "프론트가 프로필을
        // 폐기하고 온보딩을 재유도"하기로 돼 있는데 여기가 빠져 있었다. 그래서 sessionStorage에
        // 낡은/깨진 프로필이 남아 있으면 매 요청이 400 → 에러 화면 → 다시 시도해도 또 400으로
        // 갇혔다(2026-09-03 운영에서 recommend 400 반복 실측). 폐기하면 profile=null 로 바뀌어
        // 이 effect 가 비개인화로 다시 조회하고, 온보딩 유도 배너가 자연스럽게 뜬다.
        if (err instanceof ApiError && err.code === "INVALID_PROFILE" && profile) {
          clearOnboardingResult();
          setProfile(null);
          return;
        }
        setError(
          err instanceof ApiError ? err : new ApiError(0, "UNKNOWN", "추천 목록을 불러오지 못했습니다.")
        );
        setStatus("error");
      });

    return () => controller.abort();
  }, [profile, selectedRegion, category, spotType, backendSort, retryTick]);

  /**
   * 정렬 선택 핸들러. "distance"만 특별 처리한다 — geolocation 권한을 물어보고 성공해야
   * sortOption을 "distance"로 바꾼다. 실패/거부/미지원이면 sortOption을 아예 바꾸지 않으므로
   * 화면은 자동으로 "이전 상태(직전 정렬값, 기본은 추천순)"에 남는다.
   */
  const handleSortSelect = (value: SortOption) => {
    if (value !== "distance") {
      setLocationNotice(null);
      setSortOption(value);
      return;
    }

    if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
      setLocationNotice("위치 권한이 필요해요");
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setUserCoords({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        setLocationNotice(null);
        setSortOption("distance");
      },
      () => {
        setLocationNotice("위치 권한이 필요해요");
      },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 60_000 }
    );
  };

  // 거리순(클라이언트 전용) 재정렬. match_score·congestion 등 서버 값은 건드리지 않고 순서만 바꾼다.
  // location 결측(계약상 없어야 하나 방어적으로) 스팟은 맨 뒤로 보낸다.
  const displayedItems = useMemo(() => {
    const items = data?.items ?? [];
    if (sortOption !== "distance" || !userCoords) return items;
    return [...items].sort((a, b) => {
      const da = safeDistanceKm(userCoords, a.location);
      const db = safeDistanceKm(userCoords, b.location);
      if (da == null && db == null) return 0;
      if (da == null) return 1;
      if (db == null) return -1;
      return da - db;
    });
  }, [data, sortOption, userCoords]);

  // §C.7-4: matched_tags(registry 코드)는 사용자 본인 프로필의 tags 라벨로 치환한다.
  // matched_tags는 정의상 사용자 자신의 프로필과 겹친 값이라, 본인 tags 안에 라벨이 이미 있다.
  const tagLabelMap = useMemo(() => {
    const map: Record<string, string> = {};
    if (profile?.tags) {
      Object.values(profile.tags).forEach((list) => {
        list?.forEach((t) => {
          map[t.value] = t.label;
        });
      });
    }
    return map;
  }, [profile]);

  const retry = () => setRetryTick((t) => t + 1);

  const regionLabel = data?.region.region_name ?? selectedRegion.label;
  // 응답이 오면 backend의 personalized를 신뢰하고, 응답 전에는 로컬 프로필 유무로 잠정 표시한다.
  const showOnboardingCta = data ? !data.personalized : profile === null;

  return (
    <>
      {/* 2026-09-14 대표 지시 — 상단 초록 배너("오늘의 숨은 스팟 / …붐비지 않는 곳을 골랐어요") 제거. */}

      <section className="section" aria-labelledby="recommendHeading">
        <span className="eyebrow-pill eyebrow-pill--azure">프로필 맞춤 추천</span>
        <h2 className="section__title" id="recommendHeading">
          {regionLabel}의 로컬 스팟
        </h2>

        {showOnboardingCta && (
          <div className="recommend-cta-banner">
            <p className="recommend-cta-banner__text">
              취향을 알려주면 매칭 이유까지 붙은 맞춤 추천을 받을 수 있어요.
            </p>
            <Link className="btn btn--mint" href="/onboarding">
              취향 알려주기
            </Link>
          </div>
        )}

        {status === "success" && data?.meta.notice && (
          <div className="board-banner" role="status">
            {data.meta.notice}
          </div>
        )}

        {status === "success" && data && <RerankBanners rerank={data.rerank} items={data.items} />}

        {/* 2026-09-16 대표 지시 — 지역 검색창을 빼고 권역 9개 칩(+내 위치)으로. /course 는 RegionPicker 유지. */}
        <RegionBlockPicker selected={selectedRegion} onSelect={setSelectedRegion} />
        <CategoryFilter selected={category} onSelect={setCategory} />
        <SpotTypeFilter selected={spotType} onSelect={setSpotType} />
        <SortControl selected={sortOption} onSelect={handleSortSelect} locationNotice={locationNotice} />

        {/* MVP-6(부록 E): 모바일 전용 토글 — 데스크톱(1024px+)에서는 CSS로 숨기고 지도가 항상 보인다. */}
        <button
          type="button"
          className="recommend-map-toggle"
          aria-expanded={mapOpen}
          onClick={() => setMapOpen((v) => !v)}
        >
          {mapOpen ? "지도 접기" : "지도로 보기"}
        </button>

        <div className="recommend-layout">
          {/* 2026-09-18 대표 지시("지도 자체를 없애라") — NAVER 지도 아래 쌓던 시도 경계 지도를 뺐다. */}
          <div className={`recommend-layout__map${showMap ? " is-open" : ""}`}>
            {showMap ? (
              <SpotMap items={status === "success" && data ? data.items : []} regionLabel={regionLabel} />
            ) : (
              <div className="spot-map spot-map--placeholder" aria-hidden="true" />
            )}
          </div>

          <div className="recommend-layout__list">
            {status === "loading" && (
              <div className="spot-grid" role="list" aria-label="추천 스팟 불러오는 중">
                {Array.from({ length: SKELETON_COUNT }).map((_, i) => (
                  <SpotCardSkeleton key={i} />
                ))}
              </div>
            )}

            {status === "success" && data && displayedItems.length > 0 && (
              <div className="spot-grid" role="list">
                {displayedItems.map((spot) => {
                  const s = ratingSummaries[String(spot.id)];
                  return (
                    // 부록 F 파트2(F.2-6-1): 저장 토글은 카드 위에 겹쳐 그려야 해서 <Link> 밖의
                    // 래퍼 div로 분리한다(버튼을 <a> 안에 중첩하지 않기 위함).
                    <div key={spot.id} className="spot-card-wrap" role="listitem">
                      {/* 신규(관광지 상세): 스팟 탭 → 상세 화면으로 먼저 이동한다(부록 D §D.7-1 비교 진입은
                          상세 화면의 "핫플과 비교하기" 버튼으로 이관). region_code는 백엔드 응답값을 그대로
                          쿼리로 넘긴다(프론트가 지어내지 않음) — 상세 화면이 비교로 넘어갈 때도 이 값을 그대로 쓴다. */}
                      <Link
                        className="spot-card-link"
                        aria-label={`${spot.name} 상세 보기`}
                        href={`/spot/${spot.id}?region_code=${encodeURIComponent(data.region.region_code)}`}
                      >
                        <RecommendSpotCard
                          spot={spot}
                          tagLabelMap={tagLabelMap}
                          rating={s?.average ?? null}
                          reviewCount={s?.count}
                        />
                      </Link>
                      <SaveToggleButton spot={spot} />
                    </div>
                  );
                })}
              </div>
            )}

            {status === "success" && data && displayedItems.length === 0 && (
              <div className="board-error" role="status">
                <p className="board-error__msg">이 지역·취향에 맞는 스팟이 아직 없어요.</p>
                <p className="board-error__hint">다른 지역이나 카테고리를 선택해보세요.</p>
              </div>
            )}

            {status === "error" && (
              <div className="board-error" role="alert">
                <p className="board-error__msg">{error?.message ?? "추천 목록을 불러오지 못했습니다."}</p>
                <p className="board-error__hint">
                  {error?.status === 404
                    ? "추천 기능이 아직 준비 중이에요(백엔드 연동이 필요해요)."
                    : "백엔드 서버가 켜져 있는지 확인해주세요 (localhost:8000). 잠시 후 다시 시도해주세요."}
                </p>
                <button className="btn btn--coral" type="button" onClick={retry}>
                  다시 시도
                </button>
              </div>
            )}
          </div>
        </div>
      </section>
    </>
  );
}

/**
 * §35 — app/recommend/page.tsx의 Suspense fallback. useSearchParams를 쓰는 클라이언트 컴포넌트는
 * Suspense 경계가 필요하다(Next.js App Router 규약, CompareContent와 동일 패턴).
 * 기존 로딩 화면과 같은 스팟 카드 스켈레톤을 그대로 재사용한다(새 마크업 없음).
 */
export function RecommendLoadingSkeleton() {
  return (
    <section className="section" aria-label="추천 스팟 불러오는 중">
      <div className="spot-grid" role="status" aria-live="polite">
        {Array.from({ length: SKELETON_COUNT }).map((_, i) => (
          <SpotCardSkeleton key={i} />
        ))}
      </div>
    </section>
  );
}
