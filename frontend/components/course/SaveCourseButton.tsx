"use client";

import { useState } from "react";
import { CourseResponse, saveMyCourse } from "../../lib/api";

/** 저장 아이콘 — 이모지 대신 인라인 SVG(사이트 전역 관례, ShareCourseButton과 동일 톤). */
function SaveIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M5 4a1 1 0 0 1 1-1h9.5L19 6.5V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4z"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
      <path d="M8 3v5h7V3" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
      <path d="M8 21v-7h8v7" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
    </svg>
  );
}

interface SaveCourseButtonProps {
  course: CourseResponse;
  regionCode: string;
  mode: "ai" | "custom";
}

/**
 * 2026-08-17(Phase C, 대표 지시) — "코스 저장하기". `ShareCourseButton`과 나란히 쓰이는
 * 코스 결과 화면(AI 추천·내 코스 만들기 공용, `CourseTimelinePanel`)의 트리거지만, 이
 * 패널 자체가 이미 로그인 게이트 뒤에서만 렌더되므로(`CourseContent.tsx`의 `!loggedIn`
 * 분기) `ShareCourseButton`처럼 `useLoginGate`로 다시 확인하지 않는다 — 여기 도달했다는
 * 것 자체가 이미 로그인 상태라는 뜻이다.
 */
export default function SaveCourseButton({ course, regionCode, mode }: SaveCourseButtonProps) {
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");

  const handleSave = () => {
    if (status === "saving" || status === "saved") return;
    setStatus("saving");
    saveMyCourse(regionCode, mode, course)
      .then(() => setStatus("saved"))
      .catch(() => setStatus("error"));
  };

  return (
    <button
      type="button"
      className="course-share-btn"
      onClick={handleSave}
      disabled={status === "saving"}
    >
      <SaveIcon />
      {status === "saved"
        ? "저장됨"
        : status === "saving"
          ? "저장 중…"
          : status === "error"
            ? "저장 실패 · 다시 시도"
            : "코스 저장하기"}
    </button>
  );
}
