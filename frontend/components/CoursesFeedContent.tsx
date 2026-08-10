"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, SharedCourseFeedItem, fetchSharedCoursesFeed } from "../lib/api";

type Status = "loading" | "success" | "error";
const PAGE_SIZE = 20;
const SKELETON_COUNT = 6;

/** "YYYY.MM.DD" — 파싱 실패 시 원본 문자열로 폴백(사이트 전역 날짜 표기 관례). */
function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
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
 */
export default function CoursesFeedContent() {
  const [status, setStatus] = useState<Status>("loading");
  const [items, setItems] = useState<SharedCourseFeedItem[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<ApiError | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [retryTick, setRetryTick] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    setError(null);
    fetchSharedCoursesFeed(PAGE_SIZE, 0, controller.signal)
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
  }, [retryTick]);

  const handleLoadMore = () => {
    setLoadingMore(true);
    fetchSharedCoursesFeed(PAGE_SIZE, items.length)
      .then((res) => {
        setItems((prev) => [...prev, ...res.items]);
        setLoadingMore(false);
      })
      .catch(() => setLoadingMore(false));
  };

  const retry = () => setRetryTick((t) => t + 1);

  return (
    <section className="section" aria-labelledby="coursesFeedHeading">
      <span className="eyebrow-pill eyebrow-pill--azure">다른 사람 코스</span>
      <h1 className="section__title" id="coursesFeedHeading">
        다른 사람이 공유한 코스
      </h1>
      <p className="tips-intro">다른 여행자가 만들어 공유한 코스를 구경해보세요.</p>

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
                <h3 className="shared-course-card__title">{item.title}</h3>
                <p className="shared-course-card__meta">
                  {item.nickname} · {item.spot_count}곳 · 조회 {item.view_count}
                </p>
                <p className="shared-course-card__date">{formatDate(item.created_at)}</p>
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
