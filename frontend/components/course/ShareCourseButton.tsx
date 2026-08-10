"use client";

import { useState } from "react";
import { CourseResponse } from "../../lib/api";
import { useLoginGate } from "../LoginGateProvider";
import ShareCourseModal from "./ShareCourseModal";

/** 공유 아이콘 — 이모지 대신 인라인 SVG(사이트 전역 관례). */
function ShareIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="18" cy="5" r="2.6" stroke="currentColor" strokeWidth="1.7" />
      <circle cx="6" cy="12" r="2.6" stroke="currentColor" strokeWidth="1.7" />
      <circle cx="18" cy="19" r="2.6" stroke="currentColor" strokeWidth="1.7" />
      <path d="M8.3 10.7l7.4-4.2M8.3 13.3l7.4 4.2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

interface ShareCourseButtonProps {
  course: CourseResponse;
  defaultTitle: string;
}

/**
 * §41(신규) — 코스 결과 화면(AI 추천 코스·내 코스 만들기 공용, CourseContent.tsx의
 * CourseTimelinePanel)에서 쓰는 "코스 공유하기" 트리거. 로그인 게이트(§40 useLoginGate 재사용) →
 * 모달(ShareCourseModal) 순서로 연다. `.course-print-btn`과 같은 "보더+흰배경 보조 액션" 문법을
 * 참고해 `.course-share-btn`을 별도로 뒀다(값은 동일하게 재사용, 클래스는 분리 — 두 버튼이 나란히
 * 있어 각자 다른 이유로 나중에 스타일이 갈릴 수 있음을 열어둔다).
 */
export default function ShareCourseButton({ course, defaultTitle }: ShareCourseButtonProps) {
  const [open, setOpen] = useState(false);
  const { requireLogin } = useLoginGate();

  return (
    <>
      <button
        type="button"
        className="course-share-btn"
        onClick={() =>
          requireLogin(() => setOpen(true), "로그인하면 만든 코스를 다른 사람에게 공유할 수 있어요.")
        }
      >
        <ShareIcon />
        코스 공유하기
      </button>
      <ShareCourseModal open={open} onClose={() => setOpen(false)} course={course} defaultTitle={defaultTitle} />
    </>
  );
}
