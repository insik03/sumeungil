/**
 * 방문 스탬프 — **계정 데이터이며, 브라우저 위치로 현장을 인증해야 찍힌다**(대표 지시 2026-09-20:
 * "방문 스탬프도 기기 저장이 아니라 계정에, 내 위치를 브라우저에서 받아서 찍는 것").
 *
 * 종전(Phase 4)엔 "내가 눌러서 기록"하는 셀프 체크인을 localStorage 에만 두었다 — 기기를 바꾸면 사라지고
 * 아무 데서나 찍을 수 있었다. 이제:
 *  - 정본은 서버(/api/v1/stamps)이고, 받아온 목록은 메모리(`accountStamps`)에만 둔다(savedSpotsStorage 와
 *    같은 이유 — 다른 기기에서 지운 항목이 이 기기 캐시로 되살아나지 않게). `Header` 가 부팅·로그인 직후 동기화한다.
 *  - 스탬프를 찍을 때 브라우저 Geolocation 으로 현재 위치를 받아 서버에 보낸다. 서버는 그 스팟과의 거리가
 *    반경 안일 때만 저장하며 **좌표는 저장하지도 로그에 남기지도 않는다**(저장은 spot_id·찍은 시각뿐).
 *  - 비로그인은 찍을 수 없다(호출부가 requireLogin 으로 먼저 막는다). 예전 기기 저장(localStorage)은 발견 즉시 지운다.
 */
import { ApiError, SpotCategory, deleteStampRemote, fetchStamps, postStampRemote } from "./api";
import { AUTH_CHANGED_EVENT, getNickname } from "./authStorage";

const LEGACY_STORAGE_KEY = "sumeungil:stamps:v1";
export const STAMPS_CHANGED = "sumeungil:stamps-changed";

export interface Stamp {
  spot_id: number;
  name: string;
  region_code: string;
  region_name: string | null;
  category: SpotCategory;
  /** 현장 인증으로 찍힌 시각(ISO, 서버 기준). */
  stamped_at: string;
}

let accountStamps: Stamp[] = [];
let authGeneration = 0;
let syncInFlight: Promise<Stamp[]> | null = null;

function notify(): void {
  window.dispatchEvent(new Event(STAMPS_CHANGED));
}

/** 표시용 로그인 캐시. 서버가 모든 요청의 실제 인증을 검사한다. */
function loggedIn(): boolean {
  return getNickname() !== null;
}

if (typeof window !== "undefined") {
  const reset = () => {
    authGeneration += 1;
    accountStamps = [];
    syncInFlight = null;
    notify();
  };
  window.addEventListener(AUTH_CHANGED_EVENT, reset);
  window.addEventListener("storage", (event) => {
    if (event.key === "sumeungil:nickname:v1") reset();
  });
}

/** 로그인 중이면 계정 목록(메모리), 게스트면 항상 빈 목록. 예전 기기 저장은 지운다. */
export function loadStamps(): Stamp[] {
  if (typeof window === "undefined") return [];
  if (loggedIn()) return accountStamps;
  try {
    window.localStorage.removeItem(LEGACY_STORAGE_KEY);
  } catch {
    // localStorage 비활성 — 조용히 무시.
  }
  return [];
}

export function isSpotStamped(spotId: number): boolean {
  return loadStamps().some((s) => s.spot_id === spotId);
}

/** 서버 목록으로 메모리를 맞춘다. 동시에 여러 화면이 불러도 요청은 한 번만 나간다. */
export function syncStampsFromServer(): Promise<Stamp[]> {
  if (typeof window === "undefined" || !loggedIn()) return Promise.resolve(loadStamps());
  if (syncInFlight) return syncInFlight;
  const generation = authGeneration;
  syncInFlight = (async () => {
    try {
      const remote = await fetchStamps();
      if (generation !== authGeneration || !loggedIn()) return [];
      accountStamps = remote;
      notify();
      return remote;
    } catch {
      return loadStamps(); // 서버 실패면 화면을 비우지 않는다
    } finally {
      if (generation === authGeneration) syncInFlight = null;
    }
  })();
  return syncInFlight;
}

/** 위치를 못 받은 이유를 사용자에게 그대로 보여줄 수 있는 오류. */
export class StampLocationError extends Error {}

function currentPosition(): Promise<{ lat: number; lng: number; accuracy_m: number }> {
  return new Promise((resolve, reject) => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      reject(new StampLocationError("이 브라우저는 위치 기능을 지원하지 않아요."));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy_m: pos.coords.accuracy }),
      (err) => {
        if (err.code === err.PERMISSION_DENIED) {
          reject(new StampLocationError("위치 권한을 허용해야 방문을 인증할 수 있어요. 브라우저 주소창의 위치 설정을 확인해 주세요."));
        } else if (err.code === err.TIMEOUT) {
          reject(new StampLocationError("위치를 받는 데 너무 오래 걸려요. 잠시 뒤 다시 시도해 주세요."));
        } else {
          reject(new StampLocationError("현재 위치를 확인하지 못했어요. 위치 서비스를 켜고 다시 시도해 주세요."));
        }
      },
      { enableHighAccuracy: true, timeout: 15_000, maximumAge: 0 }
    );
  });
}

/**
 * 지금 이 자리에서 스탬프를 찍는다 — 브라우저 위치를 받아 서버에 대조를 맡긴다.
 * 성공하면 그 스탬프를 돌려주고 메모리 목록에 반영한다. 실패는 사용자에게 보여줄 문장을 담은 Error.
 */
export async function stampHere(spotId: number): Promise<Stamp> {
  const generation = authGeneration;
  const pos = await currentPosition();
  let stamp: Stamp;
  try {
    stamp = await postStampRemote(spotId, pos);
  } catch (e) {
    throw new Error(e instanceof ApiError ? e.message : "스탬프를 찍지 못했어요. 잠시 뒤 다시 시도해 주세요.");
  }
  if (generation === authGeneration && loggedIn()) {
    accountStamps = [stamp, ...accountStamps.filter((s) => s.spot_id !== stamp.spot_id)];
    notify();
  }
  return stamp;
}

/** 저장 화면(모아보기)에서 스탬프를 지운다 — 화면엔 바로 반영하고, 서버 실패면 서버 목록으로 되돌린다. */
export function removeStamp(spotId: number): void {
  if (!loggedIn()) return;
  accountStamps = accountStamps.filter((s) => s.spot_id !== spotId);
  notify();
  void deleteStampRemote(spotId).catch(() => {
    window.alert("스탬프를 지우지 못했어요. 연결과 로그인 상태를 확인해 주세요.");
    syncInFlight = null;
    void syncStampsFromServer();
  });
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
