"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ApiError, CompareRequest, CompareResponse, OnboardingResult, fetchCompare } from "../../lib/api";
import { clearOnboardingResult, loadOnboardingResult } from "../../lib/onboardingStorage";
import { DEFAULT_REGION } from "../recommend/constants";
import { SIDO_REGIONS } from "../regions/constants";
import RegionDropdown from "../regions/RegionDropdown";
import CongestionValue from "./CongestionValue";
import FitValue from "./FitValue";
import CompareCard from "./CompareCard";

type Status = "loading" | "success" | "unavailable" | "error";
/** undefined = sessionStorage 확인 전(SSR와 값이 갈리지 않게 첫 렌더는 항상 undefined, RecommendContent와 동일 패턴). */
type ProfileState = OnboardingResult | null | undefined;

/**
 * §D.7-4 델타 표기 — congestion_diff_pct로 "↓{abs}% 낮음" 배지, null은 "비교 불가" 회색.
 * 양수(숨은길이 더 붐빔, 이례적)는 있는 그대로 "높음"으로 표기한다 — 과장·왜곡 없이 사실만.
 */
/**
 * 2026-09-16(오버투어리즘 검토 P1-c) — "34% 낮음"은 **상대 감소율**(hidden−hotspot)/hotspot 이라
 * 퍼센트포인트 차이와 헷갈린다. 원본 index 차이(congestion_diff, %p)를 함께 적는다.
 */
function formatCongestionDelta(pct: number | null, diff: number | null): { text: string; toneClass: string } {
  if (pct == null) return { text: "예상 혼잡도 비교 불가", toneClass: "delta-badge--neutral" };
  const pp = diff == null ? "" : ` (${Math.abs(Math.round(diff))}%p 차이)`;
  if (pct < 0) return { text: `예상 혼잡도 ${Math.abs(pct)}% 낮음${pp}`, toneClass: "delta-badge--calm" };
  if (pct > 0) return { text: `예상 혼잡도 ${pct}% 높음${pp}`, toneClass: "delta-badge--hot" };
  return { text: "예상 혼잡도 차이 없음", toneClass: "delta-badge--neutral" };
}

/**
 * 비교 화면(MVP-5, 01-interface-contract.md 부록 D) 오케스트레이터.
 * - 진입: 추천 화면의 스팟 탭에서 hidden_id·region_code를 쿼리로 받는다(§D.7-1). hotspot는 항상 auto(backend 소유).
 * - profile은 RecommendContent와 동일하게 sessionStorage를 그대로 재전송한다(조작·재계산 금지).
 * - 404 COMPARE_UNAVAILABLE은 에러가 아니라 "이 지역은 비교 준비 중"으로 부드럽게 처리한다(§D.5).
 */
export default function CompareContent() {
  const searchParams = useSearchParams();
  const hiddenIdParam = searchParams.get("hidden_id");
  const parsedHiddenId = hiddenIdParam ? Number(hiddenIdParam) : NaN;
  const hiddenId = Number.isFinite(parsedHiddenId) ? parsedHiddenId : null;
  const queryRegion = searchParams.get("region_code");

  // 부록 D.7(2026-08-01) — /compare 를 **독립 목적지**로 쓸 수 있게 지역 선택을 붙인다.
  // 종전엔 스팟 상세에서 hidden_id 와 함께 들어오는 경유 화면이라 지역이 쿼리로만 정해졌고,
  // 쿼리 없이 들어오면 항상 기본 지역(부산 해운대) 고정이었다. GNB 진입점을 새로 다는 이상
  // 사용자가 지역을 바꿀 수 있어야 한다. hidden_id 로 들어온 경우(특정 스팟과의 비교)는
  // 그 스팟의 지역이 곧 맥락이므로 선택기를 띄우지 않는다.
  const [pickedRegion, setPickedRegion] = useState<string | null>(null);
  const regionCode = queryRegion || pickedRegion || DEFAULT_REGION.sigunguCd;

  const [profile, setProfile] = useState<ProfileState>(undefined);
  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<CompareResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [retryTick, setRetryTick] = useState(0);

  useEffect(() => {
    setProfile(loadOnboardingResult()?.result ?? null);
  }, []);

  useEffect(() => {
    if (profile === undefined) return; // 프로필 확인 전엔 대기(깜빡임 방지)

    const controller = new AbortController();
    setStatus("loading");
    setError(null);

    const payload: CompareRequest = {
      region_code: regionCode,
      profile: profile
        ? {
            tag_vector: profile.tag_vector,
            vector_version: profile.vector_version,
            scoring_weights: profile.scoring_weights,
            tags: profile.tags,
          }
        : null,
      hidden_id: hiddenId,
      hotspot_id: null,
    };

    fetchCompare(payload, controller.signal)
      .then((res) => {
        setData(res);
        setStatus("success");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const apiErr =
          err instanceof ApiError ? err : new ApiError(0, "UNKNOWN", "비교 결과를 불러오지 못했습니다.");
        if (apiErr.status === 404) {
          setError(apiErr);
          setStatus("unavailable");
          return;
        }
        if (apiErr.code === "INVALID_PROFILE") {
          // §D.5: sessionStorage 폐기 + 온보딩 재유도. 화면은 error 상태로 멈추고 재시도는 사용자가 누른다.
          clearOnboardingResult();
        }
        setError(apiErr);
        setStatus("error");
      });

    return () => controller.abort();
  }, [profile, regionCode, hiddenId, retryTick]);

  // §D.7-3: matched_tags(registry 코드)는 사용자 본인 프로필의 tags 라벨로 치환한다(§C.7-4 승계).
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

  if (status === "loading") {
    return <CompareLoadingSkeleton />;
  }

  if (status === "unavailable") {
    return (
      <section className="compare-section" aria-labelledby="compareHeading">
        <Link href="/recommend" className="compare-back">
          ← 추천 목록으로
        </Link>
        <h1 className="section__title" id="compareHeading" style={{ marginTop: "var(--sp-3)" }}>
          비교 리포트
        </h1>
        <div className="board-error" role="status" style={{ marginTop: "var(--sp-4)" }}>
          <p className="board-error__msg">{error?.message ?? "이 지역은 비교 준비 중이에요."}</p>
          <p className="board-error__hint">관광지·자연경관 스팟에서 핫플 비교를 이용할 수 있어요.</p>
          <Link className="btn btn--mint" href="/recommend">
            추천 목록으로 돌아가기
          </Link>
        </div>
      </section>
    );
  }

  if (status === "error") {
    return (
      <section className="compare-section" aria-labelledby="compareHeading">
        <Link href="/recommend" className="compare-back">
          ← 추천 목록으로
        </Link>
        <h1 className="section__title" id="compareHeading" style={{ marginTop: "var(--sp-3)" }}>
          비교 리포트
        </h1>
        <div className="board-error" role="alert" style={{ marginTop: "var(--sp-4)" }}>
          <p className="board-error__msg">{error?.message ?? "비교 결과를 불러오지 못했습니다."}</p>
          <p className="board-error__hint">
            {error?.code === "INVALID_PROFILE"
              ? "취향 정보가 오래되어 초기화했어요. 다시 취향을 알려주시면 더 정확해져요."
              : error?.status === 0
                ? "백엔드 서버가 켜져 있는지 확인해주세요 (localhost:8000). 잠시 후 다시 시도해주세요."
                : "잠시 후 다시 시도해주세요."}
          </p>
          <div style={{ display: "flex", gap: "var(--sp-2)", flexWrap: "wrap" }}>
            <button className="btn btn--coral" type="button" onClick={retry}>
              다시 시도
            </button>
            {error?.code === "INVALID_PROFILE" && (
              <Link className="btn btn--white" href="/onboarding">
                취향 다시 알려주기
              </Link>
            )}
          </div>
        </div>
      </section>
    );
  }

  if (!data) return null;

  const { hotspot, hidden, deltas, verdict, region, meta } = data;
  const congestionDelta = formatCongestionDelta(deltas.congestion_diff_pct, deltas.congestion_diff);

  return (
    <section className="compare-section" aria-labelledby="compareHeading">
      <Link href="/recommend" className="compare-back">
        ← 추천 목록으로
      </Link>
      <span className="eyebrow-pill eyebrow-pill--coral">핫플 vs 숨은길</span>
      <h1 className="section__title" id="compareHeading">
        {region.region_name ?? "이 지역"} 비교 리포트
      </h1>

      {/* 부록 D.7 — 특정 스팟과의 비교(hidden_id)가 아닐 때만 지역을 고를 수 있다. */}
      {/* 부록 D.8(2026-08-01, 대표 지시) — 지역을 바꾸기 쉽게 드롭다운 옆에 그 지역
          관광지 화면으로 나가는 버튼을 둔다. 비교만 보고 끝나지 않고 목록으로 이어지게. */}
      {!hiddenId && (
        <div className="board-header-row">
          <RegionDropdown
            options={SIDO_REGIONS}
            selectedCode={regionCode}
            triggerLabel={
              SIDO_REGIONS.find((s) => s.regionCode === regionCode)?.shortName ??
              region.region_name ??
              "지역"
            }
            onSelect={(sido) => setPickedRegion(sido.regionCode)}
            ariaLabel="비교할 지역 선택"
          />
          <Link
            className="btn btn--ghost-text"
            href={`/regions?region_code=${encodeURIComponent(regionCode)}`}
          >
            이 지역 관광지 전체 보기 →
          </Link>
        </div>
      )}

      <div className="compare-summary">
        {/* verdict.headline은 backend 템플릿 조립 문자열 — 텍스트 노드로만 렌더한다(§D.7-5, HTML 주입 금지). */}
        <p className="compare-summary__headline">{verdict.headline}</p>
        <div className="compare-summary__badges">
          <span className={`delta-badge ${congestionDelta.toneClass}`}>{congestionDelta.text}</span>
          {deltas.matched_count > 0 && (
            <span className="delta-badge delta-badge--fit">맞춤 조건 {deltas.matched_count}개 충족</span>
          )}
        </div>
      </div>

      {!meta.personalized && (
        <div className="recommend-cta-banner">
          <p className="recommend-cta-banner__text">취향을 알려주면 맞춤 적합도까지 함께 비교할 수 있어요.</p>
          <Link className="btn btn--mint" href="/onboarding">
            취향 알려주기
          </Link>
        </div>
      )}

      {meta.notice && (
        <div className="board-banner" role="status">
          {meta.notice}
        </div>
      )}

      {/* 모바일(<1024px): 상단 요약 + 지표별 행 스택. 좌우 대칭 표는 375px에서 깨지므로 세로 스택으로 대체. */}
      <div className="compare-rows">
        <div className="compare-column-heads" aria-hidden="true">
          <span className="compare-column-heads__side compare-column-heads__side--hotspot">붐비는 핫플</span>
          <span className="compare-column-heads__side compare-column-heads__side--hidden">숨은길</span>
        </div>
        <div className="compare-row">
          <span className="compare-row__label">예상 혼잡도</span>
          <div className="compare-row__values">
            <div className="compare-cell compare-cell--hotspot">
              <CongestionValue spot={hotspot} />
            </div>
            <div className="compare-cell compare-cell--hidden">
              <CongestionValue spot={hidden} />
            </div>
          </div>
        </div>
        <div className="compare-row">
          <span className="compare-row__label">맞춤 적합도</span>
          <div className="compare-row__values">
            <div className="compare-cell compare-cell--hotspot">
              <FitValue spot={hotspot} tagLabelMap={tagLabelMap} />
            </div>
            <div className="compare-cell compare-cell--hidden">
              <FitValue spot={hidden} tagLabelMap={tagLabelMap} />
            </div>
          </div>
        </div>
      </div>

      {/* 데스크톱(1024px↑): hotspot·hidden 2컬럼 대칭 카드로 전환(§D.7-2). */}
      <div className="compare-cards">
        <CompareCard spot={hotspot} tagLabelMap={tagLabelMap} />
        <CompareCard spot={hidden} tagLabelMap={tagLabelMap} />
      </div>
    </section>
  );
}

export function CompareLoadingSkeleton() {
  return (
    <section className="compare-section" aria-label="비교 결과 불러오는 중">
      <div className="compare-summary compare-summary--skeleton" role="status" aria-live="polite">
        <div className="skeleton-bar" style={{ width: "80%", height: "20px" }} />
        <div className="skeleton-bar" style={{ width: "50%", height: "14px", marginTop: "12px" }} />
      </div>
      <div className="compare-rows" style={{ marginTop: "var(--sp-6)" }}>
        {[0, 1].map((i) => (
          <div className="compare-row" key={i}>
            <div className="skeleton-bar" style={{ width: "60px", height: "12px", marginBottom: "10px" }} />
            <div className="compare-row__values">
              <div className="skeleton-bar" style={{ width: "100%", height: "40px" }} />
              <div className="skeleton-bar" style={{ width: "100%", height: "40px" }} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
