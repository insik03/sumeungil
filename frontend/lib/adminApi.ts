/**
 * 관리자 콘솔 API 클라이언트 — 01-interface-contract.md 부록 T(관리자)·V(표시 이름) 와 1:1.
 *
 * ## 일반 api.ts 와 다른 점 (셋 다 보안 계약이다)
 * 1. **`credentials: "include"`** — 인증이 HttpOnly 세션 쿠키다. 이게 빠지면 로그인해도
 *    이후 요청이 전부 401 이 된다. 토큰을 JS 가 읽어 헤더에 싣는 방식이 **아니다**
 *    (읽을 수 있으면 XSS 한 방에 세션이 털린다).
 * 2. **`X-Device-Id` 를 붙이지 않는다.** 그 헤더는 일반 사용자(UGC 소유권 판별)용이다.
 *    관리자 경로에 섞으면 "관리자인데 device 소유자이기도 한" 애매한 상태가 생긴다.
 * 3. **표시 이름(operator)은 로그인할 때만 보낸다.** 이후 요청에는 절대 싣지 않는다 —
 *    서버가 세션 토큰 **서명 안쪽**에서 꺼내 쓰기 때문이다(부록 V). 여기서 매 요청마다
 *    보내면 클라이언트가 남의 이름으로 감사 로그를 남길 수 있게 된다.
 *
 * ## 필드를 추측으로 늘리지 않는다
 * 아래 타입은 `backend/app/schemas/admin.py` 와 1:1 이다. 화면에 필요하다는 이유로
 * 없는 필드를 만들지 않는다. 계약이 바뀌면 이 파일보다 문서를 먼저 고친다.
 */
import { API_BASE, ApiError } from "./api";

// --- 서버 스키마와 1:1 -------------------------------------------------------

export type ReviewStatusFilter = "reported" | "hidden" | "all";
export type ReviewSortOption = "reported" | "recent";
export type CourseStatusFilter = "all" | "hidden";
export type InquiryStatusFilter = "new" | "resolved" | "all";

export interface AdminSession {
  authenticated: boolean;
  expires_at: string;
}

export interface AdminReviewItem {
  id: number;
  target_type: string;
  target_id: string;
  nickname: string;
  rating: number;
  comment: string | null;
  created_at: string;
  updated_at: string;
  hidden: boolean;
  report_count: number;
  /** device_id 원본이 아니라 키가 붙은 HMAC 앞 8자. 같은 사람이 쓴 글을 묶어 보기 위한 값이다. */
  author_hash: string;
}

export interface AdminReviewList {
  items: AdminReviewItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminCourseItem {
  share_code: string;
  nickname: string;
  title: string;
  spot_count: number;
  created_at: string;
  view_count: number;
  hidden: boolean;
  author_hash: string;
}

export interface AdminCourseList {
  items: AdminCourseItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminStats {
  reviews_total: number;
  reviews_hidden: number;
  reviews_today: number;
  reports_pending: number;
  reports_total: number;
  courses_total: number;
  courses_hidden: number;
  inquiries_total: number;
  inquiries_new: number;
  /**
   * 신고 몇 건이면 자동 숨김되는지. 서버 설정값(`REVIEW_HIDE_REPORT_THRESHOLD`, 기본 3)이다.
   * **화면에 3을 박지 말고 반드시 이 값을 쓸 것** — env 로 바뀌면 박아둔 숫자는 조용히 틀려진다.
   */
  review_hide_report_threshold: number;
  generated_at: string;
}

export interface AdminInquiryItem {
  id: number;
  nickname: string;
  contact_email: string | null;
  message: string;
  status: "new" | "resolved";
  created_at: string;
  reply: string | null;
  replied_at: string | null;
  replied_by: string | null;
}

export interface AdminInquiryList {
  items: AdminInquiryItem[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * 숨김이 "신고 누적 자동"인지 "운영자가 직접"인지 판정한다.
 *
 * API 에 `auto_hidden` 같은 필드는 없지만, 백엔드 규칙(부록 R.6)에서 확정적으로 유도된다:
 *   - 신고가 임계값에 도달해야만 `hidden` 이 되고,
 *   - 숨겨진 글에는 신고를 더 쌓을 수 없다(신고 API 가 숨겨진 글에 404 를 준다).
 * 따라서 `hidden && report_count >= 임계값` 이면 자동 경로일 수밖에 없다. 추정이 아니라 참이다.
 *
 * 임계값은 **인자로 받는다** — 서버 stats 응답에서 온 값을 넘길 것.
 */
export function isAutoHidden(
  item: { hidden: boolean; report_count: number },
  threshold: number,
): boolean {
  if (!item.hidden) return false;
  // 임계값을 아직 못 받았으면(0) 단정하지 않는다. 화면은 "숨김"까지만 표시한다.
  if (threshold <= 0) return false;
  return item.report_count >= threshold;
}


// --- 운영 트래픽 (부록 X) ----------------------------------------------------

export interface AdminTrafficDay { day: string; visitors: number; hits: number }
export interface AdminTrafficPath { path: string; hits: number }
export interface AdminTrafficHour { hour: number; hits: number }

/**
 * 오늘 가장 많이 요청한 클라이언트. **신원은 알 수 없다.**
 * 원본 IP 를 저장하지 않기로 한 결정(2026-08-10) 때문이며, `ip_hash` 는 키 붙은 HMAC 앞
 * 16자다. 이 목록의 유일한 목적은 "한 명이 비정상적으로 많이 두드리는가"를 보는 것이다 —
 * 화면에서 이것을 "접속자 IP" 처럼 표기하면 안 된다.
 */
export interface AdminHeavyClient {
  ip_hash: string;
  hits: number;
  first_seen: string;
  last_seen: string;
}

export interface AdminTraffic {
  today_visitors: number;
  today_hits: number;
  today_top_hits: number;
  daily: AdminTrafficDay[];
  top_paths: AdminTrafficPath[];
  hourly: AdminTrafficHour[];
  heavy_clients: AdminHeavyClient[];
  retention_days: number;
  generated_at: string;
}
export interface AdminModerationResult {
  ok: boolean;
  action: string;
  target_type: string;
  target_id: string;
  hidden: boolean | null;
  deleted: boolean;
}

// --- 공통 요청 ---------------------------------------------------------------

const ADMIN_BASE = `${API_BASE}/api/v1/admin`;

async function toApiError(res: Response, fallback: string): Promise<ApiError> {
  let body: { error?: { code?: string; message?: string; detail?: Record<string, unknown> } } = {};
  try {
    body = await res.json();
  } catch {
    // 프록시가 끼어들어 JSON 이 아닐 수 있다(nginx 502 HTML 등) — 기본 메시지로 넘어간다.
  }
  const err = body.error;
  return new ApiError(res.status, err?.code ?? "UNKNOWN", err?.message ?? fallback, err?.detail);
}

async function adminFetch<T>(
  path: string,
  init: RequestInit,
  fallbackMessage: string,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${ADMIN_BASE}${path}`, {
      ...init,
      // 세션 쿠키를 싣는다. 이 줄이 이 파일의 존재 이유다.
      credentials: "include",
      cache: "no-store",
      headers: { Accept: "application/json", ...(init.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "서버에 연결할 수 없습니다.");
  }
  if (!res.ok) throw await toApiError(res, fallbackMessage);
  return (await res.json()) as T;
}

// --- 인증 --------------------------------------------------------------------

/**
 * 로그인 화면 드롭다운용 표시 이름 목록. **인증 없이** 호출된다(로그인 전에 필요하므로).
 * 관리자 기능이 꺼져 있으면 라우터가 등록되지 않아 404 가 온다.
 */
/**
 * 로그인 화면이 "이름 입력칸을 그려야 하는가"만 확인한다.
 *
 * 2026-08-18(외부 보안감사 3차) — 예전에는 운영자 이름 배열을 받아 드롭다운을 그렸다.
 * 그 응답은 인증이 없어서 관리자 URL 을 찾은 사람에게 운영진 명단을 그대로 보여줬다.
 * 이제 서버가 `required` 불리언만 준다(`operators` 는 항상 빈 배열).
 */
export async function fetchAdminOperatorPolicy(): Promise<{ required: boolean }> {
  const data = await adminFetch<{ operators?: string[]; required?: boolean }>(
    "/operators",
    { method: "GET" },
    "관리자 설정을 불러오지 못했습니다.",
  );
  return { required: !!data.required };
}

/**
 * 로그인. 실패는 **사유를 구분하지 않는다** — 비밀번호 오류든 이름 불일치든 동일한 401 이다.
 * 화면도 그 원칙을 지켜야 한다(어느 쪽이 틀렸는지 알려주면 추측을 도와주는 셈이다).
 *
 * 429 일 때 `detail.retry_after_sec` 로 남은 대기 시간이 온다.
 */
export async function adminLogin(password: string, operator: string): Promise<AdminSession> {
  return adminFetch<AdminSession>(
    "/login",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password, operator }),
    },
    "로그인하지 못했습니다.",
  );
}

export async function adminLogout(): Promise<void> {
  await adminFetch<{ ok: boolean }>("/logout", { method: "POST" }, "로그아웃하지 못했습니다.");
}

/** 세션이 살아 있는지 확인. 401 이면 ApiError 로 던져진다(화면이 로그인으로 되돌린다). */
export async function fetchAdminSession(): Promise<AdminSession> {
  return adminFetch<AdminSession>("/me", { method: "GET" }, "세션을 확인하지 못했습니다.");
}

// --- 조회 --------------------------------------------------------------------

export async function fetchAdminStats(): Promise<AdminStats> {
  return adminFetch<AdminStats>("/stats", { method: "GET" }, "통계를 불러오지 못했습니다.");
}

export async function fetchAdminReviews(params?: {
  status?: ReviewStatusFilter;
  sort?: ReviewSortOption;
  limit?: number;
  offset?: number;
}): Promise<AdminReviewList> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.sort) qs.set("sort", params.sort);
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return adminFetch<AdminReviewList>(
    `/reviews${q ? `?${q}` : ""}`,
    { method: "GET" },
    "후기 목록을 불러오지 못했습니다.",
  );
}

export async function fetchAdminCourses(params?: {
  status?: CourseStatusFilter;
  limit?: number;
  offset?: number;
}): Promise<AdminCourseList> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return adminFetch<AdminCourseList>(
    `/courses${q ? `?${q}` : ""}`,
    { method: "GET" },
    "공유 코스 목록을 불러오지 못했습니다.",
  );
}


export async function fetchAdminInquiries(params?: {
  status?: InquiryStatusFilter;
  limit?: number;
  offset?: number;
}): Promise<AdminInquiryList> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return adminFetch<AdminInquiryList>(
    `/inquiries${q ? `?${q}` : ""}`,
    { method: "GET" },
    "문의 목록을 불러오지 못했습니다.",
  );
}

export async function replyInquiry(inquiryId: number, reply: string): Promise<AdminInquiryItem> {
  return adminFetch<AdminInquiryItem>(
    `/inquiries/${inquiryId}/reply`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reply }),
    },
    "답변을 등록하지 못했습니다.",
  );
}

export async function fetchAdminTraffic(days = 14): Promise<AdminTraffic> {
  return adminFetch<AdminTraffic>(
    `/traffic?days=${days}`,
    { method: "GET" },
    "트래픽 집계를 불러오지 못했습니다.",
  );
}

// --- 조작 --------------------------------------------------------------------
//
// 숨김(hide)과 삭제(delete)는 성격이 완전히 다르다:
//   hide   — 플래그만 바꾼다. unhide 로 되돌아온다.
//   delete — **되돌릴 수 없다.** 신고 기록도 FK CASCADE 로 함께 사라진다.
// 화면은 이 둘을 시각적으로 명확히 구분해야 하고, delete 는 확인 절차를 거쳐야 한다.

export async function setReviewHidden(
  reviewId: number,
  hidden: boolean,
): Promise<AdminModerationResult> {
  return adminFetch<AdminModerationResult>(
    `/reviews/${reviewId}/${hidden ? "hide" : "unhide"}`,
    { method: "POST" },
    hidden ? "후기를 가리지 못했습니다." : "후기를 복구하지 못했습니다.",
  );
}

export async function deleteReview(reviewId: number): Promise<AdminModerationResult> {
  return adminFetch<AdminModerationResult>(
    `/reviews/${reviewId}`,
    { method: "DELETE" },
    "후기를 삭제하지 못했습니다.",
  );
}

export async function setCourseHidden(
  shareCode: string,
  hidden: boolean,
): Promise<AdminModerationResult> {
  return adminFetch<AdminModerationResult>(
    `/courses/${encodeURIComponent(shareCode)}/${hidden ? "hide" : "unhide"}`,
    { method: "POST" },
    hidden ? "코스를 가리지 못했습니다." : "코스를 복구하지 못했습니다.",
  );
}

export async function deleteCourse(shareCode: string): Promise<AdminModerationResult> {
  return adminFetch<AdminModerationResult>(
    `/courses/${encodeURIComponent(shareCode)}`,
    { method: "DELETE" },
    "코스를 삭제하지 못했습니다.",
  );
}
