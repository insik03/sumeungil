"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { fetchFeatured } from "../lib/api";
import { withRegionCode } from "../lib/regionQuery";
import { SIDO_REGIONS } from "./regions/constants";

interface CoursePromoProps {
  /** 선택된 지역(sigungu_cd). FeaturedSpots/ThemeCollections와 동일 원칙. */
  regionCode?: string | null;
}

/** 6~7초 사이 임의 값 — 매 전환마다 미세하게 다른 간격이라 기계적으로 째깍거리는 느낌을 줄인다. */
function nextIntervalMs(): number {
  return 6000 + Math.random() * 1000;
}

/** 시도 대표지역 무작위 2곳(§33-1 근거) — 최대 2콜만 추가한다. */
const MAX_EXTRA_SIDO_CALLS = 2;

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function shuffle<T>(arr: T[]): T[] {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/**
 * §22/§24(03-design-spec.md) — Acenda 레퍼런스의 "EXPLORE MALDIVES" 다크 풀블리드 사진 섹션을
 * 흡수한 홈 신규 섹션. 큰 헤드라인 + /course(AI 추천 코스) CTA로 재해석했다.
 *
 * §33-1(2026-07-29, 03-design-spec.md, 대표 피드백) — 정적 사진 1장(hidden_picks[0])을
 * "관광지 사진 무작위 슬라이드(크로스페이드)"로 바꾼다. 사진 풀은 (a) 현재 지역의
 * fetchFeatured trending+hidden_picks 전부 + (b) SIDO_REGIONS(§29, 검증된 시도 대표지역 상수 —
 * 코드를 새로 지어내지 않는다)에서 무작위 2개 시도를 추가로 호출한 trending+hidden_picks —
 * 를 합쳐 "전국 무작위" 느낌을 낸다(신규 API 없음, 기존 fetchFeatured 재호출만 늘렸다 —
 * 최대 1(현재 지역)+2(무작위 시도)=3콜). null image_url은 제외하고 풀 전체를 셔플한다.
 *
 * 크로스페이드는 이미지 2겹(레이어 A/B)을 opacity로만 스왑한다 — Hero.tsx 캐러셀에서
 * scrollIntoView/track.scrollTo류가 페이지 세로 스크롤까지 끌고 간 버그(대표 리포트 2건)의
 * 교훈을 그대로 승계해 이 컴포넌트는 스크롤 관련 API를 전혀 쓰지 않는다(opacity 전환뿐이라
 * 레이아웃/스크롤에 영향이 있을 수 없는 구조).
 *
 * prefers-reduced-motion이면 자동 전환을 시작하지 않는다(첫 사진에서 정적으로 멈춘다,
 * Hero.tsx 자동 순환과 동일 원칙). 사진이 0장이면 기존 폴백(잉크→딥그린 그라디언트)을 그대로
 * 쓴다 — 이 섹션 자체를 숨기지 않는다(카피·CTA는 정적이라 사진 실패와 무관하게 항상 노출 가능).
 */
export default function CoursePromo({ regionCode }: CoursePromoProps) {
  const [pool, setPool] = useState<string[]>([]);
  const [poolReady, setPoolReady] = useState(false);
  const [frontLayer, setFrontLayer] = useState<0 | 1>(0);
  const [layerSrc, setLayerSrc] = useState<[string | null, string | null]>([null, null]);

  const poolRef = useRef<string[]>([]);
  const posRef = useRef(0);
  const frontLayerRef = useRef<0 | 1>(0);

  // 사진 풀 로딩 — 지역이 바뀔 때마다 다시 셔플(§33-1).
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    setPoolReady(false);
    setPool([]);
    setLayerSrc([null, null]);
    setFrontLayer(0);
    poolRef.current = [];
    posRef.current = 0;
    frontLayerRef.current = 0;

    async function loadPool() {
      const extraSidos = shuffle(SIDO_REGIONS).slice(0, MAX_EXTRA_SIDO_CALLS);
      const calls = [
        fetchFeatured(regionCode ?? undefined, 4, controller.signal),
        ...extraSidos.map((sido) => fetchFeatured(sido.regionCode, 4, controller.signal)),
      ];
      const results = await Promise.allSettled(calls);
      if (cancelled || controller.signal.aborted) return;

      const urls: string[] = [];
      results.forEach((r) => {
        if (r.status !== "fulfilled") return;
        r.value.trending.forEach((s) => {
          if (s.image_url) urls.push(s.image_url);
        });
        r.value.hidden_picks.forEach((s) => {
          if (s.image_url) urls.push(s.image_url);
        });
      });

      const uniqueShuffled = shuffle(Array.from(new Set(urls)));
      poolRef.current = uniqueShuffled;
      setPool(uniqueShuffled);
      setPoolReady(true);
    }

    loadPool();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [regionCode]);

  // 풀이 준비되면 첫 사진을 레이어0에 세팅.
  useEffect(() => {
    if (pool.length === 0) return;
    posRef.current = 0;
    frontLayerRef.current = 0;
    setFrontLayer(0);
    setLayerSrc([pool[0], null]);
  }, [pool]);

  // 6~7초 크로스페이드 — 사진 2장 이상 + prefers-reduced-motion이 아닐 때만 순환한다.
  useEffect(() => {
    if (pool.length < 2 || prefersReducedMotion()) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const tick = () => {
      timer = setTimeout(() => {
        if (cancelled) return;
        const p = poolRef.current;
        if (p.length < 2) return;
        const nextPos = (posRef.current + 1) % p.length;
        posRef.current = nextPos;
        const backLayer: 0 | 1 = frontLayerRef.current === 0 ? 1 : 0;

        setLayerSrc((prev) => {
          const updated: [string | null, string | null] = [prev[0], prev[1]];
          updated[backLayer] = p[nextPos];
          return updated;
        });
        frontLayerRef.current = backLayer;
        setFrontLayer(backLayer);
        tick();
      }, nextIntervalMs());
    };

    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [pool.length]);

  const hasPhotos = poolReady && pool.length > 0;
  const className = `course-promo${hasPhotos ? " course-promo--photo" : ""}`;

  return (
    <section className={className} aria-labelledby="coursePromoHeading">
      {hasPhotos && (
        <div className="course-promo__photos" aria-hidden="true">
          {([0, 1] as const).map((layer) => {
            const src = layerSrc[layer];
            if (!src) return null;
            const visible = frontLayer === layer;
            return (
              <div
                key={layer}
                className={`course-promo__photo-layer${visible ? " course-promo__photo-layer--visible" : ""}`}
                style={{ "--course-promo-photo": `url("${src}")` } as React.CSSProperties}
              />
            );
          })}
          <div className="course-promo__overlay" />
        </div>
      )}
      <div className="course-promo__inner">
        <span className="hero__eyebrow">AI 추천 코스</span>
        <h2 className="course-promo__title" id="coursePromoHeading">
          아무도 모르는
          <br />
          오늘의 코스, AI가 짜드려요
        </h2>
        {/* §35(2026-07-31, 백로그 D21) — 이 배너가 이미 받고 있던 regionCode(사진 조회용)를
            CTA 링크에도 그대로 붙여, 홈에서 고른 지역이 /course로 이어지게 한다. 미선택이면
            withRegionCode가 href를 그대로 돌려줘 기존 동작과 동일하다. */}
        <Link
          className="btn btn--coral btn--lg course-promo__cta"
          href={withRegionCode("/course", regionCode)}
        >
          AI 추천 코스 보러가기
        </Link>
      </div>
    </section>
  );
}
