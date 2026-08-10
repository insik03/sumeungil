/**
 * 거리순 정렬(신규, 클라이언트 전용) 계산 유틸.
 * 좌표는 항상 호출부(navigator.geolocation, SpotCard.location)가 실측으로 넘긴 값만 쓴다 — 지어내지 않는다.
 */
export interface GeoPoint {
  lat: number;
  lng: number;
}

const EARTH_RADIUS_KM = 6371;

/** 두 좌표 간 대권거리(km), Haversine 공식. */
export function haversineDistanceKm(a: GeoPoint, b: GeoPoint): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);

  const sinDLat = Math.sin(dLat / 2);
  const sinDLng = Math.sin(dLng / 2);
  const h = sinDLat * sinDLat + Math.cos(lat1) * Math.cos(lat2) * sinDLng * sinDLng;
  const c = 2 * Math.atan2(Math.sqrt(Math.max(0, h)), Math.sqrt(Math.max(0, 1 - h)));
  return EARTH_RADIUS_KM * c;
}

/**
 * 결측/비정상 좌표(런타임 방어용 — 계약상 SpotCard.location은 non-null이지만 혹시 모를 값을 대비)면
 * null을 반환한다. 거리순 정렬에서 이런 스팟은 맨 뒤로 보낸다(§거리순 요구사항).
 */
export function safeDistanceKm(
  origin: GeoPoint,
  loc: { lat: number; lng: number } | null | undefined
): number | null {
  if (!loc || !Number.isFinite(loc.lat) || !Number.isFinite(loc.lng)) return null;
  return haversineDistanceKm(origin, loc);
}
