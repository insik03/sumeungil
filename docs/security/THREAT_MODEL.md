# Threat Model: 숨은길 (sumeungil)

> 7차 보안 감사(2026-09-14) — 위협 모델링 회차. 이 문서는 "어떤 버그가 있는가"가 아니라 "누가·어디서·무엇을 노릴 수 있는가"를 적는다. 개별 취약점은 `evidence` 열의 근거로만 등장한다. 한 줄 패치로 사라지는 항목은 위협이 아니라 취약점이므로 여기 두지 않았다. 스키마는 `threat-model` 스킬(anthropics/defending-code-reference-harness) 규격을 따르며, 신뢰경계·공격자 프로필·가용성 등급은 `mantis-threat-model` 구성을 흡수했다.

## 1. System context

숨은길(sumeungil.co.kr)은 2026 관광데이터 활용 공모전 출품작으로, 공공데이터(관광공사 집중률·TourAPI·기상청 D18·표준데이터 축제)와 사용자의 여행 취향을 결합해 붐비지 않는 관광지와 하루 코스를 추천하는 한국어 웹 서비스다. Python 3.12 FastAPI 백엔드(라우터 19개, HTTP 라우트 74개), Next.js 15 App Router 프론트엔드, PostgreSQL 16, nginx, Prometheus, 로컬 Ollama(폴백)로 구성되며 Python/TS 소스 약 413개 파일, 커밋 234개 규모다. NAVER Cloud VM 1대(2 vCPU)에 Docker Compose로 컨테이너 8개를 올리고 호스트에는 nginx 80/443만 열린다. **Intent: PRODUCTION** — 실사용자가 있는 운영 서비스이고 공모전 심사 기간(2026-10~12월) 가용성이 중요하다.

사용자 계층은 셋이다. 익명 방문자(조회 API 전부, 브라우저가 만든 `X-Device-Id`로 리뷰·코스공유 작성/수정/삭제/신고), Google·Kakao OAuth 로그인 사용자(온보딩 취향 분석, AI 코스, 저장, 문의, 좋아요, 탈퇴), 관리자 3명(비밀번호 1개 공유 + 자기신고 표시 이름, 난독 경로 `/ops-37878f1b71`). 외부 의존은 Google Gemini API(LLM, 국외이전 고지됨), 공공데이터포털, SK Tmap, 네이버 지도 SDK(브라우저), Slack(웹훅·슬래시 명령), n8n(LLM 한도 감시), Grafana(외부 관측), GitHub Actions(CI·헬스 감시·의존성 감사), S3 호환 오프사이트 백업(선택)이다.

이 모델은 소유자 인터뷰 없이 코드·git 이력·과거 감사 보고서(2~6차, 내부 검토 8건)에서 도출했다(bootstrap). 2~6차까지 발견·수정된 취약점 85건(외부 40, 내부 45)을 근거로 쓰되, 그중 4차 DAST·5차 동시성 PoC로 실증된 것만 "실증"으로 표기했다.

## 2. Assets

| asset | description | sensitivity |
|---|---|---|
| 관리자 권한 | `/api/v1/admin/*` 콘솔(숨김·삭제·답변·회원 목록·트래픽). 비밀번호 해시 1개 + 세션 서명키로 보호. 확보 시 모든 UGC·문의 PII·운영 지표 접근 | critical |
| 서버 시크릿 | `ADMIN_PASSWORD_HASH`, `ADMIN_SESSION_SECRET`/`JWT_SECRET_KEY`/`USER_SESSION_SECRET`, OAuth client secrets, `SLACK_SIGNING_SECRET`, `POSTGRES_PASSWORD`, S3 자격증명, `GEMINI_API_KEY`, `PUBLIC_DATA_API_KEY`, `TMAP_APP_KEY`, `SLACK_WEBHOOK_URL`, TLS 개인키 | critical |
| 컨테이너/호스트 실행 무결성 | backend(비루트 10001)·frontend(node)·nginx·postgres·certbot 컨테이너와 VM 호스트 | critical |
| 사용자 계정 PII | users: email, google_sub/kakao_sub, display_name, 로그인 시각; inquiries: message·contact_email(자유서술 PII 가능) | high |
| 서비스 가용성 (CRITICAL tier) | 홈·추천·코스·축제·혼잡도 화면과 API — 심사 기간 24/7 | high |
| 콘텐츠 무결성·신뢰 | 혼잡도/추천 값의 정직성, 리뷰 표시 여부, 공유 코스 내용, "AI 요약/예상치" 고지, 운영자 사칭 차단 | high |
| 저장소·CI 무결성 | insik03/sumeungil develop/main, Actions 시크릿, Dependabot 머지 흐름, 회귀 검증 게이트 | high |
| 외부 API 쿼터/비용 (STANDARD tier) | Gemini 무료 한도(일 20회, #99), Tmap 1,000/일, 공공데이터 1,000/일 — 소진 시 사진·요약·코스 기능 전면 폴백 | medium |
| 사용자 취향 프로필·저장 코스 | onboarding_profiles(태그·벡터, 원문 미저장), ai_courses | medium |
| 방문 집계 가명 지문 | visit_* 테이블의 HMAC ip_hash(90일). 키 유출 시 재식별 가능 | medium |
| 운영 알림·관측 채널 (LOW_CRITICALITY tier) | Slack #알림-봇·#깃허브-알림, Prometheus `/prom/`, `/health/llm` — 스팸·오탐·정보 노출 | medium |
| UGC 소유권 토큰 | localStorage `sumeungil:device-id:v1` — 읽히면 그 기기의 리뷰·공유코스 전권 | medium |

## 3. Entry points & trust boundaries

| entry_point | description | trust_boundary | reachable_assets |
|---|---|---|---|
| E1 공개 조회 API | GET `/api/v1/congestion/*`, `/places/featured|seasonal|search`, `/festivals*`, `/weather/nationwide`, `/plan/outlook`, `/collections`, `/regions/*`, `/reviews`(GET), `/courses/shared`(GET), `/health`; POST `/places/recommend`, `/compare` — 인증 없음, default 버킷 120/분 | unauth internet → nginx → app → 공공데이터 원천(serviceKey) | 외부 API 쿼터, 서비스 가용성, 콘텐츠 무결성 |
| E2 스팟 상세 GET `/api/v1/places/{content_id}` | 비인증·default 버킷. ai_summary 체인: 사전생성 파일(4건) → 24h 캐시 → **라이브 LLM(Gemini)** + TourAPI detailCommon2 | unauth internet → app → LLM·원천 API (비용 경계) | 외부 API 쿼터, 서비스 가용성 |
| E3 UGC 쓰기 (device-id) | POST/PATCH/DELETE `/api/v1/reviews*`, POST `/reviews/{id}/report`, POST `/courses/share`, DELETE `/courses/shared/{code}` — `X-Device-Id`가 소유권 라벨, ugc 버킷 20/분 + 기기별 3~5/분 | pseudo-anonymous internet → 영구 DB 쓰기·공개 콘텐츠 | 콘텐츠 무결성·신뢰, 서비스 가용성(저장소), UGC 소유권 토큰 |
| E4 방문 비콘 POST `/api/v1/visit` | 비인증, 경로 문자열은 클라이언트 제공(정규식·접기), ip_hash 기록 | unauth internet → 통계 DB 쓰기 | 방문 집계 지문, 서비스 가용성 |
| E5 로그인 필수 API | POST `/onboarding/analyze`(LLM), POST `/courses/recommend|arrange`(Tmap+LLM, `wish` 자유서술), `/courses/mine*`, POST `/inquiries`(PII), likes, POST `/tips/personalized`(로그인 시 LLM), `/auth/me`(슬라이딩 재발급), PATCH `/auth/display-name`, DELETE `/auth/me` | authenticated user(HttpOnly 세션 쿠키) → 개인 데이터 + 비싼 경로 + LLM 프롬프트 경계 | 사용자 PII, 취향 프로필, 외부 API 쿼터, 콘텐츠 무결성 |
| E6 OAuth·팝업 | GET `/api/v1/auth/{google,kakao}/{login,callback}` + 콜백 HTML의 `window.opener.postMessage` | Google/Kakao → app(state 서명+nonce 쿠키) → 프론트 오리진(교차 창 메시지) | 사용자 계정 PII, 서비스 세션 |
| E7 관리자 | POST `/api/v1/admin/login`(scrypt, 5/분 라우터 리미터), `/api/v1/admin/*`(세션), GET `/admin/operators`(비인증 불리언), 프론트 `/ops-37878f1b71`. nginx IP allowlist는 주석 처리 상태 | unauth internet → 관리자 인증(비밀번호가 유일한 경계) | 관리자 권한, 사용자 PII, 콘텐츠 무결성 |
| E8 Slack 슬래시 POST `/api/v1/slack/commands` | 서명 HMAC + 5분 창이 유일한 통제, 시크릿 없으면 미등록 | Slack servers → app | 운영 알림·관측 채널(방문·문의 건수) |
| E9 관측·상태 엔드포인트 | backend `/metrics`(도커 내부, 무인증), nginx `/prom/`(Basic Auth, Grafana용), GET `/api/v1/health/llm`(공개), `/health` | docker internal → backend; internet → Prometheus API(Basic Auth) | 운영 알림·관측 채널, 서버 시크릿 간접(메트릭 라벨) |
| E10 nginx·compose·Dockerfile 설정 | XFF `$remote_addr` 덮어쓰기, `--no-proxy-headers`, 포트 미공개(expose만), TLS 1.2/1.3·HSTS 없음, 보안 헤더 4종, 스캐너 444, `client_max_body_size 1m` | 배포 설정 자체가 경계 — 한 줄 회귀로 다른 경계가 무너짐 | 서비스 가용성, 관리자 권한(레이트리밋), 컨테이너 무결성 |
| E11 아웃바운드 클라이언트 | TourAPI/KTO·표준데이터·KMA(serviceKey 쿼리스트링), Tmap(헤더), Gemini(헤더), Ollama(무인증 내부), Slack 웹훅 — 오류 응답 본문이 키를 되비출 수 있음 | app → 외부 SaaS; 응답/로그가 시크릿 유출 경로 | 서버 시크릿, 외부 API 쿼터 |
| E12 브라우저 서드파티·클라이언트 저장소 | `oapi.map.naver.com` 런타임 `<script>` 주입(CSP 미적용), TourAPI 임의 호스트 `<img>`, localStorage device-id·닉네임·온보딩 결과 | third-party origin → 사용자 브라우저 → 우리 오리진의 저장소·세션 | UGC 소유권 토큰, 서비스 세션(간접), 콘텐츠 무결성 |
| E13 의존성·베이스 이미지 | npm 30 직접 의존(lock), pip 8 핀(해시 없음), `python:3.12-slim`·`node:26-alpine`·nginx·postgres·prometheus·ollama·certbot 태그(다이제스트 미고정), deploy/ 이미지는 Dependabot 미커버 | supply_chain → 빌드/런타임 | 컨테이너 무결성, 서비스 가용성 |
| E14 GitHub 저장소·Actions | 워크플로 4개(contents:read, 포크 시크릿 차단), Dependabot PR, 브랜치 보호 없음, CODEOWNERS, 회귀 스크립트 게이트 | 기여자/봇 → main/develop → 배포(git pull) | 저장소·CI 무결성, 서버 시크릿(Actions 시크릿), 컨테이너 무결성 |
| E15 시크릿 저장·배포 경로 | `deploy/.env`(3 컨테이너 공유), sops/age 암호본, certbot 개인키 바인드, `prom.htpasswd`, `deploy/backups/` 덤프 + S3 업로드 | 호스트 파일시스템 ↔ 컨테이너 ↔ 외부 객체저장소 | 서버 시크릿, 사용자 PII(백업), 컨테이너 무결성 |
| E16 백그라운드 태스크 | 기동 프리워밍(원천 수십 콜), 공유/방문 보존 루프, 슬랙 아침 요약(Prometheus 조회), 5xx·이상행동 알림 | app 내부 → 외부 API/Slack (요청 없이도 도는 경로) | 외부 API 쿼터, 방문 집계 지문(보존), 운영 알림 채널 |
| E17 DNS·도메인 | 가비아 DNS(TXT 없음), Let's Encrypt HTTP-01 | 도메인 신뢰 → 이메일·인증서 발급 | 관리자 권한(피싱), 콘텐츠 무결성(사칭) |

## 4. Threats

| id | threat | actor | surface | asset | impact | likelihood | status | controls | evidence |
|---|---|---|---|---|---|---|---|---|---|
| T1 | 관리자 권한 탈취 — 공유 비밀번호 추측·세션 서명키(해시 파생) 유출·리미터 우회로 관리자 콘솔 장악 | remote_unauth | E7 관리자, E10 nginx·compose 설정 | 관리자 권한, 사용자 PII, 콘텐츠 무결성 | critical | possible | partially_mitigated | scrypt n=2^14 + 상수시간 비교; 라우터 리미터 5/분(threading.Lock, RATE_LIMIT_ENABLED 무관); HMAC 토큰에 해시 지문; XFF 신뢰경계 이중화 + `--no-proxy-headers`; 4h TTL. 미비: nginx IP allowlist 주석 처리, 비밀번호 1개를 3명이 공유, `ADMIN_SESSION_SECRET` 미설정 시 해시가 곧 자격증명 | 4차-High(XFF 스푸핑, DAST 실증), XFF-H-1(loopback 우회 8/8), #54(리미터 경합 PoC), 2차-1(운영값 미확인), A-7(운영자 실명 노출) |
| T2 | 사용자 계정 탈취·세션 위조 — OAuth 흐름·계정 통합·세션 서명 결함으로 타인 계정 접근 | remote_unauth | E6 OAuth·팝업, E5 로그인 필수 API | 사용자 계정 PII, 취향 프로필, 저장 코스, 문의 | critical | rare | partially_mitigated | state 서명+만료+HttpOnly nonce 대조; 이메일 검증된 경우만 통합; 세션키 없으면 라우터 미등록; `//` 포함 오픈리다이렉트 화이트리스트; 24h 슬라이딩 TTL. 미비: 서버측 세션 무효화 수단 없음, OAuth 실공격 미검증 | C-1(세션키 위조, Critical fixed), C-3/M-1(state 미바인딩 fixed), K-C1(미검증 이메일 계정 흡수 Critical fixed), K-M1/K-M2 fixed, 3차-01-2.2(토큰 재사용 accepted), 4차-미확인-OAuth |
| T3 | 서버 시크릿 유출 — 로그·오류 알림·저장소·컨테이너 환경·백업 경로로 API 키/서명키/OAuth 시크릿이 새어 세션 위조·쿼터 도용·채널 하이재킹 | remote_unauth, insider, supply_chain | E11 아웃바운드 클라이언트, E15 시크릿 저장·배포, E14 GitHub, E9 관측 | 서버 시크릿, 관리자 권한(간접), 외부 API 쿼터, 운영 알림 채널 | critical | possible | partially_mitigated | httpx 로거 WARNING; `redact_secrets`; 5xx 알림 `_scrub` + 쿼리스트링 제거; `.gitignore`/`.dockerignore`; 히스토리 스캔 0건; sops/age 암호본. 미비: `.env` 전체를 postgres·backup 컨테이너와 공유(S3 자격증명 포함), serviceKey가 쿼리스트링에 실림, `redact` 소문자 퍼센트인코딩 미치환 | 2차-4/4b(HTTP 평문 + 로그 되비침, fixed), 내부-M-1 감사반영(추가 2곳 fixed), A-3(하드코딩 키 fixed), a86784b(개인키 gitignore), 6차-L-3(env 공유 open), 3차-03-2.1(open) |
| T4 | 공급망 침해 — 알려진 취약 의존성·베이스 이미지·서드파티 액션을 통한 프론트/백엔드 RCE 또는 빌드 오염 | supply_chain | E13 의존성·베이스 이미지, E14 GitHub Actions | 컨테이너 무결성, 서비스 가용성, 서버 시크릿 | critical | likely | partially_mitigated | 핀 고정(pip ==, npm lock, 이미지 태그), Dependabot 5 생태계, 주간 npm/pip audit + Slack, 공식 액션만·permissions read·포크 시크릿 차단. 미비: 패치 SLA 부재(Critical 6일 방치), 감사 기준선이 건수라 신규 Critical 미통보, 다이제스트 미고정, deploy/ 이미지 Dependabot 미커버, pip 해시 없음 | 6차-1(#127 Next Critical open), 2차-9(Next 3회 이월), 6c80d63(starlette BadHost), a23aad1(starlette PYSEC 4건), 523d23f(postcss/sharp), 6차-3(#129 기준선 open) |
| T5 | 외부 API·LLM 쿼터 고갈로 서비스 기능 붕괴(비용 DoS) — 비인증 열거·캐시 미스 유도·재기동 프리워밍으로 공공데이터 1,000/일·Gemini 20/일·Tmap 한도 소진 | remote_unauth | E2 스팟 상세, E1 공개 조회 API, E16 백그라운드 태스크, E5(로그인 후 LLM 경로) | 외부 API 쿼터, 서비스 가용성, 콘텐츠 무결성(전면 폴백·사진 null) | high | likely | partially_mitigated | 인메모리 캐시(overview 24h·보드 10분·축제 12h), 사전생성 요약 파일, 시드 image_url 우선, llm 버킷 6/분(로그인 경로), 실패 TTL 캐시, 폴백으로 화면은 유지. 미비: `GET /places/{id}`가 비인증·default 120/분인데 사전생성 요약이 4건뿐 → content_id 순회 시 미스마다 Gemini·TourAPI 호출; 글로벌 일일 예산 없음; 프리워밍이 재기동마다 원천 수십 콜; `RATE_LIMIT_ENABLED` 꺼지면 무제한 | 코드 주석 사고 기록(get_photo 2026-07-29 detailCommon2 일일 한도 429로 전 지역 사진 null), #99(Gemini 무료 한도), 6차-L-4(429 카운터 공개), 3차-인수인계-1(LLM 버킷 검증) |
| T6 | UGC 무결성·검열 남용 — 위조 가능한 device_id로 타인 콘텐츠 삭제·수정, 신고 회전으로 정상 리뷰 자동 숨김, 공유 코스 내용 위조·사칭 | remote_unauth | E3 UGC 쓰기 (device-id), E12 클라이언트 저장소 | 콘텐츠 무결성·신뢰, UGC 소유권 토큰, 서비스 가용성(저장소) | high | likely | partially_mitigated | 서버가 스팟 id만 신뢰해 재구성(위조 필드 폐기, DAST 실증), 닉네임 정제·운영자 사칭 차단, 로그인 시 서버 표시명 강제, device_id 형식 검증·응답 비노출, 기기별 쓰기 한도·advisory lock, 관리자 hide/unhide. 미비: 신고 고유성이 device_id뿐(3회로 숨김), 숨김 발생 알림 없음, 소유권이 클라이언트 값 | 2차-Critical 코스공유 위조(fixed, 4차 실증), 6차-2/#128(신고 회전 open), 3차-01-2.3(device_id 모델 accepted), #53(기기 상한 경합 fixed PoC), 내부-Critical-1(비문자열 영구 500 fixed), 내부-M-1 기능확장(like_count 드리프트 open) |
| T7 | 프롬프트 인젝션·LLM 출력 조작 — 자유서술(온보딩 text, 코스 wish)로 태그 과다추출·부적절/허위 추천 텍스트·PII 국외 전송 유도 | remote_auth | E5 로그인 필수 API(onboarding/analyze, courses/recommend wish, tips) | 콘텐츠 무결성·신뢰, 취향 프로필, 사용자 PII(국외이전), 외부 API 쿼터 | medium | possible | partially_mitigated | 델리미터 + "데이터일 뿐" 시스템 프롬프트, NFKC·Cf 제거·300자·반복 축약·PII 마스킹, 탐지 시 LLM 스킵→룰 폴백, JSON 스키마 강제 + pydantic 재검증 + AXIS_CAP, 툴 호출 없음, 팁 프롬프트는 태그 코드만. 미비: denylist 패러프레이즈 갭(원리적), 로그인 세션 상태 실공격 미검증, wish 경로는 후보 스팟 목록과 함께 LLM에 들어감 | 내부-M-1 온보딩(우회 실증 → 과다추출, mitigated), 4차-denylist갭(open), 3차-05-2.1(accepted), 40015f5(PII 마스킹), e88c0d1(wish 신규 표면), 594ff52 |
| T8 | 저장소·메모리 자원 소진 — UGC 대량 적재, 비콘 경로 폭발, 캐시 무한 성장, 대형 페이로드로 DB/디스크/프로세스 고갈 | remote_unauth | E3 UGC 쓰기, E4 방문 비콘, E1 공개 조회 API(캐시 키) | 서비스 가용성, 방문 집계 지문 | medium | possible | partially_mitigated | 3중 보존정책(기기 20·전체 5,000·180일), 32KB 페이로드·nginx 1MB, 경로 접기·정규식, 레이트리밋 max_keys 20,000, 공유 batch 정리. 미비: MemoryCache 상한·스윕 없음, 전체 상한 기기 간 경합, `RATE_LIMIT_ENABLED` 의존 | #53(fixed), 5차-인수인계/6차-L-2(open 부분), 6차-L-1(open), A-5(온보딩 길이 fixed), K-m3(문의 버킷 fixed), 9552561(자기 증폭 루프 fixed) |
| T9 | 개인정보 과다수집·보존 위반·재식별 — 문의 자유서술/이메일·로그인 이메일·ip_hash·LLM 국외이전이 고지·보존기간·최소수집 원칙과 어긋나거나 키 유출로 가명이 풀림 | insider, remote_auth, local_admin | E5 로그인 필수 API(inquiries, onboarding), E4 방문 비콘, E15 백업, E16 보존 루프 | 사용자 계정 PII, 방문 집계 지문, 취향 프로필 | high | possible | partially_mitigated | 원본 IP 미저장·HMAC 지문·키 없으면 집계 중단, 90일/180일 자동 정리 루프, 온보딩 원문 미저장, 관리자 회원 목록에 email 미포함, 처리방침 §10 국외이전 고지, 탈퇴 API. 미비: 문의 contact_email 형식 검증 없음·보존기간 미정의, 로그에 이메일 금지 규율 검증 없음, 가명키가 관리자 세션키와 동일 파생 가능, 백업 덤프 보관 14일+S3 | A-3/A-4(fixed), 내부-L-2 감사반영(open), K-M3(처리방침 fixed), m-7(지속), K-m2(open), K-m7(닉네임 동의 open), 40015f5 |
| T10 | 클라이언트 측 스크립트 주입(XSS·서드파티 스크립트 오염)으로 device_id·표시명·온보딩 결과 탈취 및 UGC 전권 남용 | remote_unauth, supply_chain | E12 브라우저 서드파티·클라이언트 저장소, E3 UGC(렌더), E6 OAuth 팝업 HTML | UGC 소유권 토큰, 콘텐츠 무결성, 서비스 세션(HttpOnly라 직접 탈취 불가, same-origin fetch는 가능) | high | rare | partially_mitigated | 서버 정제(HTML 태그 제거, 제어문자), 프론트 `dangerouslySetInnerHTML` 0건(DAST 실증), `_js_safe_json`, postMessage 오리진 고정, `poweredByHeader` off, X-Frame-Options·nosniff. 미비: CSP `script-src`/`img-src` 없음(네이버 SDK 런타임 주입·TourAPI 임의 이미지 호스트 무제한), Swagger CDN은 prod 차단 | C-2(팝업 XSS Critical fixed), 4차 XSS 저장/반사 실증 차단, 3차-02-2.2(Slack 반사 accepted), K-m6(문의 원문 저장 accepted), 2차-12(CSP 이월) |
| T11 | CSRF·로그인 CSRF·오픈 리다이렉트로 피해자 브라우저에서 상태 변경(탈퇴·표시명 변경·좋아요)이나 공격자 계정 고정 | remote_unauth | E6 OAuth·팝업, E5 로그인 필수 API | 사용자 계정 PII, 콘텐츠 무결성 | medium | rare | partially_mitigated | SameSite=Lax + 상태 변경 라우트 전부 POST/PATCH/DELETE(5차 GET-CSRF 0건), state nonce 쿠키, `next` 화이트리스트, CORS credentials false. 미비: OAuth 실공격 미검증, CSRF 토큰 없음(Lax 의존) | M-1 OAuth(fixed), m-3(fixed), 4차-미확인-OAuth(carried), 5차 GET-CSRF 검증 |
| T12 | 인프라 경계 회귀 — nginx/compose 한 줄 변경(포트 공개·XFF append·location 확장)으로 backend/ollama/postgres 직접 노출, 레이트리밋·문서 차단·메트릭 차단 무력화 | remote_unauth, adjacent_network | E10 nginx·compose·Dockerfile, E9 관측 엔드포인트 | 서비스 가용성, 관리자 권한(브루트포스), 외부 API 쿼터, 서버 시크릿(메트릭·docs) | high | rare | partially_mitigated | 앱 자체 이중 방어(`_is_trusted_proxy_peer` RFC1918+ULA, `--no-proxy-headers`, prod에서 docs 비활성), nginx 명시 404(`/metrics`, `/docs`), expose만 사용, 주석으로 회귀 위험 명시. 미비: 설정 회귀를 잡는 자동 검사(배포 후 스모크) 없음, `RATE_LIMIT_TRUSTED_PROXY_CIDRS` 미설정(RFC1918 전체 신뢰) | 4차-High(nginx가 유일 방어선이었음 실증), XFF-H-1/M-1(fixed), 44fa13d(`/prom/` 500 방치), 1eed694 |
| T13 | 탐지 공백·알림 채널 남용 — 남용 이벤트(신고 급증·자동 숨김·관리자 로그인 성공·원천 429)가 알림되지 않거나, 유출된 웹훅으로 채널 스팸·피싱, 감사 CI가 조용히 통과 | remote_unauth, insider | E8 Slack 슬래시, E9 관측 엔드포인트, E16 백그라운드 알림, E14 GitHub Actions | 운영 알림·관측 채널, 콘텐츠 무결성(탐지 지연), 저장소·CI 무결성 | medium | possible | partially_mitigated | 5xx 알림 + 중복 억제, 401/429 전체 집계 이상행동 알림, 헬스 감시 30분(상태 전환 시만), 슬래시 명령 HMAC+5분, `/prom/` Basic Auth. 미비: 남용성 이벤트(숨김·신고·로그인 성공·쿼터 429) 무알림, 웹훅 URL 회전 절차 없음, 의존성 감사 기준선이 신규 Critical 삼킴, `/health/llm` 공개 | 6차-3/#129(open), 6차-L-4(open), 6차-2(무알림 근거), XFF-M-3/M-4(fail-open→기준선 부작용), 44fa13d |
| T14 | 도메인 사칭 피싱 — SPF/DMARC 부재로 `@sumeungil.co.kr` 발신 위조 메일로 관리자 비밀번호·OAuth 동의 탈취 또는 이용자 기만 | remote_unauth | E17 DNS·도메인, E7 관리자 | 관리자 권한, 콘텐츠 무결성·신뢰 | medium | possible | unmitigated | 없음(security.txt 연락처만). 관리자 콘솔이 비밀번호 단일 인자라 피싱 성공 시 즉시 장악 | 2차-8(DNS TXT 0건, 2026-09-14 실측), A-7(운영진 명단 노출 이력) |
| T15 | 전송 계층 다운그레이드 — HSTS 없이 첫 접속/북마크가 http로 시작해 중간자가 세션 쿠키·로그인 폼을 가로챔 | adjacent_network | E10 nginx TLS 설정, E17 도메인 | 사용자 계정 PII, 관리자 권한 | medium | rare | risk_accepted | 80→443 301, 쿠키 Secure 기본 true, TLS 1.2/1.3, 세션 티켓 off. 미비: HSTS(인증서 첫 자동갱신 성공 후 적용하기로 결정, ≈2026-10-08 이후) | 2차-11(이월·수용) |
| T16 | 저장소·CI 무결성 훼손 — 브랜치 보호 없는 develop/main에 검토 없는 머지(Dependabot 포함), 죽어 있던 회귀 게이트, Actions 스크립트 인젝션으로 취약 코드·설정이 배포됨 | supply_chain, insider | E14 GitHub 저장소·Actions | 저장소·CI 무결성, 컨테이너 무결성, 서버 시크릿(Actions) | high | possible | partially_mitigated | CI(lint·build·회귀 스크립트), CODEOWNERS, permissions read, `pull_request_target` 없음, jq 경유 문자열, release 노트 보안 카테고리. 미비: 브랜치 보호·룰셋 없음, 회귀 스크립트가 한때 전부 실패 상태였음, 감사 반영이 검토 없이 섞여 들어간 이력 | c6d5882(회귀 게이트 사망 fixed), 403a9ab(무검토 커밋 경위), XFF-L-4(fixed), 6차-확인-5(open), 9bccc1a(.gitignore로 시드 누락→추천 전면 장애) |
| T17 | 백업 유출·복구 실패 — 전체 DB 덤프가 호스트 디렉터리·S3에 축적되며 자격증명 노출 시 PII 대량 유출, 또는 복구 미검증으로 장애 시 데이터 손실 | local_admin, supply_chain, insider | E15 시크릿 저장·배포(backups, S3), E16 백업 루프 | 사용자 계정 PII, 서비스 가용성 | high | possible | partially_mitigated | umask 077, sha256, `pg_restore --list` 검증, SSE-AES256, 14일 로컬 보관, 헬스체크로 신선도 감시. 미비: 복원 리허설 기록 없음, S3 자격증명이 공유 `.env`에, 오프사이트 활성 여부 미확인, 덤프 암호화(클라이언트 측) 없음 | (없음 — Stage 4 갭 채우기) |
| T18 | 인접 컨테이너 횡적 이동 — frontend·ollama·postgres 중 하나가 뚫리면 무인증 Ollama·backend `/metrics`·RFC1918 XFF 신뢰·공유 `.env`로 다른 컨테이너의 자산에 도달 | adjacent_network | E10 compose 네트워크, E9 `/metrics`, E15 `.env` 공유 | 컨테이너 무결성, 서버 시크릿, 외부 API 쿼터(Ollama CPU) | medium | rare | partially_mitigated | 단일 브리지 네트워크지만 호스트 포트 미공개, 비루트 컨테이너, 이미지 태그 고정. 미비: 서비스별 네트워크 분리 없음, Ollama 무인증, `RATE_LIMIT_TRUSTED_PROXY_CIDRS` 미설정, `.env` 전 컨테이너 공유 | XFF-M-1(신뢰 대역 과다 → 축소), 6차-L-3(open) |
| T19 | 관리자 행위 부인·책임 추적 불가 — 비밀번호 1개를 3명이 공유하고 표시 이름은 자기신고라, 삭제·답변·숨김의 실제 행위자를 증명할 수 없음 | insider | E7 관리자 | 콘텐츠 무결성·신뢰, 사용자 PII(열람 추적) | medium | possible | partially_mitigated | `admin_actions` 감사 로그(ip_hash·operator), 서명 안쪽에 operator 고정, ADMIN_OPERATORS 대조. 미비: 개별 자격증명 없음(설계 문서가 "책임 추적 장치이지 보안 경계 아님"이라고 명시), 열람(조회) 행위는 미기록 | (없음 — Stage 4 갭 채우기; 설계 주석 `admin_auth.py issue_token` 참조) |
| T20 | Slack 명령 위조·재전송으로 운영 수치 노출 또는 채널 소음 | remote_unauth | E8 Slack 슬래시 | 운영 알림·관측 채널 | low | rare | mitigated | HMAC-SHA256(raw body) + `compare_digest` + 5분 스큐, 시크릿 없으면 미등록, ephemeral 응답, 명령 화이트리스트 | (없음 — Stage 4; 3차-02-2.2 반사 Low) |

## 5. Deprioritized

| threat | reason |
|---|---|
| SSRF (사용자 제어 URL로의 아웃바운드) | 사용자 입력이 URL·호스트로 흘러가는 코드가 없음(5차 신규 엔드포인트 SSRF 검증 포함). 외부 호출은 전부 고정 base_url + id 파라미터 |
| 커맨드/경로 인젝션 | 파일 경로·쉘 명령에 사용자 입력이 닿는 코드가 없음(4차 전수 탐색). subprocess는 검증 스크립트뿐 |
| SQL 인젝션 | 전 쿼리 `%s` 바인딩, f-string 8곳은 코드 리터럴/화이트리스트 컬럼(6차), sqlmap level 3 취약 파라미터 0건(4차). T6·T8 보다 하위 위험으로 유지 감시만 |
| 프로토타입 오염·역직렬화 | Python 백엔드, JSON만 사용, pickle/yaml.load 0건, Pydantic 거부(5차) |
| 모바일 앱·네이티브 클라이언트 공격 | 웹 전용 서비스, 앱 없음 |
| 결제·금전 자산 | 결제 기능 없음 |
| 호스트 root·VM 콘솔 접근(대표 본인) | 1인 운영 구조에서 호스트 관리자는 신뢰 루트. SSH 키 관리는 open question으로만 남김 |
| 국가급 공격자·제로데이 | 공모전 출품작의 위협 프로필 밖. 공급망(T4)으로 부분 흡수 |
| 물리적 접근 | NAVER Cloud 관리형 VM, 범위 밖 |
| Repudiation(일반 사용자) | 익명 UGC는 설계상 device_id 라벨만 두기로 한 MVP 트레이드오프(3차-01-2.3 accepted); 관리자 부인은 T19로 별도 |

## 6. Open questions

- 운영 `deploy/.env` 실값: `RATE_LIMIT_ENABLED=true`인지, `ADMIN_SESSION_SECRET`·`USER_SESSION_SECRET`이 독립 값으로 설정돼 있는지, `CORS_ALLOW_CREDENTIALS`가 비어 있는지, `RATE_LIMIT_TRUSTED_PROXY_CIDRS`를 도커 서브넷으로 좁혔는지. (T1·T5·T8·T18 의 likelihood가 여기에 달려 있다)
- nginx `/api/v1/admin/`·`/ops-37878f1b71`의 IP allowlist를 켤 수 있는가(대표·운영진 고정 IP 보유 여부). 아니면 관리자 개별 계정+2단계 인증으로 갈 것인가.
- 관리자 3명이 비밀번호 1개를 공유하는 방식을 유지할 것인가. 회전 주기·퇴사/이탈 시 절차가 있는가.
- Gemini 요금제와 일일 한도(무료 20회가 맞는가), 유료 전환 시 비용 상한(billing cap) 설정 여부. 공공데이터·Tmap 키의 실제 일일 한도와 소진 시 운영 대응.
- `GET /api/v1/places/{content_id}`의 라이브 LLM 요약을 비인증에 계속 열어둘 것인가, 아니면 사전생성 커버리지를 늘리고 라이브는 로그인/예산 뒤로 둘 것인가.
- 오프사이트 백업(`BACKUP_S3_URI`)이 실제로 활성인가. 마지막 복원 리허설은 언제였는가. 덤프 클라이언트 측 암호화가 필요한가.
- 호스트 SSH 접근자·키 목록, sops/age 키 보관 위치, `deploy/.env` 파일 권한(600)이 실제로 유지되는가.
- 리뷰 신고 정책 방향(#128): 로그인 필수 / ip_hash 병행 / 검토 대기+알림 중 무엇을 택할 것인가. 자동 숨김 자체를 유지할 것인가.
- 심사 기간(10~12월) 가용성 우선 정책에 따라 HSTS·CSP 적용 시점, 그리고 그 기간 중 배포 동결 여부.
- `sumeungil.co.kr` 도메인으로 메일을 보낼 계획이 있는가(없으면 `v=spf1 -all` + DMARC reject로 바로 잠글 수 있다).
- Grafana(aitestbed.kr)와 n8n 인스턴스의 접근 통제·계정 관리는 누가 하는가(외부 SaaS가 우리 `/prom/` 자격증명과 `/health/llm`을 보유).
- `docker logs` 보관 기간·접근자. 429 로그에 원본 IP가 남는다(2026-08-22 legal 확인 요청 항목)는 점을 처리방침이 커버하는가.
- 문의 `contact_email`·`message`의 보존 기간과 파기 절차가 정해져 있는가.

## 7. Provenance

- mode: bootstrap
- date: 2026-09-14
- target: https://github.com/insik03/sumeungil (develop) @ edb5fa7 — 로컬 클론 정적 분석, 코드 실행·운영 요청 없음
- inputs: `AI가상회사/ai-security-company/audits/sumeungil/` 2~6차 감사 보고서(취약점 분석·전공자용·DAST) + 저장소 내 `docs/03,06-security-report*.md`·`security-reports/*` 내부 검토 + `git log --all` 보안 관련 커밋 48건 + GitHub Advisory DB/Dependabot alerts(6차 조회) + `nslookup TXT`(DNS)
- owner: unset

## 8. Recommended mitigations

| mitigation | threat_ids | closes_class | effort |
|---|---|---|---|
| 비인증 경로에서 LLM·원천 호출을 떼어낸다: 스팟 요약 사전생성 커버리지 확대(배치), 라이브 LLM은 로그인 또는 별도 저한도 버킷 뒤로, 원천·Gemini에 **글로벌 일일 예산 카운터**(초과 시 즉시 폴백)를 둔다 | T5, T8 | yes | M |
| 관리자 인증을 "비밀번호 1개"에서 벗어나게 한다: 개별 계정 + TOTP 2단계(또는 최소 nginx IP allowlist 활성) + `ADMIN_SESSION_SECRET` 미설정 시 부팅 거부(fail-closed) | T1, T14, T19 | partial | M |
| 익명 device_id 기반 쓰기·신고를 계정 기준으로 옮긴다(신고는 `require_login` + `UNIQUE(review_id,user_id)`, 자동 숨김은 "검토 대기 + 슬랙 알림"으로) — 익명 작성을 유지해야 하면 `ip_hash` 병행 카운트 | T6, T8, T13 | partial | M |
| 의존성 운영 규율: Critical 48h·High 7일 패치 SLA, 감사 CI 기준선을 허용 GHSA 목록으로, critical>0 무조건 알림, Dependabot PR은 CI 통과 시 자동 머지, 브랜치 보호(PR 필수+CI 필수), deploy/ 이미지 Dependabot 추가·다이제스트 고정, pip `--require-hashes` | T4, T16, T13 | partial | S |
| 시크릿 최소 배포·회전: 컨테이너별 env 파일 분리(`POSTGRES_*`만 DB/백업에), S3 자격증명 스코프 최소화, 웹훅·API 키·세션키 회전 런북과 분기 1회 실행, `redact` 소문자 인코딩 보강 | T3, T17, T18 | partial | S |
| CSP `script-src 'self' https://oapi.map.naver.com` + `img-src` 허용 목록 + HSTS(2026-10-08 첫 갱신 성공 후) — 프론트 서드파티 표면을 선언적으로 잠근다 | T10, T15 | partial | M |
| 탐지 설계 확장: 신고 급증·자동 숨김·관리자 로그인 성공·원천/Gemini 429·백업 실패를 슬랙 알림 이벤트로 추가하고, 배포 후 스모크(포트 미공개·`/metrics` 404·XFF 무시)를 자동 검사로 고정 | T13, T12, T6 | partial | S |
| 개인정보 최소화·보존 명문화: 문의 contact_email 형식 검증·보존기간·파기 배선, 로그에 이메일/원본 IP 금지 검증 테스트, 가명키를 세션키와 분리, 처리방침에 로그 보관 항목 반영 | T9 | partial | S |
| 세션 서버측 무효화(users.session_epoch)로 로그아웃·탈퇴·키 유출 시 즉시 폐기 | T2, T1 | partial | M |
| SPF `v=spf1 -all` + DMARC `p=reject`(메일 미사용 도메인) — 도메인 사칭 메일을 원천 차단 | T14 | yes | S |
| 컨테이너 네트워크 분리(ollama·postgres 전용 내부 네트워크) + `RATE_LIMIT_TRUSTED_PROXY_CIDRS`를 nginx 서브넷으로 축소 | T18, T12 | partial | S |
| 백업 복원 리허설을 분기 절차로 두고 결과를 기록, 오프사이트 활성 확인, 덤프 클라이언트 측 암호화(age) 검토 | T17 | partial | S |
