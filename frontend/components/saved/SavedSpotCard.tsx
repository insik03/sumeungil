"use client";

import { MouseEventHandler, useEffect, useState } from "react";
import Link from "next/link";
import { SavedSpot } from "../../lib/savedSpotsStorage";
import { MAX_CART_SIZE, isInCart, toggleCartSpot } from "../../lib/courseCartStorage";
import { CATEGORY_META } from "../recommend/constants";
import { useLoginGate } from "../LoginGateProvider";

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  CATEGORY_META.map((c) => [c.value, c.label])
);

/**
 * 01-interface-contract.md §4.1 레벨→배지 매핑과 동일 규약(RecommendSpotCard와 동일 소스 진실).
 * congestion.level만으로 색·라벨을 결정한다 — index로 재판정하지 않는다.
 */
const LEVEL_META: Record<string, { label: string; badgeClass: string }> = {
  high: { label: "혼잡", badgeClass: "badge--hot" },
  mid: { label: "보통", badgeClass: "badge--mid" },
  low: { label: "여유", badgeClass: "badge--calm" },
  unknown: { label: "정보없음", badgeClass: "badge--unknown" },
};

/** "3분 전"/"2시간 전"/"5일 전" — 저장 시점이 오래될수록 스냅샷 신선도를 정직하게 알린다(F.2-3). */
function relativeSavedAt(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(diffMs)) return "저장 시각 확인 불가";
  if (diffMs < 60_000) return "방금 전";
  const min = Math.floor(diffMs / 60_000);
  if (min < 60) return `${min}분 전`;
  const hour = Math.floor(min / 60);
  if (hour < 24) return `${hour}시간 전`;
  const day = Math.floor(hour / 24);
  return `${day}일 전`;
}

interface SavedSpotCardProps {
  spot: SavedSpot;
  onRemove: () => void;
}

/**
 * 부록 F 파트2(F.2-6-2) 저장 화면 카드. RecommendSpotCard(부록 C.2/C.7)와 같은 배지·타이포 규약을
 * 재사용하되, SavedSpot(F.2-3) 스냅샷에는 address/themes/match_score가 없으므로 그 부분은
 * 그리지 않는다 — 저장하지 않은 데이터를 지어내지 않는다.
 *
 * §25(신규) — "코스에 담기" 토글을 추가했다(additive). 찜해둔 곳에서 골라 담는 입력 동선
 * (스팟 상세 진입 없이 저장 목록에서 바로 담기)이라 courseCartStorage.ts를 직접 호출한다.
 * 저장 하트(spot-card__save)와 같은 "카드 우상단 원형 플로팅 버튼" 자리에 나란히 놓는다.
 */
export default function SavedSpotCard({ spot, onRemove }: SavedSpotCardProps) {
  const levelMeta = spot.congestion ? LEVEL_META[spot.congestion.level] ?? LEVEL_META.unknown : null;

  // 서버 렌더/첫 클라이언트 렌더는 항상 미담김으로 맞춰 하이드레이션 경고를 막는다(SpotDetailContent와 동일 패턴).
  const [inCart, setInCart] = useState(false);
  const [cartFull, setCartFull] = useState(false);
  // §40(신규) — "코스에 담기"는 로그인 게이트 대상. 하트(제거)는 이미 저장된 항목을 빼는
  // 동작이라 게이트하지 않는다(신규로 사용자 데이터를 만드는 동작이 아님).
  const { requireLogin } = useLoginGate();

  useEffect(() => {
    setInCart(isInCart(spot.id));
  }, [spot.id]);

  // cart_full 안내는 잠깐만 보여주고 사라진다(타임아웃 토스트) — 카드 위에 계속 남아 있으면 방해된다.
  useEffect(() => {
    if (!cartFull) return;
    const timer = window.setTimeout(() => setCartFull(false), 2600);
    return () => window.clearTimeout(timer);
  }, [cartFull]);

  const handleToggleCart: MouseEventHandler<HTMLButtonElement> = (e) => {
    e.preventDefault();
    e.stopPropagation();
    requireLogin(() => {
      const result = toggleCartSpot({
        id: spot.id,
        name: spot.name,
        category: spot.category,
        region_code: spot.region_code,
      });
      if (result === "cart_full") {
        setCartFull(true);
        return;
      }
      setInCart(result === "added");
    }, "로그인하면 담아둔 코스를 다음에도 이어서 만들 수 있어요.");
  };

  return (
    <div className="spot-card-wrap" role="listitem">
      <Link
        className="spot-card-link"
        aria-label={`${spot.name} 상세 보기`}
        href={`/spot/${spot.id}?region_code=${encodeURIComponent(spot.region_code)}`}
      >
        <article className="spot-card spot-card--with-cart-toggle">
          <div className="spot-card__head">
            <span className="spot-card__category">{CATEGORY_LABEL[spot.category] ?? spot.category}</span>
            {spot.is_hidden_gem && <span className="badge badge--hidden-gem">숨은 스팟</span>}
          </div>

          <h3 className="spot-card__name">{spot.name}</h3>

          <div className="spot-card__badges">
            {levelMeta && (
              <span className={`badge ${levelMeta.badgeClass}`}>
                <span className="badge__icon" aria-hidden="true"></span>
                {levelMeta.label}
                {spot.congestion?.index != null ? ` ${Math.round(spot.congestion.index)}%` : ""}
              </span>
            )}
          </div>

          <p className="saved-spot-card__meta">저장 시점 정보 · {relativeSavedAt(spot.saved_at)}</p>
        </article>
      </Link>

      <button
        type="button"
        className="spot-card__save is-saved"
        aria-label={`${spot.name} 저장 해제`}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onRemove();
        }}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path
            d="M12 21s-6.7-4.35-9.3-8.1C.8 9.8 1.6 6 5 4.6c2.2-.9 4.6 0 6 2 1.4-2 3.8-2.9 6-2 3.4 1.4 4.2 5.2 2.3 8.3C18.7 16.65 12 21 12 21z"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      <button
        type="button"
        className={`spot-card__cart-toggle${inCart ? " is-in-cart" : ""}`}
        aria-label={inCart ? `${spot.name} 코스에서 빼기` : `${spot.name} 코스에 담기`}
        aria-pressed={inCart}
        onClick={handleToggleCart}
      >
        {inCart ? (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M20 6L9 17l-5-5" />
          </svg>
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
        )}
      </button>

      {cartFull && (
        <p className="spot-card__cart-full-toast" role="status">
          코스는 최대 {MAX_CART_SIZE}곳까지 담을 수 있어요.
        </p>
      )}
    </div>
  );
}
