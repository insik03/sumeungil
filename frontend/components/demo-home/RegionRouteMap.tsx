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

interface RegionRouteMapProps {
  selectedSido: SidoRegion;
  spots: FeaturedSpot[];
  spotsLoading: boolean;
  mood: string;
  onSelectSido: (sido: SidoRegion) => void;
}

interface ProjectedStop {
  spot: FeaturedSpot;
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
const MAP_TOP = 132;
const MAP_BOTTOM = 62;

function createProjector(bounds: MapBounds) {
  const midLat = (bounds.minLat + bounds.maxLat) / 2;
  const lngScale = Math.cos((midLat * Math.PI) / 180);
  const minX = bounds.minLng * lngScale;
  const maxX = bounds.maxLng * lngScale;
  const geoWidth = Math.max(maxX - minX, Number.EPSILON);
  const geoHeight = Math.max(bounds.maxLat - bounds.minLat, Number.EPSILON);
  const availableWidth = MAP_WIDTH - MAP_LEFT - MAP_RIGHT;
  const availableHeight = MAP_HEIGHT - MAP_TOP - MAP_BOTTOM;
  const scale = Math.min(availableWidth / geoWidth, availableHeight / geoHeight);
  const offsetX = MAP_LEFT + (availableWidth - geoWidth * scale) / 2;
  const offsetY = MAP_TOP + (availableHeight - geoHeight * scale) / 2;

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

function hasUsableLocation(spot: FeaturedSpot): boolean {
  const location = spot.location;
  return !!location && Number.isFinite(location.lat) && Number.isFinite(location.lng);
}

function isInsideBounds(spot: FeaturedSpot, bounds: MapBounds): boolean {
  if (!hasUsableLocation(spot)) return false;
  const { lat, lng } = spot.location;
  return lat >= bounds.minLat && lat <= bounds.maxLat && lng >= bounds.minLng && lng <= bounds.maxLng;
}

function shortMapLabel(name: string): string {
  return name.length > 13 ? `${name.slice(0, 12)}…` : name;
}

function congestionText(spot: FeaturedSpot): string {
  const index = spot.congestion?.index;
  if (index != null) return `예상 혼잡 ${Math.round(index)}%`;
  const labels: Record<string, string> = { low: "여유", mid: "보통", high: "혼잡" };
  return labels[spot.congestion?.level ?? ""] ?? "혼잡 정보 없음";
}

export default function RegionRouteMap({
  selectedSido,
  spots,
  spotsLoading,
  mood,
  onSelectSido,
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
    const project = createProjector(asset.bounds);
    const outerPath = ringPath(asset.outerRing, project);
    const districtPaths = asset.districts.flatMap((district) =>
      district.rings.map((ring, ringIndex) => ({
        key: `${district.sourceCode}-${ringIndex}`,
        path: ringPath(ring, project),
      }))
    );
    const routeStops = spots.filter((spot) => isInsideBounds(spot, asset.bounds)).slice(0, 3);
    const projectedStops: ProjectedStop[] = routeStops.map((spot, index) => {
      const point = project([spot.location.lng, spot.location.lat]);
      return {
        spot,
        ...point,
        labelWidth: Math.min(164, Math.max(72, shortMapLabel(spot.name).length * 11 + 18)),
        labelOnLeft: point.x > MAP_WIDTH * 0.66,
        // 실제 좌표가 밀집한 도심에서도 세 라벨이 한 줄에 포개지지 않도록 번호별로 엇갈린다.
        labelOffsetY: index === 1 ? -34 : index === 2 ? 34 : 0,
      };
    });
    const routePath = projectedStops
      .map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
      .join(" ");
    return { outerPath, districtPaths, projectedStops, routePath };
  }, [asset, spots]);

  const routeNames = geometry?.projectedStops.map((point) => point.spot.name) ?? [];
  const mapSummary = routeNames.length
    ? `${selectedSido.shortName}의 시군구 경계 안에서 ${routeNames.join(", ")} 순서로 이어지는 추천 경로`
    : `${selectedSido.shortName} 시도 외곽선과 시군구 경계 지도. 표시할 수 있는 추천 스팟 좌표가 없습니다.`;
  const leadStop = geometry?.projectedStops[0]?.spot;

  return (
    <figure className={styles.routeStage} aria-label={mapSummary}>
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

      <div className={styles.mapHeading} aria-hidden="true">
        <span>
          {selectedSido.shortName}
          {asset ? ` · 시군구 ${asset.districts.length}곳` : " · 경계 불러오는 중"}
        </span>
        <b>{routeNames.length > 1 ? "실좌표로 잇는 추천 경로" : "실제 행정 경계를 따라 보기"}</b>
      </div>

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

      {(mapStatus === "loading" || spotsLoading) && (
        <div className={styles.mapState} aria-live="polite">
          {selectedSido.shortName} 경계와 추천 스팟을 불러오는 중…
        </div>
      )}
      {mapStatus === "error" && (
        <div className={styles.mapState} role="status">
          경계 지도를 불러오지 못했어요.
        </div>
      )}

      {leadStop && (
        <div className={styles.hotspot} aria-hidden="true">
          <span>추천 경로 01</span>
          <strong>{leadStop.name}</strong>
          <small>{congestionText(leadStop)}</small>
        </div>
      )}
      <p className={styles.routeCaption} aria-hidden="true">
        <b>{mood}</b>에 맞춘
        <br />
        {routeNames.length ? `실제 스팟 ${routeNames.length}곳` : "좌표 있는 스팟을 찾는 중"}
      </p>
      <figcaption className={styles.srOnly}>{mapSummary}</figcaption>
    </figure>
  );
}
