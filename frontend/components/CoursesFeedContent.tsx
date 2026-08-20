"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ApiError,
  SharedCourseFeedItem,
  SharedCoursesSort,
  fetchSharedCoursesFeed,
  likeSharedCourse,
  unlikeSharedCourse,
} from "../lib/api";
import { logout } from "../lib/authStorage";
import { useLoginGate } from "./LoginGateProvider";

type Status = "loading" | "success" | "error";
const PAGE_SIZE = 20;
const SKELETON_COUNT = 6;

/** "YYYY.MM.DD" — 파싱 실패 시 원본 문자열로 폴백(사이트 전역 날짜 표기 관례). */
function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

/** 좋아요 하트 — 사이트에 기존 하트 아이콘이 없어(즐겨찾기는 북마크 아이콘) 신규 SVG(§47.5).
 * 이모지 대신 인라인 SVG(ui-ux-pro-max 체크리스트 근거), 아웃라인/채움 2벌을 fill로 전환한다. */
function HeartIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden="true"
    >
      <path
        d="M12 21s-6.7-4.35-9.3-8.1C.8 9.8 1.6 6 5 4.6c2.2-.9 4.6 0 6 2 1.4-2 3.8-2.9 6-2 3.4 1.4 4.2 5.2 2.3 8.3C18.7 16.65 12 21 12 21z"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * §41(신규) — 다른 사람이 공유한 코스 피드(`/courses`, 신규 페이지 — 지시서: "홈에 넣지 말 것").
 * 01-interface-contract.md 부록 R.7 `GET /courses/shared`를 소비한다. 목록 응답에는 course
 * payload가 없어(응답 폭발 방지, R.7) 카드에는 제목·닉네임·스팟수·조회수·날짜만 보여주고,
 * 상세는 카드 클릭 시 `/course/shared/{code}`에서 별도로 불러온다.
 *
 * 빈 상태·에러 처리는 FestivalsContent.tsx와 동일 원칙(이 페이지는 "다른 사람 코스" 전용 목적지라
 * 실패를 조용히 숨기지 않고 에러 카드 + 재시도로 안내한다) — ui-ux-pro-max ux 도메인 "Empty
 * States"(Do: 도움이 되는 메시지 + 행동 유도, 03-design-spec.md §41 근거) 그대로 반영.
 *
 * §47.5(신규, 2026-08-20, 부록 R.14) — 정렬(최신순/좋아요순)과 좋아요 하트를 추가했다.
 * 정렬은 `/course`의 `.course-mode-switch`(role=tablist)를 그대로 재사용한다(새 컴포넌트 없음,
 * 두 화면 모두 "데이터 보는 방식을 바꾸는 2택 스위치"라는 같은 상호작용). 하트는 카드
 * (`<Link>`) 내부 우상단 절대배치라 클릭 시 preventDefault+stopPropagation으로 상세 페이지
 * 이동을 막는다. 낙관적 업데이트 + 실패 시 롤백, 401이면 로그인 게이트를 다시 띄운다(R.14.7-8).
 */
export default function CoursesFeedContent() {
  const [status, setStatus] = useState<Status>("loading");
  const [items, setItems] = useState<SharedCourseFeedItem[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<ApiError | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [retryTick, setRetryTick] = useState(0);
  const [sort, setSort] = useState<SharedCoursesSort>("latest");
  const { requireLogin } = useLoginGate();

  // 좋아요 실패 시 3초간 노출 후 자동으로 지우는 인라인 문구(카드별). 사이트에 토스트가 없어
  // MyPageContent.tsx의 "계정 삭제 2단계 확인"이 쓰는 5초 자동 되돌림 관례를 참고했다(§47.5).
  const [likeNotes, setLikeNotes] = useState<Record<string, boolean>>({});
  const noteTimers = useRef<Record<string, number>>({});
  useEffect(() => {
    return () => {
      Object.values(noteTimers.current).forEach((id) => window.clearTimeout(id));
    };
  }, []);
  const showLikeNote = (shareCode: string) => {
    setLikeNotes((prev) => ({ ...prev, [shareCode]: true }));
    if (noteTimers.current[shareCode]) window.clearTimeout(noteTimers.current[shareCode]);
    noteTimers.current[shareCode] = window.setTimeout(() => {
      setLikeNotes((prev) => {
        const next = { ...prev };
        delete next[shareCode];
        return next;
      });
    }, 3000);
  };

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    setError(null);
    fetchSharedCoursesFeed(PAGE_SIZE, 0, controller.signal, sort)
      .then((res) => {
        setItems(res.items);
        setTotal(res.total);
        setStatus("success");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          err instanceof ApiError ? err : new ApiError(0, "UNKNOWN", "다른 사람 코스를 불러오지 못했습니다.")
        );
        setStatus("error");
      });
    return () => controller.abort();
  }, [retryTick, sort]);

  const handleLoadMore = () => {
    setLoadingMore(true);
    fetchSharedCoursesFeed(PAGE_SIZE, items.length, undefined, sort)
      .then((res) => {
        setItems((prev) => [...prev, ...res.items]);
        setLoadingMore(false);
      })
      .catch(() => setLoadingMore(false));
  };

  const retry = () => setRetryTick((t) => t + 1);

  // 정렬이 바뀌면 offset을 0으로 리셋해 다시 부른다(R.14.7-9) — 위 effect가 sort 의존성으로
  // 이미 처음부터 다시 불러오므로, 여기서는 items/total만 비워 이전 정렬의 잔상이 안 보이게 한다.
  const handleSortChange = (next: SharedCoursesSort) => {
    if (next === sort) return;
    setItems([]);
    setTotal(0);
    setSort(next);
  };

  // §47.5 — 낙관적 업데이트 + 실패 시 롤백. 401이면 로컬 로그인 캐시를 정리하고 로그인 게이트를
  // 다시 띄운다(R.14.7-8) — 로그인 성공 시 대기 중이던 이 좋아요 액션이 이어서 실행된다.
  const performLike = (item: SharedCourseFeedItem) => {
    const wasLiked = item.liked_by_me;
    const prevCount = item.like_count;
    setItems((prev) =>
      prev.map((it) =>
        it.share_code === item.share_code
          ? { ...it, liked_by_me: !wasLiked, like_count: wasLiked ? prevCount - 1 : prevCount + 1 }
          : it
      )
    );
    const call = wasLiked ? unlikeSharedCourse : likeSharedCourse;
    call(item.share_code)
      .then((res) => {
        setItems((prev) =>
          prev.map((it) =>
            it.share_code === item.share_code
              ? { ...it, liked_by_me: res.liked, like_count: res.like_count }
              : it
          )
        );
      })
      .catch((err: unknown) => {
        setItems((prev) =>
          prev.map((it) =>
            it.share_code === item.share_code
              ? { ...it, liked_by_me: wasLiked, like_count: prevCount }
              : it
          )
        );
        if (err instanceof ApiError && err.status === 401) {
          logout();
          requireLogin(
            () => performLike(item),
            "로그인하면 마음에 드는 코스에 좋아요를 남길 수 있어요."
          );
          return;
        }
        showLikeNote(item.share_code);
      });
  };

  const handleLike = (item: SharedCourseFeedItem) => {
    requireLogin(() => performLike(item), "로그인하면 마음에 드는 코스에 좋아요를 남길 수 있어요.");
  };

  return (
    <section className="section" aria-labelledby="coursesFeedHeading">
      <span className="eyebrow-pill eyebrow-pill--azure">다른 사람 코스</span>
      <h1 className="section__title" id="coursesFeedHeading">
        다른 사람이 공유한 코스
      </h1>
      <p className="tips-intro">다른 여행자가 만들어 공유한 코스를 구경해보세요.</p>

      <div className="course-mode-switch shared-course-sort" role="tablist" aria-label="정렬">
        <button
          type="button"
          role="tab"
          aria-selected={sort === "latest"}
          className={`course-mode-switch__tab${sort === "latest" ? " is-active" : ""}`}
          onClick={() => handleSortChange("latest")}
        >
          최신순
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={sort === "popular"}
          className={`course-mode-switch__tab${sort === "popular" ? " is-active" : ""}`}
          onClick={() => handleSortChange("popular")}
        >
          좋아요순
        </button>
      </div>

      {status === "loading" && (
        <div className="shared-course-grid" role="list" aria-label="공유 코스 불러오는 중" aria-busy="true">
          {Array.from({ length: SKELETON_COUNT }).map((_, i) => (
            <div key={i} className="shared-course-card shared-course-card--skeleton" aria-hidden="true">
              <div className="skeleton-bar" style={{ width: "70%", height: "20px" }} />
              <div className="skeleton-bar" style={{ width: "50%", height: "14px", marginTop: "8px" }} />
            </div>
          ))}
        </div>
      )}

      {status === "success" && items.length === 0 && (
        <div className="board-error" role="status">
          <p className="board-error__msg">아직 공유된 코스가 없어요.</p>
          <p className="board-error__hint">코스를 만들고 가장 먼저 공유해보세요.</p>
          <Link className="btn btn--mint" href="/course">
            코스 만들러 가기
          </Link>
        </div>
      )}

      {status === "success" && items.length > 0 && (
        <>
          <div className="shared-course-grid" role="list">
            {items.map((item) => (
              <Link
                key={item.share_code}
                href={`/course/shared/${item.share_code}`}
                className="shared-course-card"
                role="listitem"
              >
                <button
                  type="button"
                  className={`shared-course-card__like${item.liked_by_me ? " is-liked" : ""}`}
                  aria-pressed={item.liked_by_me}
                  aria-label={item.liked_by_me ? "좋아요 취소" : "좋아요"}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handleLike(item);
                  }}
                >
                  <HeartIcon filled={item.liked_by_me} />
                  <span>{item.like_count}</span>
                </button>
                <h3 className="shared-course-card__title">{item.title}</h3>
                <p className="shared-course-card__meta">
                  {item.nickname} · {item.spot_count}곳 · 조회 {item.view_count}
                </p>
                <p className="shared-course-card__date">{formatDate(item.created_at)}</p>
                {likeNotes[item.share_code] && (
                  <p className="shared-course-card__like-note" role="status">
                    반영 안 됐어요, 다시 눌러주세요
                  </p>
                )}
              </Link>
            ))}
          </div>
          {items.length < total && (
            <button
              type="button"
              className="btn btn--white review-more-btn"
              onClick={handleLoadMore}
              disabled={loadingMore}
            >
              {loadingMore ? "불러오는 중…" : `더보기 (${items.length}/${total})`}
            </button>
          )}
        </>
      )}

      {status === "error" && (
        <div className="board-error" role="alert">
          <p className="board-error__msg">{error?.message ?? "다른 사람 코스를 불러오지 못했습니다."}</p>
          <p className="board-error__hint">
            {error?.status === 0
              ? "백엔드 서버가 켜져 있는지 확인해주세요 (localhost:8000). 잠시 후 다시 시도해주세요."
              : "잠시 후 다시 시도해주세요."}
          </p>
          <button className="btn btn--coral" type="button" onClick={retry}>
            다시 시도
          </button>
        </div>
      )}
    </section>
  );
}
