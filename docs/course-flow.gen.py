# -*- coding: utf-8 -*-
"""AI 코스짜기 요청 흐름 다이어그램 생성기 (architecture.gen.py와 같은 시각 언어)."""
import re, pathlib

HERE = pathlib.Path(__file__).parent
ICONS = HERE / "icons" / "node_modules" / "simple-icons" / "icons"
def icon_path(name):
    return re.search(r'd="([^"]+)"', (ICONS / f"{name}.svg").read_text(encoding="utf-8")).group(1)
BRAND = {"nginx": "#009639", "fastapi": "#009688", "ollama": "#111111", "postgresql": "#4169E1", "naver": "#03C75A"}

W, H = 1800, 1000
out = []
def add(s): out.append(s)
TYPE_SCALE = 1.18
def text(x, y, s, size=15, weight=600, fill="#1F2328", anchor="middle", family="sans"):
    size = round(size * TYPE_SCALE, 1)
    fam = "'IBM Plex Sans KR','Malgun Gothic',sans-serif" if family == "sans" else "'IBM Plex Mono',Consolas,monospace"
    add(f'<text x="{x}" y="{y}" font-family="{fam}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{s}</text>')
def icon(name, cx, cy, size=40, color=None):
    s = size / 24
    add(f'<g transform="translate({cx - size/2:.1f},{cy - size/2:.1f}) scale({s:.4f})"><path d="{icon_path(name)}" fill="{color or BRAND[name]}"/></g>')
def rect(x, y, w, h, r=12, fill="#FFFFFF", stroke="#1F2328", sw=2.5, dash=None, op=1):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{da} opacity="{op}"/>')

COLORS = {"req": "#1E8E5A", "int": "#1D63ED", "ext": "#6E7781", "warn": "#C98217", "resp": "#7950B3"}
add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
add("<defs><style>@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;600;700&amp;family=IBM+Plex+Mono:wght@500&amp;display=swap');</style>"
    + "".join(f'<marker id="ah-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>' for k, c in COLORS.items())
    + "</defs>")
add(f'<rect width="{W}" height="{H}" fill="#12151B"/>')
add(f'<rect x="30" y="72" width="{W-60}" height="{H-102}" rx="16" fill="#FFFFFF"/>')
add('<rect x="34" y="22" width="26" height="30" rx="5" fill="#176B55"/><path d="M40 44 L47 30 L52 39 L56 33 L60 44 Z" fill="#FFFFFF"/>')
text(72, 44, "AI 코스짜기 한 번에 일어나는 일", 22, 700, "#FFFFFF", "start")
text(W - 40, 44, "POST /api/v1/courses/recommend · backend/app/services/course_service.py", 13, 400, "#9AA4AF", "end", "mono")

# ---------- 레인 ----------
LANES = [
    ("user", 175, "여행자 브라우저", "Next.js 화면"),
    ("nginx", 430, "nginx", "LLM 경로 타임아웃"),
    ("fastapi", 700, "backend", "FastAPI"),
    ("tmap", 980, "SK Tmap", "경로 API"),
    ("ollama", 1260, "ollama", "Qwen 로컬 LLM"),
    ("postgresql", 1560, "postgres", "AI 코스 저장"),
]
TOP, BOTTOM = 118, 880
X = {k: x for k, x, *_ in LANES}
for key, x, title, sub in LANES:
    rect(x - 110, TOP, 220, 74, 14, "#F6F8F7", "#1F2328", 2)
    ix = x - 74
    if key == "user":
        add(f'<rect x="{ix-20}" y="{TOP+22}" width="40" height="30" rx="6" fill="#FFFFFF" stroke="#1F2328" stroke-width="2"/><rect x="{ix-20}" y="{TOP+22}" width="40" height="9" rx="4" fill="#1F2328"/>')
        icon("naver", ix, TOP + 42, 12)
    elif key == "tmap":
        add(f'<g transform="translate({ix},{TOP+40})"><path d="M0,-16 C-9,-16 -15,-10 -15,-2 C-15,7 0,19 0,19 C0,19 15,7 15,-2 C15,-10 9,-16 0,-16 Z" fill="#E8371E"/><circle cx="0" cy="-3" r="5" fill="#FFFFFF"/></g>')
    else:
        icon(key, ix, TOP + 37, 34)
    text(x - 44, TOP + 33, title, 15, 700, "#1F2328", "start")
    text(x - 44, TOP + 55, sub, 11.5, 400, "#57606A", "start")
    add(f'<line x1="{x}" y1="{TOP+74}" x2="{x}" y2="{BOTTOM}" stroke="#C9D1D9" stroke-width="2" stroke-dasharray="6 6"/>')

# ---------- 밴드 (par / alt / opt) ----------
def band(y1, y2, x1, x2, color, fill, tag, title):
    rect(x1, y1, x2 - x1, y2 - y1, 14, fill, color, 2, "7 5", 1)
    tw = len(tag) * 9 + 22
    ttl_w = len(title) * 13 * TYPE_SCALE * 0.62 + 16
    add(f'<rect x="{x1+10}" y="{y1-15}" width="{tw + ttl_w + 12}" height="30" rx="15" fill="#FFFFFF"/>')
    add(f'<rect x="{x1+14}" y="{y1-13}" width="{tw}" height="26" rx="13" fill="{color}"/>')
    text(x1 + 14 + tw / 2, y1 + 5, tag, 12, 700, "#FFFFFF", "middle", "mono")
    text(x1 + 14 + tw + 10, y1 + 5, title, 13, 600, color, "start")

# ---------- 스텝 ----------
STEP_R = 13
def step_no(x, y, n, color):
    add(f'<circle cx="{x}" cy="{y}" r="{STEP_R}" fill="{color}"/>')
    text(x, y + 5, str(n), 12, 700, "#FFFFFF", "middle", "mono")
def msg(n, frm, to, y, label, kind="req", sub=None, lfam="sans"):
    x1, x2 = X[frm], X[to]
    c = COLORS[kind]
    d = 1 if x2 > x1 else -1
    add(f'<line x1="{x1 + d*STEP_R}" y1="{y}" x2="{x2 - d*4}" y2="{y}" stroke="{c}" stroke-width="2.6" marker-end="url(#ah-{kind})"/>')
    step_no(x1, y, n, c)
    mx = (x1 + x2) / 2
    text(mx, y - 9, label, 13, 600, c, "middle", lfam)
    if sub: text(mx, y + 20, sub, 11.5, 400, "#57606A", "middle")
def selfmsg(n, lane, y, label, kind="int", sub=None):
    x = X[lane]; c = COLORS[kind]
    add(f'<path d="M{x+STEP_R},{y} h44 a10,10 0 0 1 10,10 v14 a10,10 0 0 1 -10,10 h-40" fill="none" stroke="{c}" stroke-width="2.6" marker-end="url(#ah-{kind})"/>')
    step_no(x, y, n, c)
    text(x + 72, y + 10, label, 13, 600, c, "start")
    if sub: text(x + 72, y + 30, sub, 11.5, 400, "#57606A", "start")

y = 228
msg(1, "user", "nginx", y, "POST /api/v1/courses/recommend", "req", "지역 · 취향 프로필 · (선택) 직접 고른 스팟", "mono")
y += 56
msg(2, "nginx", "fastapi", y, "프록시", "req", "이 경로만 긴 타임아웃 · 레이트리밋 통과")
y += 50
selfmsg(3, "fastapi", y, "캐시된 스팟 풀에서 후보 선정 · 점수화", "int", "취향 · 혼잡도 · 거리 — LLM 안 씀")

# par 밴드: Tmap 동시 호출
py1 = y + 56
band(py1, py1 + 128, X["fastapi"] - 40, X["tmap"] + 150, "#1E8E5A", "#F1FAF5", "par", "구간마다 동시에 — asyncio.gather")
msg(4, "fastapi", "tmap", py1 + 36, "도보 경로", "ext")
msg(5, "fastapi", "tmap", py1 + 66, "자동차 경로", "ext")
msg(6, "tmap", "fastapi", py1 + 100, "이동시간 · 거리", "ext", "실패한 구간은 \"이동 정보 없음\" — 값을 지어내지 않는다")
y = py1 + 128

# alt 밴드: 요약
ay1 = y + 40
band(ay1, ay1 + 150, X["fastapi"] - 40, X["ollama"] + 150, "#C98217", "#FFF8EA", "alt", "코스 요약 — 동시 1건(세마포어) · 타임아웃")
msg(7, "fastapi", "ollama", ay1 + 36, "코스 요약 요청", "warn", "스팟 순서 조합이 같으면 24h 캐시 재사용")
msg(8, "ollama", "fastapi", ay1 + 80, "JSON 요약", "warn")
add(f'<line x1="{X["fastapi"]-30}" y1="{ay1+98}" x2="{X["ollama"]+140}" y2="{ay1+98}" stroke="#C98217" stroke-width="1.5" stroke-dasharray="4 4"/>')
selfmsg(9, "fastapi", ay1 + 112, "타임아웃 · 형식 오류 → 요약 없이 진행", "warn", "ai_summary: null — 화면은 그대로 뜬다")
y = ay1 + 150

# opt 밴드: 저장
oy1 = y + 36
band(oy1, oy1 + 66, X["fastapi"] - 40, X["postgresql"] + 150, "#1D63ED", "#EEF4FF", "opt", "로그인 상태면")
msg(10, "fastapi", "postgresql", oy1 + 38, "AI 코스 저장", "int", "마이페이지 · /saved에서 다시 본다")
y = oy1 + 66

# 응답
y += 44
msg(11, "fastapi", "user", y, "스팟 순서 · 구간 이동 · 지도 좌표 · 요약", "resp", "CourseTimelinePanel + CourseMap(NAVER 지도)로 렌더")

# ---------- 각주 · 범례 ----------
text(60, BOTTOM + 28, "LLM이 도는 경로는 이것과 온보딩 취향 분석, 개인화 여행 팁 셋뿐이고, 셋 다 실패해도 화면이 깨지지 않는 폴백이 있다.", 12.5, 400, "#57606A", "start")
text(60, BOTTOM + 50, "nginx는 이 세 경로(/api/v1/courses/ · /onboarding/ · /tips/)에만 긴 타임아웃을 준다. LLM 경로 레이트리밋은 IP당 분당 6회.", 12.5, 400, "#57606A", "start")
lx0, ly0 = 60, 986
for i, (k, label) in enumerate([("req", "요청"), ("int", "내부"), ("ext", "외부 API"), ("warn", "LLM · 폴백"), ("resp", "응답")]):
    x = lx0 + i * 150
    add(f'<line x1="{x}" y1="{ly0-4}" x2="{x+28}" y2="{ly0-4}" stroke="{COLORS[k]}" stroke-width="3"/>')
    text(x + 36, ly0, label, 12, 500, "#9AA4AF", "start")

add("</svg>")
svg = "\n".join(out)
(HERE / "course-flow.svg").write_text(svg, encoding="utf-8")
(HERE / "course-flow.html").write_text(f'<!doctype html><meta charset="utf-8"><style>html,body{{margin:0;background:#12151B}}</style>{svg}', encoding="utf-8")
print("ok", len(svg))
