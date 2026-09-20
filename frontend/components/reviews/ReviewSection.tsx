"use client";

import { FormEvent, useCallback, useEffect, useId, useState } from "react";
import {
  ApiError,
  ReviewItem,
  ReviewSummary,
  ReviewTargetType,
  createReview,
  deleteReview,
  fetchReviews,
  fetchReviewsSummaryBulk,
  patchReview,
  reportReview,
} from "../../lib/api";
import { getNickname } from "../../lib/authStorage";
import { useLoginGate } from "../LoginGateProvider";
import StarRatingInput from "./StarRatingInput";

const PAGE_SIZE = 10;
const COMMENT_MAX = 300;
/** R.6 reason 은 1~200자 자유 텍스트지만, 화면에서는 고정 사유 중 하나를 그대로 보낸다
 * (지시서: "사유 선택 후 202") — 입력창을 새로 만들지 않아 신고 흐름을 1탭으로 끝내고,
 * 자유 입력이 없으니 신고 사유로 개인정보가 새어 들어올 여지도 없다. */
const REPORT_REASONS = ["광고·스팸", "욕설·혐오 표현", "허위 정보", "기타"];
/** 신고 접수 토스트가 떠 있는 시간 — 기존 .spot-card__cart-full-toast(2.6초)와 동일 관례. */
const TOAST_MS = 2600;

type Status = "loading" | "success" | "error";
type FormMode = "closed" | "create" | "edit";

interface ReviewSectionProps {
  targetType: ReviewTargetType;
  targetId: number | string;
}

/** "YYYY.MM.DD" — 파싱 실패(예상 밖 날짜 형식)면 원본 문자열로 폴백한다(FestivalBanner.formatMonthDay와 동일 원칙). */
function formatReviewDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

/** 읽기 전용 별점 표시(요약 평균/개별 후기 별점 전용) — 선택 불가, RatingBadge의 별 path를 재사용. */
function StaticStars({ value, size = "base" }: { value: number; size?: "base" | "sm" }) {
  const rounded = Math.round(value);
  return (
    <span className={`static-stars static-stars--${size}`} aria-hidden="true">
      {[1, 2, 3, 4, 5].map((n) => (
        <svg
          key={n}
          viewBox="0 0 24 24"
          className={n <= rounded ? "static-stars__star is-filled" : "static-stars__star"}
        >
          <path
            d="M12 3.5l2.47 5.06 5.58.74-4.06 3.9.99 5.55L12 16.9l-4.98 2.85.99-5.55-4.06-3.9 5.58-.74L12 3.5z"
            fill="currentColor"
          />
        </svg>
      ))}
    </span>
  );
}

function ReviewSummaryBlock({ summary }: { summary: ReviewSummary }) {
  return (
    <div className="review-summary">
      <div className="review-summary__avg">
        <span className="review-summary__avg-value">
          {summary.average != null ? summary.average.toFixed(1) : "-"}
        </span>
        <div>
          <StaticStars value={summary.average ?? 0} />
          <p className="review-summary__count">후기 {summary.count}개</p>
        </div>
      </div>
      <div className="review-summary__bars">
        {([5, 4, 3, 2, 1] as const).map((n) => {
          const count = summary.distribution[String(n) as "1" | "2" | "3" | "4" | "5"];
          const pct = summary.count > 0 ? Math.round((count / summary.count) * 100) : 0;
          return (
            <div className="review-summary__bar-row" key={n}>
              <span className="review-summary__bar-label">{n}점</span>
              <span className="review-summary__bar-track">
                <span className="review-summary__bar-fill" style={{ width: `${pct}%` }} />
              </span>
              <span className="review-summary__bar-count">{count}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface ReviewFormProps {
  mode: FormMode;
  rating: number;
  comment: string;
  submitting: boolean;
  error: string | null;
  onRatingChange: (v: number) => void;
  onCommentChange: (v: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
}

function ReviewForm({
  mode,
  rating,
  comment,
  submitting,
  error,
  onRatingChange,
  onCommentChange,
  onCancel,
  onSubmit,
}: ReviewFormProps) {
  const commentId = useId();

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit();
  };

  return (
    <form className="review-form" onSubmit={handleSubmit} aria-label={mode === "edit" ? "후기 수정" : "후기 작성"}>
      <span className="onboard-label">별점</span>
      <StarRatingInput value={rating} onChange={onRatingChange} disabled={submitting} />

      <label className="onboard-label review-form__comment-label" htmlFor={commentId}>
        한줄평 (선택)
      </label>
      <textarea
        id={commentId}
        className="onboard-textarea review-form__textarea"
        maxLength={COMMENT_MAX}
        placeholder="다녀온 소감을 짧게 남겨주세요."
        value={comment}
        disabled={submitting}
        onChange={(e) => onCommentChange(e.target.value)}
      />
      <p className="onboard-textarea__count">
        {comment.length}/{COMMENT_MAX}
      </p>

      {error && (
        <p className="onboard-validation" role="alert">
          {error}
        </p>
      )}

      <div className="review-form__actions">
        <button type="button" className="btn btn--ghost-text" onClick={onCancel} disabled={submitting}>
          취소
        </button>
        <button type="submit" className="btn btn--mint" disabled={submitting || rating < 1}>
          {submitting
            ? mode === "edit"
              ? "수정하는 중…"
              : "등록하는 중…"
            : mode === "edit"
              ? "수정하기"
              : "등록하기"}
        </button>
      </div>
    </form>
  );
}

interface ReviewListItemProps {
  item: ReviewItem;
  onEdit: () => void;
  onDelete: () => void;
  deleting: boolean;
  onReport: (reason: string) => void;
  reported: boolean;
  reportPending: boolean;
}

function ReviewListItem({
  item,
  onEdit,
  onDelete,
  deleting,
  onReport,
  reported,
  reportPending,
}: ReviewListItemProps) {
  const [reportOpen, setReportOpen] = useState(false);

  return (
    <li className="review-item">
      <div className="review-item__head">
        <span className="review-item__nickname">{item.nickname}</span>
        <StaticStars value={item.rating} size="sm" />
        <span className="review-item__date">{formatReviewDate(item.created_at)}</span>
      </div>
      {item.comment && <p className="review-item__comment">{item.comment}</p>}
      <div className="review-item__actions">
        {item.is_mine ? (
          <>
            <button type="button" className="review-item__action-btn" onClick={onEdit}>
              수정
            </button>
            <button type="button" className="review-item__action-btn" onClick={onDelete} disabled={deleting}>
              {deleting ? "삭제 중…" : "삭제"}
            </button>
          </>
        ) : reported ? (
          <span className="review-item__reported-note">신고가 접수됐어요</span>
        ) : reportOpen ? (
          <div className="review-item__report-menu" role="group" aria-label={`${item.nickname}님 후기 신고 사유 선택`}>
            {REPORT_REASONS.map((reason) => (
              <button
                key={reason}
                type="button"
                className="review-item__action-btn"
                disabled={reportPending}
                onClick={() => {
                  onReport(reason);
                  setReportOpen(false);
                }}
              >
                {reason}
              </button>
            ))}
            <button type="button" className="review-item__action-btn" onClick={() => setReportOpen(false)}>
              취소
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="review-item__action-btn review-item__action-btn--muted"
            disabled={reportPending}
            onClick={() => setReportOpen(true)}
          >
            {reportPending ? "신고 접수 중…" : "신고"}
          </button>
        )}
      </div>
    </li>
  );
}

function ReviewSectionSkeleton() {
  return (
    <div aria-hidden="true">
      <div className="skeleton-bar" style={{ width: "160px", height: "40px" }} />
      <div className="skeleton-bar" style={{ width: "100%", height: "70px", marginTop: "var(--sp-3)" }} />
      <div className="skeleton-bar" style={{ width: "100%", height: "70px", marginTop: "var(--sp-3)" }} />
    </div>
  );
}

/**
 * §41(신규) — 스팟 상세/축제 상세 공용 후기 섹션. 01-interface-contract.md 부록 R을 그대로 소비한다.
 * - 요약(평균·건수·분포 막대) + 목록(최신순, 더보기 페이지네이션) + 작성/수정/삭제/신고.
 * - "후기 쓰기"는 useLoginGate()로 게이트한다(§40과 동일한 공용 훅 재사용, 새 게이트 구현 없음).
 * - 닉네임은 별도 입력칸을 두지 않는다. 2026-09-20 부터 **서버가 계정 표시 이름으로 덮어쓰므로**
 *   본문에 무엇을 보내든 결과가 같다(계약 유지 목적으로 필드 자체는 남아 있다).
 * - 2026-09-20 — 후기는 **계정 소유**다. 쓰기·수정·삭제·신고 전부 서버가 로그인을 요구하고,
 *   소유권은 user_id 로 판정한다. 기기를 바꾸거나 브라우저 저장공간을 지워도 내 글은 내 글이다.
 * - 409 REVIEW_EXISTS를 받으면 이미 로드된 목록에서 내 후기를 먼저 찾고, 없으면(내 후기가 아직
 *   로드 안 된 뒷페이지에 있을 수 있음) limit=50 1회 복구 조회로 찾아 수정 폼으로 전환한다.
 */
export default function ReviewSection({ targetType, targetId }: ReviewSectionProps) {
  const { requireLogin } = useLoginGate();
  const headingId = useId();

  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState<ApiError | null>(null);
  const [summary, setSummary] = useState<ReviewSummary | null>(null);
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [retryTick, setRetryTick] = useState(0);

  const [myReview, setMyReview] = useState<ReviewItem | null>(null);

  const [formMode, setFormMode] = useState<FormMode>("closed");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formRating, setFormRating] = useState(0);
  const [formComment, setFormComment] = useState("");
  const [formSubmitting, setFormSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [reportSubmittingId, setReportSubmittingId] = useState<number | null>(null);
  const [reportedIds, setReportedIds] = useState<Set<number>>(new Set());
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), TOAST_MS);
    return () => window.clearTimeout(t);
  }, [toast]);

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    setError(null);
    fetchReviews(targetType, targetId, { limit: PAGE_SIZE, offset: 0 }, controller.signal)
      .then((res) => {
        setSummary(res.summary);
        setItems(res.items);
        setTotal(res.total);
        const mine = res.items.find((it) => it.is_mine);
        if (mine) setMyReview(mine);
        setStatus("success");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err : new ApiError(0, "UNKNOWN", "후기를 불러오지 못했습니다."));
        setStatus("error");
      });
    return () => controller.abort();
  }, [targetType, targetId, retryTick]);

  const refreshSummaryOnly = useCallback(() => {
    fetchReviewsSummaryBulk(targetType, [targetId])
      .then((s) => {
        const fresh = s[String(targetId)];
        if (fresh) setSummary(fresh);
      })
      .catch(() => {
        // 요약만 갱신하는 보조 호출 — 실패해도 화면을 막지 않는다(이미 보이는 값 유지).
      });
  }, [targetType, targetId]);

  const openCreateForm = () => {
    setFormMode("create");
    setEditingId(null);
    setFormRating(0);
    setFormComment("");
    setFormError(null);
  };

  const openEditForm = (review: ReviewItem) => {
    setFormMode("edit");
    setEditingId(review.id);
    setFormRating(review.rating);
    setFormComment(review.comment ?? "");
    setFormError(null);
  };

  const handleOpenWrite = () => {
    requireLogin(() => {
      if (myReview) openEditForm(myReview);
      else openCreateForm();
    }, "로그인하면 이곳에 후기를 남길 수 있어요.");
  };

  const handleLoadMore = () => {
    setLoadingMore(true);
    fetchReviews(targetType, targetId, { limit: PAGE_SIZE, offset: items.length })
      .then((res) => {
        setItems((prev) => [...prev, ...res.items]);
        const mine = res.items.find((it) => it.is_mine);
        if (mine) setMyReview(mine);
        setLoadingMore(false);
      })
      .catch(() => setLoadingMore(false));
  };

  const handleSubmitCreate = async () => {
    if (formRating < 1) {
      setFormError("별점을 선택해주세요.");
      return;
    }
    const nickname = getNickname();
    if (!nickname) {
      setFormError("로그인 정보를 확인할 수 없어요. 다시 로그인해주세요.");
      return;
    }
    setFormSubmitting(true);
    setFormError(null);
    try {
      const trimmed = formComment.trim();
      const res = await createReview(targetType, targetId, nickname, formRating, trimmed || undefined);
      setSummary(res.summary);
      setItems((prev) => [res.review, ...prev]);
      setTotal((t) => t + 1);
      setMyReview(res.review);
      setFormMode("closed");
      setToast("후기가 등록됐어요.");
    } catch (err) {
      if (err instanceof ApiError && err.code === "REVIEW_EXISTS") {
        const existing = items.find((it) => it.is_mine);
        if (existing) {
          openEditForm(existing);
          setFormError("이미 작성하신 후기가 있어요 — 아래에서 바로 수정할 수 있어요.");
          return;
        }
        // 아직 로드되지 않은 뒷페이지에 내 후기가 있을 수 있다 — 1회 복구 조회.
        try {
          const recovered = await fetchReviews(targetType, targetId, { limit: 50, offset: 0 });
          const mine = recovered.items.find((it) => it.is_mine);
          setSummary(recovered.summary);
          setItems(recovered.items);
          setTotal(recovered.total);
          if (mine) {
            setMyReview(mine);
            openEditForm(mine);
            setFormError("이미 작성하신 후기가 있어요 — 아래에서 바로 수정할 수 있어요.");
          } else {
            setFormError("이미 작성하신 후기가 있어요. 아래 목록에서 확인해주세요.");
          }
        } catch {
          setFormError("이미 작성하신 후기가 있어요. 아래 목록에서 확인해주세요.");
        }
      } else {
        setFormError(
          err instanceof ApiError ? err.message : "후기를 등록하지 못했어요. 잠시 후 다시 시도해주세요."
        );
      }
    } finally {
      setFormSubmitting(false);
    }
  };

  const handleSubmitEdit = async () => {
    if (!editingId) return;
    if (formRating < 1) {
      setFormError("별점을 선택해주세요.");
      return;
    }
    setFormSubmitting(true);
    setFormError(null);
    try {
      const trimmed = formComment.trim();
      const updated = await patchReview(editingId, {
        rating: formRating,
        comment: trimmed.length > 0 ? trimmed : null,
      });
      setItems((prev) => prev.map((it) => (it.id === updated.id ? updated : it)));
      setMyReview(updated);
      setFormMode("closed");
      setToast("후기가 수정됐어요.");
      refreshSummaryOnly();
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "수정하지 못했어요. 잠시 후 다시 시도해주세요."
      );
    } finally {
      setFormSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    setDeletingId(id);
    try {
      await deleteReview(id);
      setItems((prev) => prev.filter((it) => it.id !== id));
      setTotal((t) => Math.max(0, t - 1));
      if (myReview?.id === id) setMyReview(null);
      if (formMode === "edit" && editingId === id) setFormMode("closed");
      setToast("후기를 삭제했어요.");
      refreshSummaryOnly();
    } catch (err) {
      setToast(err instanceof ApiError ? err.message : "삭제하지 못했어요. 잠시 후 다시 시도해주세요.");
    } finally {
      setDeletingId(null);
    }
  };

  const handleReport = async (id: number, reason: string) => {
    setReportSubmittingId(id);
    try {
      const res = await reportReview(id, reason);
      if (res.hidden) {
        setItems((prev) => prev.filter((it) => it.id !== id));
        setTotal((t) => Math.max(0, t - 1));
        setToast("신고가 접수돼 이 후기를 가렸어요.");
      } else {
        setReportedIds((prev) => new Set(prev).add(id));
        setToast("신고가 접수됐어요.");
      }
    } catch (err) {
      setToast(err instanceof ApiError ? err.message : "신고를 접수하지 못했어요.");
    } finally {
      setReportSubmittingId(null);
    }
  };

  const retry = () => setRetryTick((t) => t + 1);

  return (
    <section className="spot-detail__block review-section spot-detail__wide" aria-labelledby={headingId}>
      <div className="review-section__head">
        <h2 className="spot-detail__block-title" id={headingId}>
          후기{summary && summary.count > 0 ? ` ${summary.count}건` : ""}
        </h2>
        {status === "success" && (
          <button type="button" className="btn btn--mint review-section__write-btn" onClick={handleOpenWrite}>
            {myReview ? "내 후기 수정" : "후기 쓰기"}
          </button>
        )}
      </div>

      {status === "loading" && <ReviewSectionSkeleton />}

      {status === "error" && (
        <div className="board-error" role="alert">
          <p className="board-error__msg">{error?.message ?? "후기를 불러오지 못했어요."}</p>
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

      {status === "success" && summary && (
        <>
          <ReviewSummaryBlock summary={summary} />

          {formMode !== "closed" && (
            <ReviewForm
              mode={formMode}
              rating={formRating}
              comment={formComment}
              submitting={formSubmitting}
              error={formError}
              onRatingChange={setFormRating}
              onCommentChange={(v) => setFormComment(v.slice(0, COMMENT_MAX))}
              onCancel={() => setFormMode("closed")}
              onSubmit={formMode === "create" ? handleSubmitCreate : handleSubmitEdit}
            />
          )}

          {toast && (
            <p className="review-section__toast" role="status">
              {toast}
            </p>
          )}

          {items.length === 0 ? (
            <div className="review-empty">
              <p>첫 후기를 남겨보세요.</p>
            </div>
          ) : (
            <ul className="review-list">
              {items.map((item) => (
                <ReviewListItem
                  key={item.id}
                  item={item}
                  onEdit={() => openEditForm(item)}
                  onDelete={() => handleDelete(item.id)}
                  deleting={deletingId === item.id}
                  onReport={(reason) => handleReport(item.id, reason)}
                  reported={reportedIds.has(item.id)}
                  reportPending={reportSubmittingId === item.id}
                />
              ))}
            </ul>
          )}

          {items.length < total && (
            <button
              type="button"
              className="btn btn--white review-more-btn"
              onClick={handleLoadMore}
              disabled={loadingMore}
            >
              {loadingMore ? "불러오는 중…" : `후기 더보기 (${items.length}/${total})`}
            </button>
          )}

          <p className="review-section__notice">
            후기는 로그인한 계정에 저장돼요. 다른 기기에서 로그인해도 내가 쓴 후기를 수정·삭제할 수 있어요.
          </p>
        </>
      )}
    </section>
  );
}
