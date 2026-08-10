"use client";

import { useEffect, useRef, useState } from "react";
import { SpotCard } from "../../lib/api";
import { CATEGORY_META } from "./constants";

/**
 * Tmap JS API v2 SDK는 타입 선언이 없다(01-interface-contract.md 부록 E.3).
 * window.Tmapv2를 최소한으로 any 선언해 SDK 표면을 그대로 통과시키되,
 * 이 파일 밖으로 any가 새어나가지 않게 이 파일 안에서만 사용한다.
 */
declare global {
  interface Window {
    Tmapv2: any; // eslint-disable-line @typescript-eslint/no-explicit-any
  }
}

const TMAP_SDK_ID = "tmap-sdk-script";
const TMAP_SDK_BASE = "https://apis.openapi.sk.com/tmap/jsv2?version=1&appKey=";
/** 부트스트랩이 실제 SDK 클래스를 채우기까지 기다리는 상한(ms). */
const TMAP_READY_TIMEOUT_MS = 12000;

/** 실제 SDK(Tmapv2.Map 등 클래스)가 로드됐는지 판별. 부트스트랩만 로드된 상태와 구분한다. */
function tmapClassesReady(): boolean {
  const T = typeof window !== "undefined" ? window.Tmapv2 : undefined;
  return !!T && typeof T.Map === "function" && typeof T.LatLng === "function";
}

/**
 * Tmap jsv2 부트스트랩은 실제 SDK(`tmapjs2.min.js`)를 `document.write()`로 주입한다.
 * 페이지 파싱이 끝난 뒤 동적 <script>로 부트스트랩을 붙이면 document.write가 무시되어
 * 실제 클래스(Tmapv2.Map/LatLng…)가 영영 로드되지 않는다. 그래서 부트스트랩이 실행되는
 * 짧은 구간 동안 document.write/writeln을 가로채, 주입하려는 <script src>를 실제 DOM 스크립트로
 * 순서대로 붙여준다. 부트스트랩 <script>(appKey 포함)는 DOM에 그대로 남겨 실제 SDK가 appKey를
 * 찾을 수 있게 한다.
 */
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
    // 부트스트랩이 부르는 write/writeln만 가로챈다.
    document.write = capture as typeof document.write;
    document.writeln = capture as typeof document.writeln;

    const restore = () => {
      document.write = originalWrite;
      document.writeln = originalWriteln;
    };

    // 이 shim이 DOM에 붙인 스크립트들(부트스트랩 + 캡처한 실 SDK). 실패 시 전부 걷어낸다.
    const appendedScripts: HTMLScriptElement[] = [];
    let settled = false;
    let bootstrapWatchdog = 0;

    // 실패 정리: document.write 복원 + stale 스크립트 제거(재마운트 시 "existing" 폴링 함정 방지, QA M6-1)
    // + 워치독 해제. 반드시 모든 reject 경로가 이걸 통과한다.
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

    // 캡처한 실제 SDK 스크립트들을 순서대로(async=false) 붙인다.
    const appendCaptured = (idx: number) => {
      if (settled) return;
      if (idx >= capturedSrcs.length) {
        waitForReady();
        return;
      }
      const real = document.createElement("script");
      real.src = capturedSrcs[idx];
      real.async = false; // 실행 순서 보존
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
      restore(); // 부트스트랩 실행 종료 → write 가로채기는 여기서 끝(이후 실 SDK는 정상 append)
      if (capturedSrcs.length === 0) {
        // 부트스트랩이 아무 것도 write하지 않았다면(이미 로드됨 등) 클래스 유무로 판단.
        if (tmapClassesReady()) succeed();
        else fail("tmap bootstrap injected no sdk script");
        return;
      }
      appendCaptured(0);
    };
    bootstrap.onerror = () => fail("tmap sdk bootstrap load error");
    // 워치독: 부트스트랩 network hang 시 onload/onerror가 영영 안 와 document.write가
    // 패치된 채 남는 것을 방지(QA M6-2). 상한 초과 시 fail로 복원+정리한다.
    bootstrapWatchdog = window.setTimeout(
      () => fail("tmap sdk bootstrap load timeout"),
      TMAP_READY_TIMEOUT_MS
    );
    appendedScripts.push(bootstrap);
    document.head.appendChild(bootstrap);
  });
}

/** SDK/맵 생성 실패 시 폴백에서 쓸 대한민국 중앙 근사값(마커가 하나도 없을 때만 사용, §E.3 폴백과 별개). */
const KOREA_FALLBACK_CENTER = { lat: 36.5, lng: 127.8 };

type SdkStatus = "loading" | "ready" | "error";

/**
 * 모듈 스코프의 로딩 Promise. 여러 SpotMap 인스턴스/리렌더가 동시에 <script>를
 * 중복 주입하지 않게 한 번만 로드한다(부록 E.3: "클라이언트에서 동적 <script> 주입 1회").
 */
let sdkLoadPromise: Promise<void> | null = null;

function loadTmapSdk(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("no window"));
  }
  // 이미 실제 클래스까지 로드된 경우에만 즉시 통과(부트스트랩만 뜬 상태를 ready로 오인하지 않는다).
  if (tmapClassesReady()) {
    return Promise.resolve();
  }
  if (sdkLoadPromise) {
    return sdkLoadPromise;
  }

  const appKey = process.env.NEXT_PUBLIC_TMAP_APP_KEY;
  if (!appKey) {
    // 서버 시크릿과 혼동 금지 — NEXT_PUBLIC_ 키가 없으면 애초에 SDK를 부르지 않는다(부록 E.3).
    return Promise.reject(new Error("NEXT_PUBLIC_TMAP_APP_KEY가 설정되지 않았습니다."));
  }

  const bootstrapSrc = `${TMAP_SDK_BASE}${encodeURIComponent(appKey)}`;

  sdkLoadPromise = (async () => {
    // 이미 부트스트랩 <script>가 붙어 있으면(다른 인스턴스가 진행 중) 클래스 준비만 폴링한다.
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
 * 추천 화면 지도(MVP-6, 01-interface-contract.md 부록 E).
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

  // 지도 인스턴스는 SDK 준비 후 이 div에 1회만 생성한다.
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
      // SDK는 로드됐지만 맵 생성 자체가 실패(도메인 미등록 등 실질적으로 여기서도 터질 수 있음) → 폴백.
      setSdkStatus("error");
    }
  }, [sdkStatus]);

  // 스팟 목록이 바뀔 때마다 마커를 다시 그리고 bounds에 재fit한다(§E.1-4, 지역 전환 연동).
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
    if (infoWindowRef.current) {
      try {
        infoWindowRef.current.setMap(null);
      } catch {
        /* noop */
      }
      infoWindowRef.current = null;
    }

    // location 없음/유효 범위 밖 스팟은 마커를 찍지 않는다(좌표를 지어내지 않음, §E.2).
    const validSpots = items.filter((spot) => isValidLatLng(spot.location));
    if (validSpots.length === 0) return;

    try {
      const bounds = new Tmapv2.LatLngBounds();

      validSpots.forEach((spot) => {
        const position = new Tmapv2.LatLng(spot.location.lat, spot.location.lng);
        bounds.extend(position);

        const level = spot.congestion?.level ?? "unknown";
        const marker = new Tmapv2.Marker({
          position,
          icon: buildMarkerIconUrl(level, spot.is_hidden_gem),
          iconSize: new Tmapv2.Size(28, 38),
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
            content: buildPopupContent(spot),
            type: 2,
            map,
          });
        });

        markersRef.current.push(marker);
      });

      if (validSpots.length === 1) {
        map.setCenter(new Tmapv2.LatLng(validSpots[0].location.lat, validSpots[0].location.lng));
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
