"use client";

import { useEffect, useState } from "react";
import { CollectionsResponse, SpotCollection, fetchCollections } from "../lib/api";
import { FeaturedCardSkeleton, FeaturedSpotCard } from "./FeaturedSpots";

const SKELETON_COUNT = 4;

/**
 * 홈 화면에 한 번에 노출할 테마 최대 개수(Phase 3, 03-design-spec.md 근거).
 * 백엔드가 이보다 많은 테마를 내려줘도 상위 N개만 보여준다 — 동일한 가로 스크롤 카드 행이
 * 무제한으로 쌓이면 "발견" 섹션이 끝없이 길어져 선택 피로(정보 과다)를 유발한다
 * (ui-ux-pro-max ux 도메인 `content-priority`: 핵심 콘텐츠를 먼저 보여주고 부차적인 것은
 * 접거나 숨긴다). 정렬 기준은 backend 소유 — 프론트는 순서를 재정렬하지 않고 자르기만 한다.
 * (§44 — 홈은 더 이상 이 컴포넌트를 렌더하지 않지만(`/themes`로 이관), 기본값은 향후 재사용을
 * 대비해 그대로 남겨둔다.)
 */
const MAX_HOME_COLLECTIONS = 3;

/**
 * §44(신규, 2026-08-0X, 03-design-spec.md — 대표 지시 "테마별 여행은 테마별로 몇 가지만
 * 나오는데 전체를 다 볼 수 있도록 더보기가 있으면 좋겠다") — 첫 로딩 시 테마당 요청 개수.
 * 초기 화면이 무거워지지 않도록 작게 시작하고 "더보기"로 늘린다.
 */
const INITIAL_PER_THEME = 8;
/** "더보기" 클릭당 추가로 요청할 개수. 초기 배치와 같은 값으로 맞춰 체감 속도를 일정하게 유지한다. */
// 대표 지시(2026-08-01) "보통 더보기를 누르면 전체가 다 뜨지 않나" — 한 번에 크게 펼친다.
// 다만 테마당 총 후보가 수백 곳(예: 조용히 힐링 546)이라 전부를 한 화면에 깔면 카드 수천 장이
// 되어 스크롤·사진 로딩이 감당이 안 된다. 그래서 **API 상한(50)만큼 한 번에** 펼치고, 남으면
// 버튼에 남은 수를 적어 계속 누를 수 있게 한다(진행 상황을 숨기지 않는다).
const LOAD_MORE_INCREMENT = 50;

/**
 * 테마 그룹 1개 = (제목 + "전체 N곳") 헤드 + 가로 스크롤 카드 행 + 더보기 버튼. 이유브로우/h2는
 * 부모(ThemeCollections)가 섹션당 한 번만 렌더한다 — 이전 버전은 테마마다 "저혼잡 · 숨은 테마"
 * 이유브로우를 반복해(테마가 몇 개든 항상 같은 문구) 스캔할 때 "또 같은 라벨"이라는 잡음을
 * 만들었다(03-design-spec.md Phase 3 근거, ui-ux-pro-max `visual-hierarchy`: 계층은 크기/간격/
 * 대비로 만들되 반복 라벨로 만들지 않는다).
 *
 * §44 — `total`/`has_more`는 backend가 additive로 얹어준 필드(구버전 backend는 없을 수 있다).
 * `total`이 없으면 "전체 N곳" 표기를 생략하고(지어내지 않음), `has_more`가 없거나 false면
 * 더보기 버튼 자체를 렌더하지 않는다(구버전 backend에서도 화면이 깨지지 않는다).
 */
function ThemeCollectionGroup({
  collection,
  onLoadMore,
  onCollapse,
  loadingMore,
  loadError,
}: {
  collection: SpotCollection;
  onLoadMore: () => void;
  onCollapse: () => void;
  loadingMore: boolean;
  loadError: boolean;
}) {
  // 초기 노출분보다 많이 펼쳐져 있을 때만 "접기"를 보여준다(대표 지시).
  const canCollapse = collection.spots.length > INITIAL_PER_THEME;
  // 남은 개수를 버튼에 적어 "얼마나 더 있는지"를 숨기지 않는다. total 을 모르면 그냥 "더보기".
  const remaining =
    typeof collection.total === "number"
      ? Math.max(collection.total - collection.spots.length, 0)
      : null;
  const moreLabel = remaining && remaining > 0 ? `더보기 (${remaining}곳 더)` : "더보기";

  return (
    <div className="theme-collections__group">
      {/* 대표 지시(2026-08-01): 더보기는 카드 아래가 아니라 **테마 제목 옆**에 둔다
          ("전통시장 구경  더보기"). 스크롤을 끝까지 내리지 않아도 눌러 넓힐 수 있고,
          테마가 여럿 쌓인 화면에서 버튼이 카드 사이에 끼어 보이던 잡음도 사라진다. */}
      <div className="theme-collections__group-head">
        <h3 className="theme-collections__group-title">{collection.title}</h3>
        {typeof collection.total === "number" && (
          <span className="theme-collections__count">전체 {collection.total}곳</span>
        )}
        {canCollapse && (
          <button
            type="button"
            className="theme-collections__more-btn theme-collections__more-btn--collapse"
            onClick={onCollapse}
            aria-label={`${collection.title} 접기`}
          >
            접기
          </button>
        )}
        {collection.has_more && (
          <button
            type="button"
            className="theme-collections__more-btn"
            onClick={onLoadMore}
            disabled={loadingMore}
            aria-label={`${collection.title} 더보기`}
          >
            {loadingMore ? "불러오는 중…" : moreLabel}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M9 5l7 7-7 7"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        )}
      </div>
      <div className="featured-scroll" role="list" aria-label={collection.title}>
        {collection.spots.map((spot) => (
          <FeaturedSpotCard key={spot.id} spot={spot} />
        ))}
      </div>
      {loadError && (
        <p className="theme-collections__load-error" role="status">
          더 불러오지 못했어요. 잠시 후 다시 시도해주세요.
        </p>
      )}
    </div>
  );
}

type FetchStatus = "loading" | "success" | "error";
/** 테마별 "더보기" UI 상태. 데이터(spots/total/has_more)는 CollectionsResponse 쪽(data state)에
 *  그대로 두고, 이 로딩/에러 플래그만 theme_key로 따로 들고 있다(§44). */
interface MoreState {
  loadingMore: boolean;
  error: boolean;
}

interface ThemeCollectionsProps {
  /** 선택된 지역(sigungu_cd). FeaturedSpots와 동일 원칙 — 없으면 백엔드 기본 지역으로 호출한다. */
  regionCode?: string | null;
  /**
   * 지역 미선택 상태에서만 true(홈이 넘긴다). true면 backend가 9권역을 섞어 응답한다 —
   * FeaturedSpots의 동명 prop과 같은 규약이며, 프론트는 섞는 로직을 갖지 않는다.
   * (§37.5 — 대표 피드백 "테마별 여행은 새로고침해도 같은 곳만 / 인생샷도 부산만 나온다")
   */
  diverse?: boolean;
  /**
   * §A(2026-08-01, 03-design-spec.md — 대표 지시 "테마별 여행은 홈에서 빼고 카테고리로 넘겨라")
   * 상위 몇 개 테마까지 보여줄지. 기본값은 기존 홈 동작과 동일한 MAX_HOME_COLLECTIONS(3) —
   * `/themes` 페이지는 더 큰 값(Infinity)을 넘겨 전체 테마를 보여준다. API 호출·정렬 로직은
   * 그대로이고(백엔드가 이미 정렬해 내려준 순서), 프론트는 자르는 개수만 다르게 쓴다.
   */
  limit?: number;
  /**
   * true면 이 컴포넌트가 자기 자신을 감싸는 `<section className="section featured-section">` +
   * 이유브로우 + h2 헤딩을 렌더하지 않고, 테마 그룹(제목+카드행)만 렌더한다. `/themes` 페이지가
   * 이미 자신의 h1 섹션(§ThemesContent.tsx)을 갖고 있어 이중 헤딩·이중 패딩을 피하기 위함이다.
   * 홈은 기본값(false)을 그대로 써 기존 렌더 결과와 동일하다.
   */
  bare?: boolean;
}

/**
 * "테마별로 골라보는 여행" 섹션. 한 번의 fetch(/api/v1/collections)로 여러 테마 행을 채운다.
 * 현재 유일한 사용처는 `/themes` 페이지(ThemesContent.tsx, `limit={Infinity}` + `bare`) —
 * 지역 선택은 ThemesContent가 소유하고 이 컴포넌트에 `regionCode`/`diverse`로 내려준다(§44).
 * 과거 홈에도 `limit=MAX_HOME_COLLECTIONS`(미지정)로 쓰였으나 §43에서 분리됐다 — prop 구조는
 * 그대로 남겨둬 향후 재사용 시 API 계약 변경 없이 다시 꽂을 수 있다.
 *
 * §44(신규, 2026-08-0X, 03-design-spec.md — 대표 지시 "테마별로 몇 가지만 나오는데 전체를 다
 * 볼 수 있도록 더보기") — 테마별 독립 "더보기": 첫 조회는 테마당 INITIAL_PER_THEME개만 받고,
 * 테마 카드 행 아래 "더보기" 버튼을 누르면 **그 테마만** `theme=<key>&offset=<현재 개수>&
 * per_theme=<증분>&seed=<최초 응답 seed>`로 재조회해 뒤에 이어붙인다. 다른 테마는 건드리지
 * 않는다(재조회·재렌더 없음) — 각 테마가 독립적인 loadingMore/error 상태(moreState)를 갖는다.
 * seed 재사용 규약(핸드오프 필수 확인 사항): 최초 응답의 `data.seed`를 그대로 더보기 요청에
 * 실어야 backend가 같은 랜덤 조합을 이어서 준다(01-backend-design.md/01-interface-contract.md
 * 계약, 03-design-spec.md §44 근거) — 지역이 바뀌거나 새로고침하면 fetch effect가 처음부터
 * 다시 돌아 새 seed를 받는다(아래 useEffect가 [regionCode, diverse]에만 의존).
 *
 * graceful: 404/네트워크 실패 시 이 컴포넌트 전체가 조용히 사라진다(FeaturedSpots와 동일 원칙,
 * 초기 로딩에만 적용) — 반면 "더보기" 실패는 이미 보여준 카드까지 지우지 않고, 해당 테마 아래에
 * 조용한 에러 문구만 남긴다(화면이 깨지지 않게, §44 지시서 요구).
 */
export default function ThemeCollections({
  regionCode,
  diverse,
  limit = MAX_HOME_COLLECTIONS,
  bare = false,
}: ThemeCollectionsProps) {
  const [status, setStatus] = useState<FetchStatus>("loading");
  const [data, setData] = useState<CollectionsResponse | null>(null);
  const [moreState, setMoreState] = useState<Record<string, MoreState>>({});

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    setMoreState({}); // 지역이 바뀌면 이전 지역의 더보기 상태를 들고 가지 않는다.
    fetchCollections(regionCode ?? undefined, controller.signal, diverse, {
      perTheme: INITIAL_PER_THEME,
    })
      .then((res) => {
        setData(res);
        setStatus("success");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        // 엔드포인트 미배포(404)든 네트워크 실패든 원인을 구분하지 않고 조용히 숨긴다.
        setStatus("error");
      });
    return () => controller.abort();
  }, [regionCode, diverse]);

  /**
   * 접기(대표 지시 2026-08-01) — 그 테마를 처음 개수(INITIAL_PER_THEME)로 되돌린다.
   * **재조회하지 않는다**: 이미 받은 목록의 앞부분만 남기므로 원천·사진 호출이 0이고,
   * 같은 seed 안에서 자른 것이라 다시 "더보기"를 눌러도 이어붙는 순서가 어긋나지 않는다
   * (offset 은 항상 현재 보유 개수 기준이라 자동으로 맞는다).
   */
  const handleCollapse = (collection: SpotCollection) => {
    setData((prev) =>
      prev
        ? {
            ...prev,
            collections: prev.collections.map((c) =>
              c.theme_key === collection.theme_key
                ? {
                    ...c,
                    spots: c.spots.slice(0, INITIAL_PER_THEME),
                    // 잘라냈으니 남은 게 다시 생긴다(total 을 알면 그 기준, 모르면 보수적으로 true).
                    has_more:
                      typeof c.total === "number"
                        ? c.total > INITIAL_PER_THEME
                        : true,
                  }
                : c
            ),
          }
        : prev
    );
    setMoreState((prev) => ({
      ...prev,
      [collection.theme_key]: { loadingMore: false, error: false },
    }));
  };

  const handleLoadMore = (collection: SpotCollection) => {
    if (moreState[collection.theme_key]?.loadingMore) return;
    setMoreState((prev) => ({
      ...prev,
      [collection.theme_key]: { loadingMore: true, error: false },
    }));
    fetchCollections(regionCode ?? undefined, undefined, diverse, {
      theme: collection.theme_key,
      offset: collection.spots.length,
      perTheme: LOAD_MORE_INCREMENT,
      seed: data?.seed,
    })
      .then((res) => {
        const appended = res.collections.find((c) => c.theme_key === collection.theme_key);
        if (appended) {
          setData((prev) =>
            prev
              ? {
                  ...prev,
                  collections: prev.collections.map((c) =>
                    c.theme_key === collection.theme_key
                      ? {
                          ...c,
                          // 중복 방어(2026-08-01, 운영 실측): 서버 페이지네이션이 드물게 같은
                          // 스팟을 다음 페이지에 다시 실어 화면에 두 번 뜬 사례가 있었다
                          // (경주다방, id 2838756 — API 재현 13회 중 0회로 확률이 낮다).
                          // 원인은 backend 에서 조사 중이고, 여기서는 **이미 가진 id 는 버린다** —
                          // 사용자가 같은 카드를 두 번 보는 일은 어떤 경우에도 없어야 하고,
                          // React key 중복 경고도 함께 막는다.
                          spots: [
                            ...c.spots,
                            ...appended.spots.filter(
                              (s) => !c.spots.some((prevSpot) => prevSpot.id === s.id)
                            ),
                          ],
                          total: appended.total ?? c.total,
                          has_more: appended.has_more ?? false,
                        }
                      : c
                  ),
                }
              : prev
          );
        }
        setMoreState((prev) => ({
          ...prev,
          [collection.theme_key]: { loadingMore: false, error: !appended },
        }));
      })
      .catch(() => {
        setMoreState((prev) => ({
          ...prev,
          [collection.theme_key]: { loadingMore: false, error: true },
        }));
      });
  };

  if (status === "error") return null;

  const visibleCollections = (data?.collections ?? [])
    .filter((c) => c.spots.length > 0)
    .slice(0, limit);

  if (status === "success" && visibleCollections.length === 0) return null;

  const body = (
    <>
      {status === "loading" && (
        <div className="theme-collections__group">
          <div
            className="featured-scroll"
            role="list"
            aria-label="테마별 여행 불러오는 중"
            aria-busy="true"
          >
            {Array.from({ length: SKELETON_COUNT }).map((_, i) => (
              <FeaturedCardSkeleton key={i} />
            ))}
          </div>
        </div>
      )}

      {status === "success" &&
        visibleCollections.map((collection) => (
          <ThemeCollectionGroup
            key={collection.theme_key}
            collection={collection}
            onLoadMore={() => handleLoadMore(collection)}
            onCollapse={() => handleCollapse(collection)}
            loadingMore={moreState[collection.theme_key]?.loadingMore ?? false}
            loadError={moreState[collection.theme_key]?.error ?? false}
          />
        ))}
    </>
  );

  if (bare) return body;

  return (
    <section className="section featured-section" aria-label="테마별로 골라보는 여행">
      <span className="eyebrow-pill eyebrow-pill--mint">저혼잡 · 숨은 테마</span>
      <h2 className="section__title">테마별로 골라보는 여행</h2>
      {body}
    </section>
  );
}
