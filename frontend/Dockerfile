# 숨은길 frontend (Next.js 15 App Router) — Oracle Always Free ARM (aarch64) 배포용
#
# ARM64 메모: node:20-alpine 은 멀티아치(linux/amd64 + linux/arm64)라 ARM VM 에서 그대로
# 빌드하면 arm64 레이어가 자동 선택된다. --platform 불필요.
#
# 출력 모드: next.config.js 에 `output: 'standalone'` 이 **설정되어 있지 않으므로**
# 표준 `next build` → `next start` 방식을 쓴다. (standalone 으로 바꾸면 이미지가 더 작아지지만
# next.config.js 변경 = 로컬 빌드 동작 변경이라 배포 준비 단계에서는 건드리지 않는다.)
#
# ###########################################################################
# NEXT_PUBLIC_* 는 전부 "빌드타임" 값이다 (중요)
#   Next.js 는 `next build` 시점에 process.env.NEXT_PUBLIC_* 를 클라이언트 번들에
#   **문자열로 인라인**한다. 컨테이너 런타임에 environment 로 넣어봐야 이미 구워진 번들은
#   바뀌지 않는다. 따라서 ARG 로 받아 build 스테이지의 ENV 로 올린다.
#   → 백엔드 주소가 바뀌면 **재빌드**가 필요하다(`docker compose build frontend`).
# ###########################################################################

# ---------- 1) deps: 의존성만 설치(락파일 기준, 재현 가능) ----------
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---------- 2) build: next build ----------
FROM node:20-alpine AS build
WORKDIR /app

# 빌드타임 주입값. 값이 없으면 lib/api.ts 의 폴백(http://localhost:8000)이 구워져
# 배포 후 브라우저가 자기 자신을 호출하게 되므로 반드시 넘겨야 한다.
ARG NEXT_PUBLIC_API_BASE
# Tmap JS SDK 용 브라우저 공개키(부록 E.3, AI 코스짜기 경로선 CourseMap.tsx 전용).
# 서버 시크릿이 아니다 — 이 키는 IP 화이트리스트(서버 IP만 허용)라 서버측 호출에만 쓴다.
ARG NEXT_PUBLIC_TMAP_APP_KEY
# 2026-08-24: 추천 화면 지도(SpotMap.tsx)용 네이버 지도 Client ID. Tmap과 달리
# 도메인(Web 서비스 URL) 화이트리스트라 브라우저에서 정상 동작한다 — 서버 시크릿 아님.
ARG NEXT_PUBLIC_NAVER_MAP_CLIENT_ID
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE \
    NEXT_PUBLIC_TMAP_APP_KEY=$NEXT_PUBLIC_TMAP_APP_KEY \
    NEXT_PUBLIC_NAVER_MAP_CLIENT_ID=$NEXT_PUBLIC_NAVER_MAP_CLIENT_ID \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ---------- 3) runner: 프로덕션 의존성 + 빌드 산출물만 ----------
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    TZ=Asia/Seoul

# devDependencies(typescript, @types/*) 제외 — 런타임에 필요 없다.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

# --chown: next start 가 런타임에 .next/cache 에 쓸 수 있어야 한다(권한 오류 예방).
COPY --from=build --chown=node:node /app/.next ./.next
COPY --from=build --chown=node:node /app/public ./public
COPY --from=build --chown=node:node /app/next.config.js ./next.config.js

# node:alpine 기본 제공 비루트 계정 사용
USER node

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1

CMD ["npm", "run", "start"]
