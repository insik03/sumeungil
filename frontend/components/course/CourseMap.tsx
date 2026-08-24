"use client";

import { useEffect, useRef, useState } from "react";
import { CourseLeg, CourseSpot } from "../../lib/api";
import { CATEGORY_META } from "../recommend/constants";

/**
 * 2026-08-24(대표 지시) — Tmap에서 네이버 지도로 교체.
 *
 * SpotMap.tsx와 같은 이유: Tmap appKey가 IP 화이트리스트(서버 IP만 허용)라
 * 실제 사용자 브라우저에서는 지도가 영구히 안 뜨는 구조적 문제였다(대표 실측 재확인:
 * SpotMap.tsx 교체 후에도 /course는 여전히 안 뜬다고 보고 — 이 파일이 SpotMap.tsx와
 * 별개로 자체 Tmap 로더를 갖고 있어서 그때 같이 안 바뀐 것).
 *
 * 경로선(legs[].path)은 백엔드가 Tmap 경로탐색 API로 이미 좌표 배열을 만들어 보내주므로
 * 그 좌표를 그리는 것뿐이다 — 어떤 지도 SDK로 그리든 상관없다. 네이버 지도의
 * naver.maps.Polyline으로 동일하게 그린다.
 *
 * 네이버 지도 SDK는 Tmap과 달리 부트스트랩이 document.write를 안 쓴다 — 일반
 * <script src> 로드 후 onload 시점에 이미 window.naver.maps 가 전부 채워져 있다.
 */
declare global {
  interface Window {
    naver: any; // eslint-disable-line @typescript-eslint/no-explicit-any
  }
}

const NAVER_SDK_ID = "naver-map-sdk-script";
const NAVER_SDK_BASE = "https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId=";
const NAVER_READY_TIMEOUT_MS = 12000;

function naverMapsReady(): boolean {
  const n = typeof window !== "undefined" ? window.naver : undefined;
  return !!n && !!n.maps && typeof n.maps.Map === "function" && typeof n.maps.LatLng === "function";
}

const KOREA_FALLBACK_CENTER = { lat: 36.5, lng: 127.8 };

type SdkStatus = "loading" | "ready" | "error";

/**
 * 모듈 스코프 로딩 Promise. SpotMap.tsx의 것과는 별개 변수지만, 둘 다 같은
 * script id(NAVER_SDK_ID)를 쓰므로 어느 쪽이 먼저 로드해도 다른 쪽은 기존 <script>를
 * 감지해 재사용한다(중복 주입 없음).
 */
let sdkLoadPromise: Promise<void> | null = null;

function loadNaverMapsSdk(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("no window"));
  }
  if (naverMapsReady()) {
    return Promise.resolve();
  }
  if (sdkLoadPromise) {
    return sdkLoadPromise;
  }

  const clientId = process.env.NEXT_PUBLIC_NAVER_MAP_CLIENT_ID;
  if (!clientId) {
    return Promise.reject(new Error("NEXT_PUBLIC_NAVER_MAP_CLIENT_ID가 설정되지 않았습니다."));
  }

  sdkLoadPromise = new Promise<void>((resolve, reject) => {
    const existing = document.getElementById(NAVER_SDK_ID);
    if (existing) {
      const start = Date.now();
      const poll = () => {
        if (naverMapsReady()) {
          resolve();
          return;
        }
        if (Date.now() - start > NAVER_READY_TIMEOUT_MS) {
          reject(new Error("naver maps sdk not ready (timeout, shared)"));
          return;
        }
        window.setTimeout(poll, 100);
      };
      poll();
      return;
    }

    const script = document.createElement("script");
    script.id = NAVER_SDK_ID;
    script.src = `${NAVER_SDK_BASE}${encodeURIComponent(clientId)}`;
    script.async = true;
    let settled = false;
    const watchdog = window.setTimeout(() => {
      if (settled) return;
      settled = true;
      script.remove();
      reject(new Error("naver maps sdk load timeout"));
    }, NAVER_READY_TIMEOUT_MS);
    script.onload = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(watchdog);
      if (naverMapsReady()) resolve();
      else reject(new Error("naver maps sdk loaded but classes not ready"));
    };
    script.onerror = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(watchdog);
      script.remove();
      reject(new Error("naver maps sdk load error"));
    };
    document.head.appendChild(script);
  }).catch((err) => {
    sdkLoadPromise = null;
    throw err;
  });

  return sdkLoadPromise;
}

function isValidLatLng(
  loc: { lat: number; lng: number } | null | undefined
): loc is { lat: number; lng: number } {
  return (
    !!loc &&
    Number.isFinite(loc.lat) &&
    Number.isFinite(loc.lng) &&
    loc.lat >= -90 &&
    loc.lat <= 90 &&
    loc.lng >= -180 &&
    loc.lng <= 180
  );
}

/** 코스 마커는 "순서를 한눈에" 보여주는 게 우선이라 신호등 색(혼잡도) 위에 순번 숫자를 얹는다. */
const LEVEL_MARKER_COLOR: Record<string, string> = {
  low: "#2f7a54", // --g-500 (§22, 2026-07-29 딥 포레스트로 재스킨 — tokens.css와 동기화)
  mid: "#f2a93d",
  high: "#ef7339",
  unknown: "#2b82ee", // 코스 마커는 정보없음도 브랜드 아주르로(순번 가독성 우선, 경고색과 혼동 방지)
};

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  CATEGORY_META.map((c) => [c.value, c.label])
);

/** 혼잡도 색 + 순번 숫자를 담은 원형 마커를 data URL SVG로 생성(외부 이미지 CDN 불필요). */
function buildOrderMarkerIconUrl(order: number, level: string): string {
  const color = LEVEL_MARKER_COLOR[level] ?? LEVEL_MARKER_COLOR.unknown;
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="34" height="34" viewBox="0 0 34 34">` +
    `<circle cx="17" cy="17" r="15" fill="${color}" stroke="#ffffff" stroke-width="3"/>` +
    `<text x="17" y="22" font-family="sans-serif" font-size="15" font-weight="700" ` +
    `text-anchor="middle" fill="#ffffff">${order}</text>` +
    `</svg>`;
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

const LEVEL_BADGE: Record<string, { label: string; badgeClass: string }> = {
  high: { label: "혼잡", badgeClass: "badge--hot" },
  mid: { label: "보통", badgeClass: "badge--mid" },
  low: { label: "여유", badgeClass: "badge--calm" },
  unknown: { label: "정보없음", badgeClass: "badge--unknown" },
};

/**
 * 팝업 내용을 DOM으로 조립해 outerHTML로 반환한다(textContent만 사용해 원문 데이터가 HTML로
 * 해석되지 않게 함). 비교(/compare)가 아니라 스팟 상세(/spot/{id})로 링크한다 — 코스 화면은
 * 카드 탭과 동일하게 상세 진입이 자연스러운 흐름이기 때문(스코프 지시서 "카드 클릭 → /spot/{id}").
 */
function buildPopupContent(spot: CourseSpot, order: number): string {
  const level = spot.congestion?.level ?? "unknown";
  const levelMeta = LEVEL_BADGE[level] ?? LEVEL_BADGE.unknown;
  const categoryLabel = CATEGORY_LABEL[spot.category] ?? spot.category;

  const container = document.createElement("div");
  container.className = "spot-map-popup";

  const order_el = document.createElement("p");
  order_el.className = "spot-map-popup__category";
  order_el.textContent = `${order}. ${spot.slot_label}`;
  container.appendChild(order_el);

  const name = document.createElement("p");
  name.className = "spot-map-popup__name";
  name.textContent = spot.name;
  container.appendChild(name);

  const meta = document.createElement("p");
  meta.className = "spot-map-popup__category";
  meta.textContent = categoryLabel;
  container.appendChild(meta);

  const badgeRow = document.createElement("div");
  badgeRow.className = "spot-map-popup__badges";

  const congestionBadge = document.createElement("span");
  congestionBadge.className = `badge ${spot.congestion ? levelMeta.badgeClass : "badge--unknown"}`;
  congestionBadge.textContent = spot.congestion
    ? levelMeta.label + (spot.congestion.index != null ? ` ${Math.round(spot.congestion.index)}%` : "")
    : "예상 혼잡도 정보없음";
  badgeRow.appendChild(congestionBadge);
  container.appendChild(badgeRow);

  const link = document.createElement("a");
  link.className = "spot-map-popup__link";
  link.href = `/spot/${encodeURIComponent(String(spot.id))}?region_code=${encodeURIComponent(spot.region_code)}`;
  link.textContent = "자세히 보기 →";
  container.appendChild(link);

  return container.outerHTML;
}

export interface CourseMapProps {
  spots: CourseSpot[];
  legs: CourseLeg[];
  /** 지도 접근성 라벨용. 좌표를 지어내지 않으므로 상위(CourseContent)가 이미 아는 지역명을 그대로 받는다. */
  regionLabel: string;
}

/**
 * 코스 화면 지도. SpotMap.tsx(추천 화면 지도)와 같은 원칙을 따른다: 타임라인이 정본이고
 * 지도는 부가 기능이다 — SDK 로드/맵 생성/폴리라인 구간 중 어떤 단계가 실패해도 폴백 문구만
 * 보여주고 타임라인은 그대로 정상 동작한다.
 */
export default function CourseMap({ spots, legs, regionLabel }: CourseMapProps) {
  const mapDivRef = useRef<HTMLDivElement | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mapRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const markersRef = useRef<any[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const polylinesRef = useRef<any[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const infoWindowRef = useRef<any>(null);

  const [sdkStatus, setSdkStatus] = useState<SdkStatus>("loading");

  useEffect(() => {
    let cancelled = false;
    loadNaverMapsSdk()
      .then(() => {
        if (!cancelled) setSdkStatus("ready");
      })
      .catch(() => {
        if (!cancelled) setSdkStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (sdkStatus !== "ready" || !mapDivRef.current || mapRef.current) return;
    try {
      const { naver } = window;
      mapRef.current = new naver.maps.Map(mapDivRef.current, {
        center: new naver.maps.LatLng(KOREA_FALLBACK_CENTER.lat, KOREA_FALLBACK_CENTER.lng),
        zoom: 12,
      });
    } catch {
      setSdkStatus("error");
    }
  }, [sdkStatus]);

  // 스팟/구간이 바뀔 때마다 마커+경로선을 다시 그리고 bounds에 재fit한다.
  useEffect(() => {
    if (sdkStatus !== "ready" || !mapRef.current) return;
    const { naver } = window;
    const map = mapRef.current;

    markersRef.current.forEach((m) => {
      try {
        m.setMap(null);
      } catch {
        /* noop */
      }
    });
    markersRef.current = [];
    polylinesRef.current.forEach((p) => {
      try {
        p.setMap(null);
      } catch {
        /* noop */
      }
    });
    polylinesRef.current = [];
    if (infoWindowRef.current) {
      try {
        infoWindowRef.current.close();
      } catch {
        /* noop */
      }
      infoWindowRef.current = null;
    }

    // location 결측/유효범위 밖 스팟은 마커를 찍지 않는다(좌표를 지어내지 않음).
    const validEntries = spots
      .map((spot, idx) => ({ spot, order: idx + 1 }))
      .filter((e) => isValidLatLng(e.spot.location));
    if (validEntries.length === 0) return;

    try {
      const bounds = new naver.maps.LatLngBounds();

      validEntries.forEach(({ spot, order }) => {
        const position = new naver.maps.LatLng(spot.location.lat, spot.location.lng);
        bounds.extend(position);

        const level = spot.congestion?.level ?? "unknown";
        const marker = new naver.maps.Marker({
          position,
          icon: {
            url: buildOrderMarkerIconUrl(order, level),
            size: new naver.maps.Size(34, 34),
            scaledSize: new naver.maps.Size(34, 34),
            anchor: new naver.maps.Point(17, 17),
          },
          map,
        });

        naver.maps.Event.addListener(marker, "click", () => {
          if (infoWindowRef.current) {
            try {
              infoWindowRef.current.close();
            } catch {
              /* noop */
            }
          }
          infoWindowRef.current = new naver.maps.InfoWindow({
            content: buildPopupContent(spot, order),
          });
          infoWindowRef.current.open(map, marker);
        });

        markersRef.current.push(marker);
      });

      // legs[].path 좌표는 [lng, lat](WGS84) — naver.maps.LatLng은 (lat, lng) 순서라 뒤집어서 넣는다.
      // path가 null인 구간(Tmap 경로탐색 실패)은 그리지 않는다(지어내지 않음, 타임라인의 "이동 정보 없음"과 일관).
      legs.forEach((leg) => {
        if (!leg.path || leg.path.length < 2) return;
        const linePath = leg.path.map((coord) => new naver.maps.LatLng(coord[1], coord[0]));
        linePath.forEach((p: unknown) => bounds.extend(p as never));
        const polyline = new naver.maps.Polyline({
          path: linePath,
          strokeColor: "#2b82ee",
          strokeWeight: 5,
          strokeOpacity: 0.85,
          map,
        });
        polylinesRef.current.push(polyline);
      });

      if (validEntries.length === 1) {
        map.setCenter(new naver.maps.LatLng(validEntries[0].spot.location.lat, validEntries[0].spot.location.lng));
        map.setZoom(15);
      } else {
        map.fitBounds(bounds);
      }
    } catch {
      setSdkStatus("error");
    }
  }, [spots, legs, sdkStatus]);

  if (sdkStatus === "error") {
    return (
      <div className="spot-map spot-map--fallback" role="status">
        <p className="spot-map__fallback-msg">지도를 불러오지 못했습니다.</p>
        <p className="spot-map__fallback-hint">아래 코스 목록에서 이동 순서를 확인해주세요.</p>
      </div>
    );
  }

  return (
    <div className="spot-map">
      {sdkStatus === "loading" && (
        <div className="spot-map__loading" aria-hidden="true">
          <div className="skeleton-bar" style={{ width: "100%", height: "100%" }} />
        </div>
      )}
      <div ref={mapDivRef} className="spot-map__canvas" role="img" aria-label={`${regionLabel} 추천 코스 경로 지도`} />
    </div>
  );
}
