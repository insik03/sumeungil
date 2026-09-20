"use client";

import GeminiMark from "../GeminiMark";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, SpotCard, SpotDetail, fetchSpotDetail } from "../../lib/api";
import { isSpotSaved, toggleSavedSpot } from "../../lib/savedSpotsStorage";
import { StampInput, isSpotStamped, toggleStamp } from "../../lib/stampStorage";
import { CartSpotInput, MAX_CART_SIZE, isInCart, toggleCartSpot } from "../../lib/courseCartStorage";
import { CATEGORY_META } from "../recommend/constants";
import VisitTipCard from "./VisitTipCard";
import PhotoCarousel from "../PhotoCarousel";
import { PlaceholderGlyph, placeholderTone } from "../FeaturedSpots";
import { useLoginGate } from "../LoginGateProvider";
import ReviewSection from "../reviews/ReviewSection";

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  CATEGORY_META.map((c) => [c.value, c.label])
);

/**
 * 01-interface-contract.md §4.1 / SpotCard.tsx의 레벨→배지 매핑과 동일(재판정 금지, 그대로 표시).
 * congestion_level(여기서는 congestion.level)만으로 라벨·색을 정한다 — index로 재판정하지 않는다.
 */
const LEVEL_META: Record<string, { label: string; badgeClass: string }> = {
  high: { label: "혼잡", badgeClass: "badge--hot" },
  mid: { label: "보통", badgeClass: "badge--mid" },
  low: { label: "여유", badgeClass: "badge--calm" },
  unknown: { label: "정보없음", badgeClass: "badge--unknown" },
};

type ThemeKey = "pet_allowed" | "barrier_free" | "wellness";
const THEME_KEYS: ThemeKey[] = ["pet_allowed", "barrier_free", "wellness"];
const THEME_LABEL_ON: Record<ThemeKey, string> = {
  pet_allowed: "반려동물 동반 가능",
  barrier_free: "무장애 접근 가능",
  wellness: "웰니스 테마",
};

type Status = "loading" | "success" | "notfound" | "error";

interface SpotDetailContentProps {
  contentId: string;
}

/**
 * 관광지 상세 화면. RecommendContent의 스팟 카드 탭에서 진입한다(§D.7-1 비교 진입 대신 상세를 먼저 거친다).
 * congestion.level 등 서버 판정값은 그대로 표시만 하고 재판정하지 않는다.
 * Phase 4(신규) — 저장 버튼 옆에 "방문 스탬프 찍기" 토글을 추가했다(additive, 기존 레이아웃·로직 무변경).
 * stampStorage.ts(localStorage만, 서버 전송 0)로 위치/좌표 없이 "내가 눌러서 기록"만 남긴다.
 * §25(신규) — "코스에 담기" 토글을 추가했다(additive). courseCartStorage.ts(localStorage만, 서버
 * 전송 0)에 담아두면 /course "내가 고른 코스" 모드에서 POST /api/v1/courses/arrange로 순서를 짜준다.
 * §31(신규) — data.visit_tip이 있으면 예상 혼잡도 뱃지 바로 아래 "방문 타이밍" 카드(VisitTipCard)를
 * 붙인다. null이면(관광지·자연 외 카테고리, 또는 매칭 실패) 카드 자체를 렌더하지 않는다(지어내지 않음).
 * overview·recommended_for·name 등 서버 문구는 전부 텍스트 노드로만 렌더한다(HTML 주입 금지).
 */
export default function SpotDetailContent({ contentId }: SpotDetailContentProps) {
  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<SpotDetail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [retryTick, setRetryTick] = useState(0);

  // 서버 렌더/첫 클라이언트 렌더는 항상 미저장으로 맞춰 하이드레이션 경고를 막는다(SaveToggleButton과 동일 패턴).
  const [saved, setSaved] = useState(false);
  // Phase 4(신규) — 방문 스탬프도 저장 토글과 동일한 null-first 하이드레이션 패턴을 따른다.
  const [stamped, setStamped] = useState(false);
  // §25(신규) — 코스 담기도 동일한 null-first 하이드레이션 패턴. cartFullNotice는 8개 초과 시도 시에만 켠다.
  const [inCart, setInCart] = useState(false);
  const [cartFullNotice, setCartFullNotice] = useState(false);
  // §40(신규) — 저장/방문 스탬프/코스 담기는 모두 "사용자 데이터가 필요한 동작"이라 비로그인이면
  // 게이트 모달을 먼저 띄운다. 이미 로그인 상태면 requireLogin이 즉시 action을 실행해 무회귀.
  const { requireLogin } = useLoginGate();

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    setError(null);

    fetchSpotDetail(contentId, controller.signal)
      .then((res) => {
        setData(res);
        setStatus("success");
        setSaved(isSpotSaved(res.id));
        setStamped(isSpotStamped(res.id));
        setInCart(isInCart(res.id));
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const apiErr =
          err instanceof ApiError ? err : new ApiError(0, "UNKNOWN", "스팟 정보를 불러오지 못했습니다.");
        if (apiErr.status === 404) {
          setError(apiErr);
          setStatus("notfound");
          return;
        }
        setError(apiErr);
        setStatus("error");
      });

    return () => controller.abort();
  }, [contentId, retryTick]);

  const retry = () => setRetryTick((t) => t + 1);

  if (status === "loading") {
    return <SpotDetailSkeleton />;
  }

  if (status === "notfound") {
    return (
      <section className="section spot-detail" aria-labelledby="spotDetailHeading">
        <Link href="/recommend" className="compare-back">
          ← 추천 목록으로
        </Link>
        <h1 className="section__title" id="spotDetailHeading">
          스팟 상세
        </h1>
        <div className="board-error" role="status">
          <p className="board-error__msg">스팟을 찾을 수 없어요.</p>
          <p className="board-error__hint">주소가 바뀌었거나 삭제된 스팟일 수 있어요.</p>
          <Link className="btn btn--mint" href="/recommend">
            추천 목록으로 돌아가기
          </Link>
        </div>
      </section>
    );
  }

  if (status === "error") {
    return (
      <section className="section spot-detail" aria-labelledby="spotDetailHeading">
        <Link href="/recommend" className="compare-back">
          ← 추천 목록으로
        </Link>
        <h1 className="section__title" id="spotDetailHeading">
          스팟 상세
        </h1>
        <div className="board-error" role="alert">
          <p className="board-error__msg">{error?.message ?? "스팟 정보를 불러오지 못했습니다."}</p>
          <p className="board-error__hint">
            {error?.status === 0
              ? "백엔드 서버가 켜져 있는지 확인해주세요 (localhost:8000). 잠시 후 다시 시도해주세요."
              : "잠시 후 다시 시도해주세요."}
          </p>
          <button className="btn btn--coral" type="button" onClick={retry}>
            다시 시도
          </button>
        </div>
      </section>
    );
  }

  if (!data) return null;

  const levelMeta = data.congestion ? LEVEL_META[data.congestion.level] ?? LEVEL_META.unknown : null;
  const themeKeys = THEME_KEYS.filter((key) => data.themes[key] === true);

  // SaveToggleButton과 동일한 저장 스키마(SavedSpot)를 만들기 위한 최소 어댑터.
  // SpotDetail에는 match_score/match_reasons가 없으므로(계약 밖 필드) null로 채워 SpotCard 형태만 맞춘다 —
  // 값을 지어내는 것이 아니라 저장 로직(toSavedSpot)이 쓰지 않는 필드를 채우는 것뿐이다.
  const spotForSave: SpotCard = {
    id: data.id,
    name: data.name,
    category: data.category,
    region_code: data.region_code,
    address: data.address,
    location: data.location,
    congestion: data.congestion,
    themes: data.themes,
    is_hidden_gem: data.is_hidden_gem,
    match_score: null,
    match_reasons: null,
  };

  const handleToggleSave = () => {
    requireLogin(
      () => setSaved(toggleSavedSpot(spotForSave)),
      "로그인하면 저장한 곳을 다음에도 볼 수 있어요."
    );
  };

  // Phase 4(신규) — 방문 스탬프 입력. 위치/좌표는 넣지 않는다(개인정보 0, §A 지시).
  const stampInput: StampInput = {
    id: data.id,
    name: data.name,
    region_code: data.region_code,
    region_name: data.region_name,
    category: data.category,
  };

  const handleToggleStamp = () => {
    requireLogin(
      () => setStamped(toggleStamp(stampInput)),
      "로그인하면 방문 스탬프를 모아 마일스톤을 확인할 수 있어요."
    );
  };

  // §25(신규) — 코스 담기 입력. 순서(slot_label)는 담지 않는다 — arrange 호출 시 backend가 채운다.
  const cartInput: CartSpotInput = {
    id: data.id,
    name: data.name,
    category: data.category,
    region_code: data.region_code,
    region_name: data.region_name,
  };

  const handleToggleCart = () => {
    requireLogin(() => {
      const result = toggleCartSpot(cartInput);
      if (result === "cart_full") {
        setCartFullNotice(true);
        return;
      }
      setCartFullNotice(false);
      setInCart(result === "added");
    }, "로그인하면 담아둔 코스를 다음에도 이어서 만들 수 있어요.");
  };

  // 2026-08-01(부록 D.9) — 종전엔 관광지·자연경관에서만 비교를 열었다. 혼잡도 데이터가
  // 그 두 카테고리에만 있어 "같은 카테고리 핫플"을 못 찾았기 때문인데, 이제 백엔드가
  // **같은 카테고리 안에서 가장 붐비는 곳**을 핫플로 삼아 카페·시장·산책로도 비교가 성립한다
  // (실측: 스팟 상세 경로 1성공/17실패 → 14성공/1실패). 그래서 카테고리 제한을 없앤다.
  // 그래도 못 찾는 지역은 백엔드가 404 를 주고, 비교 화면이 "준비 중"으로 정직하게 처리한다.
  const isComparable = true;

  return (
    <section className="section spot-detail" aria-labelledby="spotDetailHeading">
      <Link href="/recommend" className="compare-back">
        ← 추천 목록으로
      </Link>

      {/* 2026-08-01(대표 지적 "여기 구멍이 뻥 뚫려 어색하다") — 사진이 hero 안에 있으면
          사진 열이 hero 높이에서 끝나고, 그 아래 소개·추천은 왼쪽 열로만 흘러 사진 옆이 빈다.
          사진을 **페이지 직계**로 빼서 오른쪽 열 전체를 쓰게 하면, 소개·추천이 사진 옆으로
          올라와 빈 칸이 사라진다(마크업 이동만, 내용 변경 없음). */}
      {data.images && data.images.length > 0 && (
        <div className="spot-detail__photo">
          <PhotoCarousel
            images={data.images}
            placeholderIcon={<PlaceholderGlyph />}
            placeholderTone={placeholderTone(data.category)}
            ariaLabel={`${data.name} 사진`}
          />
        </div>
      )}

      <div className="spot-detail__hero">
        {/* §36(신규) — 사진 슬라이드. images가 없거나 빈 배열이면(구버전 백엔드 포함) 컴포넌트 자체를
            마운트하지 않는다 — 이 상세 화면은 원래 사진을 전혀 렌더하지 않았으므로(§34 확인) 빈
            플레이스홀더 박스를 새로 노출하는 대신 기존 무변화를 그대로 지킨다(픽셀 동일 폴백). */}
        <div className="spot-detail__hero-head">
          <span className="spot-card__category">{CATEGORY_LABEL[data.category] ?? data.category}</span>
          {data.is_hidden_gem ? (
            <span className="badge badge--hidden-gem">숨은 스팟</span>
          ) : (
            <span className="badge badge--popular">인기명소</span>
          )}
        </div>
        {/* §23(2026-07-29) — 다른 화면 섹션 헤딩(section__title)과 같은 크기를 쓰던 걸
            에디토리얼 헤드라인 급(spot-detail__title, globals.css 근거 주석 참고)으로 올렸다. */}
        <h1 className="spot-detail__title" id="spotDetailHeading">
          {data.name}
        </h1>
        {data.address && <p className="spot-card__address">{data.address}</p>}

        <div className="spot-card__badges spot-detail__badges">
          {levelMeta ? (
            <span className={`badge ${levelMeta.badgeClass}`}>
              <span className="badge__icon" aria-hidden="true"></span>
              예상 혼잡도 {levelMeta.label}
              {data.congestion?.index != null ? ` ${Math.round(data.congestion.index)}%` : ""}
            </span>
          ) : (
            <span className="badge badge--unknown">
              <span className="badge__icon" aria-hidden="true"></span>
              예상 혼잡도 정보없음
            </span>
          )}
          {themeKeys.map((key) => (
            <span key={key} className="theme-badge theme-badge--on">
              {THEME_LABEL_ON[key]}
            </span>
          ))}
        </div>

        {data.visit_tip && (
          <VisitTipCard visitTip={data.visit_tip} regionCode={data.region_code} spotName={data.name} />
        )}
      </div>

      <div className="spot-detail__block spot-detail__block--intro">
        <h2 className="spot-detail__block-title">소개</h2>
        {data.ai_summary && (
          // AI 3줄 요약 — §23(2026-07-29): 이유브로우 칩 대신 왼쪽 강조선 + 아이콘 라벨로 재구성
          // (globals.css .ai-summary 근거 주석). "AI가 생성한 콘텐츠"라는 정직 표시는 유지, 색은 그대로 재사용.
          <div className="ai-summary">
            <span className="ai-summary__label">
              <GeminiMark provider={data.ai_provider} /> 3줄 요약
            </span>
            <p className="ai-summary__text">{data.ai_summary}</p>
          </div>
        )}
        {data.overview ? (
          data.ai_summary ? (
            // 요약이 있을 때만 전문을 접어둔다(더보기/접기) — 네이티브 <details>라 별도 상태 없이
            // 키보드 접근성을 기본으로 확보한다.
            <details className="spot-detail__overview-details">
              <summary className="spot-detail__overview-toggle">전체 소개 보기</summary>
              <p className="spot-detail__overview">{data.overview}</p>
            </details>
          ) : (
            <p className="spot-detail__overview">{data.overview}</p>
          )
        ) : (
          !data.ai_summary && (
            <p className="spot-detail__overview spot-detail__overview--empty">소개 준비 중이에요.</p>
          )
        )}
      </div>

      {data.recommended_for.length > 0 && (
        <div className="spot-detail__block spot-detail__wide">
          <h2 className="spot-detail__block-title">이런 분께 추천</h2>
          <ul className="spot-detail__recommend-list">
            {data.recommended_for.map((reason, i) => (
              <li key={i} className="reason-chip spot-detail__recommend-chip">
                {reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 핫플 비교는 예상 혼잡도 데이터가 있는 카테고리(관광지·자연경관)에서만 의미가 있다.
          그 외 카테고리는 같은 카테고리 핫플이 없어(혼잡도 데이터 없음) 비교 진입을 노출하지 않는다 —
          억지로 다른 카테고리와 비교하지 않기 위함(대표 피드백). */}
      {!isComparable && (
        <p className="spot-detail__compare-note">
          이 카테고리는 예상 혼잡도 데이터가 없어 핫플 비교를 제공하지 않아요.
        </p>
      )}
      <div className="spot-detail__actions spot-detail__wide">
        {isComparable && (
          <Link
            className="btn btn--coral btn--lg"
            href={`/compare?spot_id=${data.id}&region_code=${encodeURIComponent(data.region_code)}`}
          >
            더 한적한 곳과 비교하기
          </Link>
        )}
        <button
          type="button"
          className={`btn btn--white btn--lg${saved ? " is-saved" : ""}`}
          aria-pressed={saved}
          onClick={handleToggleSave}
        >
          {saved ? "저장됨" : "저장"}
        </button>
        {/* Phase 4(신규) — 방문 스탬프. 위치 인증이 아니라 "내가 직접 눌러 남기는" 셀프 체크인이다
            (개인정보 0, §A 지시). 저장 버튼과 같은 흰 배경 토글 레시피를 쓰되 색만 mint로 구분한다. */}
        <button
          type="button"
          className={`btn btn--white btn--lg${stamped ? " is-stamped" : ""}`}
          aria-pressed={stamped}
          onClick={handleToggleStamp}
        >
          {stamped ? (
            <>
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M20 6L9 17l-5-5" />
              </svg>
              방문함
            </>
          ) : (
            "방문 스탬프 찍기"
          )}
        </button>
        {/* §25(신규) — 코스 담기. AI가 짜주는 코스 대신 직접 고른 스팟들로 순서를 짜고 싶을 때 쓴다
            (/course "내가 고른 코스" 모드). 저장·스탬프와 같은 흰 배경 토글 레시피, 색은 브랜드
            포인트(g-500)로 "코스 계획에 담긴 상태"를 나타낸다. */}
        <button
          type="button"
          className={`btn btn--white btn--lg${inCart ? " is-in-cart" : ""}`}
          aria-pressed={inCart}
          onClick={handleToggleCart}
        >
          {inCart ? (
            <>
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M20 6L9 17l-5-5" />
              </svg>
              코스에 담김
            </>
          ) : (
            "코스에 담기"
          )}
        </button>
      </div>
      {cartFullNotice && (
        <p className="spot-detail__cart-notice" role="status">
          코스에는 최대 {MAX_CART_SIZE}곳까지 담을 수 있어요. /course 화면에서 몇 곳 빼고 다시
          담아주세요.
        </p>
      )}

      {/* §41(신규) — 후기 섹션. 축제 상세(FestivalDetailContent)와 공유하는 단일 컴포넌트다. */}
      <ReviewSection targetType="spot" targetId={data.id} />
    </section>
  );
}

export function SpotDetailSkeleton() {
  return (
    <section className="section spot-detail" aria-label="스팟 정보 불러오는 중" aria-busy="true">
      <div className="skeleton-bar" style={{ width: "120px", height: "16px" }} />
      <div className="skeleton-bar" style={{ width: "70%", height: "30px", marginTop: "16px" }} />
      <div className="skeleton-bar" style={{ width: "50%", height: "16px", marginTop: "10px" }} />
      <div className="skeleton-bar" style={{ width: "40%", height: "22px", marginTop: "16px" }} />
      <div className="skeleton-bar" style={{ width: "100%", height: "80px", marginTop: "var(--sp-6)" }} />
    </section>
  );
}
