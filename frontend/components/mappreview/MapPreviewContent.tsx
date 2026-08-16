"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  NationwideCongestionItem,
  NationwideCongestionResponse,
  fetchFeatured,
  fetchNationwideCongestion,
  fetchSpotDetail,
} from "../../lib/api";
import CongestionBoard from "../CongestionBoard";
import { loadLastRegion, saveLastRegion } from "../../lib/lastRegionStorage";
import { SIDO_REGIONS } from "../regions/constants";
import KoreaSvgMap from "./KoreaSvgMap";
import NationwideBoard from "./NationwideBoard";
import { LANDMARKS } from "./landmarks";
import { LEVEL_TEXT } from "./shared";


/**
 * 전국 지도 화면 (부록 U, 2026-08-01 대표 지시).
 *
 * 왼쪽: 실제 행정구역 경계 SVG 지도 — 시·도를 예상 혼잡도로 칠한다(전국을 한눈에).
 * 오른쪽: 고른 시·도의 **Tmap 실지도** + 그 지역 관광지 마커(정확한 위치 확인).
 * → "전국은 한눈에, 상세는 실지도로"라는 대표 결정을 그대로 구현한 것.
 */
export default function MapPreviewContent() {
  const [data, setData] = useState<NationwideCongestionResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // 대표 지시(2026-08-17) — 이 화면도 마지막으로 고른 지역을 기본값으로 시작한다(지도가
  // 처음부터 그 시·도를 골라둔 채로 열림). SSR/첫 클라이언트 렌더는 중립값(null)으로
  // 맞추고(sessionStorage는 서버에서 못 읽음 — 하이드레이션 불일치 실측으로 확인된 버그
  // 재발 방지) mount 후 effect에서 반영한다.
  const [selected, setSelectedState] = useState<string | null>(null);
  useEffect(() => {
    const last = loadLastRegion()?.area_cd;
    if (last) setSelectedState(last);
  }, []);
  const handleSelect = (sidoCode: string) => {
    setSelectedState(sidoCode);
    const sido = SIDO_REGIONS.find((s) => s.sidoCode === sidoCode);
    if (sido) {
      saveLastRegion({
        region_id: `sido-${sido.sidoCode}`,
        label: sido.representativeLabel,
        area_cd: sido.sidoCode,
        sigungu_cd: sido.regionCode,
      });
    }
  };
  /** 추천 숨은 명소. null=로딩 전/중, "none"=이 지역엔 없음, 객체=표시할 내용. */
  const [hidden, setHidden] = useState<
    { name: string; image_url: string | null; address: string | null; summary: string | null } | "none" | null
  >(null);
  const [hiddenErr, setHiddenErr] = useState<string | null>(null);

  useEffect(() => {
    const c = new AbortController();
    fetchNationwideCongestion(c.signal)
      .then(setData)
      .catch((e: unknown) => {
        if (c.signal.aborted) return;
        setErr(e instanceof Error ? e.message : String(e));
      });
    return () => c.abort();
  }, []);

  const items: NationwideCongestionItem[] = data?.items ?? [];
  const picked = items.find((i) => i.sido_code === selected) ?? null;

  // 부록 U.4 — 지역을 고르면 **가장 추천할 숨은 명소 한 곳**을 사진·한 줄 소개와 함께 가져온다.
  //  1) /places/featured 의 hidden_picks 에서 **사진 있는 첫 곳**을 고른다(사진이 이 카드의 핵심).
  //  2) 그 스팟의 상세를 불러 `ai_summary` 첫 줄을 한 줄 소개로 쓴다.
  //     요약은 사전 생성분(spot_summaries.json)이라 대부분 즉시 나오고, 없으면 null 이다 —
  //     **없는 소개를 지어내지 않는다**(그 경우 주소만 적는다).
  useEffect(() => {
    if (!picked) {
      setHidden(null);
      return;
    }
    const c = new AbortController();
    setHidden(null);
    setHiddenErr(null);
    (async () => {
      try {
        const f = await fetchFeatured(picked.region_code, 8, c.signal);
        const pick =
          (f.hidden_picks ?? []).find((s) => s.image_url) ?? (f.hidden_picks ?? [])[0];
        if (!pick) {
          setHidden("none");
          return;
        }
        let summary: string | null = null;
        try {
          const detail = await fetchSpotDetail(pick.id, c.signal);
          summary = (detail.ai_summary ?? "").split("\n")[0].trim() || null;
        } catch {
          summary = null; // 소개글 실패는 카드 자체를 막지 않는다
        }
        if (c.signal.aborted) return;
        setHidden({
          name: pick.name,
          image_url: pick.image_url ?? null,
          address: pick.address ?? null,
          summary,
        });
      } catch (e: unknown) {
        if (c.signal.aborted) return;
        setHiddenErr("숨은 명소를 불러오지 못했어요.");
      }
    })();
    return () => c.abort();
  }, [picked]);

  return (
    <section className="section" style={{ maxWidth: 1560, margin: "0 auto" }}>
      <span className="eyebrow-pill eyebrow-pill--coral">전국 혼잡 지도</span>
      <h1 className="section__title">지금 전국, 어디가 붐빌까요?</h1>
      <p style={{ opacity: 0.85, margin: "0 0 6px" }}>
        시·도를 눌러보세요. 그 지역 실제 지도와 관광지를 보여드려요.
      </p>
      {err && <p style={{ color: "#b3261e" }}>데이터를 불러오지 못했어요: {err}</p>}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(420px, 1010px) minmax(300px, 1fr)",
          gap: 24,
          alignItems: "start",
        }}
      >
        <div style={{ border: "1px solid #e3e8ee", borderRadius: 20, padding: 16 }}>
          {items.length > 0 ? (
            <KoreaSvgMap items={items} selected={selected} onSelect={handleSelect} />
          ) : (
            <p>불러오는 중…</p>
          )}
        </div>

        <div style={{ border: "1px solid #e3e8ee", borderRadius: 20, padding: 16, minHeight: 420 }}>
          {!picked && (
            <p style={{ opacity: 0.75 }}>
              왼쪽 지도에서 시·도를 선택하면 그 지역 지도가 여기에 나와요.
            </p>
          )}
          {picked && (
            <>
              {/* 클릭하면 **랜드마크가 제일 먼저** 보이게 한다(대표 지시).
                  배경은 그 지역의 **실제 관광 사진**(한국관광공사 TourAPI). 사진에 찍힌 곳의
                  이름을 하단에 그대로 밝힌다 — 랜드마크 그림과 사진이 다른 곳일 수 있어서,
                  "이 사진이 곧 그 랜드마크"라고 오해하게 두지 않는다. */}
              <div
                style={{
                  position: "relative",
                  borderRadius: 16,
                  overflow: "hidden",
                  marginBottom: 12,
                  background: picked.photo_url
                    ? `center/cover no-repeat url(${JSON.stringify(picked.photo_url)})`
                    : "linear-gradient(135deg,#dff0f7,#eef5f9)",
                  minHeight: 190,
                  display: "flex",
                  alignItems: "flex-end",
                }}
              >
                {picked.photo_url && (
                  <div
                    aria-hidden="true"
                    style={{
                      position: "absolute",
                      inset: 0,
                      background: "linear-gradient(180deg,rgba(12,32,42,0) 30%,rgba(12,32,42,.72) 100%)",
                    }}
                  />
                )}
                <div style={{ position: "relative", padding: 16, width: "100%" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    {LANDMARKS[picked.sido_code] && (
                      <img
                        src={`/landmarks/${picked.sido_code}.png`}
                        alt=""
                        width={56}
                        height={56}
                        style={{ flex: "0 0 auto", filter: "drop-shadow(0 2px 4px rgba(0,0,0,.25))" }}
                      />
                    )}
                    <div>
                      <div
                        style={{
                          fontSize: 22,
                          fontWeight: 800,
                          color: picked.photo_url ? "#fff" : "#1f3b48",
                          lineHeight: 1.2,
                          textShadow: picked.photo_url ? "0 1px 6px rgba(0,0,0,.5)" : "none",
                        }}
                      >
                        {LANDMARKS[picked.sido_code]?.name ?? picked.short_name}
                      </div>
                      <div
                        style={{
                          fontSize: 13,
                          color: picked.photo_url ? "rgba(255,255,255,.9)" : "#5c7686",
                          marginTop: 2,
                          textShadow: picked.photo_url ? "0 1px 5px rgba(0,0,0,.5)" : "none",
                        }}
                      >
                        {picked.short_name} 대표 명소
                      </div>
                    </div>
                  </div>
                  {picked.photo_spot_name && (
                    <div
                      style={{
                        marginTop: 10,
                        fontSize: 11,
                        color: "rgba(255,255,255,.82)",
                        textShadow: "0 1px 4px rgba(0,0,0,.6)",
                      }}
                    >
                      사진: {picked.photo_spot_name} · 한국관광공사
                    </div>
                  )}
                </div>
              </div>

              <h2 style={{ margin: "0 0 4px", fontSize: 17 }}>
                {picked.basis_region_name ?? picked.short_name}
              </h2>
              <p style={{ fontSize: 13, opacity: 0.8, margin: "0 0 12px" }}>
                {picked.available
                  ? `예상 혼잡도 ${LEVEL_TEXT[picked.level ?? "none"]} · ${Math.round(picked.index ?? 0)}% (관광지 ${picked.sample_count}곳 기준)`
                  : "이 지역은 예상 혼잡도 데이터가 아직 없어요."}
              </p>
              {/* 부록 U.4(2026-08-01, 대표 지시) — 이 자리에 있던 지도는 지웠다.
                  대신 **그 지역에서 가장 추천할 숨은 명소** 한 곳을 사진·이름·한 줄 소개로 보여준다.
                  이 서비스의 목적(붐비는 곳 대신 한적한 곳)이 지역을 고른 직후에 바로 보이게 하는 게
                  지도를 한 번 더 띄우는 것보다 낫다고 판단했다(지도는 아래 "자세히 보기"로 이어진다). */}
              <h3 style={{ margin: "16px 0 8px", fontSize: 15, color: "#26424f" }}>
                여기는 어때요? · 아직 붐비지 않는 곳
              </h3>
              {hiddenErr && <p style={{ color: "#b3261e", fontSize: 13 }}>{hiddenErr}</p>}
              {!hidden && !hiddenErr && <p style={{ opacity: 0.7, fontSize: 13 }}>불러오는 중…</p>}
              {hidden === "none" && (
                <p style={{ opacity: 0.75, fontSize: 13 }}>
                  이 지역은 아직 소개할 숨은 명소를 준비 중이에요.
                </p>
              )}
              {hidden && hidden !== "none" && (
                <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                  {hidden.image_url ? (
                    <img
                      src={hidden.image_url}
                      alt=""
                      width={120}
                      height={90}
                      style={{ objectFit: "cover", borderRadius: 12, flex: "0 0 auto" }}
                    />
                  ) : (
                    <div
                      style={{
                        width: 120,
                        height: 90,
                        borderRadius: 12,
                        flex: "0 0 auto",
                        background: "linear-gradient(135deg,#dff0f7,#eef5f9)",
                      }}
                    />
                  )}
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 700, fontSize: 15, color: "#1f3b48" }}>
                      {hidden.name}
                    </div>
                    {hidden.summary ? (
                      <p style={{ margin: "4px 0 0", fontSize: 13, color: "#5c7686", lineHeight: 1.5 }}>
                        {hidden.summary}
                      </p>
                    ) : (
                      /* 소개글이 원천에 없으면 지어내지 않는다 — 대신 확실한 사실(주소/분류)만 적는다. */
                      <p style={{ margin: "4px 0 0", fontSize: 13, color: "#7c93a1" }}>
                        {hidden.address ?? "소개글은 아직 준비 중이에요."}
                      </p>
                    )}
                  </div>
                </div>
              )}
              <div style={{ marginTop: 14 }}>
                <Link className="btn btn--mint" href={`/regions?region_code=${encodeURIComponent(picked.region_code)}`}>
                  {picked.short_name} 여행지 자세히 보기
                </Link>
              </div>
            </>
          )}
        </div>
      </div>

      {/* 부록 U.3(대표 지시) — 지도 **아래**에 예상 혼잡 현황판.
          지역은 위 지도가 정한다(고르기 전에는 기본 지역). 카드는 옆으로 천천히 순환한다. */}
      <div style={{ marginTop: 28 }}>
        {picked ? (
          <CongestionBoard
            areaCd={picked.sido_code === "47940" ? "47" : picked.sido_code}
            sigunguCd={picked.region_code}
            marquee
            subtitle={`${picked.short_name} · ${picked.basis_region_name ?? ""} 기준`}
          />
        ) : (
          /* 지역을 고르기 전에는 **지도에 떠 있는 시·도 전체**의 예상 혼잡도를 흘린다(대표 지시).
             특정 지역 전광판을 기본값으로 두면 "왜 부산이 기본이지?"가 되고, 전국 화면이라는
             성격과도 어긋난다. 카드를 누르면 그 지역이 선택된다(지도 클릭과 동일 동작). */
          <section className="section section--mint" aria-labelledby="nationwideBoardHeading">
            <span className="eyebrow-pill eyebrow-pill--coral">예상 혼잡 현황판</span>
            <h2 className="section__title" id="nationwideBoardHeading">
              지금 전국, 어디가 붐빌까요?
            </h2>
            <p className="board-subtitle">
              시·도별 예상 혼잡도예요. 카드를 누르면 그 지역만 자세히 볼 수 있어요.
            </p>
            {items.length > 0 ? (
              <NationwideBoard items={items} onSelect={handleSelect} />
            ) : (
              <p style={{ opacity: 0.7 }}>불러오는 중…</p>
            )}
          </section>
        )}
      </div>
    </section>
  );
}
