"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  RegionSummary,
  STAMP_MILESTONES,
  STAMPS_CHANGED,
  Stamp,
  loadStamps,
  removeStamp,
  summarizeByRegion,
  syncStampsFromServer,
} from "../../lib/stampStorage";
import StampCard from "./StampCard";

/**
 * 방문 스탬프 모아보기(2026-09-20 계정 데이터로 전환). 저장한 스팟(즐겨찾기)과는 별개의 기록이다.
 * 스팟 상세에서 브라우저 위치로 현장을 인증해 찍은 스탬프가 계정에 저장되고, 여기서 서버 목록을 보여준다
 * (좌표는 저장하지 않는다). SavedContent와 동일한 null-first 하이드레이션 패턴(첫 렌더는 항상 "아직 안 읽음")을
 * 따라 하이드레이션 경고를 막는다.
 *
 * 저장한 스팟 섹션과 시각적으로 구분하기 위해(홈 CongestionBoard처럼) section--mint 배경을 쓴다 —
 * g 계열은 tokens.css에서 이미 "여유/긍정" 시맨틱으로 쓰이고 있어 "기록·수집"의 톤과도 잘 맞는다.
 */
export default function VisitStampsSection() {
  const [stamps, setStamps] = useState<Stamp[] | null>(null);

  // 2026-09-20 — 스탬프는 계정 데이터. 서버 목록과 맞추고, 다른 화면(스팟 상세 등)에서 찍은 변경을 구독한다.
  useEffect(() => {
    const refresh = () => setStamps(loadStamps());
    refresh();
    window.addEventListener(STAMPS_CHANGED, refresh);
    void syncStampsFromServer().then(refresh);
    return () => window.removeEventListener(STAMPS_CHANGED, refresh);
  }, []);

  const handleRemove = (spotId: number) => {
    removeStamp(spotId); // 메모리에서 바로 빼고 STAMPS_CHANGED 로 화면이 따라온다
  };

  const sorted = stamps
    ? [...stamps].sort((a, b) => new Date(b.stamped_at).getTime() - new Date(a.stamped_at).getTime())
    : [];
  const regionSummary: RegionSummary[] = stamps ? summarizeByRegion(stamps) : [];
  const count = sorted.length;

  // §23(2026-07-29) — eyebrow-pill을 뺐다. section--mint 배경 자체가 이미 "저장한 스팟"과
  // 구분되는 새 블록임을 알려줘 칩 라벨이 중복 신호였다(taste-skill eyebrow 남용 경고).
  return (
    <section className="section section--mint" aria-labelledby="stampsHeading">
      <h2 className="section__title" id="stampsHeading">
        내 방문 스탬프
      </h2>
      <p className="stamp-intro">
        다녀온 곳에서 스팟 상세의 “방문 스탬프 찍기”를 누르면 브라우저 위치로 현장을 확인해 계정에 저장돼요. 위치(좌표)는 저장하지 않아요.
      </p>

      {stamps !== null && count === 0 && (
        <div className="board-error" role="status">
          <p className="board-error__msg">아직 찍은 방문 스탬프가 없어요.</p>
          <p className="board-error__hint">스팟 상세에서 방문 스탬프를 찍어보세요.</p>
          <Link className="btn btn--mint" href="/recommend">
            추천 보러가기
          </Link>
        </div>
      )}

      {count > 0 && (
        <>
          {regionSummary.length > 0 && (
            <div className="stamp-region-summary" aria-label="지역별 방문 스탬프 수">
              {regionSummary.map((r) => (
                <span className="stamp-region-pill" key={r.regionCode}>
                  {r.label} {r.count}
                </span>
              ))}
            </div>
          )}

          <StampMilestones count={count} />

          <div className="spot-grid" role="list">
            {sorted.map((s) => (
              <StampCard key={s.spot_id} stamp={s} onRemove={() => handleRemove(s.spot_id)} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

const TIER_CLASS: Record<string, string> = { 동: "bronze", 은: "silver", 금: "gold" };

/**
 * 마일스톤 배지 — 지어낸 데이터 없이 순수 개수 기반으로만 판정한다(STAMP_MILESTONES, 동 5/은 10/금 20).
 * 달성 여부를 색만으로 구분하지 않는다 — 아이콘 모양(잠김: 숫자 / 달성: 체크)과 캡션 문구가 함께
 * 이중 신호를 준다(접근성 원칙, §19.2 계승).
 */
function StampMilestones({ count }: { count: number }) {
  const nextIdx = STAMP_MILESTONES.findIndex((m) => count < m.threshold);
  const next = nextIdx >= 0 ? STAMP_MILESTONES[nextIdx] : null;

  return (
    <div className="stamp-milestones" role="list" aria-label="방문 스탬프 마일스톤">
      {STAMP_MILESTONES.map((m) => {
        const achieved = count >= m.threshold;
        return (
          <div
            className={`stamp-milestone stamp-milestone--${TIER_CLASS[m.tier]}${achieved ? " is-achieved" : ""}`}
            role="listitem"
            key={m.tier}
          >
            <span className="stamp-milestone__icon" aria-hidden="true">
              {achieved ? (
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M20 6L9 17l-5-5" />
                </svg>
              ) : (
                m.threshold
              )}
            </span>
            <span className="stamp-milestone__label">
              {m.tier} 배지 · {m.threshold}개
            </span>
          </div>
        );
      })}
      <p className="stamp-milestones__caption">
        {next ? `${next.tier} 배지까지 ${next.threshold - count}개 남았어요` : "모든 배지를 모았어요"}
      </p>
    </div>
  );
}
