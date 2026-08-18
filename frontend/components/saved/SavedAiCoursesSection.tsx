"use client";

import { useEffect, useState } from "react";
import { ApiError, MyCourseSummary, deleteMyCourse, fetchMyCourses } from "../../lib/api";
import { useLoggedInName } from "../../lib/useLoggedInName";

/** "YYYY.MM.DD" — 파싱 실패 시 원본 문자열로 폴백(SharedCoursesSection.tsx와 동일 관례). */
function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

/**
 * 2026-08-17(Phase C, 대표 지시) — "내가 저장한 AI 코스" 섹션. `SharedCoursesSection.tsx`
 * ("내가 공유한 코스" — device_id 기준, 공개 링크)와 나란히 `/saved` 페이지에 놓이지만
 * 신원 모델이 다르다 — 이건 **로그인 계정** 전용이라, 비로그인이면 섹션 자체를 렌더하지
 * 않는다(로그인해도 저장한 게 없으면 마찬가지로 안 그린다 — 두 조건 다 SharedCoursesSection
 * 의 "빈 카드를 보여줄 필요 없다" 원칙 그대로).
 */
export default function SavedAiCoursesSection() {
  const loggedIn = useLoggedInName();
  const [records, setRecords] = useState<MyCourseSummary[] | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!loggedIn) {
      setRecords(null);
      return;
    }
    let cancelled = false;
    fetchMyCourses()
      .then((items) => {
        if (!cancelled) setRecords(items);
      })
      .catch(() => {
        if (!cancelled) setRecords([]);
      });
    return () => {
      cancelled = true;
    };
  }, [loggedIn]);

  if (!loggedIn || records === null || records.length === 0) return null;

  const handleDelete = async (id: number) => {
    setDeletingId(id);
    setErrorMsg(null);
    try {
      await deleteMyCourse(id);
      setRecords((prev) => (prev ?? []).filter((r) => r.id !== id));
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : "삭제하지 못했어요. 잠시 후 다시 시도해주세요.");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <section className="section" aria-labelledby="myAiCoursesHeading">
      <span className="eyebrow-pill eyebrow-pill--azure">내가 저장한 AI 코스</span>
      <h2 className="section__title" id="myAiCoursesHeading">
        저장한 코스 관리
      </h2>
      <p className="saved-content__intro">
        계정에 저장돼요 — 로그인하면 다른 기기에서도 볼 수 있어요.
      </p>

      {errorMsg && (
        <p className="onboard-validation" role="alert">
          {errorMsg}
        </p>
      )}

      <ul className="shared-course-list">
        {records.map((r) => (
          <li key={r.id} className="shared-course-list__item">
            {/* 상세 보기 페이지는 아직 없다(이번 스코프는 저장·목록·삭제까지) — 제목은
                텍스트로만 표시. 지역 정보를 함께 보여줘 어떤 코스인지는 구분 가능하다. */}
            <span className="shared-course-list__title">
              {r.mode === "ai" ? "AI 추천 코스" : "내가 만든 코스"} · {r.region_code}
            </span>
            <span className="shared-course-list__date">{formatDate(r.created_at)}</span>
            <button
              type="button"
              className="review-item__action-btn"
              onClick={() => handleDelete(r.id)}
              disabled={deletingId === r.id}
            >
              {deletingId === r.id ? "삭제 중…" : "삭제"}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
