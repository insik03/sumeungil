interface RatingBadgeProps {
  /** 0~5 평균 별점. 아직 리뷰 데이터가 없으면 null/undefined — "-"로 정직하게 표기한다(값 지어내지 않음). */
  rating?: number | null;
  /** 리뷰 개수. 없으면 0으로 표기(실제 0건과 동일하게 보이는 건 의도 — 다음 단계에서 API가 채운다). */
  reviewCount?: number;
  className?: string;
}

/**
 * §40(신규) — 스팟/축제 카드 공용 별점·리뷰 아이콘. FeaturedSpotCard·recommend/SpotCard·FestivalCard가
 * 각자 재구현하지 않고 이 컴포넌트 하나를 공유한다(단일 소스). 지금은 rating/reviewCount를 넘겨주는
 * 호출부가 없어 항상 placeholder("-", 0)를 보여준다 — 리뷰 기능은 다음 단계에서 실데이터를 연결한다.
 *
 * 카드 전체가 이미 <Link>로 감싸여 있으므로 이 컴포넌트는 클릭 핸들러를 갖지 않는다(중첩
 * 링크/버튼 금지 — a11y 위반 방지, ui-ux-pro-max ux 도메인 "Confirmation Dialogs"류 인터랙션
 * 원칙과 동일하게 "의도치 않은 동작"을 만들지 않는다). 아이콘은 이모지 대신 인라인 SVG(사이트
 * 관례, WalkIcon/FestivalGlyph와 동일 패턴) — ui-ux-pro-max icons 도메인 "star" 키워드 조회 근거.
 */
export default function RatingBadge({ rating, reviewCount, className }: RatingBadgeProps) {
  const ratingLabel = rating != null ? rating.toFixed(1) : "-";
  const count = reviewCount ?? 0;
  const a11yLabel =
    rating != null
      ? `평균 별점 ${rating.toFixed(1)}점, 리뷰 ${count}개`
      : `별점 정보 없음, 리뷰 ${count}개`;

  return (
    <span className={`rating-badge${className ? ` ${className}` : ""}`} aria-label={a11yLabel}>
      <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M12 3.5l2.47 5.06 5.58.74-4.06 3.9.99 5.55L12 16.9l-4.98 2.85.99-5.55-4.06-3.9 5.58-.74L12 3.5z"
          fill="currentColor"
        />
      </svg>
      <span aria-hidden="true">{ratingLabel}</span>
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M4 5h16v11H9l-4 4V5z"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
      </svg>
      <span aria-hidden="true">{count}</span>
    </span>
  );
}
