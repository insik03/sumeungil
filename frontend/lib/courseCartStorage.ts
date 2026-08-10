/**
 * 커스텀 코스 장바구니("내가 고른 코스") — savedSpotsStorage.ts/stampStorage.ts와 동일한
 * localStorage 패턴을 따른다: `sumeungil:...:v1` 네임스페이스, 파싱 실패/버전 불일치 시 빈 배열
 * 폴백, id dedupe upsert, 서버 전송 0(F.2-2와 동일 원칙 — 담긴 스팟은 이 기기에만 남는다).
 *
 * 담긴 스팟 자체는 순서가 없다(사용자가 순서를 정하지 않는다) — "순서 짜주기" 버튼을 누르면
 * id 목록만 POST /api/v1/courses/arrange 에 그대로 넘기고, 순서(slot_label)는 전부 backend가
 * 판정해 내려준다(부록 I §arrange, CourseResponse와 동일 스키마). 여기서는 담기/빼기만 다룬다.
 *
 * CART_CHANGED_EVENT — 같은 스팟을 담는 진입점이 여러 화면(스팟 상세, 저장 목록)에 흩어져 있어
 * 한 화면에 여러 토글/카운트 UI가 동시에 떠 있을 수 있다(예: /course 상단 세그먼트 탭의 "(N)"
 * 카운트, 저장 목록의 카드별 토글). storage 이벤트는 다른 탭 간 동기화만 잡아주고 같은 탭 내
 * 컴포넌트끼리는 못 잡아주므로, persist 시 커스텀 이벤트를 직접 쏴서 같은 탭 안에서도
 * 구독 중인 컴포넌트가 즉시 다시 읽게 한다.
 */
import { SpotCategory } from "./api";

const STORAGE_KEY = "sumeungil:course-cart:v1";

/** 같은 탭 내 여러 화면/컴포넌트가 장바구니 변경을 구독할 때 쓰는 커스텀 이벤트 이름. */
export const CART_CHANGED_EVENT = "sumeungil:cart-changed";

/** 부록 I §arrange 계약 상한(spot_ids 2~8개)과 동일한 값 — 프론트가 새로 지어낸 제약이 아니다. */
export const MAX_CART_SIZE = 8;
export const MIN_CART_SIZE = 2;

/** 담긴 스팟 1개의 최소 표시 스냅샷. congestion 등은 담지 않는다(재판정용 데이터를 지어내지 않음 —
 * 순서를 짜면 backend가 다시 SpotCard 전체를 채워서 내려준다). */
export interface CartSpot {
  id: number;
  name: string;
  category: SpotCategory;
  region_code: string;
  region_name?: string | null;
}

/** toggleCartSpot에 넘기는 최소 입력 — SpotDetail/SavedSpot 어디서든 이 필드만 뽑아 쓸 수 있다. */
export interface CartSpotInput {
  id: number;
  name: string;
  category: SpotCategory;
  region_code: string;
  region_name?: string | null;
}

function isCartSpot(item: unknown): item is CartSpot {
  if (!item || typeof item !== "object") return false;
  const s = item as Record<string, unknown>;
  return (
    typeof s.id === "number" &&
    typeof s.name === "string" &&
    typeof s.category === "string" &&
    typeof s.region_code === "string"
  );
}

/** localStorage 파싱 실패/버전 불일치면 조용히 빈 목록으로 폴백한다(savedSpotsStorage와 동일 원칙). */
export function loadCart(): CartSpot[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isCartSpot);
  } catch {
    return [];
  }
}

function persist(list: CartSpot[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {
    // localStorage 비활성/용량초과(시크릿 모드 등) — 조용히 무시. 화면 흐름을 막지 않는다.
  }
  window.dispatchEvent(new CustomEvent(CART_CHANGED_EVENT));
}

export function isInCart(id: number): boolean {
  return loadCart().some((s) => s.id === id);
}

function toCartSpot(input: CartSpotInput): CartSpot {
  return {
    id: input.id,
    name: input.name,
    category: input.category,
    region_code: input.region_code,
    region_name: input.region_name ?? null,
  };
}

export type ToggleCartResult = "added" | "removed" | "cart_full";

/**
 * 담기/빼기 토글(id dedupe upsert). 이미 8개가 담겨 있는데 새 스팟을 추가하려 하면 담지 않고
 * "cart_full"을 반환한다(호출부가 "최대 8곳까지" 안내를 띄운다) — MAX_CART_SIZE는 arrange 계약
 * 상한과 동일한 값이라 여기서 막아도 backend 400과 어긋나지 않는다.
 */
export function toggleCartSpot(spot: CartSpotInput): ToggleCartResult {
  const list = loadCart();
  const idx = list.findIndex((s) => s.id === spot.id);
  if (idx >= 0) {
    list.splice(idx, 1);
    persist(list);
    return "removed";
  }
  if (list.length >= MAX_CART_SIZE) {
    return "cart_full";
  }
  list.push(toCartSpot(spot));
  persist(list);
  return "added";
}

export function removeFromCart(id: number): void {
  persist(loadCart().filter((s) => s.id !== id));
}

export function clearCart(): void {
  persist([]);
}
