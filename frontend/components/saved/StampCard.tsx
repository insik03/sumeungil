"use client";

import Link from "next/link";
import { Stamp } from "../../lib/stampStorage";
import { CATEGORY_META } from "../recommend/constants";

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  CATEGORY_META.map((c) => [c.value, c.label])
);

/** SavedSpotCard의 relativeSavedAt과 동일 규칙(신선도 정직 표기) — 대상 필드명만 stamped_at으로 다르다. */
function relativeStampedAt(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(diffMs)) return "기록 시각 확인 불가";
  if (diffMs < 60_000) return "방금 전";
  const min = Math.floor(diffMs / 60_000);
  if (min < 60) return `${min}분 전`;
  const hour = Math.floor(min / 60);
  if (hour < 24) return `${hour}시간 전`;
  const day = Math.floor(hour / 24);
  return `${day}일 전`;
}

interface StampCardProps {
  stamp: Stamp;
  onRemove: () => void;
}

/**
 * 저장 화면(SavedContent) "내 방문 스탬프" 모아보기 카드. SavedSpotCard(F.2-6-2)와 동일한
 * spot-card/spot-card-wrap 레시피를 재사용하고(신규 CSS 최소화), 체크 배지·메타·해제 버튼만
 * 스탬프 전용으로 새로 그린다. 클릭 시 비교 화면이 아니라 스팟 상세(/spot/{id})로 이동한다 —
 * 방문 기록은 "다시 둘러보기"가 목적이지 비교가 목적이 아니라는 판단.
 */
export default function StampCard({ stamp, onRemove }: StampCardProps) {
  return (
    <div className="spot-card-wrap" role="listitem">
      <Link className="spot-card-link" aria-label={`${stamp.name} 상세 보기`} href={`/spot/${stamp.spot_id}`}>
        <article className="spot-card">
          <div className="spot-card__head">
            <span className="spot-card__category">{CATEGORY_LABEL[stamp.category] ?? stamp.category}</span>
            <span className="stamp-card__check" aria-hidden="true">
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M20 6L9 17l-5-5" />
              </svg>
            </span>
          </div>

          <h3 className="spot-card__name">{stamp.name}</h3>

          <p className="stamp-card__meta">
            {stamp.region_name ?? stamp.region_code} · 현장 인증 · {relativeStampedAt(stamp.stamped_at)}
          </p>
        </article>
      </Link>

      <button
        type="button"
        className="stamp-card__remove"
        aria-label={`${stamp.name} 방문 스탬프 해제`}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onRemove();
        }}
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
    </div>
  );
}
