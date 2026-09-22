import { SpotCard as SpotCardType } from "../../lib/api";
import { matchTier } from "../../lib/matchTier";
import { CATEGORY_META, SIGNAL_LABEL } from "./constants";
import RatingBadge from "../RatingBadge";

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  CATEGORY_META.map((c) => [c.value, c.label])
);

/**
 * 01-interface-contract.md §4.1과 동일한 레벨→배지 매핑(BoardCard.tsx가 쓰는 규약과 동일).
 * congestion_level만으로 색·라벨을 결정한다 — index(rate)로 재판정하지 않는다.
 */
const LEVEL_META: Record<string, { label: string; badgeClass: string }> = {
  high: { label: "혼잡", badgeClass: "badge--hot" },
  mid: { label: "보통", badgeClass: "badge--mid" },
  low: { label: "여유", badgeClass: "badge--calm" },
  unknown: { label: "정보없음", badgeClass: "badge--unknown" },
};

type ThemeKey = "pet_allowed" | "barrier_free" | "wellness";
// 2026-09-22 대표 지시: 웰니스 데이터가 0건이라 항상 "정보없음"만 보여 칩에서 뺀다(타입·라벨은 유지).
const THEME_KEYS: ThemeKey[] = ["pet_allowed", "barrier_free"];
const THEME_LABEL_ON: Record<ThemeKey, string> = {
  pet_allowed: "반려동물 동반 가능",
  barrier_free: "무장애 접근 가능",
  wellness: "웰니스 테마",
};
const THEME_LABEL_UNKNOWN: Record<ThemeKey, string> = {
  pet_allowed: "반려동물 동반 정보없음",
  barrier_free: "무장애 정보없음",
  wellness: "웰니스 정보없음",
};

interface SpotCardProps {
  spot: SpotCardType;
  /** 사용자 본인 OnboardingResult.tags에서 뽑은 value→label 맵. matched_tags 표시용(§C.7-4). */
  tagLabelMap: Record<string, string>;
  /** §40(신규) — 별점·리뷰 자리. 요약이 없으면 RatingBadge가 "후기 없음"으로 표기한다. */
  rating?: number | null;
  reviewCount?: number;
}

/**
 * 스팟 카드 1개. §C.2 SpotCard 스키마를 그대로 표시만 한다 — enum·점수 재판정 없음(§C.7-4).
 * themes는 true(제공)/null(정보없음, 회색)만 배지로 노출하고 false는 카드에서 생략한다
 * (접근성 정보 없음을 "불가"와 시각적으로 구분하되, 굳이 불가 사실을 강조하지 않기 위한 디자인 선택).
 */
export default function RecommendSpotCard({ spot, tagLabelMap, rating, reviewCount }: SpotCardProps) {
  const levelMeta = spot.congestion ? LEVEL_META[spot.congestion.level] ?? LEVEL_META.unknown : null;

  // 공유 코스(/course/shared/{code})의 payload 는 **외부에서 온 임의 JSON** 이라 themes 가
  // 아예 없을 수 있다(실측: 형식이 다른 payload 에서 렌더 크래시). 옵셔널 체이닝으로 방어한다 —
  // 공개 URL 이라 남이 만든 payload 한 건이 보는 사람 화면을 죽이면 안 된다.
  const themes = spot.themes ?? ({} as SpotCardType["themes"]);
  const themeKeys = THEME_KEYS.filter((key) => themes[key] !== false);

  // QA M-1(2026-08-01): `?.` 는 match_reasons 자체만 막는다 — 외부 payload 가 `match_reasons: {}`
  // 이면 matched_tags 가 undefined 라 `.map` 에서 TypeError 로 페이지가 통째로 죽는다(공유 코스는
  // 공개 URL 이라 남이 만든 값 한 건이 열람자 전원의 화면을 깬다). 배열인지까지 확인한다.
  // 타입상으로는 필수 필드라 tsc 가 못 잡는 자리다(런타임 값의 출처가 외부 JSON).
  const matchedTagLabels = Array.isArray(spot.match_reasons?.matched_tags)
    ? spot.match_reasons!.matched_tags.map((v) => tagLabelMap[v] ?? v)
    : [];
  const signalLabels = Array.isArray(spot.match_reasons?.signals)
    ? spot.match_reasons!.signals.map((s) => SIGNAL_LABEL[s] ?? s)
    : [];
  const hasReasons = matchedTagLabels.length > 0 || signalLabels.length > 0;

  return (
    <article className="spot-card">
      <div className="spot-card__head">
        <span className="spot-card__category">{CATEGORY_LABEL[spot.category] ?? spot.category}</span>
        {spot.is_hidden_gem ? (
          <span className="badge badge--hidden-gem">숨은 스팟</span>
        ) : (
          <span className="badge badge--popular">인기명소</span>
        )}
      </div>

      <h3 className="spot-card__name">{spot.name}</h3>
      {spot.address && <p className="spot-card__address">{spot.address}</p>}

      <div className="spot-card__badges">
        {/* 대표 지시 "카드 크기는 바뀌지 않게" — 이 카드는 폭이 좁아(실측 185px) 배지가 한 줄에
            하나씩 쌓인다. 별점을 그냥 추가하면 줄이 하나 더 생겨 카드가 커진다(실측 +34px).
            그래서 혼잡도 배지와 별점을 **한 줄짜리 서브행**으로 묶어 nowrap 으로 나란히 두고,
            폭이 모자라면 혼잡도 배지 쪽이 말줄임되게 한다 — 행 수가 늘지 않는다. */}
        <div className="spot-card__congestion-row">
          {levelMeta && (
            <span className={`badge ${levelMeta.badgeClass} spot-card__congestion-badge`}>
              <span className="badge__icon" aria-hidden="true"></span>
              {levelMeta.label}
              {spot.congestion?.index != null ? ` ${Math.round(spot.congestion.index)}%` : ""}
            </span>
          )}
          <RatingBadge rating={rating} reviewCount={reviewCount} />
        </div>
        {themeKeys.map((key) => (
          <span
            key={key}
            className={`theme-badge${themes[key] === null ? " theme-badge--unknown" : " theme-badge--on"}`}
          >
            {themes[key] === null ? THEME_LABEL_UNKNOWN[key] : THEME_LABEL_ON[key]}
          </span>
        ))}
      </div>

      {spot.match_score != null && (
        <div className="spot-card__score">
          <span className="spot-card__score-label">매칭도</span>
          <div className="spot-card__score-bar">
            <div style={{ width: `${matchTier(spot.match_score).fill}%` }} />
          </div>
          <span className="spot-card__score-value">{matchTier(spot.match_score).label}</span>
        </div>
      )}

      {hasReasons && (
        <div className="spot-card__reasons">
          <span className="spot-card__reasons-label">이래서 추천했어요</span>
          <div className="spot-card__reason-tags">
            {signalLabels.map((label, i) => (
              <span key={`signal-${i}`} className="reason-chip reason-chip--signal">
                {label}
              </span>
            ))}
            {matchedTagLabels.map((label, i) => (
              <span key={`tag-${i}`} className="reason-chip">
                #{label}
              </span>
            ))}
          </div>
        </div>
      )}
    </article>
  );
}

export function SpotCardSkeleton() {
  return (
    <div className="spot-card spot-card--skeleton" role="listitem" aria-hidden="true">
      <div className="skeleton-bar" style={{ width: "60px", height: "12px" }} />
      <div className="skeleton-bar" style={{ width: "70%", height: "20px" }} />
      <div className="skeleton-bar" style={{ width: "90%", height: "14px" }} />
      <div className="skeleton-bar" style={{ width: "80px", height: "24px", borderRadius: "999px" }} />
    </div>
  );
}
