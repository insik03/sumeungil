# 00-impl-plan — 숨은길 (SUMUENGIL) 실제 구현 · MVP-1

- **문서 버전**: v1.0
- **작성**: planning-lead
- **작성일**: 2026-07-24
- **프로젝트**: `sumeungil-build` (신규 — 기존 `sumeungil/`은 설계 산출물, 여기부터가 실제 코드)
- **성격**: 상용화를 예고한 서비스의 **가동 골격(walking skeleton)**. 버리는 코드 없이 상용으로 확장 가능한 구조로 짓는다.
- **근거 문서**: `projects/sumeungil/01-backend-design.md`(DB/API/파이프라인 정본), `projects/sumeungil/00-PRD.md`(§3.2 MVP 표), `projects/sumeungil/design-variants-v2/variant-B-boutique-travel.html`(채택 디자인 — 부티크 트래블)

---

## 1. MVP-1 한 줄 정의

> **로컬에서 브라우저를 열면, 백엔드가 공공데이터(관광지 집중률)를 실제로 호출·정규화해 내려준 진짜 혼잡도가 B안 홈 화면 "실시간 전광판"에 뜬다.** 더미 데이터가 아니다.

이 골격이 서면 이후 M1(온보딩)·M3(경로 비교)·M4(지도) 등은 **같은 뼈대에 기능을 얹는** 방식으로 확장된다. MVP-1의 모든 코드는 상용에서 재사용된다.

---

## 2. 넣을 것 / 뺄 것

### 2.1 MVP-1에 넣는다

| 영역 | 항목 | 근거 |
|---|---|---|
| 백엔드 | FastAPI 앱 골격 (`app/main.py`, 라우터 분리, 미들웨어 자리) | 상용 확장의 뼈대 |
| 백엔드 | 설정 로더 — `.env` 로드 + **fail-fast**(필수 키 없으면 부팅 즉시 종료) | 01-backend §10.4 |
| 백엔드 | **혼잡도 전광판 엔드포인트 1개** `GET /api/v1/congestion/board` — 공공 API(D1) 실연동 + 캐싱 + 정규화 | M2, PRD §3.2 유일 필수요건과 직결 |
| 백엔드 | 공공 API 클라이언트 (`TatsCnctrRateService/tatsCnctrRatedList` 호출) | 키·엔드포인트 실검증 완료 |
| 백엔드 | 캐시 레이어 (인메모리 TTL, **Redis 드롭인 인터페이스**) | §2.3 결정 |
| 백엔드 | `GET /api/v1/health` — config/upstream/cache 상태 | 운영·데모 안정성 |
| 백엔드 | CORS (localhost:3000 허용) | 로컬 프론트 연동 |
| 프론트 | B안(부티크 트래블) **홈 화면**을 Next.js/React로 이식 | 채택 디자인 |
| 프론트 | 홈 "실시간 전광판"이 백엔드 API를 **실제 호출**해 혼잡도 렌더 (더미 제거) | MVP-1 핵심 |
| 프론트 | 로딩 / 에러 / stale(캐시 노후) 상태 처리 | 데모 중 원천 장애 대비 |
| 통합 | 백엔드 :8000 + 프론트 :3000 각각 기동, 브라우저에서 진짜 데이터 확인 | 완료 판정 |

### 2.2 MVP-1에서 뺀다 (다음 단계)

| 항목 | 언제 | 사유 |
|---|---|---|
| LLM 온보딩 (M1) | MVP-2 | 태그·벡터 계약(08 정본)은 있으나 LLM 벤더 미정, 골격에 불필요 |
| AI 경로 비교 (M3) | MVP-2 | 스코어링·routes 테이블 필요 — 골격 이후 |
| 지도 (M4) / 히트맵(M15) | MVP-2 | Tmap SDK 연동은 홈 이후 |
| 방문 인증(M8)·오디오(M9)·목적지 검색(M16) | MVP-3+ | 스코프 밖 |
| 로그인/인증 (F1~F4) | 별도 | 게스트조차 MVP-1엔 불필요 (전광판은 공개 엔드포인트) |
| **PostgreSQL + PostGIS** | 상용 확장 시 | §2.3 — MVP-1은 DB 없이 성립 |
| **Redis** | 상용 확장 시 | §2.3 — 인메모리 캐시로 시작 |
| 배치 수집기(job_congestion) | 상용 확장 시 | §2.3 — MVP-1은 요청 시점 fetch-on-miss |

---

## 3. 인프라 결정 (Redis / PostGIS)

> **결론: MVP-1은 Redis도 PostgreSQL/PostGIS도 로컬에 세우지 않는다.** 대신 상용에서 이 둘이 그대로 꽂히는 자리를 인터페이스로 미리 파둔다. 그래서 골격 코드는 버려지지 않는다.

### 3.1 캐시 — 인메모리로 시작, Redis는 인터페이스 뒤에

- MVP-1: `Cache` 추상(get/set/ttl) 뒤에 **프로세스 인메모리 TTL 캐시** 구현체 하나.
- 상용: 같은 `Cache` 인터페이스에 Redis 구현체를 갈아끼운다. 엔드포인트·서비스 코드는 무변경.
- 근거: 로컬 데모에 Redis 컨테이너를 강제하면 진입장벽만 오르고 상용 확장성엔 기여가 없다. 인터페이스만 지키면 확장성은 보존된다.

### 3.2 DB — MVP-1은 DB 없음, `CongestionRepository` 뒤에

- 01-backend-design의 원칙 **P1("읽기 경로에서 외부 API를 직접 호출하지 않는다")**는 상용 목표다. MVP-1은 배치수집기+DB가 아직 없으므로 **엔드포인트가 캐시 미스 시 공공 API를 직접 호출**한다 — 이건 의도된 MVP-1 단순화다.
- 이 호출을 `CongestionRepository`(입력: 지역코드 → 출력: 정규화된 혼잡도 리스트) 인터페이스 뒤에 둔다.
  - MVP-1 구현체: `LiveCongestionRepository` (공공 API fetch-on-miss + 캐시)
  - 상용 구현체: `DbCongestionRepository` (배치가 채운 `congestion_snapshots` 테이블 read) — 엔드포인트·응답 계약 무변경으로 교체.
- 근거: DB 없이도 "진짜 데이터가 화면에 뜬다"는 완료 조건을 만족하고, 상용 전환은 repository 교체 한 곳으로 국소화된다.

### 3.3 이 결정이 상용 확장성을 해치지 않는 이유

MVP-1의 인터페이스(`Cache`, `CongestionRepository`, 그리고 §01의 응답 스키마)는 상용에서 **그대로 유지**되고, 구현체만 바뀐다. 프론트가 보는 API 계약은 처음부터 상용 모양이다(§01-interface-contract).

---

## 4. 디렉토리 구조

```
projects/sumeungil-build/
  00-impl-plan.md              ← 본 문서
  01-interface-contract.md     ← 백엔드↔프론트 API 계약 (병렬 작업의 단일 근거)
  APPROVALS.md                 ← 결재 로그
  backend/                     ← FastAPI (backend-engineer 담당)
    app/
      main.py                  # 앱 생성, 라우터/CORS/미들웨어 등록
      config.py                # .env 로드 + fail-fast (필수 키 검증)
      api/
        health.py              # GET /api/v1/health, GET /health
        congestion.py          # GET /api/v1/congestion/board
      services/
        congestion_service.py  # 정규화·레벨판정·정렬·TOP N
      repositories/
        congestion_repo.py     # CongestionRepository 추상 + LiveCongestionRepository
      clients/
        kto_client.py          # 공공 API(TatsCnctrRate) 호출·파싱
      cache/
        base.py                # Cache 추상
        memory.py              # 인메모리 TTL 구현 (Redis 드롭인 자리)
      schemas/
        congestion.py          # 응답 Pydantic 모델 = 01 계약의 코드화
    requirements.txt
    .env.example               # backend가 읽는 키 목록 (실키는 아래 §5.1 참조)
    README.md                  # 실행법
  frontend/                    ← Next.js (프론트 담당 — §7 배정 참고)
    app/
      page.tsx                 # 홈 (B안 이식)
      layout.tsx
    components/
      CongestionBoard.tsx      # 실시간 전광판 (API 호출·렌더)
      BoardCard.tsx            # board-card + 혼잡도 배지
    lib/
      api.ts                   # fetch 래퍼, 타입은 01 계약과 1:1
    styles/                    # B안 디자인 토큰(CSS 변수) 이식
    .env.local.example         # NEXT_PUBLIC_API_BASE
    package.json
```

> `frontend/`는 B안 HTML의 팔레트·컴포넌트·레이아웃을 React로 옮기는 작업이다. 새 디자인을 만드는 게 아니라 **채택된 variant-B를 컴포넌트화**한다.

---

## 5. 로컬 실행 방법

### 5.1 환경변수

- MVP-1에서 백엔드가 실제로 필요로 하는 키는 **`PUBLIC_DATA_API_KEY` 하나**다(공공데이터 일반 인증키).
- 실키는 `projects/sumeungil/.env`에 있고 실호출 200이 확인됐다. backend는 이 값을 `projects/sumeungil-build/backend/.env`로 복사해 쓴다(또는 `PUBLIC_DATA_API_KEY` 환경변수로 주입).
- 추가 설정(선택, 기본값 있음): `DEFAULT_AREA_CD`, `DEFAULT_SIGUNGU_CD`(데모 기본 지역), `CACHE_TTL_SEC`(기본 600).
- **fail-fast**: `PUBLIC_DATA_API_KEY`가 없으면 부팅 즉시 종료(기본값으로 몰래 뜨지 않는다). 01-backend §10.4.
- Tmap/LLM/DB/Redis 키는 MVP-1에서 **불필요**(위 §2.2).

### 5.2 실행 (예시 — 상세 명령은 backend가 README에 확정)

```bash
# 백엔드 (:8000)
cd projects/sumeungil-build/backend
python -m venv .venv && . .venv/bin/activate     # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
cp ../../sumeungil/.env .env                       # PUBLIC_DATA_API_KEY 확보
uvicorn app.main:app --reload --port 8000

# 프론트 (:3000)
cd projects/sumeungil-build/frontend
npm install
cp .env.local.example .env.local                   # NEXT_PUBLIC_API_BASE=http://localhost:8000
npm run dev
```

### 5.3 완료 판정 (Definition of Done)

1. `GET http://localhost:8000/api/v1/health` → `200 {"status":"ok",...}`.
2. `GET http://localhost:8000/api/v1/congestion/board` → 공공 API에서 온 **정규화된 혼잡도 items** 반환.
3. `http://localhost:3000` 홈 화면의 "실시간 전광판"이 **API 응답으로 렌더**되고(더미 아님), 혼잡/보통/여유 배지가 레벨에 맞게 표시된다.
4. 원천 API를 일시 차단해도(키 무효화 등) 프론트가 죽지 않고 stale/에러 상태를 보여준다.

---

## 6. 데이터 흐름 (MVP-1)

```
[브라우저 홈]  ──GET /api/v1/congestion/board──▶  [FastAPI]
                                                     │  cache hit? ──yes──▶ 즉시 반환
                                                     │  no
                                                     ▼
                                          [CongestionRepository(Live)]
                                                     │
                                          [kto_client] ──GET──▶ apis.data.go.kr
                                                     │            /B551011/TatsCnctrRateService
                                                     │            /tatsCnctrRatedList
                                          정규화(0~100, level) · 정렬 · TOP N
                                                     │  cache.set(TTL)
                                                     ▼
                                          01 계약 스키마로 직렬화 → 응답
```

상용 전환 시: `CongestionRepository`를 `Db*`로 교체하고, 별도 배치 수집기가 공공 API→`congestion_snapshots`를 채운다. **위 흐름도의 프론트↔FastAPI 구간(=01 계약)은 불변.**

---

## 7. 담당 배정 / 확인 필요

- **backend/** = backend-engineer.
- **frontend/**(Next.js) 이식 담당은 조직에 전담 frontend-engineer가 없어 **오케스트레이터/대표 배정 필요** — designer가 B안을 만든 주체이므로 프론트 이식을 designer가 맡거나, backend-engineer가 풀스택으로 처리하는 두 안. (planning-lead 권고: 컴포넌트화 난이도가 낮으므로 backend-engineer가 계약 기준으로 프론트까지 이식하고, designer가 시각 QA만 보는 편이 왕복이 적다. 최종 결정은 대표.)
- **확인 필요 Q1**: 데모 기본 지역(`DEFAULT_AREA_CD`/`DEFAULT_SIGUNGU_CD`) 어디로 고정할지 — 부산 해운대구 등 데이터가 실제로 잘 나오는 지역을 backend가 실호출로 골라 확정.
- **확인 필요 Q2**: 공공 API 응답에 관광지명/집중률 실제 필드명 — backend가 실호출 응답으로 확인해 §01 계약의 `spot_name`/`congestion_rate`에 매핑(추측 금지).

---

## 8. 상용 확장 3줄

1. **캐시**: 인메모리 → Redis (동일 `Cache` 인터페이스, 구현체 교체).
2. **데이터**: fetch-on-miss → 배치수집기 + PostgreSQL/PostGIS(`congestion_snapshots`), `CongestionRepository`만 `Db*`로 교체 (읽기경로 P1 확보 + place_id·좌표·대안경로 필드 활성화).
3. **기능**: 같은 FastAPI 앱/Next.js 앱에 온보딩(M1)·경로비교(M3)·지도(M4) 라우터·화면을 additive로 얹음 — 골격/계약 재작성 없음.

---

## 핸드오프 노트

```
[다음 부서가 알아야 할 것]
1. backend-engineer: FastAPI 골격 + fail-fast 설정 + GET /api/v1/congestion/board(공공 API 실연동·인메모리 캐시) + /health를 짓는다. 응답 필드는 01-interface-contract.md를 정본으로 하고, 공공 API 원본 필드명은 실호출로 확인해 매핑한다(추측 금지). Redis/DB는 세우지 말고 Cache·CongestionRepository 인터페이스만 판다.
2. frontend(담당 대표 배정): variant-B 홈을 React로 이식하고, 실시간 전광판을 GET /congestion/board 실호출로 렌더한다. 더미 배열을 API 응답으로 교체하고 로딩·에러·stale 상태를 처리한다. 타입은 01 계약과 1:1.
3. 둘은 01-interface-contract.md만 보고 병렬로 진행한다 — 이 계약이 어긋나지 않는 한 서로 대기 불필요.
```
