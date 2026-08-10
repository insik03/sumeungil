"use client";

import { useState } from "react";
import { NationwideCongestionItem } from "../../lib/api";
import koreaPaths from "./koreaPaths.json";
import { LANDMARKS, LandmarkGlyph } from "./landmarks";
import { LEVEL_COLOR, LEVEL_TEXT, colorOf } from "./shared";

interface KoreaRegionPath {
  sido_code: string;
  short_name: string;
  d: string;
  label: { x: number; y: number };
}

/**
 * 전국 SVG 지도 (부록 U) — 실제 행정구역 경계 + 시·도별 랜드마크 그림 + 예상 혼잡도 색.
 *
 * 경계: Natural Earth(퍼블릭 도메인) → `backend/scripts/build_korea_svg_paths.py` 로 단순화.
 * 랜드마크: `public/landmarks/<시도코드>.png` (대표가 생성한 이미지를 누끼 처리한 것).
 *   이미지가 없거나 로딩에 실패하면 **직접 그린 SVG 그림으로 자동 폴백**한다 —
 *   외부 자산 하나 때문에 지도가 비지 않게 하기 위해서다.
 *
 * 디자인은 대표가 준 참고 시안을 따랐다(파스텔 면 + 랜드마크 + 라벨 알약 + 우상단 범례).
 * 다만 시안에 있던 "실시간"·"예상 대기 시간"은 **넣지 않는다** — 우리 데이터는 예측이고
 * 대기시간은 원천에 아예 없다(지어내지 않는다).
 */
export default function KoreaSvgMap({
  items,
  selected,
  onSelect,
}: {
  items: NationwideCongestionItem[];
  selected: string | null;
  onSelect: (sidoCode: string) => void;
}) {
  const [failed, setFailed] = useState<Set<string>>(new Set());
  const byCode = new Map(items.map((i) => [i.sido_code, i]));
  const regions = koreaPaths.regions as KoreaRegionPath[];
  const dokdo = koreaPaths.dokdo as { x: number; y: number; name: string };

  const ICON = 30; // 지도 위 랜드마크 크기(viewBox 단위). 라벨 최소간격(실측 32) 보다 작게 잡아 겹침을 막는다.

  return (
    // viewBox 는 **실측 내용 범위**(x 12~448, y 88~552)에 맞춰 잘랐다.
    // 경로 생성기가 640 높이 안에 세로 중앙정렬을 해서 위아래로 각각 88px 씩 죽은 여백이
    // 있었다(대표 지적 "여백이 너무 많다"). 상하 약 200px 를 걷어내면 같은 폭에서도 지도가
    // 훨씬 커 보이고, 그만큼 랜드마크가 덜 붙는다.
    <svg
      viewBox="6 76 520 490"
      role="group"
      aria-label="전국 시·도 예상 혼잡도 지도"
      style={{ width: "100%", maxWidth: 990, height: "auto", display: "block", margin: "0 auto" }}
    >
      <defs>
        <linearGradient id="congestionScale" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#A9D8E8" />
          <stop offset="50%" stopColor="#F8E3A3" />
          <stop offset="100%" stopColor="#F5A9A9" />
        </linearGradient>
        <filter id="softShadow" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="1.5" stdDeviation="2" floodColor="#3d5a6c" floodOpacity="0.18" />
        </filter>
      </defs>

      {/* 배경 — 옅은 바다빛 */}
      <rect x="6" y="76" width="520" height="490" rx="18" fill="#e8f4f9" />

      {/* 여름 장식(2026-08-01 대표 지시: 지금은 여름이니 벚꽃 대신 바다).
          전부 **바다 영역에만** 배치한다 — 육지를 덮으면 정보를 가린다.
          순수 장식이라 정보가 없어 aria 에서 숨긴다. */}
      <g aria-hidden="true">
        {/* 파도 — 서해·동해·남해 */}
        <g fill="none" stroke="#9ecfe4" strokeWidth="2.6" strokeLinecap="round" opacity="0.9">
          <path d="M18 250 q9 -6 18 0 t18 0" />
          <path d="M24 272 q9 -6 18 0 t18 0" />
          <path d="M14 330 q9 -6 18 0 t18 0" />
          <path d="M452 340 q9 -6 18 0 t18 0" />
          <path d="M462 364 q9 -6 18 0 t18 0" />
          <path d="M300 540 q9 -6 18 0 t18 0" />
          <path d="M352 528 q9 -6 18 0 t18 0" />
          <path d="M96 486 q9 -6 18 0 t18 0" />
        </g>

        {/* 튜브(수영링) — 서해 */}
        <g transform="translate(40,300)">
          <circle r="13" fill="#f6a9a3" stroke="#ffffff" strokeWidth="3" />
          <circle r="5.4" fill="#e8f4f9" />
          <path d="M-13 0 a13 13 0 0 1 13 -13" stroke="#ffffff" strokeWidth="6" fill="none" strokeLinecap="round" />
        </g>

        {/* 서핑보드 — 동해 */}
        <g transform="translate(470,300) rotate(-24)">
          <ellipse rx="7" ry="20" fill="#fdf3dc" stroke="#3f7f6b" strokeWidth="1.6" />
          <path d="M0 -17 V17" stroke="#8ed0c0" strokeWidth="3" strokeLinecap="round" />
        </g>

        {/* 파라솔 — 남해 */}
        <g transform="translate(250,548)">
          <path d="M0 0 V-16" stroke="#8a6b52" strokeWidth="2.2" strokeLinecap="round" />
          <path d="M-16 -15 a16 12 0 0 1 32 0 Z" fill="#8ed0c0" stroke="#3f7f6b" strokeWidth="1.4" />
          <path d="M0 -27 a16 12 0 0 1 16 12 h-16 Z" fill="#f6a9a3" />
        </g>

        {/* 해 — 좌상단 */}
        <g transform="translate(44,120)">
          <circle r="12" fill="#f9d98d" />
          {[0, 45, 90, 135, 180, 225, 270, 315].map((a) => (
            <path
              key={a}
              d="M0 -17 V-21"
              stroke="#f2c86a"
              strokeWidth="2.4"
              strokeLinecap="round"
              transform={`rotate(${a})`}
            />
          ))}
        </g>
      </g>

      {/* --- 시·도 면 --- */}
      {regions.map((r) => {
        const it = byCode.get(r.sido_code);
        const fill = colorOf(it?.available ?? false, it?.level ?? null);
        const isSel = selected === r.sido_code;
        return (
          <path
            key={r.sido_code}
            d={r.d}
            fill={fill}
            stroke={isSel ? "#2f7d63" : "#ffffff"}
            strokeWidth={isSel ? 2.6 : 1.1}
            strokeLinejoin="round"
            tabIndex={0}
            role="button"
            aria-label={
              it?.available
                ? `${r.short_name} ${LEVEL_TEXT[it.level ?? "none"]} ${Math.round(it.index ?? 0)}퍼센트`
                : `${r.short_name} 정보 없음`
            }
            aria-pressed={isSel}
            onClick={() => onSelect(r.sido_code)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(r.sido_code);
              }
            }}
            style={{ cursor: "pointer", outline: "none" }}
          />
        );
      })}

      {/* --- 랜드마크 + 라벨 알약 --- */}
      {regions.map((r) => {
        const it = byCode.get(r.sido_code);
        const lm = LANDMARKS[r.sido_code];
        const cx = r.label.x;
        const iy = r.label.y - ICON - 6;
        const pillW = Math.max(38, r.short_name.length * 8 + 30);
        const useImg = !failed.has(r.sido_code);
        return (
          // 2026-08-01(대표 지시) — 라벨·랜드마크도 **클릭 대상**이다. 작은 광역시(대전·광주·
          // 대구·세종)는 면이 좁아 그림·글자에 덮이면 면을 직접 누르기 어렵다. 여기서 같은
          // onSelect 를 호출해 "보이는 건 다 눌린다"를 만든다.
          <g
            key={`lm-${r.sido_code}`}
            role="button"
            tabIndex={0}
            aria-label={`${r.short_name} 선택`}
            onClick={() => onSelect(r.sido_code)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(r.sido_code);
              }
            }}
            style={{ cursor: "pointer", outline: "none" }}
          >
            {useImg ? (
              <image
                href={`/landmarks/${r.sido_code}.png`}
                x={cx - ICON / 2}
                y={iy}
                width={ICON}
                height={ICON}
                onError={() =>
                  setFailed((prev) => {
                    const n = new Set(prev);
                    n.add(r.sido_code);
                    return n;
                  })
                }
              />
            ) : (
              <g transform={`translate(${cx - ICON / 2}, ${iy}) scale(${ICON / 64})`}>
                <LandmarkGlyph sidoCode={r.sido_code} />
              </g>
            )}

            {/* 지역명 + 예상 혼잡도. 흰 알약 배경을 없애고(대표 지시) 글자에 흰 외곽선을
                깔아 파스텔 면 위에서도 읽히게 한다 — paint-order:stroke 로 획이 글자 뒤에 깔린다.
                랜드마크 이름은 지도에서 뺐다(자잘한 텍스트가 많아 지저분해짐) — 지역을 클릭하면
                오른쪽 패널에서 사진과 함께 크게 알려준다. */}
            <text
              x={cx}
              y={r.label.y + 4}
              textAnchor="middle"
              style={{
                font: "800 13px system-ui",
                fill: "#1f3b48",
                stroke: "#ffffff",
                strokeWidth: 3.4,
                paintOrder: "stroke",
                strokeLinejoin: "round",
              }}
            >
              {r.short_name}
              <tspan style={{ font: "700 12px system-ui", fill: "#3f6070" }}>
                {" "}
                {it?.available ? `${Math.round(it.index ?? 0)}%` : "—"}
              </tspan>
            </text>
          </g>
        );
      })}

      {/* --- 울릉도 · 독도 (2026-08-01 대표 지적 "얘네 어디 갔냐") ---
          울릉도는 원본 경계 데이터에 있어 경상북도 path 안에 **실제 모양·위치**로 그려진다.
          독도는 Natural Earth admin-1 에 아예 없어서(분쟁지역으로 별도 분류) 좌표를 직접 넣었다.
          실제 좌표는 37.2429N / 131.8667E 이고, 면적이 약 0.19km² 라 이 축척에서는 1px 도 안 된다.
          그래서 **위치는 실제 좌표 그대로** 두되 크기는 보이도록 키워 표식으로 그린다
          (동도·서도 두 바위). 지도가 독도를 실제 크기로 그린 척하지 않는다. */}
      <g>
        {/* 울릉도는 경북 안에 있지만 본토와 완전히 떨어진 섬이라 **별도 지역으로 뽑아** 자기
            혼잡도·사진을 보여준다(대표 지시). 그래서 경북 path 와 따로 클릭 대상이 된다. */}
        {(() => {
          const ul = byCode.get("47940");
          const sel = selected === "47940";
          return (
            <g
              role="button"
              tabIndex={0}
              aria-label={
                ul?.available
                  ? `울릉도 ${LEVEL_TEXT[ul.level ?? "none"]} ${Math.round(ul.index ?? 0)}퍼센트`
                  : "울릉도"
              }
              aria-pressed={sel}
              onClick={() => onSelect("47940")}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect("47940");
                }
              }}
              style={{ cursor: "pointer", outline: "none" }}
            >
              {/* 혼잡도 색 원을 배경으로 깔고 그 위에 나리분지 그림을 얹는다.
                  이 그림만 다른 랜드마크와 형태가 다르다(아치형 카드 안 풍경) — 원본이
                  그렇게 생성돼서 배경만 도려낼 수 없다. 카드 모양 그대로 쓴다(대표 결정). */}
              <circle
                cx={444}
                cy={148}
                r={17}
                fill={colorOf(ul?.available ?? false, ul?.level ?? null)}
                fillOpacity={0.55}
                stroke={sel ? "#2f7d63" : "#ffffff"}
                strokeWidth={sel ? 2.4 : 1.2}
              />
              <image href="/landmarks/47940.png" x={444 - 15} y={148 - 15} width={30} height={30} />
              <text
                x={444}
                y={172}
                textAnchor="middle"
                style={{
                  font: "800 12px system-ui",
                  fill: "#1f3b48",
                  stroke: "#ffffff",
                  strokeWidth: 3.2,
                  paintOrder: "stroke",
                  strokeLinejoin: "round",
                }}
              >
                울릉도
                <tspan style={{ font: "700 11px system-ui", fill: "#3f6070" }}>
                  {" "}
                  {ul?.available ? `${Math.round(ul.index ?? 0)}%` : "—"}
                </tspan>
              </text>
            </g>
          );
        })()}
        <g aria-label="독도" role="img">
          <ellipse cx={dokdo.x - 3.4} cy={dokdo.y} rx={4.2} ry={3.4} fill="#c8d3da" stroke="#2f5748" strokeWidth="1.2" />
          <ellipse cx={dokdo.x + 4} cy={dokdo.y + 1.2} rx={3} ry={2.4} fill="#dbe3e8" stroke="#2f5748" strokeWidth="1.2" />
          <text
            x={dokdo.x}
            y={dokdo.y + 16}
            textAnchor="middle"
            style={{ font: "700 9.5px system-ui", fill: "#26424f" }}
          >
            독도
          </text>
        </g>
      </g>

      {/* 범례 — 지도 **안 우측 하단**(대표 지시). 한때 밖으로 뺐던 이유는 우상단에 두면
          강원을 덮었기 때문인데, 이 자리는 육지가 없는 바다라 아무 정보도 가리지 않는다.
          장식(파도·서핑보드)과 겹치지 않는 좌표를 골랐다. */}
      <g aria-hidden="true">
        <rect x="336" y="440" width="184" height="112" rx="14" fill="#ffffff" fillOpacity="0.96" filter="url(#softShadow)" />
        <text x="350" y="462" style={{ font: "700 12px system-ui", fill: "#26424f" }}>
          전국 예상 혼잡도
        </text>
        <rect x="350" y="470" width="156" height="9" rx="4.5" fill="url(#congestionScale)" />
        <text x="350" y="492" style={{ font: "600 9.5px system-ui", fill: "#5c7686" }}>여유</text>
        <text x="428" y="492" textAnchor="middle" style={{ font: "600 9.5px system-ui", fill: "#5c7686" }}>보통</text>
        <text x="506" y="492" textAnchor="end" style={{ font: "600 9.5px system-ui", fill: "#5c7686" }}>복잡</text>
        <rect x="350" y="500" width="10" height="10" rx="3" fill={LEVEL_COLOR.none} />
        <text x="365" y="509" style={{ font: "500 9.5px system-ui", fill: "#5c7686" }}>정보 없음</text>
        <text x="350" y="527" style={{ font: "500 8.5px system-ui", fill: "#7c93a1" }}>
          시·도 대표 시·군·구 한 곳 기준이에요.
        </text>
        <text x="350" y="539" style={{ font: "500 8.5px system-ui", fill: "#7c93a1" }}>
          관광지 예상 집중률의 중앙값이며,
        </text>
        <text x="350" y="551" style={{ font: "500 8.5px system-ui", fill: "#7c93a1" }}>
          실시간 실측이 아니에요.
        </text>
      </g>
    </svg>
  );
}
