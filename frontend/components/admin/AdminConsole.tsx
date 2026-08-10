"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../lib/api";
import AdminTrafficTab from "./AdminTraffic";
import {
  AdminCourseItem,
  AdminReviewItem,
  AdminStats,
  CourseStatusFilter,
  ReviewSortOption,
  ReviewStatusFilter,
  adminLogout,
  deleteCourse,
  deleteReview,
  fetchAdminCourses,
  fetchAdminReviews,
  fetchAdminStats,
  isAutoHidden,
  setCourseHidden,
  setReviewHidden,
} from "../../lib/adminApi";

/**
 * 관리자 콘솔 본체 (03-admin-console-design.md §4~§5.7)
 *
 * ## 갱신 방식: 낙관적 갱신을 하지 않는다
 * hide/unhide/delete 는 응답(`AdminModerationResponse`)을 받은 뒤에야 화면을 바꾼다.
 * 운영 조작은 "됐다고 보였는데 실제로는 안 된" 상태가 가장 위험하기 때문이다.
 *
 * ## 자동 갱신(폴링)을 하지 않는다
 * 운영자 3명이 쓰는 내부 도구다. 폴링은 얻는 것 없이 서버 요청만 늘린다. 수동 새로고침만 둔다.
 */

const PAGE_SIZE = 20;

function fmtDateTime(iso: string): string {
  // 서버가 ISO8601+KST 로 준다. 관리자 도구라 상대시간 가공은 불필요 — 자르기만 한다.
  if (!iso) return "";
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : iso;
}

function fmtTime(iso: string): string {
  const m = iso.match(/T(\d{2}):(\d{2})/);
  return m ? `${m[1]}:${m[2]}` : "";
}

type Toast = { text: string; tone: "info" | "error" } | null;

type PendingDelete =
  | { kind: "review"; item: AdminReviewItem }
  | { kind: "course"; item: AdminCourseItem }
  | null;

export default function AdminConsole({
  operator,
  expiresAt,
  onSessionLost,
}: {
  operator: string;
  expiresAt: string;
  onSessionLost: () => void;
}) {
  const [tab, setTab] = useState<"reviews" | "courses" | "traffic">("reviews");
  const [stats, setStats] = useState<AdminStats | null>(null);

  const [reviewStatus, setReviewStatus] = useState<ReviewStatusFilter>("reported");
  const [reviewSort, setReviewSort] = useState<ReviewSortOption>("reported");
  const [reviews, setReviews] = useState<AdminReviewItem[] | null>(null);
  const [reviewTotal, setReviewTotal] = useState(0);

  const [courseStatus, setCourseStatus] = useState<CourseStatusFilter>("all");
  const [courses, setCourses] = useState<AdminCourseItem[] | null>(null);
  const [courseTotal, setCourseTotal] = useState(0);

  const [listError, setListError] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<PendingDelete>(null);
  const [toast, setToast] = useState<Toast>(null);

  /** 401 은 세션 만료다. 어느 요청에서 나오든 로그인 화면으로 되돌린다. */
  const guard = useCallback(
    (e: unknown): boolean => {
      if (e instanceof ApiError && e.status === 401) {
        onSessionLost();
        return true;
      }
      return false;
    },
    [onSessionLost],
  );

  const showToast = useCallback((text: string, tone: "info" | "error" = "info") => {
    setToast({ text, tone });
    setTimeout(() => setToast(null), 3200);
  }, []);

  const loadStats = useCallback(async () => {
    try {
      setStats(await fetchAdminStats());
    } catch (e) {
      guard(e);
    }
  }, [guard]);

  const loadReviews = useCallback(async () => {
    setListError(false);
    setReviews(null);
    try {
      const res = await fetchAdminReviews({
        status: reviewStatus,
        sort: reviewSort,
        limit: PAGE_SIZE,
      });
      setReviews(res.items);
      setReviewTotal(res.total);
    } catch (e) {
      if (!guard(e)) setListError(true);
    }
  }, [reviewStatus, reviewSort, guard]);

  const loadCourses = useCallback(async () => {
    setListError(false);
    setCourses(null);
    try {
      const res = await fetchAdminCourses({ status: courseStatus, limit: PAGE_SIZE });
      setCourses(res.items);
      setCourseTotal(res.total);
    } catch (e) {
      if (!guard(e)) setListError(true);
    }
  }, [courseStatus, guard]);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);
  useEffect(() => {
    if (tab === "reviews") void loadReviews();
  }, [tab, loadReviews]);
  useEffect(() => {
    if (tab === "courses") void loadCourses();
  }, [tab, loadCourses]);

  async function toggleReview(item: AdminReviewItem) {
    setBusyId(`r${item.id}`);
    try {
      const res = await setReviewHidden(item.id, !item.hidden);
      // 낙관적 갱신이 아니라 **응답값으로** 확정한다.
      setReviews((list) =>
        (list ?? []).map((r) => (r.id === item.id ? { ...r, hidden: res.hidden ?? !r.hidden } : r)),
      );
      void loadStats();
    } catch (e) {
      if (guard(e)) return;
      if (e instanceof ApiError && e.status === 404) {
        showToast("이미 처리된 항목이에요. 목록을 새로고침할게요.");
        void loadReviews();
      } else showToast("처리하지 못했어요.", "error");
    } finally {
      setBusyId(null);
    }
  }

  async function toggleCourse(item: AdminCourseItem) {
    setBusyId(`c${item.share_code}`);
    try {
      const res = await setCourseHidden(item.share_code, !item.hidden);
      setCourses((list) =>
        (list ?? []).map((c) =>
          c.share_code === item.share_code ? { ...c, hidden: res.hidden ?? !c.hidden } : c,
        ),
      );
      void loadStats();
    } catch (e) {
      if (guard(e)) return;
      if (e instanceof ApiError && e.status === 404) {
        showToast("이미 처리된 항목이에요. 목록을 새로고침할게요.");
        void loadCourses();
      } else showToast("처리하지 못했어요.", "error");
    } finally {
      setBusyId(null);
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    const { kind, item } = pendingDelete;
    const key = kind === "review" ? `r${(item as AdminReviewItem).id}` : `c${(item as AdminCourseItem).share_code}`;
    setBusyId(key);
    try {
      if (kind === "review") {
        await deleteReview((item as AdminReviewItem).id);
        setReviews((l) => (l ?? []).filter((r) => r.id !== (item as AdminReviewItem).id));
        setReviewTotal((n) => Math.max(0, n - 1));
      } else {
        await deleteCourse((item as AdminCourseItem).share_code);
        setCourses((l) => (l ?? []).filter((c) => c.share_code !== (item as AdminCourseItem).share_code));
        setCourseTotal((n) => Math.max(0, n - 1));
      }
      setPendingDelete(null);
      showToast("삭제했어요.");
      void loadStats();
    } catch (e) {
      if (guard(e)) return;
      if (e instanceof ApiError && e.status === 404) {
        showToast("이미 처리된 항목이에요. 목록을 새로고침할게요.");
        setPendingDelete(null);
        kind === "review" ? void loadReviews() : void loadCourses();
      } else showToast("삭제하지 못했어요.", "error");
    } finally {
      setBusyId(null);
    }
  }

  async function doLogout() {
    try {
      await adminLogout();
    } catch {
      // 실패해도 화면은 로그인으로 되돌린다(쿠키가 이미 죽었을 수 있다).
    }
    onSessionLost();
  }

  const threshold = stats?.review_hide_report_threshold ?? 0;

  return (
    <div className="admin">
      <header className="admin-bar">
        <span className="admin-bar__brand">
          <i className="admin-bar__dot" aria-hidden="true" />
          숨은길 관리자 콘솔
        </span>
        <span className="admin-bar__right">
          <span className="admin-bar__who">
            {operator ? `${operator}님` : "운영자"} · {fmtTime(expiresAt)}까지 세션 유지
          </span>
          <button type="button" className="admin-btn admin-btn--ghost" onClick={doLogout}>
            로그아웃
          </button>
        </span>
      </header>

      {/* --- 통계 스트립 --- */}
      <section className="admin-stats" aria-label="운영 현황">
        {stats ? (
          <>
            <button
              type="button"
              className={`admin-stat admin-stat--pill ${stats.reports_pending > 0 ? "is-warn" : ""}`}
              onClick={() => {
                setTab("reviews");
                setReviewStatus("reported");
              }}
            >
              {stats.reports_pending > 0
                ? `신고 대기 ${stats.reports_pending}`
                : "신고 대기 없음"}
            </button>
            <span className="admin-stat">
              오늘 등록 <b>{stats.reviews_today}</b>
            </span>
            <span className="admin-stat">
              후기 <b>{stats.reviews_total}</b> · 숨김 <b>{stats.reviews_hidden}</b>
            </span>
            <span className="admin-stat">
              코스 <b>{stats.courses_total}</b> · 숨김 <b>{stats.courses_hidden}</b>
            </span>
            <span className="admin-stats__meta">
              누적 신고 {stats.reports_total} · 기준 {fmtTime(stats.generated_at)}
              <button
                type="button"
                className="admin-btn admin-btn--ghost admin-btn--sm"
                onClick={() => {
                  void loadStats();
                  tab === "reviews" ? void loadReviews() : void loadCourses();
                }}
              >
                새로고침
              </button>
            </span>
          </>
        ) : (
          <span className="admin-stats__meta">현황을 불러오는 중…</span>
        )}
      </section>

      {/* --- 탭 --- */}
      <nav className="admin-tabs">
        <button
          type="button"
          className={`admin-tab ${tab === "reviews" ? "is-active" : ""}`}
          onClick={() => setTab("reviews")}
        >
          후기 관리
        </button>
        <button
          type="button"
          className={`admin-tab ${tab === "courses" ? "is-active" : ""}`}
          onClick={() => setTab("courses")}
        >
          공유 코스 관리
        </button>
        <button
          type="button"
          className={`admin-tab ${tab === "traffic" ? "is-active" : ""}`}
          onClick={() => setTab("traffic")}
        >
          트래픽
        </button>

        <span className="admin-tabs__filters">
          {tab === "traffic" ? null : tab === "reviews" ? (
            <>
              <select
                className="admin-select"
                value={reviewStatus}
                onChange={(e) => setReviewStatus(e.target.value as ReviewStatusFilter)}
                aria-label="후기 상태 필터"
              >
                <option value="reported">신고됨</option>
                <option value="hidden">숨김</option>
                <option value="all">전체</option>
              </select>
              <select
                className="admin-select"
                value={reviewSort}
                onChange={(e) => setReviewSort(e.target.value as ReviewSortOption)}
                aria-label="후기 정렬"
              >
                <option value="reported">신고 많은순</option>
                <option value="recent">최신순</option>
              </select>
            </>
          ) : (
            /* 코스에는 sort 파라미터도 reported 상태값도 API 에 없다. 없는 기능을 있는 것처럼
               보이지 않도록 정렬 드롭다운을 만들지 않는다. */
            <select
              className="admin-select"
              value={courseStatus}
              onChange={(e) => setCourseStatus(e.target.value as CourseStatusFilter)}
              aria-label="코스 상태 필터"
            >
              <option value="all">전체</option>
              <option value="hidden">숨김</option>
            </select>
          )}
        </span>
      </nav>

      {/* --- 목록 --- */}
      <section className="admin-list">
        {tab === "traffic" ? (
          <AdminTrafficTab onSessionLost={onSessionLost} />
        ) : listError ? (
          <div className="admin-empty">
            <p>목록을 불러오지 못했어요.</p>
            <button
              type="button"
              className="admin-btn admin-btn--primary"
              onClick={() => (tab === "reviews" ? void loadReviews() : void loadCourses())}
            >
              다시 시도
            </button>
          </div>
        ) : tab === "reviews" ? (
          reviews === null ? (
            <AdminSkeleton />
          ) : reviews.length === 0 ? (
            <div className="admin-empty">
              <p>
                {reviewStatus === "reported"
                  ? "신고된 후기가 없어요. 좋은 상태예요."
                  : reviewStatus === "hidden"
                    ? "숨겨진 후기가 없어요."
                    : "아직 등록된 후기가 없어요."}
              </p>
              {reviewStatus === "reported" && (
                <button
                  type="button"
                  className="admin-btn admin-btn--ghost"
                  onClick={() => setReviewStatus("all")}
                >
                  전체 후기 보기
                </button>
              )}
            </div>
          ) : (
            <>
              {reviews.map((r) => (
                <ReviewRow
                  key={r.id}
                  item={r}
                  threshold={threshold}
                  busy={busyId === `r${r.id}`}
                  onToggle={() => toggleReview(r)}
                  onDelete={() => setPendingDelete({ kind: "review", item: r })}
                />
              ))}
              <p className="admin-list__count">{reviews.length}건 표시 · 전체 {reviewTotal}건</p>
            </>
          )
        ) : courses === null ? (
          <AdminSkeleton />
        ) : courses.length === 0 ? (
          <div className="admin-empty">
            <p>{courseStatus === "hidden" ? "숨겨진 코스가 없어요." : "아직 공유된 코스가 없어요."}</p>
          </div>
        ) : (
          <>
            {courses.map((c) => (
              <CourseRow
                key={c.share_code}
                item={c}
                busy={busyId === `c${c.share_code}`}
                onToggle={() => toggleCourse(c)}
                onDelete={() => setPendingDelete({ kind: "course", item: c })}
              />
            ))}
            <p className="admin-list__count">{courses.length}건 표시 · 전체 {courseTotal}건</p>
          </>
        )}
      </section>

      {pendingDelete && (
        <DeleteDialog
          pending={pendingDelete}
          busy={busyId !== null}
          onCancel={() => setPendingDelete(null)}
          onConfirm={confirmDelete}
        />
      )}

      {toast && (
        <div className={`admin-toast ${toast.tone === "error" ? "is-error" : ""}`} role="status">
          {toast.text}
        </div>
      )}
    </div>
  );
}

function AdminSkeleton() {
  return (
    <div aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <div key={i} className="admin-row admin-row--skeleton" />
      ))}
    </div>
  );
}

function ReviewRow({
  item,
  threshold,
  busy,
  onToggle,
  onDelete,
}: {
  item: AdminReviewItem;
  threshold: number;
  busy: boolean;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const auto = isAutoHidden(item, threshold);
  const warn = threshold > 0 && item.report_count >= threshold;
  return (
    <article className={`admin-row ${item.hidden ? "is-hidden-item" : ""}`}>
      <div className="admin-row__head">
        <span className="admin-row__id">#{item.id}</span>
        <span className="admin-row__name">{item.nickname}</span>
        <span className="admin-row__meta">평점 {item.rating}/5</span>
        <span className="admin-row__badges">
          {item.report_count > 0 && (
            <span className={`admin-badge ${warn ? "is-warn" : ""}`}>신고 {item.report_count}건</span>
          )}
          {item.hidden && (
            /* "자동 숨김" 판정 근거는 lib/adminApi.ts 의 isAutoHidden() 주석 참고.
               임계값을 화면에 박지 않고 서버 stats 값을 쓴다. */
            <span className="admin-badge is-hidden">{auto ? "자동 숨김됨" : "운영자가 숨김"}</span>
          )}
        </span>
      </div>
      <p className="admin-row__body">
        {item.comment ? item.comment : <i className="admin-row__none">(한줄평 없음)</i>}
      </p>
      <p className="admin-row__sub">
        대상 {item.target_type} #{item.target_id} · 작성 {fmtDateTime(item.created_at)} ·{" "}
        {item.updated_at !== item.created_at ? `수정 ${fmtDateTime(item.updated_at)}` : "수정 없음"}
        {item.author_hash && (
          <span className="admin-row__hash" title="같은 사람이 쓴 글을 묶어보는 지문 — 원본 식별자가 아닙니다">
            작성자 지문 {item.author_hash}
          </span>
        )}
      </p>
      <div className="admin-row__actions">
        <button type="button" className="admin-btn admin-btn--primary" onClick={onToggle} disabled={busy}>
          {busy ? "처리 중…" : item.hidden ? "숨김 해제" : "숨기기"}
        </button>
        <button type="button" className="admin-btn admin-btn--danger" onClick={onDelete} disabled={busy}>
          삭제
        </button>
      </div>
    </article>
  );
}

function CourseRow({
  item,
  busy,
  onToggle,
  onDelete,
}: {
  item: AdminCourseItem;
  busy: boolean;
  onToggle: () => void;
  onDelete: () => void;
}) {
  return (
    <article className={`admin-row ${item.hidden ? "is-hidden-item" : ""}`}>
      <div className="admin-row__head">
        <span className="admin-row__name">{item.title}</span>
        <span className="admin-row__meta">
          스팟 {item.spot_count}곳 · 조회 {item.view_count}
        </span>
        <span className="admin-row__badges">
          {item.hidden && <span className="admin-badge is-hidden">숨김</span>}
        </span>
      </div>
      <p className="admin-row__sub">
        {item.nickname} · 공유코드 <span className="admin-row__code">{item.share_code}</span> ·{" "}
        {fmtDateTime(item.created_at)}
        {item.author_hash && (
          <span className="admin-row__hash" title="같은 사람이 쓴 글을 묶어보는 지문 — 원본 식별자가 아닙니다">
            작성자 지문 {item.author_hash}
          </span>
        )}
      </p>
      <div className="admin-row__actions">
        <button type="button" className="admin-btn admin-btn--primary" onClick={onToggle} disabled={busy}>
          {busy ? "처리 중…" : item.hidden ? "숨김 해제" : "숨기기"}
        </button>
        <button type="button" className="admin-btn admin-btn--danger" onClick={onDelete} disabled={busy}>
          삭제
        </button>
      </div>
    </article>
  );
}

/**
 * 삭제 확인 (§5.4). 기본 포커스를 **취소**에 둔다 — 엔터를 무심코 눌러도 삭제되지 않게.
 * 버튼 라벨도 "삭제"가 아니라 "영구 삭제"로 되돌릴 수 없음을 반복한다.
 */
function DeleteDialog({
  pending,
  busy,
  onCancel,
  onConfirm,
}: {
  pending: NonNullable<PendingDelete>;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel, busy]);

  const isReview = pending.kind === "review";
  const review = isReview ? (pending.item as AdminReviewItem) : null;
  const course = !isReview ? (pending.item as AdminCourseItem) : null;

  return (
    <div className="admin-modal" role="dialog" aria-modal="true" aria-label="삭제 확인">
      <div className="admin-modal__backdrop" onClick={() => !busy && onCancel()} />
      <div className="admin-modal__card">
        <h2 className="admin-modal__title">정말 삭제할까요?</h2>
        <p className="admin-modal__body">
          {isReview ? (
            <>
              이 후기를 완전히 삭제합니다. 신고 기록도 함께 사라지고, 되돌릴 수 없습니다.
              스팸이나 명백히 문제 있는 글이 아니라면 <b>숨기기</b>를 쓰는 걸 권장해요 — 숨기기는
              언제든 되돌릴 수 있어요.
            </>
          ) : (
            <>
              이 공유 코스를 완전히 삭제합니다. 되돌릴 수 없습니다. 공유 링크(공유코드{" "}
              {course!.share_code})도 즉시 접속할 수 없게 돼요.
            </>
          )}
        </p>
        <p className="admin-modal__quote">
          {isReview
            ? `${review!.comment ? `"${review!.comment}" — ` : ""}${review!.nickname}`
            : `${course!.title} — ${course!.nickname}`}
        </p>
        <div className="admin-modal__actions">
          <button type="button" className="admin-btn admin-btn--ghost" onClick={onCancel} disabled={busy} autoFocus>
            취소
          </button>
          <button type="button" className="admin-btn admin-btn--danger-solid" onClick={onConfirm} disabled={busy}>
            {busy ? "삭제 중…" : "영구 삭제"}
          </button>
        </div>
      </div>
    </div>
  );
}
