"use client";

import { useEffect, useRef, useState } from "react";
import { SpotCard } from "../../lib/api";
import { CATEGORY_META } from "./constants";

/**
 * 2026-08-24(대표 지시) — Tmap에서 네이버 지도로 교체.
 *
 * 원래 Tmap을 썼는데, 그 appKey가 IP 화이트리스트(서버 IP만 허용)로 걸려 있어서
 * 실제 사용자 브라우저에서는 지도가 영구히 안 뜨는 구조적 문제가 있었다(운영 서버 IP로
 * curl하면 200, 다른 IP에서 하면 403 ACCESS_DENIED — 실측 확인). 네이버 지도는
 * **도메인(Web 서비스 URL) 화이트리스트**라 이 문제가 구조적으로 없다.
 *
 * AI 코스짜기 지도(`course/CourseMap.tsx`)는 그대로 Tmap — 백엔드가 실제 Tmap
 * 경로탐색 API로 코스를 만들기 때문에 그 경로선을 그리려면 Tmap이 계속 필요하다.
 * 여기(추천 화면, 마커 표시 전용)는 Tmap 고유 기능에 안 걸려 있어서 교체 범위가 작다.
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

/** SDK/맵 생성 실패 시 폴백에서 쓸 대한민국 중앙 근사값(마커가 하나도 없을 때만 사용). */
const KOREA_FALLBACK_CENTER = { lat: 36.5, lng: 127.8 };

type SdkStatus = "loading" | "ready" | "error";

/**
 * 모듈 스코프의 로딩 Promise. 여러 SpotMap 인스턴스/리렌더가 동시에 <script>를
 * 중복 주입하지 않게 한 번만 로드한다.
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
    sdkLoadPromise = null; // 실패하면 다음 마운트에서 재시도할 수 있게 초기화
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

/**
 * 부록 E.4 마커 색상. 카드 배지(§4.1)는 mid를 azure로 쓰지만,
 * 지도 마커는 "한눈에 스캔"이 우선이라 신호등(초록/앰버/코랄) 관습을 따른다(대표 확정).
 * 값은 tokens.css의 --marker-* 와 동일하게 맞춘다(데이터URL SVG라 CSS 변수를 직접 못 써서 하드코딩).
 */
const LEVEL_MARKER_COLOR: Record<string, string> = {
  low: "#2f7a54", // --g-500 (§22, 2026-07-29 딥 포레스트로 재스킨 — tokens.css와 동기화)
  mid: "#f2a93d", // --marker-mid (신규 앰버, tokens.css 주석 참고)
  high: "#ef7339", // --b-500
  unknown: "#cbd5e1", // --gray-300
};

/** 팝업 배지는 카드/전광판과 동일한 §4.1 규약(azure=mid)을 재사용해 앱 전체 일관성을 지킨다. */
const LEVEL_BADGE: Record<string, { label: string; badgeClass: string }> = {
  high: { label: "혼잡", badgeClass: "badge--hot" },
  mid: { label: "보통", badgeClass: "badge--mid" },
  low: { label: "여유", badgeClass: "badge--calm" },
  unknown: { label: "정보없음", badgeClass: "badge--unknown" },
};

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  CATEGORY_META.map((c) => [c.value, c.label])
);

/** 혼잡도 색 채움 + 숨은 스팟 구분 표식(별)을 가진 핀 마커를 data URL SVG로 생성한다(외부 이미지 CDN 불필요). */
function buildMarkerIconUrl(level: string, isHiddenGem: boolean): string {
  const color = LEVEL_MARKER_COLOR[level] ?? LEVEL_MARKER_COLOR.unknown;
  const ringStroke = isHiddenGem ? "#1b4332" : "#ffffff";
  const ringWidth = isHiddenGem ? 3 : 1.5;
  const inner = isHiddenGem
    ? `<path d="M14 8.2l1.8 3.6 4 .6-2.9 2.8.7 4-3.6-1.9-3.6 1.9.7-4-2.9-2.8 4-.6z" fill="${color}"/>`
    : `<circle cx="14" cy="14" r="4.5" fill="${color}"/>`;
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="38" viewBox="0 0 28 38">` +
    `<path d="M14 0C6.3 0 0 6.3 0 14c0 10.2 14 24 14 24s14-13.8 14-24C28 6.3 21.7 0 14 0z" fill="${color}" stroke="${ringStroke}" stroke-width="${ringWidth}"/>` +
    `<circle cx="14" cy="14" r="7" fill="#ffffff"/>` +
    inner +
    `</svg>`;
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

/**
 * 마커 클릭 InfoWindow 내용을 DOM으로 조립해 outerHTML로 반환한다.
 * textContent만 사용해 값(스팟명 등 원문 데이터)이 HTML로 해석되지 않게 한다(안전한 렌더).
 * 표시 필드는 전부 §C.2 SpotCard에 이미 있는 값이다 — 좌표/코드를 지어내지 않는다(스코프 지시서).
 */
function buildPopupContent(spot: SpotCard): string {
  const level = spot.congestion?.level ?? "unknown";
  const levelMeta = LEVEL_BADGE[level] ?? LEVEL_BADGE.unknown;
  const categoryLabel = CATEGORY_LABEL[spot.category] ?? spot.category;
  const matchText = spot.match_score != null ? `매칭 ${Math.round(spot.match_score * 100)}%` : "취향 정보 없음";

  const container = document.createElement("div");
  container.className = "spot-map-popup";

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

  const matchBadge = document.createElement("span");
  matchBadge.className =
    "spot-map-popup__match" + (spot.match_score == null ? " spot-map-popup__match--muted" : "");
  matchBadge.textContent = matchText;
  badgeRow.appendChild(matchBadge);

  container.appendChild(badgeRow);

  // 부록 D §D.7-1과 동일 규약: hidden_id·region_code는 응답값 그대로, 좌표는 싣지 않는다.
  const link = document.createElement("a");
  link.className = "spot-map-popup__link";
  link.href = `/compare?hidden_id=${encodeURIComponent(String(spot.id))}&region_code=${encodeURIComponent(spot.region_code)}`;
  link.textContent = "비교하기 →";
  container.appendChild(link);

  return container.outerHTML;
}

export interface SpotMapProps {
  items: SpotCard[];
  /** 지도 접근성 라벨용. 좌표를 지어내지 않으므로 지역명은 상위(RecommendContent)가 이미 아는 값을 그대로 받는다. */
  regionLabel: string;
}

/**
 * 추천 화면 지도(MVP-6, 01-interface-contract.md 부록 E — 2026-08-24 네이버 지도로 교체).
 * - 리스트가 정본이고 지도는 부가 기능이다: SDK 로드/맵 생성 중 어떤 단계가 실패해도
 *   폴백 문구만 보여주고 예외를 던지지 않는다(§E.3).
 * - congestion.level/match_score 등은 여기서 재판정하지 않고 그대로 표시만 한다(§E.2 재사용).
 */
export default function SpotMap({ items, regionLabel }: SpotMapProps) {
  const mapDivRef = useRef<HTMLDivElement | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mapRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const markersRef = useRef<any[]>([]);
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

  // 지도 인스턴스는 SDK 준비 후 이 div에 1회만 생성한다.
  useEffect(() => {
    if (sdkStatus !== "ready" || !mapDivRef.current || mapRef.current) return;
    try {
      const { naver } = window;
      mapRef.current = new naver.maps.Map(mapDivRef.current, {
        center: new naver.maps.LatLng(KOREA_FALLBACK_CENTER.lat, KOREA_FALLBACK_CENTER.lng),
        zoom: 12,
      });
    } catch {
      // SDK는 로드됐지만 맵 생성 자체가 실패 → 폴백.
      setSdkStatus("error");
    }
  }, [sdkStatus]);

  // 스팟 목록이 바뀔 때마다 마커를 다시 그리고 bounds에 재fit한다(§E.1-4, 지역 전환 연동).
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
    if (infoWindowRef.current) {
      try {
        infoWindowRef.current.close();
      } catch {
        /* noop */
      }
      infoWindowRef.current = null;
    }

    // location 없음/유효 범위 밖 스팟은 마커를 찍지 않는다(좌표를 지어내지 않음, §E.2).
    const validSpots = items.filter((spot) => isValidLatLng(spot.location));
    if (validSpots.length === 0) return;

    try {
      const bounds = new naver.maps.LatLngBounds();

      validSpots.forEach((spot) => {
        const position = new naver.maps.LatLng(spot.location.lat, spot.location.lng);
        bounds.extend(position);

        const level = spot.congestion?.level ?? "unknown";
        const marker = new naver.maps.Marker({
          position,
          icon: {
            url: buildMarkerIconUrl(level, spot.is_hidden_gem),
            size: new naver.maps.Size(28, 38),
            scaledSize: new naver.maps.Size(28, 38),
            anchor: new naver.maps.Point(14, 38),
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
            content: buildPopupContent(spot),
          });
          infoWindowRef.current.open(map, marker);
        });

        markersRef.current.push(marker);
      });

      if (validSpots.length === 1) {
        map.setCenter(new naver.maps.LatLng(validSpots[0].location.lat, validSpots[0].location.lng));
        map.setZoom(15);
      } else {
        map.fitBounds(bounds);
      }
    } catch {
      setSdkStatus("error");
    }
  }, [items, sdkStatus]);

  if (sdkStatus === "error") {
    return (
      <div className="spot-map spot-map--fallback" role="status">
        <p className="spot-map__fallback-msg">지도를 불러오지 못했습니다.</p>
        <p className="spot-map__fallback-hint">아래 목록에서 스팟 정보를 확인해주세요.</p>
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
      <div ref={mapDivRef} className="spot-map__canvas" role="img" aria-label={`${regionLabel} 추천 스팟 지도`} />
    </div>
  );
}
