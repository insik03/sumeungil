/**
 * 01-interface-contract.md 부록 R.0 — "이것은 인증이 아니다". 리뷰·코스공유 쓰기 요청에 붙이는
 * X-Device-Id 헤더 값을 여기서 1회 발급해 localStorage에 영구 보관한다(authStorage.ts의 닉네임과
 * 별개 개념 — 닉네임은 "누구인지 보여주는 표시값", device_id는 "이 브라우저가 쓴 글을 서버가
 * 구분하는 값"이다. 로그아웃해도 device_id는 지우지 않는다 — 지우면 그 기기가 쓴 글의 소유권이
 * 영구히 사라진다는 게 계약의 알려진 한계다, R.0).
 *
 * 서버 형식 규약: `[A-Za-z0-9_-]{8,64}`(UUID v4 권장, 위반 시 쓰기 요청이 400 INVALID_DEVICE_ID).
 * crypto.randomUUID가 없는 환경(구형 브라우저·비보안 컨텍스트)을 위해 getRandomValues 기반
 * RFC4122-유사 v4 생성 폴백을 둔다 — 둘 다 없으면 Math.random 폴백(그래도 형식은 항상 유효하다).
 */
const DEVICE_ID_KEY = "sumeungil:device-id:v1";
const DEVICE_ID_PATTERN = /^[A-Za-z0-9_-]{8,64}$/;

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

function randomHexBytes(length: number): Uint8Array {
  const bytes = new Uint8Array(length);
  if (isBrowser() && window.crypto && typeof window.crypto.getRandomValues === "function") {
    window.crypto.getRandomValues(bytes);
    return bytes;
  }
  // 최후 폴백(구형 환경) — 암호학적으로 안전하지 않지만 device_id는 인증이 아니므로(R.0) 형식만
  // 유효하면 충분하다(신원 검증 수단이 원래 없다).
  for (let i = 0; i < length; i += 1) {
    bytes[i] = Math.floor(Math.random() * 256);
  }
  return bytes;
}

/** RFC4122 v4 형태의 UUID 문자열을 만든다(하이픈 포함, [A-Za-z0-9-] 범위라 서버 정규식을 항상 통과). */
function generateUuidV4(): string {
  if (isBrowser() && typeof window.crypto?.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  const bytes = randomHexBytes(16);
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10, 16).join(""),
  ].join("-");
}

/**
 * 저장된 device_id를 반환한다. 없거나(최초 방문) 저장된 값이 서버 형식(R.0)을 벗어나면(손상된
 * localStorage 등) 새로 발급해 덮어쓴다 — 항상 유효한 값만 반환한다는 것을 호출부가 신뢰할 수 있다.
 * localStorage 자체가 막힌 환경(시크릿 모드 등)에서는 저장에 실패해도 매 호출 새 값을 만들어
 * 반환한다(화면 흐름은 막지 않는다 — 다만 그 세션 동안 소유권이 유지되지 않는 정도의 저하일 뿐).
 */
export function getDeviceId(): string {
  if (!isBrowser()) return "";
  try {
    const existing = window.localStorage.getItem(DEVICE_ID_KEY);
    if (existing && DEVICE_ID_PATTERN.test(existing)) return existing;
    const created = generateUuidV4();
    window.localStorage.setItem(DEVICE_ID_KEY, created);
    return created;
  } catch {
    return generateUuidV4();
  }
}
