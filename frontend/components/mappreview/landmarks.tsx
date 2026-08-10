/**
 * 시·도별 대표 랜드마크 일러스트 (2026-08-01, 대표 요청: 시안 수준까지 디테일을 올릴 것).
 *
 * ## 정직 고지
 * 전부 **직접 그린 SVG**다. 외부 이미지·아이콘 폰트·클립아트를 일절 쓰지 않아 저작권 리스크가
 * 0이다(공모전 공고문의 저작권 책임 조항 대응).
 *
 * ## 스케일에 대한 실무 판단
 * 지도 위 아이콘은 기껏해야 30~40px 다. 그 크기에서는 아무리 정교하게 그려도 디테일이 안 보인다.
 * 그래서 **같은 그림을 두 크기로 쓴다**:
 *   - 지도 위: 36px 안팎(윤곽과 색으로 "무엇인지"만 전달)
 *   - 지역 선택 패널: 112px(기와 결·창문·케이블 같은 디테일이 실제로 보이는 크기)
 * 디테일을 "안 보이는 곳에 그려 넣는" 대신, 보이는 자리를 만들어 준 것이다.
 *
 * ## 스타일 규칙(시안 톤)
 * 64×64 좌표계 · 파스텔 면 채우기 · 짙은 초록 외곽선(1.6px) · 둥근 마감 ·
 * 같은 색의 진한 톤으로 그림자면을 한 겹 넣어 입체감을 준다.
 */
export interface Landmark {
  name: string;
}

export const LANDMARKS: Record<string, Landmark> = {
  "11": { name: "남산서울타워" },
  "26": { name: "광안대교" },
  "27": { name: "팔공산 갓바위" },
  "28": { name: "인천대교" },
  "29": { name: "무등산 주상절리" },
  "30": { name: "대전 한빛탑" },
  "31": { name: "울산 대왕암" },
  "36": { name: "정부세종청사" },
  "41": { name: "수원화성" },
  "43": { name: "법주사 팔상전" },
  "44": { name: "공주 공산성" },
  "46": { name: "여수 오동도" },
  "47": { name: "경주 첨성대" },
  "48": { name: "통영 한려수도" },
  "50": { name: "성산일출봉" },
  "51": { name: "설악산" },
  "52": { name: "전주 한옥마을" },
  // 울릉도는 경북 안이지만 별도 지역으로 뽑았다(대표 지시). 전용 그림은 없어 이름만 쓴다.
  "47940": { name: "울릉도 나리분지" },
};

const L = "#2f5748";
const C = {
  roof: "#93b9d3",
  roofHi: "#b3d0e3",
  roofSh: "#6d99b8",
  wall: "#faf3e6",
  wallSh: "#e7dcc7",
  wood: "#d99a6c",
  woodSh: "#bd7f53",
  stone: "#d3dae0",
  stoneSh: "#b0bcc6",
  green: "#a3d6b2",
  greenSh: "#71b98d",
  greenDeep: "#4f9b74",
  water: "#a9d8e8",
  waterSh: "#7fc0d8",
  pink: "#f2b3bd",
  pinkSh: "#dd8e9c",
  sun: "#f7d485",
  white: "#ffffff",
  red: "#c9736f",
};

const S = {
  stroke: L,
  strokeWidth: 1.6,
  strokeLinejoin: "round" as const,
  strokeLinecap: "round" as const,
};
const THIN = { stroke: L, strokeWidth: 0.9, fill: "none", strokeLinecap: "round" as const };

/** 기와 결(지붕 위 세로선 몇 줄) — 한옥 계열에서 재사용. */
function RoofRibs({ x, y, w, n = 5 }: { x: number; y: number; w: number; n?: number }) {
  const step = w / (n + 1);
  return (
    <g {...THIN}>
      {Array.from({ length: n }).map((_, i) => {
        const px = x - w / 2 + step * (i + 1);
        const dip = Math.abs(px - x) / (w / 2);
        return <path key={i} d={`M${px} ${y} L${px} ${y - (w * 0.3) * (1 - dip * 0.7)}`} />;
      })}
    </g>
  );
}

/** 한옥 지붕 한 채. 처마가 살짝 올라간 곡선 + 용마루 + 기와 결. */
function Hanok({
  x,
  y,
  w,
  fill = C.roof,
  ribs = true,
}: {
  x: number;
  y: number;
  w: number;
  fill?: string;
  ribs?: boolean;
}) {
  const h = w * 0.4;
  const e = w * 0.09; // 처마 들림
  return (
    <g>
      <path
        d={`M${x - w / 2 - e} ${y} C ${x - w / 2 + 2} ${y - h * 0.2}, ${x - w * 0.2} ${y - h}, ${x} ${y - h}
            C ${x + w * 0.2} ${y - h}, ${x + w / 2 - 2} ${y - h * 0.2}, ${x + w / 2 + e} ${y} Z`}
        fill={fill}
        {...S}
      />
      <path d={`M${x - w * 0.24} ${y - h + 1} h${w * 0.48}`} stroke={L} strokeWidth="2" strokeLinecap="round" fill="none" />
      {ribs && <RoofRibs x={x} y={y - 1} w={w * 0.92} />}
    </g>
  );
}

/** 물결 — 바다/강이 있는 랜드마크 공용. */
function Waves({ y }: { y: number }) {
  return (
    <g fill="none" strokeLinecap="round">
      <path d={`M2 ${y} q6 3 12 0 t12 0 t12 0 t12 0 t12 0`} stroke={C.water} strokeWidth="3.4" />
      <path d={`M6 ${y + 5} q5 2.4 10 0 t10 0 t10 0 t10 0`} stroke={C.waterSh} strokeWidth="2.2" opacity="0.75" />
    </g>
  );
}

export function LandmarkGlyph({ sidoCode }: { sidoCode: string }) {
  switch (sidoCode) {
    /* 서울 — 남산서울타워: 산 + 다층 전망대 + 첨탑 */
    case "11":
      return (
        <g>
          <path d="M4 58 C 14 40, 22 34, 32 34 C 42 34, 50 40, 60 58 Z" fill={C.green} {...S} />
          <path d="M32 34 C 42 34, 50 40, 60 58 L36 58 Z" fill={C.greenSh} {...S} />
          <path d="M25 58 L29 30 h6 l4 28 Z" fill={C.stone} {...S} />
          <path d="M32 58 L35 30 h4 l-3 28 Z" fill={C.stoneSh} stroke="none" />
          <path d="M23 30 h18 l-3 -6 h-12 Z" fill={C.pink} {...S} />
          <path d="M24.5 24 h15 l-2.5 -5 h-10 Z" fill={C.pinkSh} {...S} />
          <path d="M25 27.5 h14" {...THIN} />
          <path d="M32 19 V8" stroke={L} strokeWidth="1.8" strokeLinecap="round" fill="none" />
          <circle cx="32" cy="6" r="2.6" fill={C.sun} {...S} />
        </g>
      );

    /* 부산 — 광안대교: 주탑 2개 + 현수 케이블 + 야간 조명 */
    case "26":
      return (
        <g>
          <Waves y={52} />
          <path d="M4 40 h56" stroke={L} strokeWidth="2.2" fill="none" strokeLinecap="round" />
          <path d="M4 40 v6 h56 v-6" fill={C.stone} {...S} />
          <path d="M4 40 C 12 16, 24 14, 32 26 C 40 14, 52 16, 60 40" fill="none" stroke={L} strokeWidth="1.8" />
          <g {...THIN}>
            <path d="M10 40 V28 M16 40 V22 M22 40 V19 M28 40 V22 M36 40 V22 M42 40 V19 M48 40 V22 M54 40 V28" />
          </g>
          <rect x="14.6" y="12" width="5" height="34" rx="1.6" fill={C.stone} {...S} />
          <rect x="44.4" y="12" width="5" height="34" rx="1.6" fill={C.stone} {...S} />
          <circle cx="17.1" cy="10" r="2" fill={C.pink} {...S} />
          <circle cx="46.9" cy="10" r="2" fill={C.pink} {...S} />
        </g>
      );

    /* 대구 — 팔공산 갓바위: 능선 + 갓 쓴 좌불 바위 */
    case "27":
      return (
        <g>
          <path d="M2 58 L18 26 l10 13 8-10 26 29 Z" fill={C.green} {...S} />
          <path d="M36 29 l26 29 H30 Z" fill={C.greenSh} {...S} />
          <path d="M2 58 h60" stroke={L} strokeWidth="1.6" fill="none" />
          <ellipse cx="42" cy="26" rx="11" ry="3.2" fill={C.stoneSh} {...S} />
          <path d="M35 26 C 36 14, 48 14, 49 26 Z" fill={C.stone} {...S} />
          <path d="M42 16.5 a3.4 3.4 0 1 1 0.1 0" fill={C.stone} {...S} />
          <path d="M38 21 q4 -2.6 8 0" {...THIN} />
          <path d="M14 34 l3 5 h-6 Z" fill={C.greenDeep} {...S} />
        </g>
      );

    /* 인천 — 인천대교: 사장교 주탑 + 부채꼴 케이블 */
    case "28":
      return (
        <g>
          <Waves y={52} />
          <path d="M2 42 h60 v5 H2 Z" fill={C.stone} {...S} />
          <path d="M28 42 V6 h3 v36" fill={C.white} {...S} />
          <g {...THIN}>
            <path d="M29.5 9 L8 42 M29.5 9 L51 42 M29.5 16 L14 42 M29.5 16 L45 42 M29.5 23 L20 42 M29.5 23 L39 42" />
          </g>
          <path d="M24 42 h11 v-4 h-11 Z" fill={C.stoneSh} {...S} />
          <path d="M46 47 h12 l-2 5 H48 Z" fill={C.white} {...S} />
          <path d="M52 47 v-4" {...THIN} />
        </g>
      );

    /* 광주 — 무등산 주상절리(입석대): 육각 돌기둥 무리 */
    case "29":
      return (
        <g>
          <path d="M2 58 L16 32 l9 9 9-13 28 30 Z" fill={C.green} {...S} />
          <path d="M36 28 l28 30 H30 Z" fill={C.greenSh} {...S} />
          <g {...S} fill={C.stone}>
            <path d="M34 44 l3-2 3 2 v-20 l-3-2 -3 2 Z" />
            <path d="M40 44 l3-2 3 2 v-25 l-3-2 -3 2 Z" fill={C.stoneSh} />
            <path d="M46 44 l3-2 3 2 v-18 l-3-2 -3 2 Z" />
          </g>
          <path d="M2 58 h60" stroke={L} strokeWidth="1.6" fill="none" />
        </g>
      );

    /* 대전 — 한빛탑: 전망 원반 + 세로 리브 */
    case "30":
      return (
        <g>
          <ellipse cx="32" cy="57" rx="16" ry="4" fill={C.greenSh} {...S} />
          <path d="M24 55 h16 l-3 -12 h-10 Z" fill={C.stoneSh} {...S} />
          <path d="M27.5 43 L30 16 h4 l2.5 27 Z" fill={C.wall} {...S} />
          <g {...THIN}>
            <path d="M29 43 L31 17 M32 43 L32.6 17 M35 43 L33.6 17" />
          </g>
          <ellipse cx="32" cy="21" rx="11" ry="4" fill={C.water} {...S} />
          <ellipse cx="32" cy="21" rx="6" ry="2" fill={C.waterSh} stroke="none" />
          <path d="M32 16 V7" stroke={L} strokeWidth="1.7" fill="none" strokeLinecap="round" />
          <circle cx="32" cy="5.4" r="2.4" fill={C.sun} {...S} />
        </g>
      );

    /* 울산 — 대왕암: 붉은 기암 + 흰 등대 + 파도 */
    case "31":
      return (
        <g>
          <Waves y={50} />
          <path d="M4 46 q6 -14 13 -5 q5 -12 12 -1 q5 -9 11 0 q5 -6 10 3 Z" fill={C.stoneSh} {...S} />
          <path d="M17 41 q5 -12 12 -1 l-6 6 Z" fill={C.stone} stroke="none" />
          <path d="M38 34 L40 12 h5 l2 22 Z" fill={C.white} {...S} />
          <path d="M43.5 34 L45 12 h0.001 l2 22 Z" fill={C.wallSh} stroke="none" />
          <rect x="39.8" y="17" width="5.6" height="3.2" fill={C.red} {...S} />
          <rect x="39.8" y="24" width="5.6" height="3.2" fill={C.red} {...S} />
          <path d="M39 12 h7 l-3.5 -4 Z" fill={C.sun} {...S} />
        </g>
      );

    /* 세종 — 정부세종청사: 물결 지붕 + 유리 파사드 */
    case "36":
      return (
        <g>
          <path d="M4 56 h56 v-16 H4 Z" fill={C.wall} {...S} />
          <path d="M4 40 C 14 22, 26 34, 34 26 C 42 18, 52 28, 60 40 Z" fill={C.roof} {...S} />
          <path d="M34 26 C 42 18, 52 28, 60 40 H38 Z" fill={C.roofSh} stroke="none" />
          <g {...THIN}>
            <path d="M12 56 V40 M20 56 V40 M28 56 V40 M36 56 V40 M44 56 V40 M52 56 V40" />
            <path d="M4 48 h56" />
          </g>
          <path d="M2 56 h60" stroke={L} strokeWidth="1.8" fill="none" />
          <path d="M28 56 v-8 h8 v8" fill={C.water} {...S} />
        </g>
      );

    /* 경기 — 수원화성: 성벽 여장 + 문루 2층 + 홍예문 */
    case "41":
      return (
        <g>
          <path d="M2 58 h60 v-16 H2 Z" fill={C.stone} {...S} />
          <path d="M2 42 h4v-4h4v4h5v-4h4v4h10v-4h4v4h5v-4h4v4h5v-4h4v4h5" fill="none" {...S} />
          <g {...THIN}>
            <path d="M2 50 h60 M12 58 v-8 M24 58 v-8 M40 58 v-8 M52 58 v-8" />
          </g>
          <path d="M22 58 v-12 a10 10 0 0 1 20 0 v12" fill={C.wall} {...S} />
          <path d="M27 58 v-9 a5 5 0 0 1 10 0 v9" fill={C.woodSh} {...S} />
          <Hanok x={32} y={38} w={30} />
          <Hanok x={32} y={26} w={22} fill={C.roofHi} />
          <path d="M25 38 h14 v-8 H25 Z" fill={C.wood} {...S} />
        </g>
      );

    /* 충북 — 법주사 팔상전: 5층 목탑 */
    case "43":
      return (
        <g>
          <path d="M14 58 h36 v-4 H14 Z" fill={C.stoneSh} {...S} />
          <rect x="22" y="42" width="20" height="12" fill={C.wood} {...S} />
          <path d="M26 54 v-9 h5 v9" fill={C.woodSh} {...S} />
          <Hanok x={32} y={44} w={38} />
          <Hanok x={32} y={34} w={31} fill={C.roofHi} />
          <Hanok x={32} y={25} w={24} />
          <Hanok x={32} y={17} w={17} fill={C.roofHi} />
          <path d="M32 12 V5" stroke={L} strokeWidth="1.7" fill="none" strokeLinecap="round" />
          <circle cx="32" cy="4" r="2.2" fill={C.sun} {...S} />
        </g>
      );

    /* 충남 — 공주 공산성: 언덕 성벽 + 성문 + 깃발 */
    case "44":
      return (
        <g>
          <path d="M2 58 C 12 40, 52 40, 62 58 Z" fill={C.green} {...S} />
          <path d="M34 41 C 48 42, 56 48, 62 58 H36 Z" fill={C.greenSh} stroke="none" />
          <path d="M10 54 h44 v-12 H10 Z" fill={C.stone} {...S} />
          <path d="M10 42 h4v-4h4v4h6v-4h4v4h8v-4h4v4h6v-4h4v4h4" fill="none" {...S} />
          <g {...THIN}>
            <path d="M10 48 h44 M20 54 v-6 M32 54 v-6 M44 54 v-6" />
          </g>
          <path d="M26 54 v-8 a6 6 0 0 1 12 0 v8" fill={C.woodSh} {...S} />
          <path d="M50 38 V26" {...THIN} />
          <path d="M50 27 l8 3 -8 3 Z" fill={C.red} {...S} />
        </g>
      );

    /* 전남 — 여수 오동도: 섬 + 동백 + 등대 + 배 */
    case "46":
      return (
        <g>
          <Waves y={52} />
          <path d="M8 46 C 14 24, 44 22, 52 46 Z" fill={C.green} {...S} />
          <path d="M32 22.6 C 44 24, 50 32, 52 46 H34 Z" fill={C.greenSh} stroke="none" />
          <g {...S}>
            <circle cx="18" cy="36" r="3.4" fill={C.pink} />
            <circle cx="27" cy="41" r="2.6" fill={C.pinkSh} />
            <circle cx="40" cy="38" r="3" fill={C.pink} />
          </g>
          <path d="M42 30 L43.6 14 h4 L49 30 Z" fill={C.white} {...S} />
          <rect x="43.4" y="19" width="4" height="2.8" fill={C.red} {...S} />
          <path d="M42.6 14 h5.6 l-2.8 -3.4 Z" fill={C.sun} {...S} />
          <path d="M10 56 h14 l-2.4 4 H12.4 Z" fill={C.white} {...S} />
        </g>
      );

    /* 경북 — 경주 첨성대: 곡선 석축 + 단 + 창구 */
    case "47":
      return (
        <g>
          <path d="M16 58 h32 v-5 H16 Z" fill={C.stoneSh} {...S} />
          <path d="M20 53 C 20 30, 25 12, 32 12 C 39 12, 44 30, 44 53 Z" fill={C.stone} {...S} />
          <path d="M32 12 C 39 12, 44 30, 44 53 H34 Z" fill={C.stoneSh} stroke="none" />
          <g {...THIN}>
            <path d="M21.4 46 h21.2 M22.6 39 h18.8 M24.4 32 h15.2 M26.6 25 h10.8 M28.4 19 h7.2" />
          </g>
          <rect x="28.4" y="32.4" width="7.2" height="7" fill={C.woodSh} {...S} />
          <path d="M26.4 12.6 h11.2" stroke={L} strokeWidth="2" fill="none" />
          <path d="M25.4 9.6 h13.2 v3 H25.4 Z" fill={C.stone} {...S} />
        </g>
      );

    /* 경남 — 통영 한려수도: 다도해 + 여객선 + 갈매기 */
    case "48":
      return (
        <g>
          <Waves y={50} />
          <path d="M2 44 C 8 28, 20 28, 26 44 Z" fill={C.green} {...S} />
          <path d="M30 44 C 38 26, 54 26, 62 44 Z" fill={C.greenSh} {...S} />
          <path d="M46 26 C 54 28, 59 34, 62 44 H48 Z" fill={C.greenDeep} stroke="none" />
          <path d="M16 58 h26 l-3.6 5 H19.6 Z" fill={C.white} {...S} />
          <path d="M22 58 v-8 h12 v8" fill={C.wall} {...S} />
          <g {...THIN}>
            <path d="M25 54 h2 M30 54 h2" />
          </g>
          <path d="M28 50 V44" {...THIN} />
          <path d="M46 14 q3 -2.4 6 0 q3 -2.4 6 0" {...THIN} />
        </g>
      );

    /* 제주 — 성산일출봉: 분화구 능선 + 일출 + 현무암 */
    case "50":
      return (
        <g>
          <circle cx="46" cy="16" r="7" fill={C.sun} {...S} />
          <Waves y={52} />
          <path d="M4 46 C 10 26, 20 16, 32 16 C 46 16, 56 28, 60 46 Z" fill={C.greenDeep} {...S} />
          <path d="M32 16 C 46 16, 56 28, 60 46 H34 Z" fill="#3f8863" stroke="none" />
          <path d="M12 27 q6 -6 12 -3 q6 3 11 -2 q5 -4 10 1" {...THIN} />
          <g {...S} fill={C.stoneSh}>
            <path d="M8 46 q3 -5 6 0 Z" />
            <path d="M50 46 q3 -5 6 0 Z" />
          </g>
        </g>
      );

    /* 강원 — 설악산: 뾰족한 암봉 + 만년설 + 소나무 */
    case "51":
      return (
        <g>
          <path d="M2 58 L14 30 l7 9 8-19 10 17 6-7 17 28 Z" fill={C.stone} {...S} />
          <path d="M29 20 l10 17 6-7 17 28 H33 Z" fill={C.stoneSh} stroke="none" />
          <path d="M29 20 l5 8.6 -5 2.4 -4.6 -2.6 Z" fill={C.white} {...S} />
          <path d="M14 30 l3.6 6 -3.6 1.8 -3.4 -2 Z" fill={C.white} {...S} />
          <path d="M46 30 l3 5 -3 1.6 -2.8 -1.8 Z" fill={C.white} {...S} />
          <path d="M2 58 h60" stroke={L} strokeWidth="1.7" fill="none" />
          <path d="M9 58 v-7 M9 52 l-3 4 h6 Z" fill={C.greenDeep} {...S} />
        </g>
      );

    /* 전북 — 전주 한옥마을: 기와집 세 채 + 담장 */
    case "52":
      return (
        <g>
          <path d="M2 58 h60" stroke={L} strokeWidth="1.7" fill="none" />
          <rect x="6" y="40" width="18" height="16" fill={C.wall} {...S} />
          <Hanok x={15} y={40} w={24} />
          <path d="M11 56 v-9 h6 v9" fill={C.woodSh} {...S} />
          <rect x="34" y="44" width="24" height="12" fill={C.wallSh} {...S} />
          <Hanok x={46} y={44} w={30} fill={C.roofSh} />
          <g {...THIN}>
            <path d="M40 56 v-8 M52 56 v-8 M34 50 h24" />
          </g>
          <Hanok x={30} y={34} w={16} fill={C.roofHi} />
          <rect x="25" y="34" width="10" height="6" fill={C.wall} {...S} />
        </g>
      );

    default:
      return null;
  }
}
