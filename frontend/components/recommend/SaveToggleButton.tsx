"use client";

import { useEffect, useState } from "react";
import { SpotCard } from "../../lib/api";
import { isSpotSaved, toggleSavedSpot } from "../../lib/savedSpotsStorage";
import { useLoginGate } from "../LoginGateProvider";

interface SaveToggleButtonProps {
  spot: SpotCard;
}

/**
 * 부록 F 파트2(F.2-6-1) 저장 토글. 서버 호출 0(F.2-2) — localStorage upsert/제거만 한다.
 * 스팟 카드가 <Link>(비교 화면 이동)로 감싸여 있으므로, 카드 위에 겹쳐 그리고
 * 클릭 시 상위 Link 내비게이션을 막는다(preventDefault/stopPropagation).
 * §40(신규) — 비로그인 상태에서 누르면 로그인 게이트 모달을 먼저 띄우고, 로그인 성공 시
 * 원래 누르려던 저장 토글이 이어서 실행된다. 이미 로그인 상태면 기존과 동일하게 즉시 토글.
 */
export default function SaveToggleButton({ spot }: SaveToggleButtonProps) {
  // 서버 렌더/첫 클라이언트 렌더는 항상 미저장으로 맞춰 하이드레이션 경고를 막고,
  // mount 후에만 localStorage 값을 반영한다(onboardingStorage 소비 패턴과 동일 원칙).
  const [saved, setSaved] = useState(false);
  const { requireLogin } = useLoginGate();

  useEffect(() => {
    setSaved(isSpotSaved(spot.id));
  }, [spot.id]);

  return (
    <button
      type="button"
      className={`spot-card__save${saved ? " is-saved" : ""}`}
      aria-pressed={saved}
      aria-label={saved ? `${spot.name} 저장 해제` : `${spot.name} 저장하기`}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        requireLogin(
          () => setSaved(toggleSavedSpot(spot)),
          "로그인하면 저장한 곳을 다음에도 볼 수 있어요."
        );
      }}
    >
      <svg
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill={saved ? "currentColor" : "none"}
        stroke="currentColor"
        strokeWidth="2"
        aria-hidden="true"
      >
        <path
          d="M12 21s-6.7-4.35-9.3-8.1C.8 9.8 1.6 6 5 4.6c2.2-.9 4.6 0 6 2 1.4-2 3.8-2.9 6-2 3.4 1.4 4.2 5.2 2.3 8.3C18.7 16.65 12 21 12 21z"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}
