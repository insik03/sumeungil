"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, CongestionBoardResponse, fetchCongestionBoard } from "../lib/api";
import BoardCard, { BoardCardSkeleton } from "./BoardCard";
import RegionDropdown from "./regions/RegionDropdown";
import { DEFAULT_SIDO_CODE, SIDO_REGIONS } from "./regions/constants";

type Status = "loading" | "success" | "error";

const SKELETON_COUNT = 5;

interface CongestionBoardProps {
  /** 선택된 지역 코드. 둘 다 없으면(null/undefined) 백엔드 기본 지역(§1.1)으로 호출한다. */
  areaCd?: string | null;
  sigunguCd?: string | null;
  /** 부록 U.3(2026-08-01, 대표 지시) — 전국 지도 아래에 붙는 모드.
   *  지역은 **위 지도가 정하므로** 자체 지역 드롭다운을 숨기고, 카드를 옆으로 천천히 순환시킨다. */
  marquee?: boolean;
  /** marquee 모드에서 제목 위에 붙일 부제(예: "경상북도 경주시"). */
  subtitle?: string | null;
}

interface EffectiveRegion {
  areaCd: string | null;
  sigunguCd: string | null;
}

function regionFromProps(areaCd?: string | null, sigunguCd?: string | null): EffectiveRegion {
  return { areaCd: areaCd ?? null, sigunguCd: sigunguCd ?? null };
}

const DEFAULT_SIDO =
  SIDO_REGIONS.find((s) => s.sidoCode === DEFAULT_SIDO_CODE) ?? SIDO_REGIONS[0];

/**
 * §42(2026-08-01, 03-design-spec.md, 대표 지시 "전광판도 보는 지역을 선택할 수 있어야") — 전광판이
 * 자체 지역 선택 상태(region)를 갖는다. RecommendContent.tsx §35(지연 초기화 + 의존성 기반 동기화)와
 * 동일 패턴: prop(areaCd/sigunguCd)이 바뀌면(홈 Hero에서 지역을 고르는 경우) 동기화하되, 드롭다운으로
 * 고른 선택은 prop이 바뀌기 전까지 그대로 유지한다. prop이 전혀 없는 화면(홈 밖 단독 사용)에서는
 * SIDO_REGIONS의 기본 시도(부산, 홈 기본 지역과 동일)로 시작해 선택만으로 동작한다.
 */
export default function CongestionBoard({ areaCd, sigunguCd, marquee = false, subtitle }: CongestionBoardProps) {
  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<CongestionBoardResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [retryTick, setRetryTick] = useState(0);

  // 지연 초기화 — 첫 렌더부터 prop 지역으로 시작한다(기본 지역으로 한 번 조회한 뒤 다시 조회하는
  // 이중 호출을 피함). prop이 전혀 없으면(단독 사용) EffectiveRegion이 전부 null로 시작하고,
  // 백엔드 기본 지역(§1.1, 부산 해운대)으로 첫 조회가 나간다 — 아래 matchedSido가 이를
  // DEFAULT_SIDO_CODE와 동일한 지역이라 자연스럽게 매칭한다.
  const [region, setRegion] = useState<EffectiveRegion>(() => regionFromProps(areaCd, sigunguCd));

  // prop 동기화 — prop 값 자체가 바뀔 때만 반영한다(RecommendContent.tsx §35와 동일 패턴). 드롭다운으로
  // 사용자가 고른 선택은 이 effect의 의존성(areaCd, sigunguCd)에 없으므로 덮어써지지 않는다.
  useEffect(() => {
    setRegion((prev) => {
      const next = regionFromProps(areaCd, sigunguCd);
      if (prev.areaCd === next.areaCd && prev.sigunguCd === next.sigunguCd) return prev;
      return next;
    });
  }, [areaCd, sigunguCd]);

  const load = useCallback(
    (signal?: AbortSignal) => {
      setStatus("loading");
      setError(null);
      fetchCongestionBoard(
        region.areaCd || region.sigunguCd
          ? { areaCd: region.areaCd ?? undefined, sigunguCd: region.sigunguCd ?? undefined }
          : undefined,
        signal
      )
        .then((res) => {
          setData(res);
          setStatus("success");
        })
        .catch((err: unknown) => {
          if (signal?.aborted) return;
          setError(
            err instanceof ApiError
              ? err
              : new ApiError(0, "UNKNOWN", "혼잡도 데이터를 불러오지 못했습니다.")
          );
          setStatus("error");
        });
    },
    [region.areaCd, region.sigunguCd]
  );

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load, retryTick]);

  const retry = () => setRetryTick((t) => t + 1);

  // 드롭다운 선택 → area_cd + sigungu_cd 를 **둘 다** 넘긴다.
  // SidoRegion.sidoCode 가 곧 법정동 시도 2자리(= area_cd)다(상수 주석 참고) — 지어내는 값이 아니다.
  // sigungu_cd 만 보내면 서버가 area_cd 를 기본값(부산 26)으로 채워 "26 + 강릉51150" 같은
  // 어긋난 조합이 되어 0건이 돌아온다(실측: /board?sigungu_cd=51150 → 0건,
  // ?area_cd=51&sigungu_cd=51150 → 10건). 반드시 짝으로 보낼 것.
  const handleSelectSido = (sido: (typeof SIDO_REGIONS)[number]) => {
    setRegion({ areaCd: sido.sidoCode, sigunguCd: sido.regionCode });
  };
  const matchedSido =
    SIDO_REGIONS.find((s) => s.regionCode === (region.sigunguCd ?? DEFAULT_SIDO.regionCode)) ??
    null;
  const dropdownLabel = matchedSido?.shortName ?? data?.region.area_name ?? "지역 선택";

  return (
    <section id="board" className="section section--mint" aria-labelledby="boardHeading">
      <span className="eyebrow-pill eyebrow-pill--coral">예상 혼잡 전광판</span>
      <h2 className="section__title" id="boardHeading">
        오늘의 예상 방문 집중도
      </h2>

      {subtitle && <p className="board-subtitle">{subtitle}</p>}

      <div className="board-header-row">
        {!marquee && (
        <RegionDropdown
          options={SIDO_REGIONS}
          selectedCode={matchedSido?.regionCode ?? null}
          triggerLabel={dropdownLabel}
          onSelect={handleSelectSido}
          ariaLabel="전광판 지역 선택"
        />
        )}

        {status === "loading" && (
          <span className="sample-tag">혼잡도 예측 데이터 불러오는 중…</span>
        )}

        {status === "success" && data && (
          <span className="sample-tag" aria-live="polite">
            <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M12 2C7.58 2 4 5.58 4 10c0 5.25 6.72 11.34 7.06 11.64a1.5 1.5 0 0 0 1.88 0C13.28 21.34 20 15.25 20 10c0-4.42-3.58-8-8-8zm0 11a3 3 0 1 1 0-6 3 3 0 0 1 0 6z"
                fill="currentColor"
              />
            </svg>
            지금 보는 지역 · {data.region.area_name ?? "선택 지역"}
          </span>
        )}
      </div>

      {status === "success" && data?.meta.is_stale && (
        <div className="board-banner" role="status">
          {data.meta.notice ?? "최신 데이터 지연 — 이전 값 표시 중"}
        </div>
      )}

      {status === "success" && !data?.meta.is_stale && data?.meta.degraded && data?.meta.notice && (
        <div className="board-banner" role="status">
          {data.meta.notice}
        </div>
      )}

      {status === "loading" && (
        <div className="board" role="list" aria-label="혼잡도 전광판 로딩 중">
          {Array.from({ length: SKELETON_COUNT }).map((_, i) => (
            <BoardCardSkeleton key={i} />
          ))}
        </div>
      )}

      {status === "success" && data && data.items.length > 0 && (
        <>
          {marquee ? (
            /* 옆으로 천천히 순환하는 띠(대표 지시). 목록을 두 번 이어 붙이고 -50% 까지
               움직이면 이음매 없이 무한 반복된다. 재생 시간은 카드 수에 비례시켜
               개수가 달라도 **흐르는 속도가 일정**하게 유지한다(카드당 3.2초).
               마우스를 올리면 멈춘다(읽고 싶을 때 붙잡을 수 있게). 클릭은 멈추지 않는다 —
               키보드(:focus-visible)로 들어왔을 때만 멈춘다(2026-09-20 대표 지적, globals.css).
               prefers-reduced-motion 사용자에게는 애니메이션을 끄고 가로 스크롤로 준다. */
            <div className="board-marquee" role="list" aria-label="예상 혼잡도 순환 목록">
              <div
                className="board-marquee__track"
                style={{ animationDuration: `${Math.max(12, data.items.length * 3.2)}s` }}
              >
                {[...data.items, ...data.items].map((item, i) => (
                  <BoardCard key={`${item.rank}-${item.spot_name}-${i}`} item={item} />
                ))}
              </div>
            </div>
          ) : (
            <div className="board" role="list">
              {data.items.map((item) => (
                <BoardCard key={`${item.rank}-${item.spot_name}`} item={item} />
              ))}
            </div>
          )}
          <p className="board-source-note">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M12 2v6M12 22v-4M8.5 5.5a7 7 0 0 0 0 13M15.5 5.5a7 7 0 0 1 0 13M5.5 8.5a11 11 0 0 0 0 7M18.5 8.5a11 11 0 0 1 0 7"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
              <circle cx="12" cy="12" r="2.4" fill="currentColor" />
            </svg>
            KT 이동통신 데이터로 예측한 향후 방문 집중도 · 실시간 실측이 아니며 실제 상황과 다를 수
            있어요
            {data.region.area_name ? ` · ${data.region.area_name}` : ""}
          </p>
          {/* §31(신규) — 전광판 카드마다 best_day를 붙이는 건 스팟 수만큼 forecast 호출이 늘어나
              (N×forecast) 호출 폭증이라, 카드 단위 대신 섹션 하단 1줄 안내로 상세 진입을 유도한다. */}
          <p className="board-forecast-hint">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8" />
              <path d="M12 8v5l3 2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            스팟을 눌러 &ldquo;언제 가면 한적한지&rdquo; 예보를 확인하세요
          </p>
        </>
      )}

      {status === "success" && data && data.items.length === 0 && (
        <div className="board-error" role="status">
          <p className="board-error__msg">이 지역은 아직 예상 혼잡도 데이터가 없어요.</p>
          <p className="board-error__hint">다른 지역을 선택해보세요.</p>
        </div>
      )}

      {/* 부록 D.7(2026-08-01) — "붐비는 걸 확인했다"에서 "그럼 어디 가지"로 넘어가는 흐름.
          지정과제2(쏠림 완화)의 핵심 동선이라, 전광판에서 대체 제안으로 바로 건너가게 한다.
          지금 보고 있는 지역을 그대로 넘겨 맥락이 끊기지 않게 한다. */}
      {status === "success" && data && data.items.length > 0 && (
        <div className="board-cta-row">
          <Link className="btn btn--mint" href={`/compare?region_code=${encodeURIComponent(matchedSido?.regionCode ?? DEFAULT_SIDO.regionCode)}`}>
            이 지역, 대신 갈 만한 한적한 곳 보기
          </Link>
          {/* 2026-09-16 — 혼잡 확인 → 코스 선택까지 이어지는 동선(오버투어리즘 검토 P2-a). */}
          <Link className="btn btn--outline" href={`/course?region_code=${encodeURIComponent(matchedSido?.regionCode ?? DEFAULT_SIDO.regionCode)}`}>
            이 지역으로 코스 짜기
          </Link>
        </div>
      )}

      {status === "error" && (
        <div className="board-error" role="alert">
          <p className="board-error__msg">{error?.message ?? "혼잡도 데이터를 불러오지 못했습니다."}</p>
          <p className="board-error__hint">
            백엔드 서버가 켜져 있는지 확인해주세요 (localhost:8000). 잠시 후 다시 시도해주세요.
          </p>
          <button className="btn btn--coral" type="button" onClick={retry}>
            다시 시도
          </button>
        </div>
      )}
    </section>
  );
}
