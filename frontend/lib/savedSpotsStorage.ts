/**
 * 저장한 스팟 — 2026-09-16(대표 지시 "기기가 아닌 그 계정의 데이터로") 계정 보관함으로 전환.
 *
 * 정본은 로그인 상태면 서버(`/api/v1/saved-spots`, saved_spots 테이블)이고, localStorage 는
 * **캐시**다. 화면(SaveToggleButton·SpotDetail·SavedContent·MyPage)이 쓰는 동기 API
 * (loadSavedSpots / isSpotSaved / toggleSavedSpot / removeSavedSpot)는 그대로 두고, 로그인
 * 상태에서는 토글·삭제가 캐시를 즉시 바꾼 뒤 서버에 같은 변경을 보낸다(실패해도 화면은 막지 않고
 * 다음 동기화에서 서버 값으로 되돌아온다).
 *
 * - 비로그인: 종전과 같은 기기 로컬 저장(캐시가 곧 정본).
 * - 로그인 직후(Header 부팅 동기화·저장 화면 진입): `syncSavedSpotsFromServer()` 가 로컬에만 있던
 *   항목을 서버로 한 번 올린 뒤(합치기), 서버 목록으로 캐시를 덮어쓴다.
 * - 로그아웃: authStorage.logout 이 캐시 키를 지운다 — 같은 기기의 다음 계정이 이전 계정의 저장을
 *   보지 않게(온보딩 결과와 같은 이유).
 * 키 이름은 유지한다(`sumeungil:saved-spots:v1`) — 스키마가 같아서 기존 사용자의 로컬 저장이 그대로
 * 첫 동기화 때 계정으로 옮겨진다.
 */
import { CongestionLevel, SpotCard, SpotCategory, deleteSavedSpotRemote, fetchSavedSpots, putSavedSpotRemote } from "./api";
import { getNickname } from "./authStorage";

export const SAVED_SPOTS_STORAGE_KEY = "sumeungil:saved-spots:v1";
const STORAGE_KEY = SAVED_SPOTS_STORAGE_KEY;

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

/** 로그인 여부 — 닉네임 캐시가 있으면 로그인 상태(authStorage 관례). 서버 401 이면 호출부가 조용히 무시한다. */
function loggedIn(): boolean {
  return getNickname() !== null;
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
 * 로그인 상태면 같은 변경을 서버에도 보낸다(응답을 기다리지 않는다).
 */
export function toggleSavedSpot(spot: SpotCard): boolean {
  const list = loadSavedSpots();
  const idx = list.findIndex((s) => s.id === spot.id);
  if (idx >= 0) {
    list.splice(idx, 1);
    persist(list);
    if (loggedIn()) void deleteSavedSpotRemote(spot.id).catch(() => undefined);
    return false;
  }
  const saved = toSavedSpot(spot);
  list.push(saved);
  persist(list);
  if (loggedIn()) void putSavedSpotRemote(saved.id, saved.congestion).catch(() => undefined);
  return true;
}

export function removeSavedSpot(id: number): void {
  persist(loadSavedSpots().filter((s) => s.id !== id));
  if (loggedIn()) void deleteSavedSpotRemote(id).catch(() => undefined);
}

let syncInFlight: Promise<SavedSpot[]> | null = null;

/**
 * 서버 보관함과 캐시를 맞춘다. 로그인 상태가 아니면 캐시를 그대로 돌려준다.
 * ① 캐시에만 있는 항목(비로그인 때 저장한 것)을 서버에 올린다 → ② 서버 목록으로 캐시를 덮어쓴다.
 * 동시에 여러 화면이 불러도 요청은 한 번만 나간다.
 */
export function syncSavedSpotsFromServer(): Promise<SavedSpot[]> {
  if (typeof window === "undefined" || !loggedIn()) return Promise.resolve(loadSavedSpots());
  if (syncInFlight) return syncInFlight;
  syncInFlight = (async () => {
    try {
      const local = loadSavedSpots();
      let remote = await fetchSavedSpots();
      const remoteIds = new Set(remote.map((s) => s.id));
      const onlyLocal = local.filter((s) => !remoteIds.has(s.id));
      if (onlyLocal.length > 0) {
        await Promise.all(onlyLocal.map((s) => putSavedSpotRemote(s.id, s.congestion).catch(() => undefined)));
        remote = await fetchSavedSpots();
      }
      persist(remote);
      return remote;
    } catch {
      return loadSavedSpots(); // 서버 실패(401·네트워크)면 캐시 유지 — 화면을 비우지 않는다
    } finally {
      syncInFlight = null;
    }
  })();
  return syncInFlight;
}
