interface RatingBadgeProps {
  /** 0~5 평균 별점. 아직 리뷰 데이터가 없으면 null/undefined다. */
  rating?: number | null;
  /** 리뷰 개수. 평균 별점과 함께 API의 일괄 요약 응답으로 채운다. */
  reviewCount?: number;
  className?: string;
}

/**
 * §40(신규) — 스팟/축제 카드 공용 별점·리뷰 아이콘. FeaturedSpotCard·recommend/SpotCard·FestivalCard가
 * 각자 재구현하지 않고 이 컴포넌트 하나를 공유한다(단일 소스). 리뷰가 아직 없으면 숫자처럼
 * 보이는 placeholder 대신 "후기 없음"을 표시해 실제 별점으로 오인하지 않게 한다.
 *
 * 카드 전체가 이미 <Link>로 감싸여 있으므로 이 컴포넌트는 클릭 핸들러를 갖지 않는다(중첩
 * 링크/버튼 금지 — a11y 위반 방지, ui-ux-pro-max ux 도메인 "Confirmation Dialogs"류 인터랙션
 * 원칙과 동일하게 "의도치 않은 동작"을 만들지 않는다). 아이콘은 이모지 대신 인라인 SVG(사이트
 * 관례, WalkIcon/FestivalGlyph와 동일 패턴) — ui-ux-pro-max icons 도메인 "star" 키워드 조회 근거.
 */
export default function RatingBadge({ rating, reviewCount, className }: RatingBadgeProps) {
  const count = reviewCount ?? 0;
  const hasReviews = rating != null && count > 0;
  const ratingLabel = rating?.toFixed(1);
  const a11yLabel = hasReviews ? `평균 별점 ${ratingLabel}점, 리뷰 ${count}개` : "아직 후기가 없습니다";

  return (
    <span className={`rating-badge${className ? ` ${className}` : ""}`} aria-label={a11yLabel}>
      <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M12 3.5l2.47 5.06 5.58.74-4.06 3.9.99 5.55L12 16.9l-4.98 2.85.99-5.55-4.06-3.9 5.58-.74L12 3.5z"
          fill="currentColor"
        />
      </svg>
      {hasReviews ? (
        <>
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
        </>
      ) : (
        <span aria-hidden="true">후기 없음</span>
      )}
    </span>
  );
}
