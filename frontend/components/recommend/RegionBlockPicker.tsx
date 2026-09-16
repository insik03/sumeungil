"use client";

import { useState } from "react";
import { REGION_BLOCKS, RegionBlock } from "../regions/blocks";
import ChipScrollRow from "../ChipScrollRow";
import type { SelectedRegion } from "./RegionPicker";

/**
 * 2026-09-16(대표 지시) — 맞춤추천의 지역 선택을 "검색창 + 시도 17칩"에서 **권역 9개 칩**으로 줄였다
 * (출발일 플래너와 같은 REGION_BLOCKS: 경기·서울 / 강원 / 충북 / 충남·대전·세종 / 전북 / 전남·광주 /
 * 경북·대구 / 경남·부산·울산 / 제주). 각 권역의 대표 시군구 코드를 그대로 region_code 로 넘긴다.
 *
 * "내 위치로 고르기"는 브라우저 Geolocation(대표: "위치정보는 chrome에서 받으면") 으로 좌표를 받아
 * 가장 가까운 권역 중심점을 고른다 — 좌표는 서버로 보내지 않고 이 계산에만 쓴다(개인정보처리방침
 * 위치정보 항목과 동일 원칙). 거부·실패하면 조용히 안내만 하고 기존 선택을 유지한다.
 */
const BLOCK_CENTER: Record<string, { lat: number; lng: number }> = {
  gyeonggi: { lat: 37.5665, lng: 126.978 }, // 서울
  gangwon: { lat: 37.7519, lng: 128.8761 }, // 강릉
  chungbuk: { lat: 36.6424, lng: 127.489 }, // 청주
  chungnam: { lat: 36.3504, lng: 127.3845 }, // 대전
  jeonbuk: { lat: 35.8242, lng: 127.148 }, // 전주
  jeonnam: { lat: 35.1595, lng: 126.8526 }, // 광주
  gyeongbuk: { lat: 35.8714, lng: 128.6014 }, // 대구
  gyeongnam: { lat: 35.1796, lng: 129.0756 }, // 부산
  jeju: { lat: 33.4996, lng: 126.5312 }, // 제주
};

function nearestBlock(lat: number, lng: number): RegionBlock {
  let best = REGION_BLOCKS[0];
  let bestD = Number.POSITIVE_INFINITY;
  for (const b of REGION_BLOCKS) {
    const c = BLOCK_CENTER[b.key];
    if (!c) continue;
    // 위도 1도 ≈ 111km, 경도는 위도 보정 — 국내 거리 비교엔 이 근사로 충분하다.
    const dy = (lat - c.lat) * 111;
    const dx = (lng - c.lng) * 111 * Math.cos((lat * Math.PI) / 180);
    const d = dx * dx + dy * dy;
    if (d < bestD) {
      bestD = d;
      best = b;
    }
  }
  return best;
}

interface RegionBlockPickerProps {
  selected: SelectedRegion;
  onSelect: (region: SelectedRegion) => void;
}

export default function RegionBlockPicker({ selected, onSelect }: RegionBlockPickerProps) {
  const [geoStatus, setGeoStatus] = useState<"idle" | "loading" | "denied" | "unsupported">("idle");

  const pick = (b: RegionBlock) => onSelect({ sigunguCd: b.regionCode, label: b.label });

  const useMyLocation = () => {
    if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
      setGeoStatus("unsupported");
      return;
    }
    setGeoStatus("loading");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setGeoStatus("idle");
        pick(nearestBlock(pos.coords.latitude, pos.coords.longitude));
      },
      () => setGeoStatus("denied"),
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 5 * 60 * 1000 }
    );
  };

  return (
    <div className="spot-region-row">
      <span className="dest-search__quick-label">지역 선택</span>
      <ChipScrollRow>
        <button
          type="button"
          className="chip chip--all"
          onClick={useMyLocation}
          disabled={geoStatus === "loading"}
          aria-label="내 위치로 가까운 권역 고르기"
        >
          {geoStatus === "loading" ? "위치 확인 중…" : "📍 내 위치"}
        </button>
        {REGION_BLOCKS.map((b) => {
          const active = b.regionCode === selected.sigunguCd;
          return (
            <button
              key={b.key}
              type="button"
              className={`chip chip--all${active ? " is-active" : ""}`}
              aria-pressed={active}
              onClick={() => pick(b)}
            >
              {b.label}
            </button>
          );
        })}
      </ChipScrollRow>
      <p className="dest-search__status" aria-live="polite">
        {geoStatus === "denied" && "위치 권한이 없어 직접 골라주세요. 위치는 권역을 고르는 데만 쓰고 저장하지 않아요."}
        {geoStatus === "unsupported" && "이 브라우저는 위치 확인을 지원하지 않아요."}
      </p>
    </div>
  );
}
