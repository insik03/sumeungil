/** Account saves use the server as the source of truth. Guest saves remain local.
 * Account snapshots are memory-only and discarded on authentication changes.
 * Guest lists are never silently uploaded to a different account.
 */
import { CongestionLevel, SpotCard, SpotCategory, deleteSavedSpotRemote, fetchSavedSpots, putSavedSpotRemote } from "./api";
import { AUTH_CHANGED_EVENT, getNickname } from "./authStorage";

export const SAVED_SPOTS_STORAGE_KEY = "sumeungil:saved-spots:v1";
const STORAGE_KEY = SAVED_SPOTS_STORAGE_KEY;
let accountSpots: SavedSpot[] = [];
let confirmedSpots: SavedSpot[] = [];
const latestWrite = new Map<number, number>();
let revision = 0;
export const SAVED_SPOTS_CHANGED = "sumeungil:saved-spots-changed";
function notify(): void { window.dispatchEvent(new Event(SAVED_SPOTS_CHANGED)); }

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

/** 표시용 로그인 캐시. 서버가 모든 저장 요청의 실제 인증을 검사한다. */
function loggedIn(): boolean {
  return getNickname() !== null;
}

/**
 * localStorage 파싱 실패/버전 불일치(:v1 ≠ 현재 스키마)면 조용히 빈 목록으로 폴백한다
 * (F.2-6-3, 손상 데이터로 화면이 죽지 않게 한다).
 */
export function loadSavedSpots(): SavedSpot[] {
  if (typeof window === "undefined") return [];
  if (loggedIn()) return accountSpots;
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
  if (loggedIn()) { accountSpots = list; notify(); return; }
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
let writes: Promise<void> = Promise.resolve();
function enqueueWrite(action: () => Promise<unknown>, id: number, saved: SavedSpot | null): void {
  const generation = authGeneration;
  const writeRevision = revision;
  latestWrite.set(id, writeRevision);
  writes = writes.then(async () => {
    if (generation !== authGeneration || !loggedIn()) return;
    try {
      await action();
      if (generation !== authGeneration || !loggedIn()) return;
      confirmedSpots = confirmedSpots.filter(s => s.id !== id);
      if (saved) confirmedSpots.push(saved);
    } catch {
      if (generation !== authGeneration || !loggedIn()) return;
      if (latestWrite.get(id) === writeRevision) {
        const restored = accountSpots.filter(s => s.id !== id);
        const confirmed = confirmedSpots.find(s => s.id === id);
        if (confirmed) restored.push(confirmed);
        persist(restored);
      }
      window.alert("저장 변경을 서버에 반영하지 못했습니다. 연결과 로그인 상태를 확인하고 다시 시도해주세요.");
    }
  });
}

export function toggleSavedSpot(spot: SpotCard): boolean {
  revision += 1;
  const list = [...loadSavedSpots()];
  const idx = list.findIndex((s) => s.id === spot.id);
  if (idx >= 0) {
    list.splice(idx, 1);
    persist(list);
    if (loggedIn()) enqueueWrite(() => deleteSavedSpotRemote(spot.id), spot.id, null);
    return false;
  }
  const saved = toSavedSpot(spot);
  list.push(saved);
  persist(list);
  if (loggedIn()) enqueueWrite(() => putSavedSpotRemote(saved.id, saved.congestion), saved.id, saved);
  return true;
}

export function removeSavedSpot(id: number): void {
  revision += 1;
  persist(loadSavedSpots().filter((s) => s.id !== id));
  if (loggedIn()) enqueueWrite(() => deleteSavedSpotRemote(id), id, null);
}

let authGeneration = 0;
if (typeof window !== "undefined") {
  window.addEventListener(AUTH_CHANGED_EVENT, () => { authGeneration += 1; accountSpots = []; confirmedSpots = []; latestWrite.clear(); syncInFlight = null; notify(); });
  window.addEventListener("storage", (event) => {
    if (event.key === "sumeungil:nickname:v1") { authGeneration += 1; accountSpots = []; confirmedSpots = []; latestWrite.clear(); syncInFlight = null; notify(); }
  });
}
let syncInFlight: Promise<SavedSpot[]> | null = null;

/**
 * 서버 보관함과 캐시를 맞춘다. 로그인 상태가 아니면 캐시를 그대로 돌려준다.
 * 서버 목록으로 계정 메모리 캐시만 갱신한다. 비로그인 저장은 자동으로 계정에 합치지 않는다.
 * 동시에 여러 화면이 불러도 요청은 한 번만 나간다.
 */
export function syncSavedSpotsFromServer(): Promise<SavedSpot[]> {
  if (typeof window === "undefined" || !loggedIn()) return Promise.resolve(loadSavedSpots());
  if (syncInFlight) return syncInFlight;
  const syncGeneration = authGeneration;
  syncInFlight = (async () => {
    try {
      const generation = authGeneration;
      const startedRevision = revision;
      const name = getNickname();
      await writes;
      if (generation !== authGeneration || !loggedIn()) return [];
      const remote = await fetchSavedSpots();
      // Never re-upload a cache: it may contain another device's deleted items.
      if (generation !== authGeneration || !loggedIn() || getNickname() !== name) return [];
      if (revision !== startedRevision) return loadSavedSpots();
      confirmedSpots = [...remote];
      persist(remote);
      return remote;
    } catch {
      return loadSavedSpots(); // 서버 실패(401·네트워크)면 캐시 유지 — 화면을 비우지 않는다
    } finally {
      if (authGeneration === syncGeneration) syncInFlight = null;
    }
  })();
  return syncInFlight;
}
