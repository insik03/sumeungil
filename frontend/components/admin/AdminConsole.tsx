"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../lib/api";
import AdminTrafficTab from "./AdminTraffic";
import {
  AdminCourseItem,
  AdminInquiryItem,
  AdminReviewItem,
  AdminStats,
  AdminUserItem,
  CourseStatusFilter,
  InquiryStatusFilter,
  ReviewSortOption,
  ReviewStatusFilter,
  adminLogout,
  deleteCourse,
  deleteReview,
  fetchAdminCourses,
  fetchAdminInquiries,
  fetchAdminReviews,
  fetchAdminStats,
  fetchAdminUsers,
  isAutoHidden,
  replyInquiry,
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
  const [tab, setTab] = useState<"reviews" | "courses" | "inquiries" | "users" | "traffic">(
    "reviews",
  );
  const [stats, setStats] = useState<AdminStats | null>(null);

  const [reviewStatus, setReviewStatus] = useState<ReviewStatusFilter>("reported");
  const [reviewSort, setReviewSort] = useState<ReviewSortOption>("reported");
  const [reviews, setReviews] = useState<AdminReviewItem[] | null>(null);
  const [reviewTotal, setReviewTotal] = useState(0);

  const [courseStatus, setCourseStatus] = useState<CourseStatusFilter>("all");
  const [courses, setCourses] = useState<AdminCourseItem[] | null>(null);
  const [courseTotal, setCourseTotal] = useState(0);

  const [inquiryStatus, setInquiryStatus] = useState<InquiryStatusFilter>("new");
  const [inquiries, setInquiries] = useState<AdminInquiryItem[] | null>(null);
  const [inquiryTotal, setInquiryTotal] = useState(0);

  const [users, setUsers] = useState<AdminUserItem[] | null>(null);
  const [userTotal, setUserTotal] = useState(0);

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

  const loadInquiries = useCallback(async () => {
    setListError(false);
    setInquiries(null);
    try {
      const res = await fetchAdminInquiries({ status: inquiryStatus, limit: PAGE_SIZE });
      setInquiries(res.items);
      setInquiryTotal(res.total);
    } catch (e) {
      if (!guard(e)) setListError(true);
    }
  }, [inquiryStatus, guard]);

  const loadUsers = useCallback(async () => {
    setListError(false);
    setUsers(null);
    try {
      const res = await fetchAdminUsers({ limit: PAGE_SIZE });
      setUsers(res.items);
      setUserTotal(res.total);
    } catch (e) {
      if (!guard(e)) setListError(true);
    }
  }, [guard]);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);
  useEffect(() => {
    if (tab === "reviews") void loadReviews();
  }, [tab, loadReviews]);
  useEffect(() => {
    if (tab === "courses") void loadCourses();
  }, [tab, loadCourses]);
  useEffect(() => {
    if (tab === "inquiries") void loadInquiries();
  }, [tab, loadInquiries]);
  useEffect(() => {
    if (tab === "users") void loadUsers();
  }, [tab, loadUsers]);

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

  async function submitReply(item: AdminInquiryItem, reply: string) {
    setBusyId(`i${item.id}`);
    try {
      const updated = await replyInquiry(item.id, reply);
      setInquiries((list) => (list ?? []).map((i) => (i.id === item.id ? updated : i)));
      void loadStats();
      showToast("답변을 등록했어요.");
    } catch (e) {
      if (guard(e)) return;
      if (e instanceof ApiError && e.status === 404) {
        showToast("이미 삭제됐거나 없는 문의예요. 목록을 새로고침할게요.");
        void loadInquiries();
      } else showToast("답변을 등록하지 못했어요.", "error");
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

  /** 새로고침/재시도 버튼 공용 — 지금 탭에 맞는 목록만 다시 부른다(트래픽 탭은 자체 로드). */
  function refreshCurrentList() {
    if (tab === "reviews") void loadReviews();
    else if (tab === "courses") void loadCourses();
    else if (tab === "inquiries") void loadInquiries();
    else if (tab === "users") void loadUsers();
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
            <button
              type="button"
              className="admin-stat admin-stat--pill"
              onClick={() => setTab("users")}
            >
              회원 <b>{stats.users_total}</b>
              {stats.users_today > 0 ? ` · 오늘 +${stats.users_today}` : ""}
            </button>
            <span className="admin-stat">
              후기 <b>{stats.reviews_total}</b> · 숨김 <b>{stats.reviews_hidden}</b>
            </span>
            <span className="admin-stat">
              코스 <b>{stats.courses_total}</b> · 숨김 <b>{stats.courses_hidden}</b>
            </span>
            <button
              type="button"
              className={`admin-stat admin-stat--pill ${stats.inquiries_new > 0 ? "is-warn" : ""}`}
              onClick={() => {
                setTab("inquiries");
                setInquiryStatus("new");
              }}
            >
              {stats.inquiries_new > 0 ? `미답변 문의 ${stats.inquiries_new}` : "미답변 문의 없음"}
            </button>
            <span className="admin-stats__meta">
              누적 신고 {stats.reports_total} · 기준 {fmtTime(stats.generated_at)}
              <button
                type="button"
                className="admin-btn admin-btn--ghost admin-btn--sm"
                onClick={() => {
                  void loadStats();
                  refreshCurrentList();
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
          className={`admin-tab ${tab === "inquiries" ? "is-active" : ""}`}
          onClick={() => setTab("inquiries")}
        >
          고객문의
        </button>
        <button
          type="button"
          className={`admin-tab ${tab === "users" ? "is-active" : ""}`}
          onClick={() => setTab("users")}
        >
          회원
        </button>
        <button
          type="button"
          className={`admin-tab ${tab === "traffic" ? "is-active" : ""}`}
          onClick={() => setTab("traffic")}
        >
          트래픽
        </button>

        <span className="admin-tabs__filters">
          {tab === "traffic" || tab === "users" ? null : tab === "inquiries" ? (
            <select
              className="admin-select"
              value={inquiryStatus}
              onChange={(e) => setInquiryStatus(e.target.value as InquiryStatusFilter)}
              aria-label="문의 상태 필터"
            >
              <option value="new">미답변</option>
              <option value="resolved">답변완료</option>
              <option value="all">전체</option>
            </select>
          ) : tab === "reviews" ? (
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
              onClick={refreshCurrentList}
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
        ) : tab === "courses" ? (
          courses === null ? (
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
          )
        ) : tab === "inquiries" ? (
          inquiries === null ? (
            <AdminSkeleton />
          ) : inquiries.length === 0 ? (
            <div className="admin-empty">
              <p>
                {inquiryStatus === "new"
                  ? "아직 답변할 문의가 없어요."
                  : inquiryStatus === "resolved"
                    ? "답변한 문의가 없어요."
                    : "아직 들어온 문의가 없어요."}
              </p>
            </div>
          ) : (
            <>
              {inquiries.map((i) => (
                <InquiryRow
                  key={i.id}
                  item={i}
                  busy={busyId === `i${i.id}`}
                  onReply={(reply) => submitReply(i, reply)}
                />
              ))}
              <p className="admin-list__count">{inquiries.length}건 표시 · 전체 {inquiryTotal}건</p>
            </>
          )
        ) : users === null ? (
          <AdminSkeleton />
        ) : users.length === 0 ? (
          <div className="admin-empty">
            <p>아직 가입한 회원이 없어요.</p>
          </div>
        ) : (
          <>
            {users.map((u, idx) => (
              <UserRow key={`${u.nickname}-${u.created_at}-${idx}`} item={u} />
            ))}
            <p className="admin-list__count">{users.length}명 표시 · 전체 {userTotal}명</p>
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
 * 문의 1건 + 답변 작성/수정 칸.
 *
 * 리뷰/코스 행과 달리 낙관적 갱신을 흉내내지 않는다 — textarea 입력값은 답변 등록이
 * 성공한 뒤 부모가 내려주는 최신 item.reply로만 갱신된다(리뷰/코스와 같은 원칙:
 * "됐다고 보였는데 실제로는 안 된" 상태를 만들지 않는다). 답변이 이미 있으면 칸에
 * 미리 채워 넣어 오탈자 정정 같은 재작성을 쉽게 한다.
 */
function InquiryRow({
  item,
  busy,
  onReply,
}: {
  item: AdminInquiryItem;
  busy: boolean;
  onReply: (reply: string) => void;
}) {
  const [draft, setDraft] = useState(item.reply ?? "");

  useEffect(() => {
    setDraft(item.reply ?? "");
  }, [item.reply]);

  const trimmed = draft.trim();
  const canSubmit = !busy && trimmed.length > 0 && trimmed !== (item.reply ?? "");

  return (
    <article className="admin-row">
      <div className="admin-row__head">
        <span className="admin-row__id">#{item.id}</span>
        <span className="admin-row__name">{item.nickname}</span>
        {item.contact_email && <span className="admin-row__meta">{item.contact_email}</span>}
        <span className="admin-row__badges">
          <span className={`admin-badge ${item.status === "new" ? "is-warn" : ""}`}>
            {item.status === "new" ? "미답변" : "답변완료"}
          </span>
        </span>
      </div>
      <p className="admin-row__body">{item.message}</p>
      <p className="admin-row__sub">작성 {fmtDateTime(item.created_at)}</p>

      <div className="admin-reply">
        <label className="admin-field">
          <span className="admin-field__label">
            답변{item.replied_at ? ` · ${item.replied_by || "운영자"}가 ${fmtDateTime(item.replied_at)}에 작성` : ""}
          </span>
          <textarea
            className="admin-field__input admin-field__input--textarea"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="이 문의에 대한 답변을 입력하세요"
            disabled={busy}
            rows={3}
          />
        </label>
        <div className="admin-row__actions">
          <button
            type="button"
            className="admin-btn admin-btn--primary"
            onClick={() => onReply(trimmed)}
            disabled={!canSubmit}
          >
            {busy ? "등록 중…" : item.reply ? "답변 수정" : "답변 등록"}
          </button>
        </div>
      </div>
    </article>
  );
}

/** 회원 1명. 조회 전용 — 숨기기/삭제 같은 조작 버튼이 없다(계정 관리 기능이 아니다). */
function UserRow({ item }: { item: AdminUserItem }) {
  return (
    <article className="admin-row">
      <div className="admin-row__head">
        <span className="admin-row__name">{item.nickname}</span>
        <span className="admin-row__badges">
          <span className="admin-badge">
            {item.provider === "google" ? "구글" : item.provider === "kakao" ? "카카오" : "-"}
          </span>
        </span>
      </div>
      <p className="admin-row__sub">
        가입 {fmtDateTime(item.created_at)} · 마지막 로그인 {fmtDateTime(item.last_login_at)}
      </p>
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
