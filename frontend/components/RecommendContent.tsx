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
import { loadOnboardingResult } from "../lib/onboardingStorage";
import { safeDistanceKm } from "../lib/geo";
import CategoryFilter from "./recommend/CategoryFilter";
import RegionPicker, { SelectedRegion } from "./recommend/RegionPicker";
import RecommendSpotCard, { SpotCardSkeleton } from "./recommend/SpotCard";
import SaveToggleButton from "./recommend/SaveToggleButton";
import RerankBanners from "./recommend/RerankBanners";
import SpotMap from "./recommend/SpotMap";
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
  const paramRegionCode = searchParams.get("region_code");

  const [profile, setProfile] = useState<ProfileState>(undefined);
  // 지연 초기화 — 첫 렌더부터 쿼리 지역으로 시작한다(기본 지역으로 한 번 조회한 뒤 다시 조회하는
  // 이중 호출을 피하기 위함). 유효하지 않은 쿼리면 기존 기본 지역 그대로.
  const [selectedRegion, setSelectedRegion] = useState<SelectedRegion>(
    () =>
      regionSelectionFromCode(paramRegionCode) ?? {
        sigunguCd: DEFAULT_REGION.sigunguCd,
        label: DEFAULT_REGION.label,
      }
  );

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

  // sessionStorage는 클라이언트에서만 읽는다 — 서버 렌더와 첫 클라이언트 렌더를 일치시켜 하이드레이션 경고를 막는다.
  useEffect(() => {
    setProfile(loadOnboardingResult()?.result ?? null);
  }, []);

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
            // 실패해도 조용히 무시 — RatingBadge가 "-"/0 폴백을 그대로 보여준다.
          });
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
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
      <section className="onboard-hero" aria-label="추천 소개">
        <span className="hero__eyebrow">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M12 2l2.2 6.8H21l-5.6 4.1 2.2 6.9L12 15.8 6.4 19.8l2.2-6.9L3 8.8h6.8L12 2z"
              fill="currentColor"
            />
          </svg>
          오늘의 숨은 스팟
        </span>
        <h1 className="onboard-hero__title">
          {regionLabel}에서
          <br />
          붐비지 않는 곳을 골랐어요
        </h1>
        <p className="onboard-hero__sub">
          {profile
            ? "온보딩에서 알려주신 취향을 바탕으로 어울리는 순서대로 정렬했어요."
            : "지금은 예상 혼잡도가 낮은 순으로 보여드리고 있어요. 취향을 알려주시면 더 꼭 맞는 순서로 바꿔드려요."}
        </p>
      </section>

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

        <RegionPicker selected={selectedRegion} onSelect={setSelectedRegion} />
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
 * Suspense 경계가 필요하다(Next.js App Router 규약, AskContent/CompareContent와 동일 패턴).
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
