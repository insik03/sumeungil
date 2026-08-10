# -*- coding: utf-8 -*-
"""전국 SVG 지도용 시·도 경계 path 생성 (부록 U.2, 2026-08-01).

## 출처와 라이선스 (중요 — 공모전 제출물이라 근거를 남긴다)
- 원천: **Natural Earth** `ne_10m_admin_1_states_provinces.geojson`
  (https://github.com/nvkelso/natural-earth-vector, 공식 배포 저장소)
- 라이선스: **퍼블릭 도메인**. 공식 이용약관(naturalearthdata.com/about/terms-of-use)에
  "All versions of Natural Earth raster + vector map data found on this website are in the
  public domain", "personal, educational, and commercial purposes", "No permission is needed
  to use Natural Earth. Crediting the authors is unnecessary." 로 명시돼 있다.
  → 상업적 이용 가능, 변형 가능, 출처 표기 의무 없음(그래도 아래 asset 에 출처를 남긴다).
- 대안으로 검토했다가 **쓰지 않은 것**: GADM(비상업 한정), OpenStreetMap(ODbL 동일조건),
  출처 불명 SVG(권리 확인 불가). 공고문상 저작권 문제 시 수상 취소·상금 회수 조항이 있어
  권리가 가장 깨끗한 것만 쓴다.

## 하는 일
원본 GeoJSON(약 39MB, 전 세계) → 한국 17개 시·도만 추출 → 좌표 단순화(Douglas–Peucker)
→ 화면 좌표로 투영 → SVG path 문자열로 저장. **원본 39MB 는 저장소에 넣지 않는다**
(결과물만 수백 KB 로 남긴다).

## 실행
    py scripts/build_korea_svg_paths.py --src <다운로드한 ne_10m ... .geojson>
    → frontend/components/mappreview/koreaPaths.json 생성
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

# Natural Earth 의 name_ko → 우리 법정동 시도 2자리(area_cd).
# ISO 코드(iso_3166_2)는 우리 체계와 다르다(강원 KR-42≠51, 전북 KR-45≠52, 제주 KR-49≠50,
# 세종 KR-50≠36) — 그래서 코드가 아니라 **한국어 지역명**으로 매핑한다.
NAME_KO_TO_SIDO: dict[str, str] = {
    "서울특별시": "11",
    "부산광역시": "26",
    "대구광역시": "27",
    "인천광역시": "28",
    "광주광역시": "29",
    "대전광역시": "30",
    "울산광역시": "31",
    "세종특별자치시": "36",
    "경기도": "41",
    "충청북도": "43",
    "충청남도": "44",
    "전라남도": "46",
    "경상북도": "47",
    "경상남도": "48",
    "제주특별자치도": "50",
    "강원도": "51",
    "전라북도": "52",
}

SHORT_NAME: dict[str, str] = {
    "11": "서울", "26": "부산", "27": "대구", "28": "인천", "29": "광주",
    "30": "대전", "31": "울산", "36": "세종", "41": "경기", "43": "충북",
    "44": "충남", "46": "전남", "47": "경북", "48": "경남", "50": "제주",
    "51": "강원", "52": "전북",
}

# 화면 크기(viewBox). 세로로 긴 한반도 비율에 맞춘다.
VIEW_W = 460.0
VIEW_H = 640.0
PADDING = 12.0

# 단순화 강도(도 단위 거리). 값이 클수록 파일이 작아지고 해안선이 뭉툭해진다.
# 0.004° ≈ 약 400m — 전국 조망 지도에서는 눈에 띄지 않으면서 용량을 크게 줄인다.
SIMPLIFY_TOLERANCE = 0.004
# 이 면적(도²) 미만의 섬 조각은 버린다. 전국 지도에서 점으로도 안 보이는 것들이라
# 남겨두면 용량만 먹는다. 제주(약 0.18)·거제·강화 등은 이 값보다 훨씬 크므로 살아남는다.
MIN_RING_AREA = 0.0008


def _perp_dist(p, a, b) -> float:
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def simplify(points: list, tol: float) -> list:
    """Douglas–Peucker. 외부 라이브러리 없이(이 환경에 shapely 등이 없다) 순수 파이썬으로."""
    if len(points) < 3:
        return points
    dmax, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        d = _perp_dist(points[i], points[0], points[-1])
        if d > dmax:
            dmax, idx = d, i
    if dmax <= tol:
        return [points[0], points[-1]]
    return simplify(points[: idx + 1], tol)[:-1] + simplify(points[idx:], tol)


def ring_area(ring: list) -> float:
    """신발끈 공식(부호 없는 면적, 도² 단위). 섬 조각 걸러내기용."""
    s = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def polygon_centroid(pts: list) -> tuple[float, float]:
    """폴리곤 면적 중심(화면 좌표). 면적이 0 에 수렴하면 정점 평균으로 폴백."""
    a = 0.0
    cx = 0.0
    cy = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    a *= 0.5
    if abs(a) < 1e-9:
        return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)
    return (cx / (6 * a), cy / (6 * a))


# 라벨이 겹치는 몇 곳만 손으로 밀어준다(화면 좌표 px).
# 경기도는 **서울을 도넛처럼 감싸고 있어** 면적 중심이 서울 한복판에 찍힌다 — 남서쪽으로 뺀다.
# 인천도 서울·경기와 가까워 살짝 왼쪽으로 민다.
# 2026-08-01(대표 지적 "세종·충남·대전이 다닥다닥 겹친다") — 면적 중심끼리 너무 가까운 곳은
# 손으로 밀어 최소 간격을 확보한다. 좁은 내륙(세종·대전)은 서로 반대로, 해안 도(충남·전남·인천)는
# **바다 쪽으로** 뺀다(대표 제안). 아이콘 크기도 함께 줄여 실제 겹침을 없앴다.
# 실측 최소간격: 세종↔충남 12px → 46px, 대전↔세종 26px → 47px, 광주↔전남 23px → 46px.
# 2026-08-01 개정(대표 지시: "지역 매칭은 되게 보여야지") — 라벨을 바다로 빼는 방식을 **폐기**한다.
# 앞선 버전은 겹침을 피하려고 충남·광주·울산을 바다로 밀었는데, 그러면 어느 지역 라벨인지
# 알 수 없다. 라벨은 **반드시 자기 지역 안**에 둔다. 겹침은 (1) 아이콘 축소 (2) 같은 지역 안에서의
# 소폭 이동 (3) 작은 광역시는 도 라벨을 반대편으로 밀기 로 푼다.
LABEL_NUDGE: dict[str, tuple[float, float]] = {
    "41": (30.0, 26.0),    # 경기 → 서울을 감싸므로 남동쪽 경기 땅으로
    "28": (-8.0, 6.0),     # 인천 → 서쪽(서울과 분리, 인천 안)
    "44": (-16.0, 8.0),    # 충남 → 서쪽(세종·대전과 분리, 충남 안)
    "36": (-4.0, -18.0),   # 세종 → 위쪽(대전과 분리, 세종 안)
    "30": (0.0, 0.0),      # 대전 → 지역 정중앙(대표 지시)
    "29": (0.0, 0.0),      # 광주 → 지역 정중앙(전남 라벨을 대신 남쪽으로)
    "46": (10.0, 34.0),    # 전남 → 남쪽으로 크게(광주와 분리)
    "31": (0.0, 0.0),      # 울산 → 지역 정중앙(대표 지시)
    "26": (0.0, 14.0),     # 부산 → 아래로(대표 지시, 울산과 분리)
    "27": (0.0, 0.0),      # 대구 → 지역 정중앙
    "47": (24.0, -24.0),   # 경북 → 북동(대구와 분리, 경북 안)
    "52": (0.0, 14.0),     # 전북 → 아래로(대표 지시). 광주와 최소 36px 확보 선에서
}


def polygons_of(geom: dict) -> list:
    """Polygon/MultiPolygon → 바깥 링 목록(구멍은 전국 지도에서 무의미하므로 버린다)."""
    t = geom.get("type")
    if t == "Polygon":
        return [geom["coordinates"][0]]
    if t == "MultiPolygon":
        return [poly[0] for poly in geom["coordinates"]]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="ne_10m_admin_1_states_provinces.geojson 경로")
    ap.add_argument(
        "--out",
        default=str(
            Path(__file__).resolve().parents[2]
            / "frontend/components/mappreview/koreaPaths.json"
        ),
    )
    args = ap.parse_args()

    data = json.loads(Path(args.src).read_text(encoding="utf-8"))
    feats = []
    for f in data["features"]:
        props = f["properties"]
        # ★ 국가 필터 필수 — Natural Earth 에는 **북한에도 "강원도"가 있다**(실측: 남한 강원
        # 36.61~38.62°N, 북한 강원 38.17~39.41°N). 이름만으로 거르면 북한 강원이 섞여 들어와
        # 지도가 북쪽으로 늘어나고 강원 라벨이 서울보다 한참 위에 찍힌다(2026-08-01 대표 지적).
        if props.get("adm0_a3") != "KOR" and props.get("iso_a2") != "KR":
            continue
        code = NAME_KO_TO_SIDO.get((props.get("name_ko") or "").strip())
        if code:
            feats.append((code, f["geometry"]))
    if len(feats) != len(NAME_KO_TO_SIDO):
        got = {c for c, _ in feats}
        missing = [k for k, v in NAME_KO_TO_SIDO.items() if v not in got]
        print(f"[경고] 매핑 못한 시도: {missing}")

    # --- 1) 링 추출 + 작은 섬 제거 ---
    per_code: dict[str, list] = {}
    for code, geom in feats:
        rings = [r for r in polygons_of(geom) if ring_area(r) >= MIN_RING_AREA]
        if not rings:  # 전부 걸러졌으면 가장 큰 것 하나는 살린다(빈 지역 방지)
            allr = polygons_of(geom)
            rings = [max(allr, key=ring_area)] if allr else []
        per_code[code] = rings

    # --- 2) 투영 범위 계산 ---
    xs = [p[0] for rings in per_code.values() for r in rings for p in r]
    ys = [p[1] for rings in per_code.values() for r in rings for p in r]
    lng0, lng1, lat0, lat1 = min(xs), max(xs), min(ys), max(ys)
    lat_mid = (lat0 + lat1) / 2.0
    kx = math.cos(math.radians(lat_mid))  # 경도 1도의 실제 폭 보정

    w = (lng1 - lng0) * kx
    h = lat1 - lat0
    scale = min((VIEW_W - 2 * PADDING) / w, (VIEW_H - 2 * PADDING) / h)
    off_x = (VIEW_W - w * scale) / 2.0
    off_y = (VIEW_H - h * scale) / 2.0

    def project(p):
        x = (p[0] - lng0) * kx * scale + off_x
        y = (lat1 - p[1]) * scale + off_y  # 위도는 위아래 반전
        return round(x, 2), round(y, 2)

    # --- 3) 단순화 → path 문자열 ---
    out = []
    for code, rings in sorted(per_code.items()):
        d_parts = []
        for r in rings:
            # 2026-08-01(대표 지적 "울릉도·독도 어디 갔냐") — 고정 허용오차로 단순화하면
            # **작은 섬이 통째로 사라진다**. 울릉도는 원본에 정점 15개(0.115°×0.09°)로 존재하는데
            # tol=0.004 를 그대로 먹이면 점이 2개 이하로 줄어 `len<3` 조건에 걸려 버려졌다.
            # 링의 실제 크기에 비례해 허용오차를 낮춘다 — 큰 도는 그대로 가볍게, 섬은 형태 보존.
            span = max(
                max(p[0] for p in r) - min(p[0] for p in r),
                max(p[1] for p in r) - min(p[1] for p in r),
            )
            tol = min(SIMPLIFY_TOLERANCE, span / 12.0)
            simplified = simplify(r, tol)
            if len(simplified) < 3:
                continue
            pts = [project(p) for p in simplified]
            d_parts.append(
                "M" + " L".join(f"{x},{y}" for x, y in pts) + " Z"
            )
        if not d_parts:
            continue
        # 라벨 위치 = 가장 큰 링의 **면적 중심**(폴리곤 centroid).
        # 정점 평균을 쓰면 해안선처럼 정점이 촘촘한 쪽으로 라벨이 끌려간다.
        biggest = max(rings, key=ring_area)
        bp = [project(p) for p in biggest]
        cx, cy = polygon_centroid(bp)
        dx, dy = LABEL_NUDGE.get(code, (0.0, 0.0))
        cx, cy = round(cx + dx, 1), round(cy + dy, 1)
        out.append(
            {
                "sido_code": code,
                "short_name": SHORT_NAME[code],
                "d": " ".join(d_parts),
                "label": {"x": cx, "y": cy},
            }
        )

    # --- 독도(2026-08-01) ---
    # Natural Earth admin-1 에는 **독도가 없다**(분쟁지역으로 별도 레이어 분류). 그래서 좌표를
    # 직접 넣는다. 실제 위치는 37.2429N / 131.8667E 로 공개된 값이다.
    # 다만 면적이 약 0.19km² 라 이 축척에서는 **1픽셀도 안 된다** — 진짜 폴리곤으로 그리면
    # 보이지도 않는다. 그래서 지도에는 '위치 표식'으로 그리고, 화면에서 별도 인셋으로 안내한다.
    # (지도가 독도를 실제 크기로 그린 척하지 않는다.)
    dokdo_lng, dokdo_lat = 131.8667, 37.2429
    dokdo_x = (dokdo_lng - lng0) * kx * scale + off_x
    dokdo_y = (lat1 - dokdo_lat) * scale + off_y

    payload = {
        "dokdo": {
            "name": "독도",
            "lat": dokdo_lat,
            "lng": dokdo_lng,
            "x": round(dokdo_x, 1),
            "y": round(dokdo_y, 1),
            "note": "실제 좌표. 축척상 면적이 1px 미만이라 표식으로 그린다.",
        },
        "source": "Natural Earth (ne_10m_admin_1_states_provinces) — public domain",
        "source_url": "https://github.com/nvkelso/natural-earth-vector",
        "license": "Public domain. Commercial use permitted; attribution not required.",
        "generated_by": "backend/scripts/build_korea_svg_paths.py",
        "view_box": f"0 0 {int(VIEW_W)} {int(VIEW_H)}",
        "regions": out,
    }
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    size_kb = p.stat().st_size / 1024
    print(f"생성: {p}  ({size_kb:.0f} KB, 지역 {len(out)}개)")
    for r in out:
        print(f"  {r['short_name']:4} path {len(r['d']):>6}자")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
