"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { ApiError, CourseResponse, shareCourse } from "../../lib/api";
import { getNickname } from "../../lib/authStorage";
import { addMySharedCourse } from "../../lib/sharedCoursesStorage";

interface ShareCourseModalProps {
  open: boolean;
  onClose: () => void;
  course: CourseResponse;
  defaultTitle: string;
}

type Status = "form" | "submitting" | "success" | "error";

/**
 * §41(신규) — 코스 공유 모달. LoginModal.tsx가 이미 확립한 모달 접근성 레시피(배경 스크롤 잠금,
 * 열릴 때 입력창 포커스, Esc/백드롭 닫기, 닫힘 시 포커스 복귀)를 그대로 따라 만들었다 — 새 모달
 * 패턴을 발명하지 않고 `.login-modal__backdrop`/`.login-modal` 클래스를 그대로 재사용한다(신규
 * hex·신규 배경 레시피 없음, 사이트에 모달이 2종류로 보이지 않게).
 *
 * 로그인 게이트는 이 컴포넌트를 여는 쪽(ShareCourseButton.tsx)이 useLoginGate()로 이미 확보한
 * 뒤에만 열리므로, 여기서는 로그인 여부를 다시 확인하지 않고 authStorage 닉네임을 그대로 쓴다
 * (ReviewSection.tsx의 "닉네임 재입력 없음" 결정과 동일 근거).
 */
export default function ShareCourseModal({ open, onClose, course, defaultTitle }: ShareCourseModalProps) {
  const [title, setTitle] = useState(defaultTitle.slice(0, 40));
  const [status, setStatus] = useState<Status>("form");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [shareCode, setShareCode] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const inputRef = useRef<HTMLInputElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    setTitle(defaultTitle.slice(0, 40));
    setStatus("form");
    setErrorMsg(null);
    setShareCode(null);
    setCopyState("idle");
    const t = window.setTimeout(() => inputRef.current?.focus(), 30);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      previousFocusRef.current?.focus();
    };
  }, [open, onClose, defaultTitle]);

  if (!open) return null;

  const shareUrl =
    shareCode && typeof window !== "undefined" ? `${window.location.origin}/course/shared/${shareCode}` : "";

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const trimmed = title.trim().slice(0, 40);
    if (!trimmed) {
      setErrorMsg("코스 제목을 입력해주세요.");
      return;
    }
    const nickname = getNickname();
    if (!nickname) {
      setErrorMsg("로그인 정보를 확인할 수 없어요. 다시 로그인해주세요.");
      return;
    }
    setStatus("submitting");
    setErrorMsg(null);
    try {
      const res = await shareCourse({ nickname, title: trimmed, course });
      addMySharedCourse({ share_code: res.share_code, title: trimmed, created_at: res.created_at });
      setShareCode(res.share_code);
      setStatus("success");
    } catch (err) {
      setErrorMsg(
        err instanceof ApiError ? err.message : "코스를 공유하지 못했어요. 잠시 후 다시 시도해주세요."
      );
      setStatus("error");
    }
  };

  const handleCopy = async () => {
    try {
      if (!navigator.clipboard || !window.isSecureContext) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(shareUrl);
      setCopyState("copied");
    } catch {
      // 폴백 — 아래 readOnly 입력창은 항상 노출돼 있어(포커스 시 자동 전체 선택) 수동 복사가 가능하다.
      setCopyState("failed");
    }
    window.setTimeout(() => setCopyState("idle"), 2400);
  };

  return (
    <div
      className="login-modal__backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="shareCourseModalTitle"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="login-modal share-course-modal">
        {status === "success" && shareCode ? (
          <>
            <h2 className="login-modal__title" id="shareCourseModalTitle">
              공유 링크가 만들어졌어요
            </h2>
            <p className="login-modal__sub">이 링크가 있으면 누구나 이 코스를 볼 수 있어요.</p>
            <div className="share-course-modal__link-row">
              <input
                className="login-modal__input share-course-modal__link-input"
                readOnly
                value={shareUrl}
                aria-label="공유 링크"
                onFocus={(e) => e.currentTarget.select()}
              />
              <button type="button" className="btn btn--mint" onClick={handleCopy}>
                {copyState === "copied" ? "복사됨" : "링크 복사"}
              </button>
            </div>
            {copyState === "failed" && (
              <p className="onboard-validation" role="status">
                복사에 실패했어요 — 위 링크를 눌러 직접 선택해 복사해주세요.
              </p>
            )}
            <p className="login-modal__note">
              지금은 데모라 이 링크만 있으면 누구나 볼 수 있어요. 비밀 URL일 뿐 비밀번호는 아니에요.
            </p>
            <div className="login-modal__actions">
              <button type="button" className="btn btn--ghost-text" onClick={onClose}>
                닫기
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={handleSubmit}>
            <h2 className="login-modal__title" id="shareCourseModalTitle">
              코스 공유하기
            </h2>
            <p className="login-modal__sub">제목을 붙이면 링크로 다른 사람에게 코스를 보여줄 수 있어요.</p>
            <label className="login-modal__label" htmlFor="shareCourseTitle">
              코스 제목
            </label>
            <input
              ref={inputRef}
              id="shareCourseTitle"
              className="login-modal__input"
              type="text"
              maxLength={40}
              value={title}
              disabled={status === "submitting"}
              onChange={(e) => setTitle(e.target.value)}
            />
            {errorMsg && (
              <p className="onboard-validation" role="alert">
                {errorMsg}
              </p>
            )}
            <p className="login-modal__note">
              지금은 데모 로그인이라 닉네임만으로 공유돼요. 공유 코스에는 개인정보를 남기지 말아주세요.
            </p>
            <div className="login-modal__actions">
              <button
                type="button"
                className="btn btn--ghost-text"
                onClick={onClose}
                disabled={status === "submitting"}
              >
                취소
              </button>
              <button
                type="submit"
                className="btn btn--mint"
                disabled={status === "submitting" || title.trim().length === 0}
              >
                {status === "submitting" ? "공유하는 중…" : "공유하기"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
