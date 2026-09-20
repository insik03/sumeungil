"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ApiError, FestivalsResponse, ReviewSummary, fetchFestivals, fetchReviewsSummaryBulk } from "../lib/api";
import { saveLastRegion } from "../lib/lastRegionStorage";
import { FestivalCard } from "./FestivalBanner";
import { FeaturedCardSkeleton } from "./FeaturedSpots";
import FestivalRegionFilter, { FestivalRegion } from "./festivals/FestivalRegionFilter";
import { REGION_BLOCKS } from "./regions/blocks";
import { regionSelectionFromCode } from "./recommend/constants";
import FestivalMonthFilter from "./festivals/FestivalMonthFilter";
import FestivalStatusFilter, { FestivalStatusValue } from "./festivals/FestivalStatusFilter";

type FetchStatus = "loading" | "success" | "error";

const SKELETON_COUNT = 8;
const FETCH_LIMIT = 500; // 2026-09-20: 서버 상한 500 — 전량 받아 30건씩 페이지로 나눈다.
// 2026-09-20 대표 결정 — 한 페이지 30건, 1·2·3… 페이지 번호로 나눈다(정렬은 서버: 진행중 종료 임박순 → 예정 시작일순).
const PAGE_SIZE = 30;
/** 월 필터를 쓰지 않는 기본 뷰의 조회 기간. 지시서: "기본 뷰는 90 유지". */
const DEFAULT_WINDOW_DAYS = 90;
/** 월 필터 선택 시 — 가을 축제 등 먼 시점도 놓치지 않도록 넉넉히 요청(지시서 근거). */
const MONTH_FILTER_WINDOW_DAYS = 365;

/**
 * `/festivals` 전국 축제 페이지 — §27(03-design-spec.md). 오케스트레이터 지시서의 병렬 확장
 * 백엔드 계약(GET /api/v1/festivals?region_code=&limit=&month=&window_days=)을 그대로 쓴다.
 *
 * - 지역/월 필터는 서버에 다시 요청한다(region_code/month/window_days 파라미터).
 * - 진행중/예정/전체 토글은 클라이언트 전용(FestivalStatusFilter) — 서버가 이미 정렬해 내려준
 *   `festival.ongoing` 값을 그대로 신뢰해 나눈다(재판정하지 않는다).
 * - total은 optional(§K/§27 하위호환) — 백엔드가 아직 안 내려주면 건수 표기를 생략한다
 *   (지어내지 않는다, R1과 동일 원칙).
 * - 404/네트워크 실패(엔드포인트 미배포 등)는 홈 FestivalBanner처럼 조용히 숨기지 않고 에러
 *   카드 + 재시도 버튼으로 안내한다 — 이 페이지는 "축제 전용" 페이지라 실패를 숨기면 사용자가
 *   기능이 아예 없다고 오해할 수 있다(RecommendContent의 에러 처리와 동일 원칙).
 *
 * 2026-09-20 대표 지적 — "4번째 페이지에서 축제 보고 뒤로가기 하면 1번 페이지로 온다".
 * 목록 상태(지역·월·상태·페이지)가 컴포넌트 state 라, 상세로 나가면서 언마운트되면 통째로
 * 사라졌다. 넷 다 **URL 쿼리**로 옮긴다 — 뒤로가기가 그 URL 을 그대로 복원하므로 별도 저장소가
 * 필요 없고, 링크를 공유해도 같은 화면이 뜬다. 페이지만 고치면 지역·월·상태는 그대로 날아가
 * "4페이지로 돌아왔는데 내가 고른 지역이 아닌" 더 이상한 상태가 되므로 함께 옮겼다.
 *
 * 필터 변경은 router.replace 다(push 아님) — 칩을 누를 때마다 히스토리가 쌓이면 뒤로가기를
 * 여러 번 눌러야 이 화면을 빠져나간다. 상세로 나가는 순간의 URL 이 곧 복원 대상이라 replace 로도
 * 목적은 달성된다.
 */
/** URL 쿼리 → 선택 지역. 권역 key 가 우선이고, 없으면 시군구 코드(검색으로 고른 경우)를 본다. */
function regionFromQuery(block: string | null, region: string | null): FestivalRegion | null {
  const b = block ? REGION_BLOCKS.find((x) => x.key === block) : undefined;
  if (b) return { blockKey: b.key, sigunguCd: null, label: b.label, representativeCode: b.regionCode };
  const sel = regionSelectionFromCode(region);
  // 검색으로 고른 시군구는 라벨이 검색 응답에만 있었다. 칩 17개 안이면 그 라벨을, 아니면
  // 중립 라벨("선택한 지역")을 쓴다 — 코드로부터 지명을 지어내지 않는다(§35와 같은 규칙).
  if (sel) return { blockKey: null, sigunguCd: sel.sigunguCd, label: sel.label, representativeCode: sel.sigunguCd };
  return null;
}

/** "YYYY-MM" 만 통과시킨다. 형식이 어긋난 쿼리는 무시(월 필터 없음)한다. */
function monthFromQuery(value: string | null): string | null {
  return value && /^\d{4}-\d{2}$/.test(value) ? value : null;
}

function statusFromQuery(value: string | null): FestivalStatusValue {
  return value === "ongoing" || value === "upcoming" ? value : "all";
}

/** Suspense fallback — 목록 자리에 같은 스켈레톤을 깔아 경계 진입 시 화면이 튀지 않게 한다. */
export function FestivalsLoadingSkeleton() {
  return (
    <section className="section" aria-labelledby="festivalsHeading">
      <span className="eyebrow-pill eyebrow-pill--azure">전국 축제</span>
      <h1 className="section__title" id="festivalsHeading">
        전국 축제
      </h1>
      <div className="festivals-grid" role="list" aria-label="축제 정보 불러오는 중" aria-busy="true">
        {Array.from({ length: SKELETON_COUNT }).map((_, i) => (
          <FeaturedCardSkeleton key={i} />
        ))}
      </div>
    </section>
  );
}

export default function FestivalsContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // 목록 상태는 전부 URL 이 정본이다(위 docstring 참고). 컴포넌트 state 로 들고 있으면
  // 상세로 나갔다 돌아올 때 통째로 사라진다.
  const selectedRegion = useMemo(
    () => regionFromQuery(searchParams.get("block"), searchParams.get("region")),
    [searchParams]
  );
  const month = monthFromQuery(searchParams.get("month"));
  const statusFilter = statusFromQuery(searchParams.get("status"));
  const pageParam = Number(searchParams.get("page"));
  const requestedPage = Number.isInteger(pageParam) && pageParam > 0 ? pageParam : 1;

  /** 쿼리를 갈아끼운다. 기본값(전국·월없음·전체·1페이지)은 URL 에서 빼 주소를 깔끔하게 둔다. */
  const writeQuery = useCallback(
    (next: { region?: FestivalRegion | null; month?: string | null; status?: FestivalStatusValue; page?: number }) => {
      const qs = new URLSearchParams(searchParams.toString());
      const set = (k: string, v: string | null) => (v ? qs.set(k, v) : qs.delete(k));
      if ("region" in next) {
        set("block", next.region?.blockKey ?? null);
        set("region", next.region?.sigunguCd ?? null);
      }
      if ("month" in next) set("month", next.month ?? null);
      if ("status" in next) set("status", next.status && next.status !== "all" ? next.status : null);
      // 지역·월·상태가 바뀌면 목록 자체가 달라지므로 페이지는 1로(종전 동작과 동일).
      const page = "page" in next ? next.page ?? 1 : "region" in next || "month" in next || "status" in next ? 1 : requestedPage;
      set("page", page > 1 ? String(page) : null);
      const q = qs.toString();
      // replace: 칩을 누를 때마다 히스토리가 쌓이면 뒤로가기로 화면을 못 빠져나간다.
      router.replace(q ? `${pathname}?${q}` : pathname, { scroll: false });
    },
    [pathname, requestedPage, router, searchParams]
  );

  // §27 "전국=기본" 요구사항은 그대로 유지(이 화면 자체의 기본값은 여전히 미선택/전국) — 대표
  // 지시(2026-08-17, 마지막 선택 지역을 기본 화면 기준으로)는 여기서 "고르면 기억한다" 쪽만
  // 적용한다. 다른 화면(홈 등)이 그 기억을 기본값으로 쓴다.
  const setSelectedRegion = (region: FestivalRegion | null) => {
    writeQuery({ region });
    if (region) {
      // 다른 화면은 시군구 단위로만 지역을 받으므로 권역이면 그 대표 시군구를 넘긴다
      // (종전 시도 칩도 대표 시군구를 저장했으므로 동작 폭은 그대로다).
      saveLastRegion({
        region_id: `sigungu-${region.representativeCode}`,
        label: region.label,
        area_cd: region.representativeCode.slice(0, 2),
        sigungu_cd: region.representativeCode,
      });
    }
  };
  const setMonth = (value: string | null) => writeQuery({ month: value });
  const setStatusFilter = (value: FestivalStatusValue) => writeQuery({ status: value });

  const [status, setStatus] = useState<FetchStatus>("loading");
  const [data, setData] = useState<FestivalsResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  // §41(신규) — 카드마다 개별 호출 금지(01-interface-contract.md 부록 R.5) — 필터로 바뀐 목록마다 1회.
  const [summaries, setSummaries] = useState<Record<string, ReviewSummary>>({});

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    setError(null);

    // 권역 칩이면 region_block(권역 전체), 검색으로 고른 시군구면 region_code(그 시군구만).
    fetchFestivals(selectedRegion?.sigunguCd ?? undefined, FETCH_LIMIT, controller.signal, {
      month: month ?? undefined,
      windowDays: month ? MONTH_FILTER_WINDOW_DAYS : DEFAULT_WINDOW_DAYS,
      regionBlock: selectedRegion?.blockKey ?? undefined,
    })
      .then((res) => {
        setData(res);
        setStatus("success");
        fetchReviewsSummaryBulk(
          "festival",
          res.festivals.map((f) => f.id),
          controller.signal
        )
          .then((s) => setSummaries(s))
          .catch(() => {
            // 실패해도 조용히 무시 — RatingBadge가 "후기 없음" 상태를 보여준다.
          });
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          err instanceof ApiError ? err : new ApiError(0, "UNKNOWN", "축제 정보를 불러오지 못했습니다.")
        );
        setStatus("error");
      });

    return () => controller.abort();
  }, [selectedRegion, month, retryTick]);

  // 진행중/예정/전체는 서버 재요청 없이 클라이언트에서만 나눈다(서버가 이미 정렬한 ongoing 값을 그대로 신뢰).
  const filteredFestivals = useMemo(() => {
    const festivals = data?.festivals ?? [];
    if (statusFilter === "ongoing") return festivals.filter((f) => f.ongoing);
    if (statusFilter === "upcoming") return festivals.filter((f) => !f.ongoing);
    return festivals;
  }, [data?.festivals, statusFilter]);

  // 페이지 번호도 URL 이 정본이다. 필터가 바뀌면 writeQuery 가 1로 되돌린다.
  const pageCount = Math.max(1, Math.ceil(filteredFestivals.length / PAGE_SIZE));
  // 링크로 들어온 ?page=99 나, 필터가 바뀌어 목록이 짧아진 경우를 마지막 페이지로 눌러 담는다
  // (빈 화면을 보여주지 않는다). URL 은 그대로 두고 화면만 맞춘다.
  const page = Math.min(requestedPage, pageCount);
  const setPage = (n: number) => writeQuery({ page: n });
  const pageFestivals = filteredFestivals.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const retry = () => setRetryTick((t) => t + 1);

  return (
    <section className="section" aria-labelledby="festivalsHeading">
      <span className="eyebrow-pill eyebrow-pill--azure">전국 축제</span>
      <div className="festivals-page__head">
        <h1 className="section__title" id="festivalsHeading">
          전국 축제
        </h1>
        {/* total 미배포(구버전 백엔드) 시 건수를 지어내지 않고 생략한다 — R1과 동일 원칙. */}
        {status === "success" && typeof data?.total === "number" && (
          <span className="festivals-page__count">전체 {data.total}건</span>
        )}
      </div>
      <p className="tips-intro">지역과 시기를 골라 전국의 축제 소식을 확인해보세요.</p>

      <div className="festivals-filter-bar">
        <FestivalRegionFilter selected={selectedRegion} onSelect={setSelectedRegion} />
        <FestivalMonthFilter selected={month} onSelect={setMonth} />
        <FestivalStatusFilter selected={statusFilter} onSelect={setStatusFilter} />
      </div>

      {status === "loading" && (
        <div
          className="festivals-grid"
          role="list"
          aria-label="축제 정보 불러오는 중"
          aria-busy="true"
        >
          {Array.from({ length: SKELETON_COUNT }).map((_, i) => (
            <FeaturedCardSkeleton key={i} />
          ))}
        </div>
      )}

      {status === "success" && filteredFestivals.length === 0 && (
        <div className="festival-empty" role="status">
          <p className="festival-empty__msg">이 조건의 축제가 아직 없어요.</p>
          <p className="festival-empty__hint">지역·월·진행 상태를 다르게 선택해보세요.</p>
        </div>
      )}

      {status === "success" && filteredFestivals.length > 0 && (
        <div className="festivals-grid" role="list">
          {pageFestivals.map((festival) => {
            const s = summaries[String(festival.id)];
            return (
              <FestivalCard
                key={festival.id}
                festival={festival}
                rating={s?.average ?? null}
                reviewCount={s?.count}
              />
            );
          })}
        </div>
      )}

      {status === "success" && pageCount > 1 && (
        <nav className="pager" aria-label="축제 목록 페이지">
          <button type="button" className="pager__btn" disabled={page === 1} onClick={() => setPage(page - 1)}>
            이전
          </button>
          {Array.from({ length: pageCount }, (_, i) => i + 1).map((n) => (
            <button
              key={n}
              type="button"
              className={`pager__btn pager__num${n === page ? " is-active" : ""}`}
              aria-current={n === page ? "page" : undefined}
              onClick={() => {
                setPage(n);
                document.getElementById("festivalsHeading")?.scrollIntoView({ block: "start" });
              }}
            >
              {n}
            </button>
          ))}
          <button type="button" className="pager__btn" disabled={page === pageCount} onClick={() => setPage(page + 1)}>
            다음
          </button>
        </nav>
      )}

      {status === "error" && (
        <div className="board-error" role="alert">
          <p className="board-error__msg">{error?.message ?? "축제 정보를 불러오지 못했습니다."}</p>
          <p className="board-error__hint">
            {error?.status === 404
              ? "축제 페이지가 아직 준비 중이에요(백엔드 연동이 필요해요)."
              : "백엔드 서버가 켜져 있는지 확인해주세요 (localhost:8000). 잠시 후 다시 시도해주세요."}
          </p>
          <button className="btn btn--coral" type="button" onClick={retry}>
            다시 시도
          </button>
        </div>
      )}
    </section>
  );
}
