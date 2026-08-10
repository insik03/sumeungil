import { CompareSpot } from "../../lib/api";
import { CATEGORY_META } from "../recommend/constants";
import CongestionValue from "./CongestionValue";
import FitValue from "./FitValue";

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  CATEGORY_META.map((c) => [c.value, c.label])
);

interface CompareCardProps {
  spot: CompareSpot;
  tagLabelMap: Record<string, string>;
}

const ROLE_LABEL: Record<CompareSpot["role"], string> = {
  hotspot: "붐비는 핫플",
  hidden: "AI가 찾은 숨은길",
};

/**
 * 1024px 이상 전용 대칭 카드(§D.7-2). hotspot/hidden 완전히 같은 마크업 구조로 렌더해
 * "대칭 비교"라는 화면 의도를 그대로 드러낸다. 값 렌더 로직은 CongestionValue/FitValue와
 * 공유해 모바일 지표행과 판정이 어긋나지 않는다.
 */
export default function CompareCard({ spot, tagLabelMap }: CompareCardProps) {
  return (
    <article className={`compare-card compare-card--${spot.role}`}>
      <div className="compare-card__head">
        <span className="compare-card__role">{ROLE_LABEL[spot.role]}</span>
        {spot.is_hidden_gem && <span className="badge badge--hidden-gem">숨은 스팟</span>}
      </div>
      {/* 부록 D.8(2026-08-01, 대표 지시) — 비교하려면 사진이 있어야 한다.
          없으면 회색 자리로 두고 "준비 중"이라고 적는다(다른 장소 사진으로 채우지 않는다). */}
      {spot.image_url ? (
        <img className="compare-card__photo" src={spot.image_url} alt="" loading="lazy" />
      ) : (
        <div className="compare-card__photo compare-card__photo--empty" aria-hidden="true">
          사진 준비 중
        </div>
      )}
      {spot.photo_credit && <p className="compare-card__credit">{spot.photo_credit}</p>}
      <h3 className="compare-card__name">{spot.name}</h3>
      {spot.category && <p className="compare-card__category">{CATEGORY_LABEL[spot.category] ?? spot.category}</p>}

      <div className="compare-card__section">
        <span className="compare-card__section-label">예상 혼잡도</span>
        <CongestionValue spot={spot} />
      </div>

      <div className="compare-card__section">
        <span className="compare-card__section-label">맞춤 적합도</span>
        <FitValue spot={spot} tagLabelMap={tagLabelMap} />
      </div>
    </article>
  );
}
