# -*- coding: utf-8 -*-
"""숨은길 인프라 다이어그램 생성기 (BCSD Infra Structure 스타일 참고).

사용법 (docs/ 에서):
  mkdir icons && cd icons && npm init -y && npm i simple-icons@16.29.0 && cd ..
  python architecture.gen.py            # architecture.svg / architecture.html 생성
  chrome --headless=new --window-size=1800,1000 --force-device-scale-factor=3 \n         --screenshot=architecture.png file:///<절대경로>/architecture.html
구성이 바뀌면 이 파일의 노드·화살표를 고치고 다시 뽑는다. 로고는 simple-icons(CC0).
"""
import re, pathlib

HERE = pathlib.Path(__file__).parent
ICONS = HERE / "icons" / "node_modules" / "simple-icons" / "icons"

def icon_path(name):
    svg = (ICONS / f"{name}.svg").read_text(encoding="utf-8")
    return re.search(r'd="([^"]+)"', svg).group(1)

BRAND = {
    "nginx": "#009639", "docker": "#2496ED", "postgresql": "#4169E1", "nextdotjs": "#111111",
    "fastapi": "#009688", "ollama": "#111111", "prometheus": "#E6522C", "grafana": "#F46800",
    "github": "#181717", "githubactions": "#2088FF", "letsencrypt": "#003A70", "naver": "#03C75A",
    "kakao": "#3C1E1E", "google": "#4285F4", "python": "#3776AB",
}

W, H = 1800, 1000
out = []
def add(s): out.append(s)

# ---------- 프리미티브 ----------
def icon(name, cx, cy, size=44, color=None):
    d = icon_path(name)
    c = color or BRAND[name]
    s = size / 24
    add(f'<g transform="translate({cx - size/2:.1f},{cy - size/2:.1f}) scale({s:.4f})"><path d="{d}" fill="{c}"/></g>')

TYPE_SCALE = 1.18
def text(x, y, s, size=15, weight=600, fill="#1F2328", anchor="middle", family="sans", ls=0):
    size = round(size * TYPE_SCALE, 1)
    fam = "'IBM Plex Sans KR','Malgun Gothic',sans-serif" if family == "sans" else "'IBM Plex Mono',Consolas,monospace"
    add(f'<text x="{x}" y="{y}" font-family="{fam}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" letter-spacing="{ls}">{s}</text>')

def node(name, cx, cy, title, sub=None, size=46, color=None, title_size=15):
    icon(name, cx, cy, size, color)
    text(cx, cy + size/2 + 22, title, title_size, 600)
    if sub:
        text(cx, cy + size/2 + 40, sub, 12, 400, "#57606A")

def box(x, y, w, h, r=22, stroke="#1F2328", fill="#FFFFFF", sw=2.5, dash=None):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{da}/>')

def caption(x, y, s, color="#176B55", size=16):
    """박스 아래 캡션 — BCSD의 'Build / Production / DB' 오렌지 라벨 자리."""
    text(x, y, s, size, 700, color, "start", ls=0.3)

COLORS = {"traffic": "#1E8E5A", "internal": "#1D63ED", "alert": "#D93025", "backup": "#E8871E", "ext": "#6E7781"}
def arrow(pts, kind="traffic", label=None, lx=None, ly=None, dash=None, lanchor="middle", lfam="sans", lsize=12.5):
    c = COLORS[kind]
    d = " ".join(f"{p[0]},{p[1]}" for p in pts)
    da = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<polyline points="{d}" fill="none" stroke="{c}" stroke-width="2.8" marker-end="url(#ah-{kind})"{da} stroke-linejoin="round"/>')
    if label:
        if lx is None:
            (x1, y1), (x2, y2) = pts[0], pts[-1]
            lx, ly = (x1 + x2) / 2, (y1 + y2) / 2 - 8
        tw = len(label) * (lsize * TYPE_SCALE * 0.62 if lfam == "sans" else lsize * TYPE_SCALE * 0.6) + 14
        ax = lx - tw / 2 if lanchor == "middle" else (lx - 6 if lanchor == "start" else lx - tw + 6)
        add(f'<rect x="{ax:.1f}" y="{ly - lsize*TYPE_SCALE - 2}" width="{tw:.1f}" height="{lsize*TYPE_SCALE + 8}" rx="6" fill="#FFFFFF" opacity="0.92"/>')
        text(lx, ly, label, lsize, 600, c, lanchor, lfam)

# ---------- 캔버스 ----------
add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
add("""<defs>
<style>@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;600;700&amp;family=IBM+Plex+Mono:wght@500&amp;display=swap');</style>
""" + "".join(f'<marker id="ah-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>' for k, c in COLORS.items()) + "</defs>")
add(f'<rect width="{W}" height="{H}" fill="#12151B"/>')
add(f'<rect x="30" y="72" width="{W-60}" height="{H-102}" rx="16" fill="#FFFFFF"/>')
# 제목 (다크 프레임 위)
add('<rect x="34" y="22" width="26" height="30" rx="5" fill="#176B55"/>')
add('<path d="M40 44 L47 30 L52 39 L56 33 L60 44 Z" fill="#FFFFFF"/>')
text(72, 44, "숨은길 Infra Structure", 22, 700, "#FFFFFF", "start")
text(W - 40, 44, "sumeungil.co.kr · 2026-09 기준 · 실제 deploy/docker-compose.yml 구성", 13, 400, "#9AA4AF", "end", "mono")

# ---------- 왼쪽: Slack · 사용자 · GitHub ----------
# Slack (심볼은 4색 알약) — BCSD처럼 좌상단
def slack(cx, cy):
    for (dx, dy, rot, col) in [(-10, -4, 0, "#36C5F0"), (4, -10, 90, "#2EB67D"), (10, 4, 180, "#ECB22E"), (-4, 10, 270, "#E01E5A")]:
        add(f'<rect x="{cx+dx-14}" y="{cy+dy-4}" width="24" height="8" rx="4" fill="{col}" transform="rotate({rot} {cx+dx} {cy+dy})"/>')
slack(140, 150)
text(140, 192, "Slack 알림-봇", 15, 600)
text(140, 210, "에러 · 이상 · 아침 요약 · /서버상태", 12, 400, "#57606A")

# 여행자 (브라우저) — nginx와 같은 높이에 두어 트래픽 화살표가 일직선이 되게
add('<rect x="98" y="398" width="84" height="64" rx="10" fill="#FFFFFF" stroke="#1F2328" stroke-width="2.5"/>')
add('<rect x="98" y="398" width="84" height="16" rx="8" fill="#1F2328"/><rect x="98" y="406" width="84" height="8" fill="#1F2328"/>')
add('<circle cx="108" cy="406" r="3" fill="#FF5F57"/><circle cx="118" cy="406" r="3" fill="#FEBC2E"/><circle cx="128" cy="406" r="3" fill="#28C840"/>')
icon("naver", 140, 440, 22)
text(140, 486, "여행자 브라우저", 15, 600)
text(140, 504, "Next.js 화면 · NAVER 지도 SDK", 12, 400, "#57606A")
text(140, 524, "브라우저는 nginx만 본다", 12, 400, "#57606A")

node("github", 140, 700, "GitHub", "develop → main 릴리스", 46)
node("githubactions", 140, 850, "GitHub Actions", "CI · 의존성 감사 · 30분 헬스체크", 42)

# ---------- 가운데: NAVER Cloud VM ----------
VX, VY, VW, VH = 330, 150, 850, 780
box(VX, VY, VW, VH, 26)
icon("naver", VX + 30, VY + 30, 26)
text(VX + 52, VY + 36, "NAVER Cloud VM 1대 · Docker Compose · 컨테이너 8개", 15, 700, "#1F2328", "start")
caption(VX + 6, VY + VH + 28, "Production", size=17)
text(VX + 150, VY + VH + 28, "2 vCPU · 15GB · x86_64 · Rocky Linux", 13, 400, "#57606A", "start")

# 엣지 서브박스 (호스트에 열린 포트)
box(VX + 20, VY + 70, 230, 400, 18, "#1E8E5A", "#F1FAF5", 2)
text(VX + 135, VY + 96, "호스트에 열린 포트: 80 · 443뿐", 13, 700, "#1E8E5A")
node("letsencrypt", VX + 135, VY + 150, "certbot", "Let's Encrypt · 12h 자동 갱신", 40)
node("nginx", VX + 135, VY + 300, "nginx", "TLS 종단 · 리버스 프록시", 52)
text(VX + 135, VY + 388, "봇 경로 차단 · LLM 경로별 타임아웃", 12, 400, "#57606A")
arrow([(VX + 135, VY + 208), (VX + 135, VY + 268)], "internal", "인증서", dash="4 4", lx=VX + 165, ly=VY + 244)

# 앱 컨테이너
node("nextdotjs", 700, 300, "frontend", "Next.js 15 · :3000", 48)
node("fastapi", 700, 520, "backend", "FastAPI · Python 3.12 · :8000", 48)
text(700, 602, "레이트리밋 · 인메모리 캐시 · 세션 쿠키", 12, 400, "#57606A")

# Docker 내부망 박스
DX, DY, DW, DH = 860, 220, 300, 690
box(DX, DY, DW, DH, 22, "#2496ED", "#EAF4FF", 2.5)
icon("docker", DX + 34, DY + 30, 30)
text(DX + 56, DY + 36, "도커 내부망 · 호스트 포트 없음", 13, 700, "#1D63ED", "start")
def tile(cy, name, title, sub, sub2=None, color=None):
    box(DX + 24, cy - 52, DW - 48, 118, 14, "#B6D4F5", "#FFFFFF", 1.5)
    icon(name, DX + 62, cy - 6, 40, color)
    text(DX + 96, cy - 10, title, 15, 700, "#1F2328", "start")
    text(DX + 96, cy + 10, sub, 12, 400, "#57606A", "start")
    if sub2: text(DX + 96, cy + 28, sub2, 12, 400, "#57606A", "start")
tile(DY + 118, "postgresql", "postgres 16", "회원 · 취향 · AI코스 · 후기", "공유코스 · 문의 · 방문로그")
tile(DY + 262, "ollama", "ollama · Qwen", "로컬 추론 · 외부 전송 없음", "취향 추출 · 코스 요약 · 여행 팁")
tile(DY + 406, "prometheus", "prometheus", "backend /metrics 수집", "Grafana는 nginx /prom/ 경유")
tile(DY + 550, "python", "postgres-backup", "pg_dump 매일 · 로컬 14일 보관", "S3 호환 버킷으로 오프사이트")

# ---------- 오른쪽: 외부 ----------
RX, RW = 1280, 470
# 공공데이터포털
box(RX, 150, RW, 300, 22)
add(f'<rect x="{RX+22}" y="170" width="92" height="26" rx="6" fill="#1F2328"/>')
text(RX + 68, 188, "data.go.kr", 12, 700, "#FFFFFF", "middle", "mono")
text(RX + 126, 189, "공공데이터포털 · backend만 호출", 14, 700, "#1F2328", "start")
rows = [("한국관광공사 TourAPI", "관광지 · 축제 · 사진 · 상세"),
        ("한국관광공사 집중률", "관광지별 혼잡도 예측 · 오늘부터 17일"),
        ("기상청 관광지 단기예보", "날씨 재정렬 · 실내 스팟 우선"),
        ("공공데이터 표준 문화축제", "축제 일정 · 지역 매칭")]
for i, (t, s) in enumerate(rows):
    y = 228 + i * 54
    add(f'<circle cx="{RX+34}" cy="{y-5}" r="5" fill="#1E8E5A"/>')
    text(RX + 50, y, t, 14, 600, "#1F2328", "start")
    text(RX + 50, y + 18, s, 12, 400, "#57606A", "start")
caption(RX + 6, 478, "Public Data")

# 외부 서비스
box(RX, 490, RW, 190, 22)
text(RX + 22, 520, "외부 서비스 — backend만 호출", 14, 700, "#1F2328", "start")
# Tmap: 경로 핀 아이콘 (자체 드로잉)
add(f'<g transform="translate({RX+70},590)"><path d="M0,-22 C-12,-22 -20,-13 -20,-3 C-20,10 0,26 0,26 C0,26 20,10 20,-3 C20,-13 12,-22 0,-22 Z" fill="#E8371E"/><circle cx="0" cy="-4" r="7" fill="#FFFFFF"/></g>')
text(RX + 70, 636, "SK Tmap 경로", 14, 600)
text(RX + 70, 654, "도보 · 자동차 이동시간", 12, 400, "#57606A")
node("google", RX + 235, 586, "Google OAuth", "로그인", 40)
add(f'<rect x="{RX+360}" y="566" width="40" height="40" rx="10" fill="#FFCD00"/>')
icon("kakao", RX + 380, 586, 26, "#3C1E1E")
text(RX + 380, 636, "Kakao OAuth", 14, 600)
text(RX + 380, 654, "로그인", 12, 400, "#57606A")
caption(RX + 6, 700, "External")

# 운영·감시
box(RX, 740, RW, 190, 22)
text(RX + 22, 770, "운영 · 감시 — VM 밖", 14, 700, "#1F2328", "start")
node("grafana", RX + 110, 840, "Grafana", "aitestbed.kr · 외부 대시보드", 42)
# S3 호환 버킷 (원통)
bx, by = RX + 340, 840
add(f'<ellipse cx="{bx}" cy="{by-20}" rx="26" ry="9" fill="#E8871E"/><rect x="{bx-26}" y="{by-20}" width="52" height="40" fill="#E8871E"/><ellipse cx="{bx}" cy="{by+20}" rx="26" ry="9" fill="#C46E12"/><ellipse cx="{bx}" cy="{by-20}" rx="26" ry="9" fill="#F3A54A"/>')
text(bx, by + 50, "오프사이트 백업 버킷", 14, 600)
text(bx, by + 68, "S3 호환 · 매일 업로드", 12, 400, "#57606A")
caption(RX + 6, 958, "Ops")

# ---------- 화살표 ----------
NGX, NGY = VX + 135, VY + 300         # nginx 중심 (465, 450)
# 여행자 → nginx (일직선)
arrow([(192, 436), (NGX - 30, 436)], "traffic", "https://sumeungil.co.kr", lx=300, ly=426, lfam="mono", lsize=12)
# GitHub Actions → nginx 헬스체크 (nginx 왼쪽 아래로 진입)
arrow([(190, 850), (320, 850), (320, 464), (NGX - 30, 464)], "traffic", "GET /api/v1/health · 30분마다", lx=300, ly=842, dash="6 4", lfam="mono", lsize=11.5)
# nginx → frontend / backend
arrow([(NGX + 34, NGY - 10), (640, NGY - 10), (640, 300), (672, 300)], "traffic", "/", lx=600, ly=305)
arrow([(NGX + 34, NGY + 10), (600, NGY + 10), (600, 520), (672, 520)], "traffic", "/api/  ·  /health", lx=600, ly=500, lfam="mono", lsize=12)
# backend → postgres / ollama
arrow([(740, 505), (DX + 24, DY + 118)], "internal", "저장 · 조회", lx=800, ly=410)
arrow([(740, 520), (DX + 24, DY + 262)], "internal", ":11434", lx=810, ly=500, lfam="mono", lsize=12)
# prometheus → backend (scrape) — 오른쪽 아래에서 들어온다
arrow([(DX + 24, DY + 406), (812, DY + 406), (812, 540), (728, 540)], "internal", "scrape /metrics", lx=840, ly=650, dash="5 4")
# GitHub → GitHub Actions
arrow([(140, 745), (140, 820)], "ext", "push · PR", lx=190, ly=788)
# backend → Slack (에러/요약): VM 위쪽 여백으로 빠져나가 좌상단 Slack으로
arrow([(676, 548), (620, 548), (620, 110), (160, 110), (160, 130)], "alert", "에러 · 이상 · 아침 요약", lx=400, ly=104)
# GitHub Actions → Slack: 패널 왼쪽 가장자리를 따라 위로
arrow([(118, 850), (48, 850), (48, 150), (106, 150)], "alert", "장애 · 복구 알림", lx=80, ly=300, lanchor="middle")
# backend → 외부 API: 도커 박스 위쪽으로 나가 오른쪽 거터(x=1230)에서 갈라진다
arrow([(722, 496), (800, 496), (800, 205), (RX, 205)], "ext", "관광지 · 혼잡도 · 날씨 · 축제", lx=1030, ly=197, dash="6 4")
arrow([(1230, 205), (1230, 586), (RX, 586)], "ext", "Tmap · OAuth", lx=1230, ly=560, dash="6 4")
# backup → S3
arrow([(DX + DW, DY + 550), (1230, DY + 550), (1230, 840), (RX + 314, 840)], "backup", "오프사이트", lx=1230, ly=810, dash="4 4")
# Grafana → nginx /prom/ → prometheus (두 박스 사이 틈으로)
arrow([(RX + 110, 812), (RX + 110, 726), (1200, 726), (1200, DY + 406), (DX + DW, DY + 406)], "internal", "nginx /prom/ · Basic Auth", lx=1300, ly=720, dash="5 4")

# ---------- 범례 ----------
lx0, ly0 = 60, 986
for i, (k, label) in enumerate([("traffic", "사용자 트래픽"), ("internal", "내부망"), ("ext", "외부 API"), ("alert", "알림"), ("backup", "백업")]):
    x = lx0 + i * 150
    add(f'<line x1="{x}" y1="{ly0-4}" x2="{x+28}" y2="{ly0-4}" stroke="{COLORS[k]}" stroke-width="3"/>')
    text(x + 36, ly0, label, 12, 500, "#9AA4AF", "start")

add("</svg>")
svg = "\n".join(out)
(HERE / "architecture.svg").write_text(svg, encoding="utf-8")
html = f'<!doctype html><meta charset="utf-8"><style>html,body{{margin:0;background:#12151B}}</style>{svg}'
(HERE / "architecture.html").write_text(html, encoding="utf-8")
print("ok", len(svg))
