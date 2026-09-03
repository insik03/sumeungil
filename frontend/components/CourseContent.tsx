"use client";

import { Fragment, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  ApiError,
  CourseLeg,
  CourseResponse,
  OnboardingResult,
  PlaceSearchItem,
  analyzeOnboarding,
  fetchArrangeCourse,
  fetchCourse,
  fetchMyOnboardingProfile,
} from "../lib/api";
import { logout } from "../lib/authStorage";
import { clearOnboardingResult, loadOnboardingResult, saveOnboardingResult } from "../lib/onboardingStorage";
import { loadLastRegion, saveLastRegion } from "../lib/lastRegionStorage";
import { CartSpot, MAX_CART_SIZE, MIN_CART_SIZE, loadCart } from "../lib/courseCartStorage";
import { useLoggedInName } from "../lib/useLoggedInName";
import LoginRequiredGate from "./LoginRequiredGate";
import RegionMapSection from "./RegionMapSection";
import RegionPicker, { SelectedRegion } from "./recommend/RegionPicker";
import CourseMap from "./course/CourseMap";
import CourseStepCard from "./course/CourseStepCard";
import CourseStepPhotoStrip from "./course/CourseStepPhotoStrip";
import SpotSearchBox from "./course/SpotSearchBox";
import ShareCourseButton from "./course/ShareCourseButton";
import SaveCourseButton from "./course/SaveCourseButton";
import { CATEGORY_META, DEFAULT_REGION, regionSelectionFromCode } from "./recommend/constants";
import { OPINION_EXAMPLES } from "./course/opinionExamples";
import { AXIS_LABEL_FALLBACK, LOADING_EXPECTED_SECONDS, LOADING_MESSAGES, RESULT_AXIS_ORDER } from "./onboarding/constants";

type Status = "loading" | "success" | "error";
/** undefined = sessionStorage 확인 전(SSR와 값이 갈리지 않게 첫 렌더는 항상 undefined). */
type ProfileState = OnboardingResult | null | undefined;
/** §25(신규) — "내가 고른 코스" 결과 상태. idle = 아직 "순서 짜주기"를 누르기 전(패널 자체를 그리지 않음). */
type ArrangeStatus = "idle" | Status;
/** §25(신규) — 상단 모드 전환. ai는 기존 동작 그대로, custom은 이번에 새로 추가한 흐름. */
type CourseMode = "ai" | "custom";

const SKELETON_COUNT = 3;
const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  CATEGORY_META.map((c) => [c.value, c.label])
);

/** 미터를 사람이 읽기 쉬운 거리 문구로. 1km 미만은 m, 이상은 소수 1자리 km. */
function formatMeters(meters: number): string {
  if (meters < 1000) return `${Math.round(meters)}m`;
  return `${(meters / 1000).toFixed(1)}km`;
}

/** 도보 아이콘 — 이모지(🚶) 대신 인라인 SVG(발자국). ui-ux-pro-max 체크리스트 근거. */
function WalkIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <ellipse cx="8" cy="7" rx="2.2" ry="3" fill="currentColor" transform="rotate(-15 8 7)" />
      <ellipse cx="16" cy="16" rx="2.2" ry="3" fill="currentColor" transform="rotate(15 16 16)" />
      <circle cx="8" cy="3" r="1.1" fill="currentColor" />
      <circle cx="16" cy="12" r="1.1" fill="currentColor" />
    </svg>
  );
}

/** 차량 아이콘 — 이모지(🚗) 대신 인라인 SVG. ui-ux-pro-max 체크리스트 근거. */
function CarIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M5 11l1.5-4.5A2 2 0 0 1 8.4 5h7.2a2 2 0 0 1 1.9 1.5L19 11h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1a2 2 0 1 1-4 0H8a2 2 0 1 1-4 0H3a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h2Z"
        fill="currentColor"
      />
      <circle cx="7" cy="16" r="1.6" fill="#ffffff" />
      <circle cx="17" cy="16" r="1.6" fill="#ffffff" />
    </svg>
  );
}

/** §28(신규) — 인쇄 버튼 아이콘. 이모지(🖨️) 대신 인라인 SVG(ui-ux-pro-max 체크리스트 근거). */
function PrinterIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M6 9V3h12v6M6 18H4a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1h16a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-2M6 14h12v7H6v-7Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** 코스짜기 의견 입력의 서버 절단 기준(§47.3, 01-interface-contract.md §B.1과 동일 300자). */
const OPINION_MAX_LENGTH = 300;

/**
 * §47.3(신규, 03-design-spec.md) — 코스짜기 상단 의견 입력 로딩. `OnboardingLoading.tsx`(§B.5-3)와
 * 동일한 실측 문구·경과 초 표기(20~30초)를 재사용하되, 이미 `.onboard-card` 위젯 안에 얹히는
 * 인라인 로딩이라 `.onboard-section`/`.onboard-card` 이중 래핑 없이 `.onboard-loading`만 가져온다.
 * "/ask의 5~10초 문구를 베끼면 실제(20~30초)와 달라 이탈한다"는 지시서 경고를 그대로 따랐다.
 */
function CourseOpinionLoading() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setElapsed((t) => t + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  const progress = Math.min(92, Math.round((elapsed / LOADING_EXPECTED_SECONDS) * 92));
  const messageIndex = Math.min(
    LOADING_MESSAGES.length - 1,
    Math.floor(elapsed / (LOADING_EXPECTED_SECONDS / LOADING_MESSAGES.length))
  );
  return (
    <div className="onboard-loading course-opinion__loading" role="status" aria-live="polite">
      <div className="onboard-loading__spinner" aria-hidden="true" />
      <p className="onboard-loading__msg">{LOADING_MESSAGES[messageIndex]}</p>
      <div className="onboard-loading__bar" aria-hidden="true">
        <div className="onboard-loading__bar-fill" style={{ width: `${progress}%` }} />
      </div>
      <p className="onboard-loading__elapsed">
        {elapsed}초 경과 · 보통 20~30초 정도 걸려요. 화면을 벗어나지 말고 잠시만 기다려주세요.
      </p>
    </div>
  );
}

/**
 * 구간 이동 정보 한 줄. walk/car 둘 다 있으면 "·"로 이어 붙이고, 하나도 없으면(Tmap 실패 구간)
 * "이동 정보 없음"으로 표시한다 — 값을 지어내지 않는다(§핸드오프 계약).
 */
function CourseLegInfo({ leg }: { leg: CourseLeg }) {
  const parts: { key: string; node: ReactNode }[] = [];
  if (leg.walk) {
    parts.push({
      key: "walk",
      node: (
        <span className="course-leg__part">
          <WalkIcon />
          도보 {leg.walk.minutes}분({formatMeters(leg.walk.meters)})
        </span>
      ),
    });
  }
  if (leg.car) {
    parts.push({
      key: "car",
      node: (
        <span className="course-leg__part">
          <CarIcon />차 {leg.car.minutes}분
        </span>
      ),
    });
  }

  if (parts.length === 0) {
    return (
      <div className="course-leg course-leg--unknown" role="status">
        이동 정보 없음
      </div>
    );
  }
  return (
    <div className="course-leg">
      {parts.map((p, i) => (
        <Fragment key={p.key}>
          {i > 0 && <span className="course-leg__sep">·</span>}
          {p.node}
        </Fragment>
      ))}
    </div>
  );
}

function CourseTimelineSkeleton() {
  return (
    <ol className="course-timeline" aria-hidden="true">
      {Array.from({ length: SKELETON_COUNT }).map((_, i) => (
        <li key={i} className="course-timeline__item">
          <div className="course-timeline__rail">
            <span className="course-timeline__node course-timeline__node--skeleton" />
            {i < SKELETON_COUNT - 1 && <span className="course-timeline__rail-line" />}
          </div>
          <div className="course-timeline__content">
            <div className="skeleton-bar" style={{ width: "70px", height: "20px", borderRadius: "999px" }} />
            <div className="spot-card spot-card--skeleton" style={{ marginTop: "8px" }}>
              <div className="skeleton-bar" style={{ width: "60px", height: "12px" }} />
              <div className="skeleton-bar" style={{ width: "70%", height: "20px" }} />
              <div className="skeleton-bar" style={{ width: "90%", height: "14px" }} />
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

interface CourseTimelinePanelProps {
  status: Status;
  data: CourseResponse | null;
  error: ApiError | null;
  tagLabelMap: Record<string, string>;
  mapOpen: boolean;
  onToggleMap: () => void;
  showMap: boolean;
  onRetry: () => void;
  /** 결과가 0곳일 때(성공 응답이지만 spots가 빈 배열) 문구 — 모드별로 원인이 달라 문구를 분리한다. */
  emptyMsg: string;
  emptyHint: string;
  /** 네트워크 자체 실패(status 0)일 때만 다른 문구를 보여줄지 판단하는 훅 — AI 모드의 404 분기와 동일 원칙. */
  errorHint: (error: ApiError | null) => string;
  /**
   * §28(신규) — data.ai_title이 null/undefined일 때 쓰는 폴백 헤드라인. 모드별로 "기존 제목"이
   * 달라(AI="{지역} 하루 코스", 커스텀="내가 만든 코스") 호출부가 결정해 넘긴다(지어내지 않음).
   */
  fallbackTitle: string;
  /** 2026-08-17(Phase C) — "코스 저장하기" 호출 시 함께 보낼 mode(ai/custom 요청 구분용). */
  saveMode: "ai" | "custom";
}

/**
 * §25(신규) — 지도 토글 + 타임라인(성공/스켈레톤/빈 결과/에러) 렌더 블록. AI 추천 코스와
 * "내가 고른 코스"(arrange) 둘 다 CourseResponse를 그대로 쓰므로(부록 I §arrange, 스키마 동일)
 * 이 블록 하나를 두 모드가 공유한다 — 타임라인 마크업을 두 번 베끼지 않는다.
 */
function CourseTimelinePanel({
  status,
  data,
  error,
  tagLabelMap,
  mapOpen,
  onToggleMap,
  showMap,
  onRetry,
  emptyMsg,
  emptyHint,
  errorHint,
  fallbackTitle,
  saveMode,
}: CourseTimelinePanelProps) {
  // §28(신규) — 스텝 앵커 id. CourseStepPhotoStrip의 썸네일 클릭 시 이 id로 스크롤 이동한다
  // (course-timeline__item에 그대로 부여, 별도 상태 없이 인덱스로만 생성).
  const stepIds = status === "success" && data ? data.spots.map((_, i) => `course-step-${i}`) : [];
  const totalDistanceKm =
    status === "success" && data && data.total_distance_m != null && data.total_distance_m > 0
      ? (data.total_distance_m / 1000).toFixed(1)
      : null;

  return (
    <>
      <button
        type="button"
        className="recommend-map-toggle"
        aria-expanded={mapOpen}
        onClick={onToggleMap}
      >
        {mapOpen ? "지도 접기" : "지도로 보기"}
      </button>

      {/* §28(신규, 부록 I.12) — 실제로 짜인 코스의 감성 제목 + 메타(지역·스팟 수·총 도보거리) +
          인쇄 버튼. ai_title이 null이면 값을 지어내지 않고 모드별 폴백 제목을 쓴다.
          total_distance_m이 null/0이면 총거리 항목 자체를 숨긴다(0m 표기 금지, 부록 I.12-2). */}
      {status === "success" && data && data.spots.length > 0 && (
        <div className="course-result-head">
          <h3 className="course-result-head__title">{data.ai_title || fallbackTitle}</h3>
          <div className="course-result-head__meta">
            {data.region.region_name && (
              <span className="course-result-head__meta-item">{data.region.region_name}</span>
            )}
            <span className="course-result-head__meta-item">{data.spots.length}곳</span>
            {totalDistanceKm && (
              <span className="course-result-head__meta-item">총 도보 {totalDistanceKm}km</span>
            )}
          </div>
          <div className="course-result-head__actions">
            <button type="button" className="course-print-btn" onClick={() => window.print()}>
              <PrinterIcon />
              코스 인쇄하기
            </button>
            {/* §41(신규) — 코스 공유하기. AI 추천/내 코스 만들기 두 모드 모두 이 패널을 공유하므로
                (부록 I §arrange 응답이 CourseResponse와 동일 스키마) 여기 한 곳만 붙이면 두 모드
                모두 자동으로 적용된다(§25 comment와 동일한 "패널 재사용" 근거). */}
            <ShareCourseButton course={data} defaultTitle={data.ai_title || fallbackTitle} />
            {/* 2026-08-17(Phase C) — 계정에 저장(공개 공유와 별개). 위와 같은 이유로 이 한
                곳에만 붙이면 AI 추천/내 코스 만들기 둘 다 자동 적용된다. */}
            <SaveCourseButton
              course={data}
              regionCode={data.region.region_code}
              mode={saveMode}
            />
          </div>
        </div>
      )}

      {/* §26(신규) — arrange/recommend 공통 additive 필드(ai_summary). null/undefined면(LLM 실패·
          미배포) 박스를 아예 그리지 않는다(지어내지 않음). 스팟 상세의 .ai-summary 박스 문법을
          그대로 재사용한다(SpotDetailContent.tsx §23 근거) — 새 클래스를 만들지 않았다. */}
      {status === "success" && data?.ai_summary && (
        <div className="ai-summary">
          <span className="ai-summary__label">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z"
                fill="currentColor"
              />
            </svg>
            AI 코스 요약
          </span>
          <p className="ai-summary__text">{data.ai_summary}</p>
        </div>
      )}

      {/* §28(신규, 06-deep-audit-gap-plan §2-B B-9) — 코스 전체를 사진으로 훑는 가로 스트립.
          spots가 2곳 미만이면 컴포넌트 내부에서 null을 반환한다(중복 가드 없이 그대로 위임). */}
      {status === "success" && data && (
        <CourseStepPhotoStrip spots={data.spots} stepIds={stepIds} />
      )}

      <div className="recommend-layout">
        <div className={`recommend-layout__map${showMap ? " is-open" : ""}`}>
          {showMap ? (
            <CourseMap
              spots={status === "success" && data ? data.spots : []}
              legs={status === "success" && data ? data.legs : []}
              regionLabel={data?.region.region_name ?? ""}
            />
          ) : (
            <div className="spot-map spot-map--placeholder" aria-hidden="true" />
          )}
        </div>

        <div className="recommend-layout__list">
          {status === "loading" && <CourseTimelineSkeleton />}

          {status === "success" && data && data.spots.length > 0 && (
            <ol className="course-timeline">
              {data.spots.map((spot, i) => {
                const isLastSpot = i === data.spots.length - 1;
                const leg = data.legs[i];
                return (
                  <li key={spot.id} id={stepIds[i]} className="course-timeline__item">
                    <div className="course-timeline__rail">
                      <span className="course-timeline__node">{i + 1}</span>
                      {!isLastSpot && <span className="course-timeline__rail-line" />}
                    </div>
                    <div className="course-timeline__content">
                      <span className="course-timeline__slot-badge">{spot.slot_label}</span>
                      <div className="spot-card-wrap">
                        <Link
                          className="spot-card-link"
                          aria-label={`${spot.name} 상세 보기`}
                          href={`/spot/${spot.id}?region_code=${encodeURIComponent(data.region.region_code)}`}
                        >
                          <CourseStepCard spot={spot} tagLabelMap={tagLabelMap} />
                        </Link>
                      </div>
                      {leg && <CourseLegInfo leg={leg} />}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}

          {status === "success" && data && data.spots.length === 0 && (
            <div className="board-error" role="status">
              <p className="board-error__msg">{emptyMsg}</p>
              <p className="board-error__hint">{emptyHint}</p>
            </div>
          )}

          {status === "error" && (
            <div className="board-error" role="alert">
              <p className="board-error__msg">{error?.message ?? "코스를 불러오지 못했어요."}</p>
              <p className="board-error__hint">{errorHint(error)}</p>
              <button className="btn btn--coral" type="button" onClick={onRetry}>
                다시 시도
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

/** AI 모드 에러 안내 — 기존 CourseContent 로직 그대로(무변경). */
function aiErrorHint(error: ApiError | null): string {
  return error?.status === 404
    ? "코스 추천 기능이 아직 준비 중이에요(백엔드 연동이 필요해요)."
    : "백엔드 서버가 켜져 있는지 확인해주세요 (localhost:8000). 잠시 후 다시 시도해주세요.";
}

/** §25/§26 — "내 코스 만들기"(arrange) 에러 안내. 400 INVALID_SPOTS 등은 backend 메시지를 그대로 보여준다. */
function customErrorHint(error: ApiError | null): string {
  if (error?.status === 0) {
    return "백엔드 서버가 켜져 있는지 확인해주세요 (localhost:8000). 잠시 후 다시 시도해주세요.";
  }
  return "추가한 스팟을 확인하고 다시 시도해주세요.";
}

/**
 * AI 추천 코스 / 내 코스 만들기(/course) 화면. 헤더의 "AI 여행 경로" 메뉴 진입점.
 * §25→§26(2026-07-29 재작업) — 상단 세그먼트로 두 모드를 전환한다.
 *   - AI 추천 코스: 기존 동작 그대로(무변경). sessionStorage의 OnboardingResult를 그대로
 *     재전송한다(조작·재계산 금지). RegionPicker로 지역을 고른다.
 *   - 내 코스 만들기: 화면 내 useState(builderSpots)만으로 목록을 관리한다(저장 없음, §26).
 *     SpotSearchBox로 검색해 추가하고, id만 POST /api/v1/courses/arrange로 넘겨 순서를 받는다
 *     (부록 I §arrange) — region_code 없이 spot_ids만 보낸다(스팟들이 이미 구체적 위치를 갖고
 *     있어 지역 선택이 필요 없다). 응답 스키마가 CourseResponse와 동일해 위 CourseTimelinePanel을
 *     그대로 재사용한다. 마운트 시 1회만 courseCartStorage(스팟 상세/저장 목록의 "코스에 담기"
 *     버튼이 쓰는 localStorage)를 초기값으로 흡수한다 — 그 이후로는 이 화면 상태와 저장소가
 *     서로 동기화되지 않는다(§26 설계 결정, 03-design-spec.md §26 참고).
 * congestion/match_score/slot_label 순서는 두 모드 모두 서버 값 그대로 표시만 한다.
 *
 * §35(2026-07-31, 03-design-spec.md — 지역 컨텍스트 전파, 백로그 D21) — URL `?region_code=`를 AI
 * 추천 코스 모드의 초기 지역으로 소비한다(RecommendContent와 완전히 동일한 규칙: 숫자 5자리가
 * 아니면 무시하고 기본 지역 유지, 쿼리는 초기값 주입일 뿐이라 이후 RegionPicker 선택이 우선).
 * "내 코스 만들기" 모드는 애초에 region_code를 쓰지 않으므로(spot_ids만 전송) 영향이 없다.
 */
export default function CourseContent() {
  const searchParams = useSearchParams();
  const paramRegionCode = searchParams.get("region_code");
  // 2026-08-17(대표 지시) — AI 코스짜기(추천·직접만들기 둘 다)는 로그인 필수.
  const loggedIn = useLoggedInName();

  // 마이페이지의 "내 코스 만들기" 타일이 ?mode=custom으로 바로 이 탭에 진입시킨다.
  const [mode, setMode] = useState<CourseMode>(searchParams.get("mode") === "custom" ? "custom" : "ai");

  const [profile, setProfile] = useState<ProfileState>(undefined);
  // 지연 초기화 — 첫 조회부터 쿼리 지역으로 나간다(기본 지역 조회 후 재조회하는 이중 호출 방지).
  // URL 쿼리는 SSR에서도 동일하게 읽혀 하이드레이션이 안전하다 — 마지막으로 고른 지역(세션
  // 기억)은 sessionStorage라 서버에서 못 읽으므로 초기 state에 넣지 않는다(하이드레이션
  // 에러, 실측으로 확인된 버그 재발 방지) — 아래 effect에서 mount 후 반영한다.
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
  // useState 세터와 동일한 시그니처(값 또는 함수형 업데이터) 유지 — 아래 §35 동기화 effect의
  // 함수형 업데이터 호출부를 그대로 쓸 수 있게 한다. 실제로 바뀔 때만 기억해둔다.
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

  // 화면이 떠 있는 상태로 다른 region_code가 들어올 때만 동기화한다(사용자의 RegionPicker 선택은
  // paramCode가 그대로면 effect가 다시 돌지 않아 덮이지 않는다).
  useEffect(() => {
    const fromQuery = regionSelectionFromCode(paramRegionCode);
    if (!fromQuery) return;
    setSelectedRegion((prev) => (prev.sigunguCd === fromQuery.sigunguCd ? prev : fromQuery));
  }, [paramRegionCode]);

  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<CourseResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [retryTick, setRetryTick] = useState(0);

  // §26(재작업) — "내 코스 만들기". builderSpots는 null=아직 초기값을 흡수하기 전(하이드레이션
  // 깜빡임 방지, §25의 cartSpots와 동일 원칙), 이후로는 검색 추가/제거만으로 이 배열을 바꾼다
  // (localStorage에 다시 쓰지 않는다 — 대표 지시 "저장 X"). arrangeStatus는 "idle"=아직
  // "순서 짜주기"를 누르기 전(패널을 아예 그리지 않는다).
  const [builderSpots, setBuilderSpots] = useState<CartSpot[] | null>(null);
  const [arrangeStatus, setArrangeStatus] = useState<ArrangeStatus>("idle");
  const [arrangeData, setArrangeData] = useState<CourseResponse | null>(null);
  const [arrangeError, setArrangeError] = useState<ApiError | null>(null);

  // §47.3(신규) — AI 모드 상단 "어떤 여행을 원하세요?" 의견 입력. 컨시어지 축약판 — 신규 API
  // 없이 POST /onboarding/analyze(text)를 그대로 재사용하고, 성공하면 profile을 갱신해 아래
  // fetchCourse effect([profile, ...] 의존성)가 자동으로 다시 코스를 짜게 한다.
  const [opinionText, setOpinionText] = useState("");
  const [opinionStatus, setOpinionStatus] = useState<ArrangeStatus>("idle");
  const [opinionError, setOpinionError] = useState<ApiError | null>(null);
  const opinionAbortRef = useRef<AbortController | null>(null);

  // 마운트 시 1회만 courseCartStorage를 초기값으로 흡수한다(§26) — 이후 다른 화면에서 "코스에
  // 담기"를 눌러도 이 화면이 열려 있는 동안은 반영되지 않는다(화면을 새로고침/재진입하면 반영).
  useEffect(() => {
    setBuilderSpots(loadCart());
  }, []);

  // 추천 화면(MVP-6 부록 E)과 동일한 모바일 접이식 지도 패턴 — 리스트(타임라인)가 정본.
  // 두 모드가 같은 지도 열림 상태를 공유한다(동시에 한쪽만 화면에 보이므로 문제 없음).
  const [mapOpen, setMapOpen] = useState(false);
  const [isDesktop, setIsDesktop] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const update = () => setIsDesktop(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  const showMap = isDesktop || mapOpen;

  // 2026-08-17(Phase C) — 로그인 중이면 계정에 저장된 취향 프로필을 우선 쓴다(재로그인·
  // 다른 기기에서도 유지). 서버에 없으면(온보딩을 아직 안 함) 이번 세션 sessionStorage로
  // 폴백한다. 비로그인이면(사실 이 화면 자체가 게이트로 막혀 있지만 방어적으로) 기존대로
  // sessionStorage만 본다.
  useEffect(() => {
    if (!loggedIn) {
      setProfile(loadOnboardingResult()?.result ?? null);
      return;
    }
    let cancelled = false;
    fetchMyOnboardingProfile()
      .then((serverProfile) => {
        if (cancelled) return;
        setProfile(serverProfile ?? loadOnboardingResult()?.result ?? null);
      })
      .catch(() => {
        if (cancelled) return;
        setProfile(loadOnboardingResult()?.result ?? null);
      });
    return () => {
      cancelled = true;
    };
  }, [loggedIn]);

  useEffect(() => {
    if (profile === undefined) return; // 프로필 확인 전엔 대기(깜빡임 방지)
    if (!loggedIn) return; // 2026-08-17: 비로그인이면 화면 자체가 게이트로 바뀐다(아래 return문)

    const controller = new AbortController();
    setStatus("loading");
    setError(null);

    fetchCourse(
      selectedRegion.sigunguCd,
      profile
        ? {
            tag_vector: profile.tag_vector,
            vector_version: profile.vector_version,
            scoring_weights: profile.scoring_weights,
            tags: profile.tags,
          }
        : null,
      controller.signal
    )
      .then((res) => {
        setData(res);
        setStatus("success");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && err.status === 401) {
          // 세션이 도중에 만료됐다 — 로컬 캐시를 정리하면 화면이 자동으로 로그인
          // 게이트로 돌아간다(useLoggedInName()이 null로 바뀜, 위 return문 참고).
          logout();
          setStatus("loading");
          return;
        }
        // 부록 C.4a — 프로필 구조 위반(400 INVALID_PROFILE)이면 로컬 프로필을 폐기하고
        // 비개인화로 다시 조회한다(RecommendContent.tsx와 같은 처리, 2026-09-03). 그대로 두면
        // 낡은 sessionStorage 프로필 때문에 "다시 시도"를 눌러도 영영 400이다.
        if (err instanceof ApiError && err.code === "INVALID_PROFILE" && profile) {
          clearOnboardingResult();
          setProfile(null);
          return;
        }
        setError(
          err instanceof ApiError ? err : new ApiError(0, "UNKNOWN", "추천 코스를 불러오지 못했습니다.")
        );
        setStatus("error");
      });

    return () => controller.abort();
  }, [profile, selectedRegion, retryTick, loggedIn]);

  // §C.7-4와 동일 원칙: matched_tags(registry 코드) → 사용자 본인 프로필 tags 라벨로 치환.
  // arrange 결과(match_reasons가 있다면)도 같은 프로필 라벨을 그대로 재사용한다.
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

  // §47.3 — 의견 제출 성공 후 "이렇게 이해했어요" 칩에 쓸 축 목록(비어있지 않은 축만).
  const opinionUnderstoodAxes = useMemo(
    () => RESULT_AXIS_ORDER.filter((axis) => (profile?.tags[axis]?.length ?? 0) > 0),
    [profile]
  );

  const retry = () => setRetryTick((t) => t + 1);

  const regionLabel = data?.region.region_name ?? selectedRegion.label;
  const showOnboardingCta = profile === null;

  const hasProfile = Boolean(profile);
  const canSubmitOpinion = opinionText.trim().length > 0 && opinionStatus !== "loading";

  const handleSubmitOpinion = () => {
    const trimmed = opinionText.trim();
    if (!trimmed || opinionStatus === "loading") return;
    setOpinionStatus("loading");
    setOpinionError(null);
    const controller = new AbortController();
    opinionAbortRef.current = controller;
    analyzeOnboarding({ text: trimmed, region_code: selectedRegion.sigunguCd }, controller.signal)
      .then((res) => {
        // §B.5-7과 동일 원칙 — sessionStorage 갱신 + profile state 갱신. profile이 바뀌면
        // 위 fetchCourse effect가 이미 [profile, ...] 의존성으로 자동 재호출한다(재구현 불필요).
        saveOnboardingResult(res);
        setProfile(res);
        setOpinionStatus("success");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return; // 사용자가 직접 취소
        if (err instanceof ApiError && err.status === 401) {
          logout();
          setOpinionStatus("idle");
          return;
        }
        setOpinionError(
          err instanceof ApiError ? err : new ApiError(0, "UNKNOWN", "의견을 반영하지 못했습니다.")
        );
        setOpinionStatus("error");
      });
  };

  const handleCancelOpinionLoading = () => {
    opinionAbortRef.current?.abort();
    setOpinionStatus("idle");
  };

  const builderCount = builderSpots?.length ?? 0;
  const canArrange = builderCount >= MIN_CART_SIZE && arrangeStatus !== "loading";
  const builderIds = useMemo(() => builderSpots?.map((s) => s.id) ?? [], [builderSpots]);

  // 목록이 바뀌면(추가/제거) 이미 받아온 결과가 낡은 정보가 된다 — 다시 눌러야 하게 초기화한다
  // (§25.4 원칙 그대로 승계).
  const resetArrangeResult = () => {
    setArrangeStatus("idle");
    setArrangeData(null);
    setArrangeError(null);
  };

  // §26 — 검색 결과 선택 시 호출. id dedupe + MAX_CART_SIZE(8곳) 상한은 SpotSearchBox가 이미
  // existingIds/atMax로 막지만, 방어적으로 여기서도 한 번 더 확인한다(다른 진입점 추가 대비).
  const handleAddSpot = (item: PlaceSearchItem) => {
    setBuilderSpots((prev) => {
      const list = prev ?? [];
      if (list.some((s) => s.id === item.id) || list.length >= MAX_CART_SIZE) return list;
      return [
        ...list,
        {
          id: item.id,
          name: item.name,
          category: item.category,
          region_code: item.region_code,
          region_name: item.region_name,
        },
      ];
    });
    resetArrangeResult();
  };

  const handleRemoveFromBuilder = (id: number) => {
    setBuilderSpots((prev) => (prev ? prev.filter((s) => s.id !== id) : prev));
    resetArrangeResult();
  };

  const handleArrange = () => {
    if (!loggedIn) return; // 방어적 가드 — 버튼은 로그인 상태에서만 렌더된다(아래 return문)
    if (!builderSpots || builderSpots.length < MIN_CART_SIZE) return;
    setArrangeStatus("loading");
    setArrangeError(null);
    fetchArrangeCourse(builderSpots.map((s) => s.id))
      .then((res) => {
        setArrangeData(res);
        setArrangeStatus("success");
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          // 세션이 도중에 만료됐다 — 로컬 캐시를 정리하면 화면이 자동으로 로그인
          // 게이트로 돌아간다(useLoggedInName()이 null로 바뀜, 위 return문 참고).
          logout();
          setArrangeStatus("idle");
          return;
        }
        setArrangeError(
          err instanceof ApiError ? err : new ApiError(0, "UNKNOWN", "코스 순서를 짜지 못했습니다.")
        );
        setArrangeStatus("error");
      });
  };

  return (
    <>
      <section className="onboard-hero" aria-label="코스 만들기 소개">
        <span className="hero__eyebrow">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M12 2l2.2 6.8H21l-5.6 4.1 2.2 6.9L12 15.8 6.4 19.8l2.2-6.9L3 8.8h6.8L12 2z"
              fill="currentColor"
            />
          </svg>
          {mode === "ai" ? "AI 추천 코스" : "내 코스 만들기"}
        </span>
        {mode === "ai" ? (
          <>
            <h1 className="onboard-hero__title">
              {regionLabel} 하루,
              <br />
              순서대로 짜드렸어요
            </h1>
            <p className="onboard-hero__sub">
              {profile
                ? "온보딩에서 알려주신 취향을 바탕으로 아침부터 저녁까지 이동 동선을 붙여 코스를 짰어요."
                : "지금은 예상 혼잡도가 낮은 순으로 하루 코스를 짜드리고 있어요. 취향을 알려주시면 더 꼭 맞는 코스로 바꿔드려요."}
            </p>
          </>
        ) : (
          <>
            <h1 className="onboard-hero__title">
              가고 싶은 곳을 검색해서,
              <br />
              순서와 AI 요약까지 받아보세요
            </h1>
            <p className="onboard-hero__sub">
              가게·관광지 이름으로 검색해 코스에 추가하면, 이동 동선을 붙여 하루 코스로 이어드리고
              AI가 코스를 짧게 요약해드려요. 2곳 이상 추가하면 순서를 짤 수 있어요.
            </p>
          </>
        )}
      </section>

      {!loggedIn ? (
        <LoginRequiredGate
          title="로그인이 필요해요"
          message="AI 코스짜기는 로그인 후 이용할 수 있어요. 로그인하면 만든 코스를 저장해 다시 볼 수도 있어요."
        />
      ) : (
      <>
      {/* 2026-08-29(대표 지시) — "지도를 AI 코스짜기에도 넣어줘". 처음엔 로그인 게이트보다
          위(미리보기)에 뒀는데 대표가 "로그인해야 볼 수 있게 해야지"로 재지시 — 로그인
          이후에만 보이도록 이 안(게이트 통과 후 분기)으로 옮겼다. 홈과 같은 컴포넌트 재사용은
          그대로(RegionMapSection.tsx, 새로 안 만듦). */}
      <RegionMapSection regionCode={selectedRegion.sigunguCd} />
      <section className="section" aria-labelledby="courseHeading">
        <div className="course-mode-switch" role="tablist" aria-label="코스 만들기 방식">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "ai"}
            className={`course-mode-switch__tab${mode === "ai" ? " is-active" : ""}`}
            onClick={() => setMode("ai")}
          >
            AI 추천 코스
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "custom"}
            className={`course-mode-switch__tab${mode === "custom" ? " is-active" : ""}`}
            onClick={() => setMode("custom")}
          >
            내 코스 만들기{builderCount > 0 ? ` (${builderCount})` : ""}
          </button>
        </div>

        {mode === "ai" && (
          <>
            <span className="eyebrow-pill eyebrow-pill--azure">AI 추천 코스</span>
            <h2 className="section__title" id="courseHeading">
              {regionLabel} 하루 코스
            </h2>

            {/* §47.3(신규) — 컨시어지 축약판. 신규 API·LLM 경로 없음(POST /onboarding/analyze
                재사용). 정식 온보딩(축 전체) 배너는 그대로 아래 두고, 이 입력은 "지금 한 줄만
                말하고 바로 반영" 경로로 보완한다. */}
            <div className="onboard-card course-opinion">
              <label className="onboard-label" htmlFor="courseOpinion">
                어떤 여행을 원하세요? {hasProfile && "(선택)"}
              </label>
              <textarea
                id="courseOpinion"
                className="onboard-textarea course-opinion__textarea"
                rows={2}
                maxLength={OPINION_MAX_LENGTH}
                placeholder="예: 아이랑 갈만한 비 오는 날 실내 명소 위주로"
                value={opinionText}
                onChange={(e) => setOpinionText(e.target.value)}
                disabled={opinionStatus === "loading"}
              />
              <div className="chip-row" role="group" aria-label="예시">
                {OPINION_EXAMPLES.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    className="onboard-chip"
                    onClick={() => setOpinionText(ex)}
                    disabled={opinionStatus === "loading"}
                  >
                    {ex}
                  </button>
                ))}
              </div>
              <div className="onboard-submit">
                <button
                  type="button"
                  className="btn btn--mint"
                  disabled={!canSubmitOpinion}
                  onClick={handleSubmitOpinion}
                >
                  {opinionStatus === "loading" ? "코스 다시 짜는 중…" : "이 의견으로 코스 다시 짜기"}
                </button>
              </div>

              {opinionStatus === "loading" && (
                <>
                  <CourseOpinionLoading />
                  <button
                    type="button"
                    className="onboard-loading__cancel"
                    onClick={handleCancelOpinionLoading}
                  >
                    취소하고 다시 입력하기
                  </button>
                </>
              )}

              {opinionStatus === "error" && (
                <p className="onboard-validation" role="alert">
                  {opinionError?.message ?? "의견을 반영하지 못했어요. 잠시 후 다시 시도해주세요."}
                </p>
              )}

              {opinionStatus === "success" && opinionUnderstoodAxes.length > 0 && (
                <div className="course-opinion__understood">
                  <h3 className="onboard-axis-group__label">이렇게 이해했어요</h3>
                  {opinionUnderstoodAxes.map((axis) => (
                    <div className="onboard-axis-group" key={axis}>
                      <span className="onboard-axis-group__label">{AXIS_LABEL_FALLBACK[axis]}</span>
                      <div className="onboard-tag-row">
                        {profile?.tags[axis]!.map((tag) => (
                          <span key={tag.value} className="onboard-tag">
                            #{tag.label}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {showOnboardingCta && (
              <div className="recommend-cta-banner">
                <p className="recommend-cta-banner__text">
                  취향을 알려주면 매칭 이유까지 붙은 맞춤 코스를 받을 수 있어요.
                </p>
                <Link className="btn btn--mint" href="/onboarding">
                  취향 알려주기
                </Link>
              </div>
            )}

            {status === "success" && data?.notice && (
              <div className="board-banner" role="status">
                {data.notice}
              </div>
            )}

            <RegionPicker selected={selectedRegion} onSelect={setSelectedRegion} />

            <CourseTimelinePanel
              status={status}
              data={data}
              error={error}
              tagLabelMap={tagLabelMap}
              mapOpen={mapOpen}
              onToggleMap={() => setMapOpen((v) => !v)}
              showMap={showMap}
              onRetry={retry}
              emptyMsg="이 지역에는 아직 짜드릴 수 있는 코스가 없어요."
              emptyHint="다른 지역을 선택해보세요."
              errorHint={aiErrorHint}
              fallbackTitle={`${regionLabel} 하루 코스`}
              saveMode="ai"
            />
          </>
        )}

        {mode === "custom" && (
          <>
            <span className="eyebrow-pill eyebrow-pill--azure">내 코스 만들기</span>
            <h2 className="section__title" id="courseHeading">
              가게·관광지를 검색해서 코스 만들기
            </h2>

            <SpotSearchBox
              existingIds={builderIds}
              atMax={builderCount >= MAX_CART_SIZE}
              onAdd={handleAddSpot}
            />

            {builderSpots === null ? null : builderSpots.length === 0 ? (
              <div className="board-error" role="status">
                <p className="board-error__msg">아직 추가한 스팟이 없어요.</p>
                <p className="board-error__hint">
                  위 검색창에서 가게·관광지 이름을 검색해 추가해보세요.
                </p>
              </div>
            ) : (
              <>
                <ul className="course-cart-list" aria-label="추가한 스팟 목록">
                  {builderSpots.map((spot) => (
                    <li key={spot.id} className="course-cart-list__item">
                      <div className="course-cart-list__info">
                        <span className="course-cart-list__category">
                          {CATEGORY_LABEL[spot.category] ?? spot.category}
                        </span>
                        <span className="course-cart-list__name">{spot.name}</span>
                      </div>
                      <button
                        type="button"
                        className="course-cart-list__remove"
                        aria-label={`${spot.name} 코스에서 빼기`}
                        onClick={() => handleRemoveFromBuilder(spot.id)}
                      >
                        <svg
                          width="16"
                          height="16"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2.5"
                          strokeLinecap="round"
                          aria-hidden="true"
                        >
                          <path d="M6 6l12 12M18 6L6 18" />
                        </svg>
                      </button>
                    </li>
                  ))}
                </ul>

                {builderCount < MIN_CART_SIZE && (
                  <p className="course-cart-hint" role="status">
                    2곳 이상 추가해주세요. 위 검색창에서 더 추가할 수 있어요.
                  </p>
                )}
                {builderCount >= MAX_CART_SIZE && (
                  <p className="course-cart-hint" role="status">
                    최대 {MAX_CART_SIZE}곳까지 추가할 수 있어요.
                  </p>
                )}

                <button
                  type="button"
                  className="btn btn--coral btn--lg btn--block course-cart-arrange-btn"
                  disabled={!canArrange}
                  onClick={handleArrange}
                >
                  {arrangeStatus === "loading" ? "순서 짜는 중…" : "순서 짜주기"}
                </button>
              </>
            )}

            {arrangeStatus !== "idle" && (
              <>
                {arrangeStatus === "success" && arrangeData?.notice && (
                  <div className="board-banner" role="status">
                    {arrangeData.notice}
                  </div>
                )}
                <CourseTimelinePanel
                  status={arrangeStatus}
                  data={arrangeData}
                  error={arrangeError}
                  tagLabelMap={tagLabelMap}
                  mapOpen={mapOpen}
                  onToggleMap={() => setMapOpen((v) => !v)}
                  showMap={showMap}
                  onRetry={handleArrange}
                  emptyMsg="순서를 짤 수 있는 스팟이 없어요."
                  emptyHint="추가한 스팟 목록을 확인하고 다시 시도해주세요."
                  errorHint={customErrorHint}
                  fallbackTitle="내가 만든 코스"
                  saveMode="custom"
                />
              </>
            )}
          </>
        )}
      </section>
      </>
      )}
    </>
  );
}

/**
 * §35 — app/course/page.tsx의 Suspense fallback. useSearchParams를 쓰는 클라이언트 컴포넌트는
 * Suspense 경계가 필요하다(Next.js App Router 규약). 기존 코스 타임라인 스켈레톤을 그대로
 * 재사용한다(새 마크업 없음).
 */
export function CourseLoadingSkeleton() {
  return (
    <section className="section" aria-label="코스 불러오는 중">
      <div role="status" aria-live="polite">
        <CourseTimelineSkeleton />
      </div>
    </section>
  );
}
