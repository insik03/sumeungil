"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { FeaturedSpot } from "../../lib/api";
import ChipScrollRow from "../ChipScrollRow";
import { SIDO_REGIONS, SidoRegion } from "../regions/constants";
import styles from "./DemoHome.module.css";

type Coordinate = [number, number];

interface MapBounds {
  minLng: number;
  minLat: number;
  maxLng: number;
  maxLat: number;
}

interface DistrictBoundary {
  sourceCode: string;
  regionCode: string | null;
  nameKo: string;
  nameEng: string;
  rings: Coordinate[][];
}

interface RegionMapAsset {
  version: number;
  source: string;
  sidoCode: string;
  nameKo: string;
  nameEng: string;
  bounds: MapBounds;
  outerRing: Coordinate[];
  districts: DistrictBoundary[];
}

/**
 * 지도가 실제로 쓰는 스팟 필드만 뽑은 최소 타입(2026-09-04). FeaturedSpot(홈·추천의 featured 픽)과
 * CourseSpot(AI 코스 결과, SpotCard 확장)이 둘 다 이 모양을 만족해 같은 지도에 그릴 수 있다 —
 * 대표 지시 "추천 경로도 AI 코스랑 같이": 코스 화면에서는 featured 대신 실제 코스 스팟을 잇는다.
 */
export type RouteSpot = Pick<FeaturedSpot, "id" | "name" | "location" | "congestion">;

interface RegionRouteMapProps {
  selectedSido: SidoRegion;
  spots: RouteSpot[];
  spotsLoading: boolean;
  /** 경로로 이을 최대 스팟 수. 기본 3(홈·추천의 "대표 3곳"). AI 코스는 코스 길이만큼 넘긴다. */
  maxStops?: number;
  onSelectSido: (sido: SidoRegion) => void;
  /**
   * 실제 홈 임베드용(대표 지시 2026-08-29 — 데모와 원래 홈을 자연스럽게 합치기). 이 컴포넌트를
   * 품는 화면이 이미 자체 지역 선택 UI(Hero.tsx의 검색바+시도 칩)를 갖고 있으면 내부 도시
   * 선택 칩을 중복 노출하지 않는다 — 지도는 그 선택을 그대로 반영만 한다.
   */
  hidePicker?: boolean;
}

interface ProjectedStop {
  spot: RouteSpot;
  x: number;
  y: number;
  labelWidth: number;
  labelOnLeft: boolean;
  labelOffsetY: number;
}

const MAP_WIDTH = 620;
const MAP_HEIGHT = 660;
const MAP_LEFT = 52;
const MAP_RIGHT = 48;
// 데모 홈 단독 사용(도시선택 칩바+제목 두 줄이 위쪽을 차지)일 때의 여백. 실제 홈 임베드는
// hidePicker라 칩바가 없고 제목도 한 줄로 압축돼(CSS top:22px) 그만큼 덜 필요하다 —
// 그대로 두면 지도 모양이 카드 안에서 작게 붕 뜬 것처럼 보인다(대표 지적 2026-08-29
// "히어로 배너랑 지도 위치 부자연스럽다" 재작업).
const MAP_TOP = 132;
const MAP_TOP_COMPACT = 56;
const MAP_BOTTOM = 62;
const MAP_BOTTOM_COMPACT = 34;

function createProjector(bounds: MapBounds, compact: boolean) {
  const midLat = (bounds.minLat + bounds.maxLat) / 2;
  const lngScale = Math.cos((midLat * Math.PI) / 180);
  const minX = bounds.minLng * lngScale;
  const maxX = bounds.maxLng * lngScale;
  const geoWidth = Math.max(maxX - minX, Number.EPSILON);
  const geoHeight = Math.max(bounds.maxLat - bounds.minLat, Number.EPSILON);
  const top = compact ? MAP_TOP_COMPACT : MAP_TOP;
  const bottom = compact ? MAP_BOTTOM_COMPACT : MAP_BOTTOM;
  const availableWidth = MAP_WIDTH - MAP_LEFT - MAP_RIGHT;
  const availableHeight = MAP_HEIGHT - top - bottom;
  const scale = Math.min(availableWidth / geoWidth, availableHeight / geoHeight);
  const offsetX = MAP_LEFT + (availableWidth - geoWidth * scale) / 2;
  const offsetY = top + (availableHeight - geoHeight * scale) / 2;

  return ([lng, lat]: Coordinate) => ({
    x: offsetX + (lng * lngScale - minX) * scale,
    y: offsetY + (bounds.maxLat - lat) * scale,
  });
}

function ringPath(ring: Coordinate[], project: ReturnType<typeof createProjector>): string {
  return ring
    .map((coordinate, index) => {
      const point = project(coordinate);
      return `${index === 0 ? "M" : "L"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`;
    })
    .join(" ") + " Z";
}

function hasUsableLocation(spot: RouteSpot): boolean {
  const location = spot.location;
  return !!location && Number.isFinite(location.lat) && Number.isFinite(location.lng);
}

function isInsideBounds(spot: RouteSpot, bounds: MapBounds): boolean {
  if (!hasUsableLocation(spot)) return false;
  const { lat, lng } = spot.location;
  return lat >= bounds.minLat && lat <= bounds.maxLat && lng >= bounds.minLng && lng <= bounds.maxLng;
}

function shortMapLabel(name: string): string {
  return name.length > 13 ? `${name.slice(0, 12)}…` : name;
}


export default function RegionRouteMap({
  selectedSido,
  spots,
  spotsLoading,
  onSelectSido,
  hidePicker = false,
  maxStops = 3,
}: RegionRouteMapProps) {
  const [asset, setAsset] = useState<RegionMapAsset | null>(null);
  const [mapStatus, setMapStatus] = useState<"loading" | "ready" | "error">("loading");
  const rawId = useId().replace(/:/g, "");
  const gridId = `region-map-grid-${rawId}`;
  const clipId = `region-map-clip-${rawId}`;

  useEffect(() => {
    const controller = new AbortController();
    setAsset(null);
    setMapStatus("loading");
    fetch(`/data/region-maps/${selectedSido.sidoCode}.json`, {
      signal: controller.signal,
      cache: "force-cache",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`region map ${response.status}`);
        return (await response.json()) as RegionMapAsset;
      })
      .then((nextAsset) => {
        if (controller.signal.aborted) return;
        setAsset(nextAsset);
        setMapStatus("ready");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setMapStatus("error");
      });
    return () => controller.abort();
  }, [selectedSido.sidoCode]);

  const geometry = useMemo(() => {
    if (!asset) return null;
    const project = createProjector(asset.bounds, hidePicker);
    const outerPath = ringPath(asset.outerRing, project);
    const districtPaths = asset.districts.flatMap((district) =>
      district.rings.map((ring, ringIndex) => ({
        key: `${district.sourceCode}-${ringIndex}`,
        path: ringPath(ring, project),
      }))
    );
    const routeStops = spots.filter((spot) => isInsideBounds(spot, asset.bounds)).slice(0, Math.max(1, maxStops));
    const projectedStops: ProjectedStop[] = routeStops.map((spot, index) => {
      const point = project([spot.location.lng, spot.location.lat]);
      return {
        spot,
        ...point,
        labelWidth: Math.min(164, Math.max(72, shortMapLabel(spot.name).length * 11 + 18)),
        labelOnLeft: point.x > MAP_WIDTH * 0.66,
        // 실제 좌표가 밀집한 도심에서도 라벨이 한 줄에 포개지지 않도록 번호별로 엇갈린다
        // (0·위·아래 를 3개 주기로 반복 — 코스가 3곳을 넘어도 같은 규칙).
        labelOffsetY: index % 3 === 1 ? -34 : index % 3 === 2 ? 34 : 0,
      };
    });
    const routePath = projectedStops
      .map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
      .join(" ");
    return { outerPath, districtPaths, projectedStops, routePath };
  }, [asset, spots, hidePicker, maxStops]);

  const routeNames = geometry?.projectedStops.map((point) => point.spot.name) ?? [];
  const mapSummary = routeNames.length
    ? `${selectedSido.shortName}의 시군구 경계 안에서 ${routeNames.join(", ")} 순서로 이어지는 추천 경로`
    : `${selectedSido.shortName} 시도 외곽선과 시군구 경계 지도. 표시할 수 있는 추천 스팟 좌표가 없습니다.`;

  return (
    <figure
      className={`${styles.routeStage}${hidePicker ? ` ${styles.routeStageBare}` : ""}`}
      aria-label={mapSummary}
    >
      {!hidePicker && (
        <div className={styles.cityPicker} aria-label="지도 지역 선택">
          <span>지도 지역</span>
          <ChipScrollRow>
            {SIDO_REGIONS.map((sido) => {
              const active = sido.sidoCode === selectedSido.sidoCode;
              return (
                <button
                  key={sido.sidoCode}
                  type="button"
                  className={`chip chip--all ${styles.cityChip}${active ? ` is-active ${styles.cityChipActive}` : ""}`}
                  aria-pressed={active}
                  onClick={() => onSelectSido(sido)}
                >
                  {sido.shortName}
                </button>
              );
            })}
          </ChipScrollRow>
        </div>
      )}

      {/* 2026-09-05(대표 "추천경로 텍스트 박스가 지도를 가린다") — 지도 위에 얹혀 있던 제목 박스
          (지역·시군구 수·경로 라벨)와 하단 캡션(무드·스팟 수)을 뺐다. 지도는 그림만, 설명은
          스크린리더용 figcaption 이 계속 맡는다. */}
      <svg className={styles.regionMap} viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`} aria-hidden="true">
        <defs>
          <pattern id={gridId} width="22" height="22" patternUnits="userSpaceOnUse">
            <path d="M22 0H0V22" className={styles.mapGrid} />
          </pattern>
          {geometry && (
            <clipPath id={clipId}>
              <path d={geometry.outerPath} />
            </clipPath>
          )}
        </defs>
        <rect width={MAP_WIDTH} height={MAP_HEIGHT} fill={`url(#${gridId})`} />

        {geometry && (
          <>
            <path className={styles.mapRegion} d={geometry.outerPath} />
            <g className={styles.mapBoundaries} clipPath={`url(#${clipId})`}>
              {geometry.districtPaths.map((district) => (
                <path key={district.key} d={district.path} />
              ))}
            </g>
            <path className={styles.mapCoast} d={geometry.outerPath} />
            {geometry.routePath && <path className={styles.routeLine} d={geometry.routePath} />}
            {geometry.projectedStops.map((point, index) => {
              const labelX = point.labelOnLeft ? -point.labelWidth - 23 : 23;
              const leaderX = point.labelOnLeft ? -23 : 23;
              return (
                <g
                  key={point.spot.id}
                  className={styles.mapPin}
                  transform={`translate(${point.x.toFixed(2)} ${point.y.toFixed(2)})`}
                >
                  {point.labelOffsetY !== 0 && (
                    <line
                      className={styles.mapPinLeader}
                      x1={point.labelOnLeft ? -14 : 14}
                      y1="0"
                      x2={leaderX}
                      y2={point.labelOffsetY}
                    />
                  )}
                  <rect
                    className={styles.mapPinLabel}
                    x={labelX}
                    y={point.labelOffsetY - 14}
                    width={point.labelWidth}
                    height="28"
                    rx="3"
                  />
                  <text className={styles.mapPinName} x={labelX + 9} y={point.labelOffsetY + 4}>
                    {shortMapLabel(point.spot.name)}
                  </text>
                  <circle r="16" />
                  <text className={styles.mapPinNumber} textAnchor="middle" y="4">
                    {index + 1}
                  </text>
                </g>
              );
            })}
          </>
        )}
      </svg>

      {/* 2026-09-18 대표 지시("이거도 좀 없애줄래") — 지도 위에 얹히던 상태 박스("…불러오는 중", "불러오지
          못했어요")를 뺐다. 로딩 중엔 경계만, 실패 시엔 빈 격자만 보인다 — 설명은 figcaption(스크린리더)이 맡는다. */}

      {/* 2026-09-14 대표 지시 — 좌하단 "추천 경로 01" 카드 제거(지도를 가림). */}
      <figcaption className={styles.srOnly}>{mapSummary}</figcaption>
    </figure>
  );
}
