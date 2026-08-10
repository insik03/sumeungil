/**
 * §41(신규) — "내가 공유한 코스" 로컬 추적. 01-interface-contract.md 부록 R.7 코스 공유 피드
 * (`GET /courses/shared`)는 다른 사람 코스와 구분 없이 전체 목록만 내려주고(목록 항목에는 `is_mine`
 * 필드가 없다 — 상세 조회(`GET /courses/shared/{code}`)에만 있다). 그런데 상세 조회는 "조회할 때마다
 * 조회수가 오른다"는 트랜잭션(부록 R.7)이라, "내가 공유한 목록"을 보여주려고 상세를 매번 다시 불러오면
 * 내 코스의 view_count가 내가 확인할 때마다 올라가는 부작용이 생긴다. 그래서 서버에 다시 묻는 대신
 * 이 기기가 직접 공유를 만들 때(ShareCourseModal.tsx) 그 스냅샷을 localStorage에 남겨 /saved 화면의
 * "내가 공유한 코스" 섹션(SharedCoursesSection.tsx)을 채운다 — courseCartStorage.ts와 동일한
 * `sumeungil:...:v1` 네임스페이스·파싱 방어 규칙을 따른다.
 */
const STORAGE_KEY = "sumeungil:shared-courses:v1";

/** 목록 표시에 필요한 최소 스냅샷만 남긴다 — course payload 전체를 다시 들고 있지 않는다(중복 저장 방지). */
export interface SharedCourseRecord {
  share_code: string;
  title: string;
  created_at: string;
}

function isSharedCourseRecord(item: unknown): item is SharedCourseRecord {
  if (!item || typeof item !== "object") return false;
  const r = item as Record<string, unknown>;
  return (
    typeof r.share_code === "string" && typeof r.title === "string" && typeof r.created_at === "string"
  );
}

/** localStorage 파싱 실패/버전 불일치면 조용히 빈 목록으로 폴백한다(savedSpotsStorage와 동일 원칙). */
export function loadMySharedCourses(): SharedCourseRecord[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isSharedCourseRecord);
  } catch {
    return [];
  }
}

function persist(list: SharedCourseRecord[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {
    // localStorage 비활성/용량초과(시크릿 모드 등) — 조용히 무시. 화면 흐름을 막지 않는다.
  }
}

/** 새로 공유한 코스를 맨 앞에 추가한다(최신순). 같은 share_code가 이미 있으면 갱신(중복 방지). */
export function addMySharedCourse(record: SharedCourseRecord): void {
  const rest = loadMySharedCourses().filter((r) => r.share_code !== record.share_code);
  persist([record, ...rest]);
}

export function removeMySharedCourse(shareCode: string): void {
  persist(loadMySharedCourses().filter((r) => r.share_code !== shareCode));
}
