/**
 * 01-interface-contract.md 부록 F.2-2/F.2-3/F.2-6 — 저장코스는 서버 엔드포인트 없이
 * 클라이언트 localStorage 단독으로 성립한다(서버 호출 0). onboardingStorage.ts와 동일한
 * 네임스페이스·버전 접미 규칙(`sumeungil:...:v1`)을 따른다.
 * 저장 단위는 primitive = 단일 스팟 즐겨찾기(SavedSpot). 묶음(SavedCourse)은 F.2-3 계약상
 * 선택 구현이며 MVP-7 build DoD(F.2-7)는 즐겨찾기까지만 필수라 이 파일에서는 만들지 않는다.
 */
import { CongestionLevel, SpotCard, SpotCategory } from "./api";

const STORAGE_KEY = "sumeungil:saved-spots:v1";

/** 부록 F.2-3 SavedSpot 스키마 — SpotCard(부록 C.2)의 표시에 필요한 최소 스냅샷 + 저장 메타. */
export interface SavedSpot {
  id: number;
  name: string;
  category: SpotCategory;
  region_code: string;
  location: { lat: number; lng: number } | null;
  congestion: { index: number | null; level: CongestionLevel; tier: "A" | "B" | "C" | "none" } | null;
  is_hidden_gem: boolean;
  /** 저장 시각(ISO). 저장 시점 스냅샷임을 정직 표기하는 데 쓴다(F.2-3 "스냅샷 신선도"). */
  saved_at: string;
}

function isSavedSpot(item: unknown): item is SavedSpot {
  if (!item || typeof item !== "object") return false;
  const s = item as Record<string, unknown>;
  return (
    typeof s.id === "number" &&
    typeof s.name === "string" &&
    typeof s.category === "string" &&
    typeof s.region_code === "string" &&
    typeof s.saved_at === "string"
  );
}

/**
 * localStorage 파싱 실패/버전 불일치(:v1 ≠ 현재 스키마)면 조용히 빈 목록으로 폴백한다
 * (F.2-6-3, 손상 데이터로 화면이 죽지 않게 한다).
 */
export function loadSavedSpots(): SavedSpot[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isSavedSpot);
  } catch {
    return [];
  }
}

function persist(list: SavedSpot[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {
    // localStorage 비활성/용량초과(시크릿 모드 등) — 조용히 무시. 화면 흐름을 막지 않는다.
  }
}

export function isSpotSaved(id: number): boolean {
  return loadSavedSpots().some((s) => s.id === id);
}

/** SpotCard(부록 C.2) 스냅샷을 SavedSpot(F.2-3)으로 축약한다 — 없는 필드(address·themes 등)는 담지 않는다. */
function toSavedSpot(spot: SpotCard): SavedSpot {
  return {
    id: spot.id,
    name: spot.name,
    category: spot.category,
    region_code: spot.region_code,
    location: spot.location ?? null,
    congestion: spot.congestion,
    is_hidden_gem: spot.is_hidden_gem,
    saved_at: new Date().toISOString(),
  };
}

/**
 * 저장/해제 토글(id로 dedupe upsert). 반환값 = 토글 후 저장 상태(true = 저장됨).
 */
export function toggleSavedSpot(spot: SpotCard): boolean {
  const list = loadSavedSpots();
  const idx = list.findIndex((s) => s.id === spot.id);
  if (idx >= 0) {
    list.splice(idx, 1);
    persist(list);
    return false;
  }
  list.push(toSavedSpot(spot));
  persist(list);
  return true;
}

export function removeSavedSpot(id: number): void {
  persist(loadSavedSpots().filter((s) => s.id !== id));
}
