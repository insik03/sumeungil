"use client";

import { useEffect, useRef, useState } from "react";
import { CourseLeg, CourseSpot } from "../../lib/api";
import { CATEGORY_META } from "../recommend/constants";

/**
 * Tmap JS API v2 SDK는 타입 선언이 없다 — SpotMap.tsx와 동일하게 window.Tmapv2를 최소 any로
 * 선언해 SDK 표면만 통과시키고, any는 이 파일 밖으로 새어나가지 않게 한다.
 * SpotMap.tsx는 지시서상 수정 대상이 아니라서(읽기 전용) 아래 SDK 로딩 shim은
 * SpotMap.tsx의 loadTmapSdk/loadRealSdkViaWriteShim 패턴을 그대로 참고해 이 파일 안에서 재구현했다
 * (모듈 스코프 로딩 promise를 공용 유틸로 뽑으면 SpotMap.tsx도 같이 고쳐야 해서 이번 스코프에서는 분리 유지).
 */
declare global {
  interface Window {
    Tmapv2: any; // eslint-disable-line @typescript-eslint/no-explicit-any
  }
}

const TMAP_SDK_ID = "tmap-sdk-script";
const TMAP_SDK_BASE = "https://apis.openapi.sk.com/tmap/jsv2?version=1&appKey=";
const TMAP_READY_TIMEOUT_MS = 12000;

function tmapClassesReady(): boolean {
  const T = typeof window !== "undefined" ? window.Tmapv2 : undefined;
  return !!T && typeof T.Map === "function" && typeof T.LatLng === "function";
}

function loadRealSdkViaWriteShim(bootstrapSrc: string): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const capturedSrcs: string[] = [];
    // eslint-disable-next-line @typescript-eslint/unbound-method
    const originalWrite = document.write;
    // eslint-disable-next-line @typescript-eslint/unbound-method
    const originalWriteln = document.writeln;

    const capture = (markup: string) => {
      const re = /<script[^>]+src=['"]([^'"]+)['"]/gi;
      let m: RegExpExecArray | null;
      while ((m = re.exec(markup)) !== null) capturedSrcs.push(m[1]);
    };
    document.write = capture as typeof document.write;
    document.writeln = capture as typeof document.writeln;

    const restore = () => {
      document.write = originalWrite;
      document.writeln = originalWriteln;
    };

    const appendedScripts: HTMLScriptElement[] = [];
    let settled = false;
    let bootstrapWatchdog = 0;

    const fail = (msg: string) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(bootstrapWatchdog);
      restore();
      appendedScripts.forEach((s) => {
        try {
          s.remove();
        } catch {
          /* noop */
        }
      });
      reject(new Error(msg));
    };
    const succeed = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(bootstrapWatchdog);
      restore();
      resolve();
    };

    const waitForReady = () => {
      const start = Date.now();
      const tick = () => {
        if (settled) return;
        if (tmapClassesReady()) {
          succeed();
        } else if (Date.now() - start > TMAP_READY_TIMEOUT_MS) {
          fail("tmap sdk classes not ready (timeout)");
        } else {
          window.setTimeout(tick, 100);
        }
      };
      tick();
    };

    const appendCaptured = (idx: number) => {
      if (settled) return;
      if (idx >= capturedSrcs.length) {
        waitForReady();
        return;
      }
      const real = document.createElement("script");
      real.src = capturedSrcs[idx];
      real.async = false;
      real.onload = () => appendCaptured(idx + 1);
      real.onerror = () => fail("tmap real sdk load error");
      appendedScripts.push(real);
      document.head.appendChild(real);
    };

    const bootstrap = document.createElement("script");
    bootstrap.id = TMAP_SDK_ID;
    bootstrap.src = bootstrapSrc;
    bootstrap.async = true;
    bootstrap.onload = () => {
      if (settled) return;
      window.clearTimeout(bootstrapWatchdog);
      restore();
      if (capturedSrcs.length === 0) {
        if (tmapClassesReady()) succeed();
        else fail("tmap bootstrap injected no sdk script");
        return;
      }
      appendCaptured(0);
    };
    bootstrap.onerror = () => fail("tmap sdk bootstrap load error");
    bootstrapWatchdog = window.setTimeout(
      () => fail("tmap sdk bootstrap load timeout"),
      TMAP_READY_TIMEOUT_MS
    );
    appendedScripts.push(bootstrap);
    document.head.appendChild(bootstrap);
  });
}

const KOREA_FALLBACK_CENTER = { lat: 36.5, lng: 127.8 };

type SdkStatus = "loading" | "ready" | "error";

let sdkLoadPromise: Promise<void> | null = null;

function loadTmapSdk(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("no window"));
  }
  if (tmapClassesReady()) {
    return Promise.resolve();
  }
  if (sdkLoadPromise) {
    return sdkLoadPromise;
  }

  const appKey = process.env.NEXT_PUBLIC_TMAP_APP_KEY;
  if (!appKey) {
    return Promise.reject(new Error("NEXT_PUBLIC_TMAP_APP_KEY가 설정되지 않았습니다."));
  }

  const bootstrapSrc = `${TMAP_SDK_BASE}${encodeURIComponent(appKey)}`;

  sdkLoadPromise = (async () => {
    const existing = document.getElementById(TMAP_SDK_ID);
    if (existing) {
      const start = Date.now();
      while (!tmapClassesReady()) {
        if (Date.now() - start > TMAP_READY_TIMEOUT_MS) {
          throw new Error("tmap sdk classes not ready (timeout, shared)");
        }
        await new Promise((r) => window.setTimeout(r, 100));
      }
      return;
    }
    await loadRealSdkViaWriteShim(bootstrapSrc);
  })().catch((err) => {
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
    loadTmapSdk()
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
      const { Tmapv2 } = window;
      mapRef.current = new Tmapv2.Map(mapDivRef.current, {
        center: new Tmapv2.LatLng(KOREA_FALLBACK_CENTER.lat, KOREA_FALLBACK_CENTER.lng),
        width: "100%",
        height: "100%",
        zoom: 12,
      });
    } catch {
      setSdkStatus("error");
    }
  }, [sdkStatus]);

  // 스팟/구간이 바뀔 때마다 마커+경로선을 다시 그리고 bounds에 재fit한다.
  useEffect(() => {
    if (sdkStatus !== "ready" || !mapRef.current) return;
    const { Tmapv2 } = window;
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
        infoWindowRef.current.setMap(null);
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
      const bounds = new Tmapv2.LatLngBounds();

      validEntries.forEach(({ spot, order }) => {
        const position = new Tmapv2.LatLng(spot.location.lat, spot.location.lng);
        bounds.extend(position);

        const level = spot.congestion?.level ?? "unknown";
        const marker = new Tmapv2.Marker({
          position,
          icon: buildOrderMarkerIconUrl(order, level),
          iconSize: new Tmapv2.Size(34, 34),
          map,
        });

        marker.addListener("click", () => {
          if (infoWindowRef.current) {
            try {
              infoWindowRef.current.setMap(null);
            } catch {
              /* noop */
            }
          }
          infoWindowRef.current = new Tmapv2.InfoWindow({
            position,
            content: buildPopupContent(spot, order),
            type: 2,
            map,
          });
        });

        markersRef.current.push(marker);
      });

      // legs[].path 좌표는 [lng, lat](WGS84) — Tmapv2.LatLng은 (lat, lng) 순서라 뒤집어서 넣는다.
      // path가 null인 구간(Tmap 실패)은 그리지 않는다(지어내지 않음, 타임라인의 "이동 정보 없음"과 일관).
      legs.forEach((leg) => {
        if (!leg.path || leg.path.length < 2) return;
        const linePath = leg.path.map((coord) => new Tmapv2.LatLng(coord[1], coord[0]));
        linePath.forEach((p: unknown) => bounds.extend(p));
        const polyline = new Tmapv2.Polyline({
          path: linePath,
          strokeColor: "#2b82ee",
          strokeWeight: 5,
          strokeOpacity: 0.85,
          map,
        });
        polylinesRef.current.push(polyline);
      });

      if (validEntries.length === 1) {
        map.setCenter(new Tmapv2.LatLng(validEntries[0].spot.location.lat, validEntries[0].spot.location.lng));
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
