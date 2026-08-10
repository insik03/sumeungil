/**
 * Phase 4(신규, §A) — 방문 스탬프. 오케스트레이터 지시: "개인정보 0" — GPS 위치인증·사진인증은
 * 위치정보법·초상권 재검토 전 금지(대표 방침, 벤치마크 플랜 CEO-W3). 스탬프는 "내가 눌러서 기록"하는
 * 셀프 체크인만 지원한다 — 서버 전송 0, 좌표 수집 0. savedSpotsStorage.ts(F.2-3)와 동일한 localStorage
 * 네임스페이스·버전 접미 규칙(`sumeungil:...:v1`)·파싱 실패 시 빈 배열 폴백·id dedupe upsert 패턴을 따른다.
 */
import { SpotCategory } from "./api";

const STORAGE_KEY = "sumeungil:stamps:v1";

/**
 * 지시서 최소 스키마는 { spot_id, name, region_code, category, stamped_at }다. 여기에 region_name만
 * 추가했다 — region_code는 시군구 코드(예: "26350")라 그 값만으로는 "지역별 수집 현황"(예: "부산 3 ·
 * 제주 1")을 사람이 읽을 수 있는 라벨로 보여줄 방법이 없다. 새 값을 지어내는 게 아니라 SpotDetail이
 * 이미 내려주는 region_name(01-interface-contract.md §G.1)을 그대로 스냅샷하는 것뿐이라 서버 계약을
 * 새로 만들거나 개인정보를 추가로 모으는 게 아니다(위치/좌표 아님, 지역명 텍스트일 뿐).
 */
export interface Stamp {
  spot_id: number;
  name: string;
  region_code: string;
  region_name: string | null;
  category: SpotCategory;
  /** 직접 체크인한 시각(ISO). "위치 인증"이 아니라 "내가 누른 시각"임을 카드에서 정직하게 표기하는 데 쓴다. */
  stamped_at: string;
}

/** toggleStamp에 넘기는 최소 입력 — SpotDetail(§G.1)에서 그대로 뽑아 쓸 수 있는 필드만 요구한다. */
export interface StampInput {
  id: number;
  name: string;
  region_code: string;
  region_name: string | null;
  category: SpotCategory;
}

function isStamp(item: unknown): item is Stamp {
  if (!item || typeof item !== "object") return false;
  const s = item as Record<string, unknown>;
  return (
    typeof s.spot_id === "number" &&
    typeof s.name === "string" &&
    typeof s.region_code === "string" &&
    typeof s.category === "string" &&
    typeof s.stamped_at === "string"
  );
}

/** localStorage 파싱 실패/버전 불일치면 조용히 빈 목록으로 폴백한다(savedSpotsStorage와 동일 원칙). */
export function loadStamps(): Stamp[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isStamp);
  } catch {
    return [];
  }
}

function persist(list: Stamp[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {
    // localStorage 비활성/용량초과(시크릿 모드 등) — 조용히 무시. 화면 흐름을 막지 않는다.
  }
}

export function isSpotStamped(spotId: number): boolean {
  return loadStamps().some((s) => s.spot_id === spotId);
}

function toStamp(input: StampInput): Stamp {
  return {
    spot_id: input.id,
    name: input.name,
    region_code: input.region_code,
    region_name: input.region_name,
    category: input.category,
    stamped_at: new Date().toISOString(),
  };
}

/**
 * 저장/해제 토글(spot_id로 dedupe upsert). 반환값 = 토글 후 스탬프 상태(true = 방문 기록됨).
 * 스팟 상세 페이지의 "방문 스탬프 찍기" 버튼이 이 함수 하나로 찍기/해제를 모두 처리한다.
 */
export function toggleStamp(input: StampInput): boolean {
  const list = loadStamps();
  const idx = list.findIndex((s) => s.spot_id === input.id);
  if (idx >= 0) {
    list.splice(idx, 1);
    persist(list);
    return false;
  }
  list.push(toStamp(input));
  persist(list);
  return true;
}

/** 저장 화면(모아보기)에서 개별 스탬프를 해제할 때 쓴다 — removeSavedSpot과 동일한 관례. */
export function removeStamp(spotId: number): void {
  persist(loadStamps().filter((s) => s.spot_id !== spotId));
}

/** 마일스톤 규칙 — 지어낸 데이터 없이 순수 개수 기반(동 5개 / 은 10개 / 금 20개, 오케스트레이터 지시). */
export interface Milestone {
  tier: "동" | "은" | "금";
  threshold: number;
}
export const STAMP_MILESTONES: Milestone[] = [
  { tier: "동", threshold: 5 },
  { tier: "은", threshold: 10 },
  { tier: "금", threshold: 20 },
];

export interface RegionSummary {
  regionCode: string;
  /** region_name이 있으면 사람이 읽는 지역명, 없으면 region_code로 폴백한다(값을 지어내지 않음). */
  label: string;
  count: number;
}

/** 지역별 수집 현황(예: "부산 3 · 제주 1") — 개수 내림차순 정렬. */
export function summarizeByRegion(stamps: Stamp[]): RegionSummary[] {
  const map = new Map<string, RegionSummary>();
  for (const s of stamps) {
    const existing = map.get(s.region_code);
    if (existing) {
      existing.count += 1;
    } else {
      map.set(s.region_code, {
        regionCode: s.region_code,
        label: s.region_name ?? s.region_code,
        count: 1,
      });
    }
  }
  return Array.from(map.values()).sort((a, b) => b.count - a.count);
}
