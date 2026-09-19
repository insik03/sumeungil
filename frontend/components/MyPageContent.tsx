"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  API_BASE,
  ApiError,
  InquirySummary,
  OnboardingResult,
  createInquiry,
  fetchMyCourses,
  fetchMyInquiries,
  fetchMyOnboardingProfile,
} from "../lib/api";
import { deleteAccount, setLoggedInName } from "../lib/authStorage";
import { loadMySharedCourses } from "../lib/sharedCoursesStorage";
import { loadSavedSpots } from "../lib/savedSpotsStorage";
import { loadStamps, STAMP_MILESTONES } from "../lib/stampStorage";
import { useLoggedInName } from "../lib/useLoggedInName";
import { syncSessionFromServer } from "../lib/authStorage";
import LinkProviderButtons, { LinkOutcome, LinkProvider } from "./LinkProviderButtons";
import LoginRequiredGate from "./LoginRequiredGate";

const NICKNAME_MAX = 20; // LoginModal.tsx와 동일 상수(서버 NICKNAME_MAX가 실제 기준, 이건 입력창 UX용).
const INQUIRY_MESSAGE_MAX = 2000; // backend schemas/inquiry.py MESSAGE_MAX와 동일(입력창 UX용).

function fmtInquiryDate(iso: string): string {
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  return m ? `${m[1]}.${m[2]}.${m[3]} ${m[4]}:${m[5]}` : iso;
}

/**
 * 마이페이지(2026-08-17, 대표 지시 — "계정삭제창이 아닌 마이페이지 창으로 바꾸고
 * 그 안에 여러가지를 또 만들거임", 이어서 "대한민국 구석구석 마이페이지처럼, UI는
 * 바꾸되 기능은 비슷하게").
 *
 * 구석구석 마이페이지를 그대로 베끼지 않고, 숨은길에 **실제로 있는 기능**만 "나의 활동"
 * 타일로 옮겨왔다 — 지어낸 카운트·기능 없음:
 *   - 즐겨찾기 → 저장한 스팟(savedSpotsStorage, 로컬)
 *   - 방문 스탬프 → stampStorage(로컬, 동/은/금 배지도 이미 있음)
 *   - 코스 → 저장한 AI 코스(서버, fetchMyCourses) + 공유한 코스(로컬, sharedCoursesStorage) 합산
 * 구석구석에 있지만 숨은길엔 없는 기능(댓글 목록, 관광정보 수정요청, 프로필 이미지 업로드,
 * 여행 일정 캘린더, 디지털 관광주민증/배지랜드/구독 같은 정부 서비스 전용 기능)은 실제
 * 데이터가 없어 빈 타일을 만들지 않고 의도적으로 뺐다. Q&A만은 예외로 살렸다 — "고객문의창도
 * 있어야 할 거 같다"는 2026-08-18 지시로 "고객문의" 타일 + 폼 + inquiries 테이블을 새로
 * 만들었다(backend/app/api/inquiries.py 참고). 관리자 답변 기능(같은 날 후속 지시 — "답변도
 * 작성하는 칸이 있었으면 좋겠어")까지 추가된 뒤로는 여기서도 지난 문의 + 답변을 보여준다
 * (admin 콘솔에서만 보이는 답변은 고객이 영영 못 보므로 기능이 완결되지 않는다).
 *
 * 로그인 게이트는 onboarding/ask/course와 동일한 LoginRequiredGate를 그대로 쓴다.
 * 계정 삭제 2단계 확인 패턴(5초 내 다시 누르면 삭제)은 Header.tsx에 있던 걸 그대로 옮겼다.
 */
export default function MyPageContent() {
  const nickname = useLoggedInName();
  // 2026-08-18(대표 지시) — "나의 활동" 타일 중 "계정관리"·"고객문의"를 눌러야만 각
  // 화면이 뜨도록 바꿨다. 기본은 항상 활동 그리드.
  const [view, setView] = useState<"activity" | "account" | "inquiry">("activity");
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const deleteConfirmTimerRef = useRef<number | null>(null);

  // 고객문의 폼 — 제출 성공하면 폼 대신 접수 완료 문구를 보여준다(같은 문의를 실수로
  // 중복 제출하지 않도록, 리뷰/코스공유 등 기존 "성공 후 폼 숨김" 관례와 동일).
  const [inquiryMessage, setInquiryMessage] = useState("");
  const [inquirySaving, setInquirySaving] = useState(false);
  const [inquiryError, setInquiryError] = useState<string | null>(null);
  const [inquirySubmitted, setInquirySubmitted] = useState(false);
  // 지난 문의 + 답변 목록. "답변 작성" 기능은 어딘가에서 보여야 완결되므로(관리자만 보는
  // 답변은 의미가 없다) 문의 화면을 열 때마다 불러온다.
  const [myInquiries, setMyInquiries] = useState<InquirySummary[] | null>(null);

  // 닉네임(표시 이름) 변경 — 로그인 직후 LoginModal의 "표시 이름 정하기" 단계와 같은
  // PATCH /api/v1/auth/display-name을 재사용한다. 서버가 사칭 차단·HTML 제거 등 실제
  // 검증을 하므로 여기서는 빈 값만 막는다(서버 400 메시지를 그대로 보여준다).
  // 2026-09-18 — 연결된 로그인 방식(/me providers). 연결에 성공하면 다시 읽는다.
  const [providers, setProviders] = useState<Record<string, boolean> | null>(null);
  const [linkNote, setLinkNote] = useState<string | null>(null);
  useEffect(() => {
    void syncSessionFromServer().then((info) => setProviders(info?.providers ?? {}));
  }, []);
  const handleLinkDone = (provider: LinkProvider, outcome: LinkOutcome) => {
    const name = provider === "google" ? "구글" : provider === "kakao" ? "카카오" : "네이버";
    if (outcome === "linked") {
      setLinkNote(`${name} 계정을 연결했어요. 그 계정의 저장 코스·취향이 이 계정으로 합쳐졌어요.`);
      void syncSessionFromServer().then((info) => setProviders(info?.providers ?? {}));
    } else if (outcome === "already") setLinkNote(`${name} 계정은 이미 이 계정에 연결돼 있어요.`);
    else if (outcome === "conflict") setLinkNote(`이 계정에는 이미 다른 ${name} 계정이 연결돼 있어요.`);
    else if (outcome === "not_logged_in") setLinkNote("로그인이 풀렸어요. 다시 로그인한 뒤 시도해주세요.");
    else setLinkNote("연결에 실패했어요. 잠시 후 다시 시도해주세요.");
  };
  const [nicknameEditing, setNicknameEditing] = useState(false);
  const [nicknameInput, setNicknameInput] = useState("");
  const [nicknameSaving, setNicknameSaving] = useState(false);
  const [nicknameError, setNicknameError] = useState<string | null>(null);

  // 즐겨찾기·방문 스탬프·공유한 코스는 로컬(sessionStorage/localStorage) — mount 후에만
  // 읽는다(SavedContent.tsx와 동일한 null-first 하이드레이션 패턴, 서버/첫 클라이언트
  // 렌더와 값이 갈리지 않게). 저장한 AI 코스만 서버 호출(fetchMyCourses)이 필요하다.
  const [savedSpotCount, setSavedSpotCount] = useState<number | null>(null);
  const [stampCount, setStampCount] = useState<number | null>(null);
  const [courseCount, setCourseCount] = useState<number | null>(null);

  // §47.1(신규) — "여행 준비" 섹션 프로필 유무 판정. GET /api/v1/onboarding/me(이미 존재,
  // CourseContent.tsx의 fetchMyOnboardingProfile 재사용) 1회 호출. 새 API 0.
  // undefined=확인 전(문구 숨김), null=아직 취향 미분석, OnboardingResult=분석 완료.
  const [travelProfile, setTravelProfile] = useState<OnboardingResult | null | undefined>(undefined);

  useEffect(() => {
    if (!nickname) return;
    setSavedSpotCount(loadSavedSpots().length);
    setStampCount(loadStamps().length);
    const sharedCount = loadMySharedCourses().length;
    let cancelled = false;
    fetchMyCourses()
      .then((items) => {
        if (!cancelled) setCourseCount(items.length + sharedCount);
      })
      .catch(() => {
        if (!cancelled) setCourseCount(sharedCount);
      });
    fetchMyOnboardingProfile()
      .then((profile) => {
        if (!cancelled) setTravelProfile(profile);
      })
      .catch(() => {
        if (!cancelled) setTravelProfile(null);
      });
    return () => {
      cancelled = true;
    };
  }, [nickname]);

  useEffect(() => {
    return () => {
      if (deleteConfirmTimerRef.current) window.clearTimeout(deleteConfirmTimerRef.current);
    };
  }, []);

  const handleDeleteAccount = () => {
    if (!deleteConfirm) {
      setDeleteConfirm(true);
      deleteConfirmTimerRef.current = window.setTimeout(() => setDeleteConfirm(false), 5000);
      return;
    }
    if (deleteConfirmTimerRef.current) window.clearTimeout(deleteConfirmTimerRef.current);
    setDeleteConfirm(false);
    void deleteAccount();
  };

  const startEditNickname = () => {
    setNicknameInput(nickname ?? "");
    setNicknameError(null);
    setNicknameEditing(true);
  };

  const cancelEditNickname = () => {
    setNicknameEditing(false);
    setNicknameError(null);
  };

  const submitNickname = async () => {
    const trimmed = nicknameInput.trim();
    if (trimmed.length === 0) return;
    setNicknameSaving(true);
    setNicknameError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/display-name`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: trimmed }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setNicknameError(
          typeof body?.detail === "string" ? body.detail : "표시 이름 저장에 실패했어요. 다시 시도해주세요."
        );
        return;
      }
      const data = await res.json();
      setLoggedInName(typeof data?.name === "string" ? data.name : trimmed);
      setNicknameEditing(false);
    } catch {
      setNicknameError("네트워크 오류로 저장하지 못했어요. 다시 시도해주세요.");
    } finally {
      setNicknameSaving(false);
    }
  };

  const loadMyInquiries = async () => {
    try {
      setMyInquiries(await fetchMyInquiries());
    } catch {
      // 지난 문의를 못 불러와도 문의 작성 자체는 계속할 수 있어야 한다 — 조용히 빈 상태로 둔다.
      setMyInquiries([]);
    }
  };

  const submitInquiry = async () => {
    const trimmed = inquiryMessage.trim();
    if (trimmed.length === 0) return;
    setInquirySaving(true);
    setInquiryError(null);
    try {
      await createInquiry(trimmed, null);
      setInquirySubmitted(true);
      void loadMyInquiries();
    } catch (err) {
      setInquiryError(err instanceof ApiError ? err.message : "문의를 접수하지 못했어요. 다시 시도해주세요.");
    } finally {
      setInquirySaving(false);
    }
  };

  const openInquiryView = () => {
    setInquiryMessage("");
    setInquiryError(null);
    setInquirySubmitted(false);
    setView("inquiry");
    void loadMyInquiries();
  };

  if (!nickname) {
    return (
      <LoginRequiredGate
        title="로그인이 필요해요"
        message="마이페이지는 로그인 후 이용할 수 있어요."
      />
    );
  }

  const stampTier = currentStampTier(stampCount ?? 0);

  return (
    <section className="section" aria-labelledby="mypageHeading">
      <span className="eyebrow-pill eyebrow-pill--azure">마이페이지</span>
      <h1 className="section__title" id="mypageHeading">
        마이페이지
      </h1>

      <div className="compare-summary" style={{ marginTop: "var(--sp-4)" }}>
        <p className="compare-summary__headline">반가워요, {nickname}님</p>
        {stampTier && (
          <div className="compare-summary__badges">
            <span className="delta-badge delta-badge--fit">{stampTier} 배지 보유</span>
          </div>
        )}
      </div>

      {view === "activity" ? (
        <>
          {/* §47.1(신규, 03-design-spec.md) — "여행 준비" 섹션. 새 색·새 컴포넌트 언어를
              만들지 않고 .onboard-card로 감싸 "나의 활동"의 배경 없는 평면 그리드와 구분한다.
              타일은 .mypage-activity__item 등을 100% 재사용하고, 2칸 전용 그리드만 신규다. */}
          <div className="onboard-card" style={{ marginTop: "var(--sp-6)" }}>
            <span className="eyebrow-pill eyebrow-pill--coral">여행 준비</span>
            <h2 className="quick-menu__title" style={{ marginTop: "var(--sp-2)" }}>
              어디로 떠나볼까요?
            </h2>
            {travelProfile !== undefined && (
              <p className="onboard-result__sub" style={{ marginTop: "4px" }}>
                {travelProfile === null
                  ? "아직 취향을 알려주지 않았어요"
                  : `취향 분석 완료 · ${Object.values(travelProfile.tags).flat().length}개 키워드`}
              </p>
            )}
            <ul className="mypage-activity__grid mypage-activity__grid--prep">
              <ActivityTile
                href="/onboarding"
                label={travelProfile ? "취향 다시 분석하기" : "취향 알려주기"}
                count={null}
                icon={<SparkleIcon />}
              />
              <ActivityTile href="/course" label="AI 코스짜기" count={null} icon={<RouteIcon />} />
              {/* 태준 제안(2026-09-03) — "본인이 원하는 장소를 정하고" 부분은 /course의 기존
                  "내 코스 만들기"(직접 스팟 선택 후 AI가 순서 배치) 모드와 정확히 일치한다.
                  새 페이지 대신 ?mode=custom으로 그 탭에 바로 진입시킨다(CourseContent.tsx). */}
              <ActivityTile
                href="/course?mode=custom"
                label="내 코스 만들기"
                count={null}
                icon={<RouteIcon />}
              />
            </ul>
          </div>

          <nav className="mypage-activity" aria-label="나의 활동">
          <h2 className="quick-menu__title" style={{ marginTop: "var(--sp-6)" }}>
            나의 활동
          </h2>
          <ul className="mypage-activity__grid">
            <ActivityTile
              href="/saved"
              label="즐겨찾기"
              count={savedSpotCount}
              icon={<BookmarkIcon />}
            />
            <ActivityTile href="/saved" label="방문 스탬프" count={stampCount} icon={<StampIcon />} />
            <ActivityTile href="/saved" label="코스" count={courseCount} icon={<RouteIcon />} />
            <ActivityTile onClick={() => setView("account")} label="계정관리" count={null} icon={<GearIcon />} />
            <ActivityTile onClick={openInquiryView} label="고객문의" count={null} icon={<MailIcon />} />
          </ul>
          </nav>
        </>
      ) : view === "account" ? (
        <div style={{ marginTop: "var(--sp-6)" }}>
          <button type="button" className="btn btn--ghost-text" onClick={() => setView("activity")}>
            ← 나의 활동으로
          </button>

          <div className="onboard-card" style={{ marginTop: "var(--sp-4)" }}>
            <h2 className="onboard-result__title" style={{ marginBottom: "var(--sp-5)" }}>
              계정관리
            </h2>

            <div className="mypage-field">
              <span className="onboard-label">표시 이름</span>
              {nicknameEditing ? (
                <div className="mypage-field__edit">
                  <input
                    className="login-modal__input"
                    type="text"
                    maxLength={NICKNAME_MAX}
                    value={nicknameInput}
                    onChange={(e) => setNicknameInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void submitNickname();
                    }}
                    autoFocus
                  />
                  {nicknameError && (
                    <p className="login-modal__note" role="alert">
                      {nicknameError}
                    </p>
                  )}
                  <div className="mypage-field__actions">
                    <button
                      type="button"
                      className="btn btn--ghost-text"
                      onClick={cancelEditNickname}
                      disabled={nicknameSaving}
                    >
                      취소
                    </button>
                    <button
                      type="button"
                      className="btn btn--mint"
                      onClick={() => void submitNickname()}
                      disabled={nicknameSaving || nicknameInput.trim().length === 0}
                    >
                      {nicknameSaving ? "저장 중…" : "저장"}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="mypage-field__display">
                  <span className="mypage-field__value">{nickname}</span>
                  <button type="button" className="btn btn--ghost-text" onClick={startEditNickname}>
                    변경
                  </button>
                </div>
              )}
            </div>

            <hr className="mypage-divider" />

            {/* 2026-09-18(대표 결정) — 구글·카카오를 로그인으로 증명해 한 계정으로 묶는다. */}
            <div className="mypage-field">
              <span className="onboard-label">로그인 연결</span>
              <p className="onboard-result__sub" style={{ marginBottom: "var(--sp-3)" }}>
                구글과 카카오를 모두 연결해 두면 어느 쪽으로 로그인해도 같은 계정이에요. 연결할 때 그 계정에
                있던 저장 코스·취향은 이 계정으로 합쳐져요.
              </p>
              {providers && <LinkProviderButtons providers={providers} onDone={handleLinkDone} />}
              {linkNote && (
                <p className="onboard-result__sub" role="status" style={{ marginTop: "var(--sp-2)" }}>
                  {linkNote}
                </p>
              )}
            </div>

            <hr className="mypage-divider" />

            <div className="mypage-field">
              <span className="onboard-label">계정 삭제</span>
              <p className="onboard-result__sub" style={{ marginBottom: "var(--sp-4)" }}>
                계정을 삭제하면 이메일·표시 이름·로그인 연동 정보와 온보딩 취향·저장한 AI 코스·좋아요·
                고객문의가 <strong>즉시 삭제되고 되돌릴 수 없어요</strong>(별도 보관 기간 없이 바로
                파기해요). 이미 작성한 리뷰·공유 코스는 게시물로 남으니 지우려면 먼저 직접 삭제해주세요.
              </p>
              <button type="button" className="btn btn--ghost-text" onClick={handleDeleteAccount}>
                {deleteConfirm ? "정말 삭제할까요? 다시 누르면 삭제돼요" : "계정 삭제"}
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div style={{ marginTop: "var(--sp-6)" }}>
          <button type="button" className="btn btn--ghost-text" onClick={() => setView("activity")}>
            ← 나의 활동으로
          </button>

          <div className="onboard-card" style={{ marginTop: "var(--sp-4)" }}>
            <h2 className="onboard-result__title" style={{ marginBottom: "var(--sp-2)" }}>
              고객문의
            </h2>

            {inquirySubmitted ? (
              <div className="board-error" role="status">
                <p className="board-error__msg">문의가 접수됐어요.</p>
                <p className="board-error__hint">확인 후 이 화면에서 답변을 볼 수 있어요.</p>
              </div>
            ) : (
              <>
                <p className="onboard-result__sub" style={{ marginBottom: "var(--sp-4)" }}>
                  불편했던 점이나 궁금한 점을 남겨주세요.
                </p>
                <label className="onboard-label" htmlFor="inquiryMessage">
                  문의 내용
                </label>
                <textarea
                  id="inquiryMessage"
                  className="onboard-textarea"
                  maxLength={INQUIRY_MESSAGE_MAX}
                  rows={6}
                  value={inquiryMessage}
                  onChange={(e) => setInquiryMessage(e.target.value)}
                  placeholder="예: 카카오 로그인이 안 돼요 / 리뷰 삭제가 안 돼요"
                />
                <p className="onboard-hint">
                  답변에 필요한 연락처 외의 개인정보(주민번호·카드번호 등)는 적지 마세요.
                </p>
                {inquiryError && (
                  <p className="login-modal__note" role="alert">
                    {inquiryError}
                  </p>
                )}
                <div className="mypage-field__actions" style={{ marginTop: "var(--sp-4)" }}>
                  <button
                    type="button"
                    className="btn btn--mint"
                    onClick={() => void submitInquiry()}
                    disabled={inquirySaving || inquiryMessage.trim().length === 0}
                  >
                    {inquirySaving ? "접수 중…" : "문의 보내기"}
                  </button>
                </div>
              </>
            )}
          </div>

          {myInquiries && myInquiries.length > 0 && (
            <div className="onboard-card" style={{ marginTop: "var(--sp-4)" }}>
              <h2 className="onboard-result__title" style={{ marginBottom: "var(--sp-3)" }}>
                지난 문의
              </h2>
              <ul className="mypage-inquiry-history" style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {myInquiries.map((inq) => (
                  <li key={inq.id} className="mypage-inquiry-history__item">
                    <div className="mypage-inquiry-history__head">
                      <span className="mypage-inquiry-history__date">{fmtInquiryDate(inq.created_at)}</span>
                      <span
                        className={`mypage-inquiry-history__status ${inq.status === "resolved" ? "is-answered" : ""}`}
                      >
                        {inq.status === "resolved" ? "답변완료" : "답변 대기중"}
                      </span>
                    </div>
                    {inq.reply && <p className="mypage-inquiry-history__reply">{inq.reply}</p>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/** stampStorage.STAMP_MILESTONES(동 5/은 10/금 20)를 그대로 재사용 — 새 기준을 만들지 않는다. */
function currentStampTier(count: number): string | null {
  let tier: string | null = null;
  for (const m of STAMP_MILESTONES) {
    if (count >= m.threshold) tier = m.tier;
  }
  return tier;
}

/** href면 페이지 이동(다른 라우트), onClick이면 이 페이지 안에서 화면만 바꾼다("계정관리" —
 * 같은 로그인 세션 안에서 그리드↔계정관리를 오가는 거라 라우트를 새로 만들 필요가 없다). */
function ActivityTile({
  href,
  onClick,
  label,
  count,
  icon,
}: {
  href?: string;
  onClick?: () => void;
  label: string;
  count: number | null;
  icon: React.ReactNode;
}) {
  const content = (
    <>
      <span className="mypage-activity__icon-wrap">
        <span className="mypage-activity__icon">{icon}</span>
        {count !== null && count > 0 && (
          <span className="mypage-activity__count">{count > 99 ? "99+" : count}</span>
        )}
      </span>
      <span className="mypage-activity__label">{label}</span>
    </>
  );
  return (
    <li>
      {href ? (
        <Link className="mypage-activity__item" href={href}>
          {content}
        </Link>
      ) : (
        <button type="button" className="mypage-activity__item" onClick={onClick}>
          {content}
        </button>
      )}
    </li>
  );
}

function BookmarkIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M6 3.5h12a1 1 0 011 1V21l-7-4-7 4V4.5a1 1 0 011-1z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function StampIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M8.2 12.4l2.4 2.4 5.2-5.4"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function GearIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="3.2" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M12 3.5v2.2M12 18.3v2.2M20.5 12h-2.2M5.7 12H3.5M17.7 6.3l-1.6 1.6M7.9 16.1l-1.6 1.6M17.7 17.7l-1.6-1.6M7.9 7.9L6.3 6.3"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

function MailIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3" y="5" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M4 6.5l8 6 8-6"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** §47.1 — ServiceQuickMenu.tsx의 "onboarding" 케이스와 동일 별 모양 path 재사용(진입점마다
 * 다른 아이콘을 쓰지 않는다). */
function SparkleIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 3l1.8 5.6H20l-4.8 3.5 1.8 5.6L12 14.2 7 17.7l1.8-5.6L4 8.6h6.2L12 3z"
        fill="currentColor"
      />
    </svg>
  );
}

function RouteIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M4 19c3.5-1 4.2-6.2 8-6.2s4.5 5.2 8 6.2"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      <circle cx="4" cy="19" r="1.7" fill="currentColor" />
      <circle cx="20" cy="19" r="1.7" fill="currentColor" />
      <path d="M12 5v4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="12" cy="3.4" r="1.6" fill="currentColor" />
    </svg>
  );
}
