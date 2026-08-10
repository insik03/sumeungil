"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, deleteSharedCourse } from "../../lib/api";
import { SharedCourseRecord, loadMySharedCourses, removeMySharedCourse } from "../../lib/sharedCoursesStorage";

/** "YYYY.MM.DD" — 파싱 실패 시 원본 문자열로 폴백(사이트 전역 날짜 표기 관례). */
function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

/**
 * §41(신규) — "내가 공유한 코스" 관리 섹션. sharedCoursesStorage.ts(이 기기가 만든 공유만 로컬
 * 추적)를 읽어 목록을 보여주고, 삭제는 실제로 서버(DELETE /courses/shared/{code})를 호출해
 * 지운 뒤에만 로컬 목록에서도 지운다(서버 삭제가 실패하면 로컬 기록은 남겨 재시도할 수 있게 한다).
 * 공유한 적이 없으면 섹션 자체를 렌더하지 않는다 — /saved에 처음 온 사용자 대부분(아직 코스를
 * 공유해본 적 없는 사람)에게 빈 카드를 보여줄 필요가 없다(공유 진입점은 코스 결과 화면에 따로 있다).
 */
export default function SharedCoursesSection() {
  const [records, setRecords] = useState<SharedCourseRecord[] | null>(null);
  const [deletingCode, setDeletingCode] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    setRecords(loadMySharedCourses());
  }, []);

  if (records !== null && records.length === 0) return null;

  const handleDelete = async (code: string) => {
    setDeletingCode(code);
    setErrorMsg(null);
    try {
      await deleteSharedCourse(code);
      removeMySharedCourse(code);
      setRecords((prev) => (prev ?? []).filter((r) => r.share_code !== code));
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : "삭제하지 못했어요. 잠시 후 다시 시도해주세요.");
    } finally {
      setDeletingCode(null);
    }
  };

  return (
    <section className="section" aria-labelledby="mySharedHeading">
      <span className="eyebrow-pill eyebrow-pill--azure">내가 공유한 코스</span>
      <h2 className="section__title" id="mySharedHeading">
        공유한 코스 관리
      </h2>
      <p className="saved-content__intro">
        이 기기에서 만든 공유 링크만 모아 보여드려요 — 지금은 데모라 링크만 있으면 누구나 볼 수
        있어요.
      </p>

      {errorMsg && (
        <p className="onboard-validation" role="alert">
          {errorMsg}
        </p>
      )}

      <ul className="shared-course-list">
        {(records ?? []).map((r) => (
          <li key={r.share_code} className="shared-course-list__item">
            <Link href={`/course/shared/${r.share_code}`} className="shared-course-list__title">
              {r.title}
            </Link>
            <span className="shared-course-list__date">{formatDate(r.created_at)}</span>
            <button
              type="button"
              className="review-item__action-btn"
              onClick={() => handleDelete(r.share_code)}
              disabled={deletingCode === r.share_code}
            >
              {deletingCode === r.share_code ? "삭제 중…" : "삭제"}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
