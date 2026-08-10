# 01-backend-design — 숨은길 (SUMUENGIL)

- **문서 버전**: **v1.3** (스코프 개정 증분 — M8~M12 + **M14 날씨 연동 rerank** 반영)
- **작성**: backend-engineer
- **작성일**: 2026-07-22 (v1.0) / 2026-07-22 개정 (v1.1) / 2026-07-23 개정 (v1.2) / **2026-07-23 개정 (v1.3)**
- **근거 문서**: **`projects/sumeungil/08-interface-contract.md` (정본 — 본 문서보다 상위 권위)**, `projects/sumeungil/00-PRD.md` (확정 PRD, §3.2 개정판·R10), `projects/sumeungil/_공모전분석-대회요강.md` (§5.2 공식 체크리스트), `projects/sumeungil/04-qa-report.md`, `projects/sumeungil/06-security-report.md`, `projects/sumeungil/_draft-원본기획서.md` (대표 초안, 참고용)

> **v1.1 개정 요지**: 08 정본 §7.2의 backend 지시 12건(B1~B12) + 보안 High 6건(S-H1·S-H2·S-H3·S-H4·S-H6·S-H7) + QA 자체신고 재판정 3건을 반영했다. **08 정본과 본 문서가 충돌하면 08이 정본이다.** 변경 내역 전수는 문서 말미 **14절 "재작업 반영 내역"** 참조.
>
> **v1.2 개정 요지 (2026-07-23)**: 대표 지시로 대회 공식 개발 체크리스트(요강 §5.2)가 스코프 상위 기준이 되면서 기존 후순위 3건이 MVP로 승격됐다 — **M8(웹 Geo-location + 사진 방문 인증, ex-N1), M9(오디오 가이드 연동, ex-N3), M10(Tmap Route API 연동, ex-N4)**. 이 3건을 **§15 스코프 개정 증분**에 신규 설계했고, **M11(두루누비)·M12(축제)는 이미 본 문서에 설계돼 있어 §15.4에 소재만 정정 등재**했다. **08 정본(compare 34필드·태그 계약)은 손대지 않았다** — M8~M10은 08 계약 표면 밖의 독립 기능이다(§15.0 확인). R10 제약(보조 신호 한정·금전 유인 미결합·EXIF 불신·개인정보 최소수집)을 설계 제약으로 흡수했다.
>
> **v1.3 개정 요지 (2026-07-23)**: 대표가 기상청 "관광코스별 관광지 상세 날씨 조회서비스"(D18, 키 발급 완료)를 **명시적으로 채택**해 **M14(날씨 연동 경로 보정)**로 등재됐다(PRD §3.2). **AI의 5축 스코어링(`scoring_weights`, 08 §1·§2 정본)은 손대지 않는다** — 날씨는 6번째 스코어링 축이 아니라, **점수 산출 이후 backend 선택 레이어에서 한 번만 적용하는 재정렬(rerank) 레이어**로 붙인다. M6(로드밸런싱)과 동일한 위치·동일한 "선택 레이어 단 1회 적용" 패턴이며, M6 **다음 단계**(§7.1.2 파이프라인 [3.5])에 끼운다. compare 34필드는 수정하지 않고 **신규 필드만 additive-only로 추가**했다(§15.8.8). D18 응답 스키마는 미검증(키만 발급)이라 필드명은 전부 "가정"이다. 설계는 **§15.8**에 있다.
- **문서 성격**: **설계 문서**. 실제 서비스 코드는 구현하지 않았다 (PRD 3.4 / 6.2 제약). 문서 내 DDL·API 스펙·의사코드는 "이렇게 구현된다"를 대표가 그림으로 이해하기 위한 설계 산출물이다.

> ## 이 문서를 읽기 전 알아야 할 3가지
> 1. **공공데이터 API의 실제 엔드포인트·필드명은 검증되지 않았다.** 이 문서에서 외부 API 인터페이스로 표기된 것은 전부 **가정(Assumption)**이며, `12절 확인 필요 집계표`에 모아두었다. 추측으로 지어낸 필드명은 사용하지 않았다.
> 2. **v1.1 기준 PRD 논스코프(N1~N8)는 설계하지 않았다.** 단 **v1.2에서 N1·N3·N4가 M8·M9·M10으로 승격**돼 `§15`에 신규 설계됐다(11절의 N1/N3/N4 제한사항 기술은 승격 배경으로 보존). 여전히 후순위인 N2(쿠폰)·N5(PWA) 등은 `11절 비MVP 처리`에 그대로 둔다.
> 3. **R1(집중률 예측 데이터 SPOF)에 대한 Plan B를 7.5절에 완전히 설계했다.** 이 데이터가 실시간 API로 제공되지 않아도 M2·M3가 성립하도록 3-Tier 폴백 구조를 만들었다.

---

## 1. 설계 요약 (대표용 1분 브리핑)

| 질문 | 답 |
|---|---|
| 서버는 몇 개인가 | 3개 프로세스. ① API 서버 ② 배치 수집기(스케줄러) ③ (선택) NLP 워커. 초기엔 ①+②를 한 컨테이너 안에서 돌려도 무방 |
| 데이터는 어디에 사는가 | PostgreSQL + PostGIS (영구), Redis (혼잡도 캐시·카운터·세션) |
| 공공 API를 사용자 요청마다 부르는가 | **아니다.** 배치 수집기가 주기적으로 당겨서 DB에 적재하고, API 서버는 DB/Redis만 읽는다. 공공 API 쿼터·장애가 사용자 화면에 직접 전파되지 않는다 |
| 집중률 데이터가 실시간 API가 아니면 어떻게 되나 | 3단계로 자동 강등(Tier A → B → C)된다. Tier C는 외부 데이터 없이도 자체 산출식으로 혼잡 지수를 만든다. 화면에는 "데이터 출처/신선도"를 항상 표기한다 |
| 2차 오버투어리즘(풍선효과)은 어떻게 막나 | Redis에 코스별 "안내 발급 카운터"를 슬라이딩 윈도로 세고, 수용력 대비 비율이 임계치를 넘으면 B/C/D 대안으로 확률적 분산한다 (8절) |
| 기술 스택은 초안대로 Node인가 | **Python/FastAPI 단일 스택을 제안**한다. 근거는 9절. 단 **결정은 대표/planning-lead 몫**이며 Node 유지 시의 보완안도 함께 적었다 |

---

## 2. 시스템 아키텍처

### 2.1 전체 구성도

```
┌──────────────────────────────────────────────────────────────────────────┐
│  CLIENT (Mobile-First 반응형 웹 / Next.js)                                │
│  0 온보딩 · 1 홈(혼잡도 전광판) · 2 여행지 추천 · 3 AI 경로 비교 · 4 저장코스 │
└───────────────┬──────────────────────────────────┬───────────────────────┘
                │ HTTPS (JSON)                     │ JS SDK 직접 로드
                │                                  │ (지도 타일·마커 렌더)
                ▼                                  ▼
┌──────────────────────────────────────┐   ┌────────────────────────────┐
│  Nginx (TLS 종단 · 정적 · 리버스프록시) │   │  Kakao Map JS SDK (제안)    │
└───────────────┬──────────────────────┘   │  ※ 라이선스 확인 필요 (R6)  │
                │                          └────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  API SERVER  (FastAPI 제안 / 무상태 stateless)                            │
│                                                                          │
│   [middleware]  request-log · rate-limit · auth(JWT) · error-envelope     │
│   ────────────────────────────────────────────────────────────────────    │
│   /onboarding   /congestion   /places   /routes/compare   /me/routes      │
│                                                                          │
│   ※ 외부 공공 API를 요청 경로에서 직접 호출하지 않는다 (DB/Redis만 읽음)     │
│   ※ 예외: NLP 추론 1건 (온보딩) — AI팀 인터페이스로 위임                    │
└───┬───────────────────────┬──────────────────────────┬───────────────────┘
    │                       │                          │
    │ read/write            │ cache/counter            │ 함수 호출 or 내부 HTTP
    ▼                       ▼                          ▼
┌────────────────┐  ┌──────────────────┐  ┌────────────────────────────────┐
│ PostgreSQL 16  │  │ Redis 7          │  │ AI MODULE (ai-optimization-    │
│ + PostGIS 3    │  │                  │  │            engineer 담당)       │
│                │  │ congestion:*     │  │  extract_tags()                │
│ users          │  │ route:candidates │  │  score_routes()                │
│ places(GEOG)   │  │ lb:counter:*     │  │  ※ backend는 시그니처만 정의     │
│ routes         │  │ ratelimit:*      │  │  ※ 구현·모델선택은 AI팀          │
│ congestion_*   │  │ session:guest:*  │  └────────────────┬───────────────┘
│ local_merchants│  └──────────────────┘                   │ (LLM 채택 시)
└────────▲───────┘           ▲                             ▼
         │ UPSERT            │ SETEX                ┌──────────────┐
         │                   │                     │ LLM API (외부)│
┌────────┴───────────────────┴──────────┐          │ ※ 국외이전    │
│  BATCH COLLECTOR (APScheduler/Celery)  │          │   법률검토 대상│
│                                        │          └──────────────┘
│  job_congestion  (T-1h / 확인 필요)     │
│  job_places      (주 1회)               │
│  job_festivals   (일 1회)               │
│  job_merchants   (월 1회)               │
│  job_courses     (주 1회, 두루누비)      │
│                                        │
│  공통: 재시도(exp backoff) · 원문보관   │
│        · staleness 표시 · 실패 알림      │
└────────────────┬───────────────────────┘
                 │ HTTPS (API key from ENV/Secret Store)
                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  EXTERNAL PUBLIC DATA (전부 "확인 필요" 상태 — 4절 참조)                    │
│  한국관광공사 TourAPI / 한국관광 데이터랩 / 두루누비 / 소상공인시장진흥공단   │
│  / 전국문화축제 표준데이터 / 공공데이터포털 각종                            │
└──────────────────────────────────────────────────────────────────────────┘
```

### 2.2 핵심 설계 원칙 4가지

| # | 원칙 | 이유 |
|---|---|---|
| P1 | **읽기 경로에서 외부 API를 호출하지 않는다** | 공공 API 쿼터 소진·장애·지연이 사용자 화면(특히 심사 시연)에 직접 전파되는 것을 차단 |
| P2 | **모든 외부 데이터는 원문(raw JSON)을 그대로 보관한 뒤 정규화한다** | 필드 스펙이 미확인(R1)이므로, 스펙 오해가 있어도 원문에서 재파싱하면 재수집 없이 복구 가능 |
| P3 | **모든 혼잡도 값은 출처·신선도·신뢰등급을 함께 전달한다** | Plan B 강등 시 화면이 "왜 이 값인지" 설명할 수 있어야 함. 심사위원 질문 대비 |
| P4 | **시크릿은 코드에 존재하지 않는다** | 환경변수/시크릿 스토어만. 10.4절에 강제 규칙 |

---

## 3. 위치 정밀도 결정 (PRD 6.1-(c) 부서 간 합의 항목)

R4(개인정보·위치정보법)에 대한 backend 입장이다. **최종 결정은 legal-counsel 판정 후 planning-lead가 확정한다.**

| 대상 | 정밀도 | 저장 여부 | 근거 |
|---|---|---|---|
| **관광지/상점 좌표** (places, local_merchants) | 정밀 좌표 (WGS84) | DB 영구 저장 | 공개된 시설 정보이며 개인정보가 아님. 지도·경로 계산에 필수 |
| **사용자 위치 — 기본** | **시/군/구 단위 선택 (region_code)** | user_profiles에 저장 | R4 완화. "부산 해운대구" 수준이면 M2·M3 전 기능이 성립한다 |
| **사용자 위치 — 정밀 (opt-in)** | 브라우저 Geolocation, **클라이언트에서 소수점 3자리로 반올림**(약 110m 격자) | **저장하지 않음**. **요청 body로만** 수신하고 응답 후 폐기. **앱·웹서버(Nginx)·프록시 전 계층에서 미기록** | "내 근처 정렬" 편의 기능 한정. 미동의 시 시군구 중심좌표로 대체 |

**설계 결론**: MVP는 **시군구 단위를 기본 경로로 두고, 정밀 좌표는 비저장 opt-in 부가 기능**으로 둔다. 이 구조면 "위치정보를 수집·보관하지 않는다"고 말할 수 있어 R4 리스크가 크게 준다.

### 3.1 좌표 전송 방식 규약 (보안 S-H2 반영 — 필수)

> **초판의 결함**: `GET /api/v1/places?near=35.1587,129.1604`처럼 좌표를 **URL 쿼리스트링**에 실었다. 쿼리스트링은 Nginx `combined` 로그의 `$request`에 URI 전체가 기록되므로, **`guest_id` 쿠키 값과 GPS 좌표가 같은 로그 라인에 축적**된다. 이는 식별자와 결합된 위치정보 = 개인위치정보이며, 위 표의 "저장하지 않음"이라는 주장이 기술적으로 성립하지 않게 만든다. 앱 미들웨어(`request_log.py`)는 Nginx보다 뒷단이라 이를 막을 수 없다.
>
> 같은 좌표를 `POST /routes/compare`(D1)는 이미 body로 받고 있었으므로, **설계 내부 비대칭이기도 했다.**

| # | 강제 수단 | 적용 지점 | 내용 |
|---|---|---|---|
| L1 | **전송 방식** | API 계약 (§6.1 C1) | 정밀 좌표는 **GET 쿼리스트링으로 받지 않는다.** 좌표 기반 조회는 `POST /api/v1/places/search`(body 수신)로 분리한다. `GET /api/v1/places`는 `region_code` 기반 조회만 유지 |
| L2 | **해상도 축소** | 클라이언트(designer) | 좌표를 **소수점 3자리로 반올림해 전송**한다(약 110m). "내 근처 정렬" 용도에 충분하며, 잔류하더라도 개인 특정도가 크게 낮아진다 |
| L3 | **웹서버 로그** | Nginx `log_format` | `$request` 대신 **`$uri`만 기록**(쿼리스트링 제외). 불가피하면 `map`으로 좌표 파라미터를 `***` 치환. **이 설정은 배포 산출물의 필수 항목이며 누락 시 배포 차단** |
| L4 | **앱 로그** | `middleware/request_log.py` | body의 `lat`/`lng`/`near` 키를 마스킹. 요청 본문 전체 로깅 금지 |
| L5 | **외부 유출** | 프론트 | 좌표를 URL·`Referer`·브라우저 히스토리에 남기지 않는다(GET 미사용으로 자동 충족). 지도 SDK 호출에 사용자 좌표를 그대로 전달하지 않는다 |

> **확인 필요 (Q-L1)**: 비저장 1회성 정밀 좌표 수신도 위치정보법상 신고 대상인지 → legal-counsel 판정 필요.
> **추가 질의 (SEC→L-A)**: 위 L3 적용 **이전** 상태(로그 잔류)를 "수집·보관"으로 볼 수 있는지도 함께 판정 대상이다. L-1 판정의 전제가 여기에 걸려 있다.

---

## 4. 데이터셋 검증 표 (PRD 6.2-①)

> **중요**: 아래 "확인상태" 컬럼이 이 표의 본체다. **`확인됨`이 하나도 없다** — 이 파이프라인에서 실제 API 호출 테스트를 하지 않았기 때문이다(PRD 3.4). 초안 7절이 "확정 데이터셋 연동 명세"라고 표기한 것을 그대로 신뢰하지 않았다.
>
> **2026-07-23 갱신**: 대표가 관광콘텐츠랩(api.visitkorea.or.kr)에서 10개 데이터셋의 **활용신청 승인**을 실제로 받았다(신청일 2026-07-23, 만료예정일 2028-07-23). 아래 표에 `키발급` 상태로 반영했다. **주의: 키 발급 = 활용신청 승인일 뿐, 실제 호출로 응답 스키마를 받아본 것은 아직 아니다.** 필드명·형식은 여전히 "가정"이며, 실호출 검증 전까지 `확인됨`으로 격상하지 않는다.

확인상태 범례: `확인필요` = 존재·형태 미검증 / `대체필요` = 미검증 + 실패 시 대안이 반드시 필요 / `대체가능` = 없어도 MVP 성립 / **`키발급`** = 활용신청 승인 완료, 응답 스키마는 미검증

| # | 데이터셋 (초안 표기) | 제공기관 (초안 표기) | 확인상태 | 사용 MVP | 필요 필드(설계상 요구사항) | 갱신주기(설계 가정) | 미확인 사항 |
|---|---|---|---|---|---|---|---|
| D1 | 관광지 집중률 방문자 추이 **예측** 정보 | 한국관광공사 (데이터랩) | **대체필요 (최우선)** | M2, M3, M6 | 지역/관광지 식별자, 기준시각, 예측시각, 집중률 또는 방문자 추정치, 등급 | 시간별 희망 | **실시간 REST API인지 / 통계 리포트·파일 다운로드인지 확인 필요.** 이것이 M2·M3의 SPOF (R1) |
| D2 | 빅데이터 지역별 방문자수 | 한국관광공사 | 대체필요 | M2 폴백, M3 | 지역코드, 기간, 방문자수(내국인/외국인 구분 여부 불명) | 월/일 단위 추정 | 최소 시간 해상도, 지역 단위(시군구? 읍면동?), 공개 지연(lag) 확인 필요 |
| D3 | 지역별 관광 수요 강도 | 한국관광공사 | **키발급 (2026-07-23)** | M2 폴백 | 지역코드, 기간, 강도 지수 | 미상 | 지수의 정의·정규화 범위(0~100?)는 여전히 실호출 전까지 확인 필요 |
| D4 | 두루누비 정보 서비스 (걷기·자전거 코스) | 한국관광공사 / 두루누비 | 확인필요 | M3, M4 | 코스 ID, 코스명, 총거리, 소요시간, 난이도, **경로 좌표열(LineString)** | 분기/연 단위 추정 | **경로 좌표열(polyline)을 실제로 제공하는지가 핵심.** 좌표열이 없으면 지도 위 "선(Line)" 표현이 불가. 키 미발급 |
| D5 | 기초지자체 중심 관광지 정보 | 지자체 / 공공데이터포털 | 확인필요 | M3, M5 | 명칭, 주소, 좌표, 분류, 설명 | 월/분기 | 좌표 좌표계(WGS84? TM?) 확인 필요. **자매 데이터셋 "관광지별 연관 관광지 정보"(별도 ID)는 대표가 키발급 받음** — 후자는 D5-2로 신설, 4.2절 참고 |
| D6 | 지역별 관광 자원/다양성 | 한국관광공사 | **부분 키발급 (자원수요만, 2026-07-23), 실호출 성공 (2026-07-24)** | M3(보조) | 지역코드, 자원 수/다양성 지수 | 미상 | "관광 자원 수요"는 키발급됨. "관광 다양성"은 별도 데이터셋(미확인) — 두 지표를 하나의 행으로 합쳐 쓴 원 설계가 부정확했음, 4.2절 참고. **엔드포인트 실호출 검증됨**: `GET https://apis.data.go.kr/B551011/AreaTarResDemService/areaTarSvcDemList` — 필수 파라미터 `serviceKey, MobileOS, MobileApp, areaCd, baseYm`. 정상 응답 envelope: `{response:{header:{resultCode,resultMsg}, body:{items, numOfRows, pageNo, totalCount}}}` (params 누락 시엔 flat `{resultCode, resultMsg}` 형태로 다름 — 두 형태를 다 파싱해야 함). `areaCd=1(서울)·baseYm=202606` 조합은 데이터 0건 — 다른 지역/월로 재시도 필요, 데이터 자체가 없는 것인지 lag 때문인지는 추가 확인 필요 |
| D7 | 소상공인시장진흥공단 상권정보 API | 소상공인시장진흥공단 | 확인필요 | M5 | 상가 ID, 상호, 업종 대/중/소분류, 좌표, 주소 | 분기 | 반경 검색 지원 여부, 일일 호출 쿼터 확인 필요. 키 미발급 |
| D8 | 한국관광공사 근처 음식점/숙박 API | 한국관광공사 (TourAPI 계열) | **키발급 추정 (2026-07-23)** | M5 | 좌표 기반 반경 검색, 콘텐츠 ID/명칭/좌표/이미지 | 수시 | 대표가 발급받은 "국문 관광정보 서비스_GW"가 이 TourAPI 베이스 서비스로 추정되나, **동일 데이터셋인지 실호출로 재확인 필요.** 반경 상한, 이미지 저작권·재배포 조건도 별도 확인 필요 |
| D9 | 전국문화축제 표준데이터 | 행정안전부 표준데이터 계열 | 확인필요 | M2(배너) | 축제명, 기간(시작/종료), 개최장소, 좌표 또는 주소 | 일 1회 | 좌표 미제공 시 주소→좌표 지오코딩 필요 (지오코딩 쿼터 별도 소요). 키 미발급 |
| D10 | 전국공연행사 표준데이터 | 행안부 계열 | 대체가능 | — | (D9와 동일 구조) | 일 1회 | MVP 제외 가능 |
| D11 | 반려동물 동반 / 무장애 / 웰니스 / 고캠핑 | 한국관광공사 | **키발급 — 4종 전부 (2026-07-23)** | M3(가중치), M5 | 콘텐츠 ID, 반려동물 동반 가능 여부, 무장애 편의시설 플래그 | 수시 | **초안 페르소나 1(아이+반려견)의 핵심 필터.** 4개 데이터셋 모두 개별 승인 완료. 플래그가 boolean인지 서술문인지는 실호출 전까지 확인 필요 |
| D12 | 주차장 정보 | (초안 2.1에 언급, 7절 표엔 미기재) | 확인필요 | M3 | 주차장명, 좌표, 주차면수, 요금 | 월 | 초안 내에서도 데이터셋 출처가 특정되지 않음. 키 미발급 |
| D13 | 관광지 오디오 가이드 (오디) | 한국관광공사 | **확인필요 (M9 승격, ex-N3)** | M9 | 스팟/콘텐츠 ID, 오디오 제목, 언어, 재생시간, 스트리밍/파일 URL | 수시(설계 가정) | **스트리밍 URL이 상시 URL인지 서명·만료 URL인지 확인 필요**(캐시 TTL을 좌우). 데이터셋 실재·필드 스펙 미검증. §15.2 참조 |
| D14 | 관광사진 / 공모전 수상작 | 한국관광공사 | **키발급됨(2026-07-24, 활용신청 승인), 실호출은 실패** | M5 보조(썸네일) | 사진 제목·촬영일·촬영지·키워드·웹용 이미지 URL, 공공누리 1유형(자유 이용 가능) | 실시간 | Base URL `apis.data.go.kr/B551011/PhotoGalleryService1`(Swagger로 확인), 오퍼레이션 `galleryList1`/`gallerySearchList1` 등. **실호출 결과 `403 Forbidden`(평문, JSON 에러 아님)** — 파라미터·UA·프로토콜 바꿔도 동일해 게이트웨이/승인반영지연으로 추정, 원인 미확정. 재시도 및 계정 페이지의 실제 End Point 재확인 필요. **D14는 더 이상 "MVP 제외"가 아니다** — 대회 요강의 이미지 저작권 사전 점검 요건에 대응하는 용도로 승격, M5 스팟 카드 썸네일 소스 후보 |
| D15 | 웹 Geo-location (브라우저) + 방문 사진 | (자체 수집) | **보조신호 한정 (M8 승격, ex-N1)** | M8 | 브라우저 Geolocation 좌표(요청 body·비저장), 목적지 좌표(places), 사진(오브젝트스토리지 참조·단기 TTL) | 이벤트성 | **EXIF는 신뢰 소스로 쓰지 않는다.** 서버 수신 시점 좌표만 사용. 위치정보법·초상권 재검토 필요(legal). §15.1 참조 |
| D16 | Tmap Route API (경로탐색 서비스) | SK텔레콤 (TMAP) | **과금 확인됨 (2026-07-23), 키 미발급** | M10, M3·M4 | 출발/도착/경유 좌표, 이동수단, 경로 좌표열(polyline), 총거리·소요시간 | 실시간(요청형) | 요금은 확정됨(4.3절) — **무료 1,000건/일**, 초과 시 정액제(월 220만원) 또는 종량제(11원/건). 개발·시연 트래픽으로는 무료 한도 내 충분할 전망. **API 키는 SK Open API(openapi.sk.com) 별도 가입 필요, 아직 미발급.** 좌표계·비상업 이용조건은 여전히 확인 필요. §7.6 `snapped` 대안의 실체. §15.3 참조 |
| D17 | 국가유산청 국립무형유산원_공방 정보 목록 조회 서비스 (신규) | 국가유산청 | **키발급 (2026-07-23)** | M5(보조) | 공방명, 위치, 공예분야, 체험 가능 여부(추정) | 미상 | 원본 초안이 언급한 "로컬 공방"(연인 페르소나 가중치)에 대응하는 실제 데이터셋. 필드 스펙 미검증. 이번 스코프에 새로 편입 |
| D18 | 기상청_관광코스별 관광지 상세 날씨 조회서비스 (신규) | 기상청 | **키발급 (2026-07-23)** | **M14(rerank 보조)** | 코스/관광지 식별자, 기준일시(발표시각), 예보시각, 날씨 상태(SKY/PTY), 강수확률(POP) | 3시간(발표주기 추정) | **대표가 M14로 채택 확정(2026-07-23).** 단 **AI 5축 스코어링에는 넣지 않는다** — 점수 산출 이후 선택 레이어의 재정렬(rerank)로만 반영한다(§15.8). 응답 필드명·SKY/PTY 코드·POP 필드는 **실호출 전까지 전부 "가정"**(§15.8.9 Q-D18) |

### 4.1 이 표에서 대표가 읽어야 할 것

- **D1이 무너지면 M2(전광판)와 M3(1:1 비교)의 "혼잡도" 축이 동시에 무너진다.** 그래서 7.5절 Plan B가 이 문서에서 가장 중요한 부분이다.
- **D4의 좌표열(polyline) 제공 여부**가 두 번째 급소다. 초안의 핵심 가치인 "끊기지 않는 명확한 선(Line)"이 여기에 달려 있다. 좌표열이 없으면 → 7.6절 대안.
- D10, D14는 MVP에서 빼도 서사가 성립한다 (PRD 3.1 판정기준 3).

### 4.2 신규 확인 사항 (2026-07-23, 대표 API 키 발급 대조 중 발견)

- **"관광지별 연관 관광지 정보"(D5-2, 신규)** — D5(기초지자체 중심 관광지 정보)와 이름이 비슷하지만 **다른 데이터셋**이다. 지자체별 중심관광지와 연결성 높은 연관 관광지를 전체/관광지/음식/숙박 유형별 최대 50위까지 제공 — **M3(우회 경로 후보)·M6(로드밸런싱 대안 경로 후보) 산출에 KTO가 이미 계산해둔 데이터를 그대로 쓸 수 있다는 뜻**이라 가치가 크다. 대표가 키를 발급받았으므로 M3/M6 설계에 이 데이터셋을 반영할지는 다음 재작업 라운드에서 검토한다.
- **D6 정정** — "지역별 관광 자원/다양성"을 원래 표가 하나의 행으로 합쳐놨는데, 실제로는 "관광 자원 수요"와 "관광 다양성"이 서로 다른 두 데이터셋이다. 대표는 전자만 키를 발급받았다.
- **D8 재확인 필요** — "한국관광공사 근처 음식점/숙박 API"라고 원 설계가 지칭한 것이 대표가 발급받은 "국문 관광정보 서비스_GW"와 동일한지 실호출로 확인해야 한다. TourAPI는 계열 서비스가 여러 개(언어별 GW 포함)라 이름만으로 단정하지 않는다.
- **D16(Tmap) 과금 확정** — 무료 1,000건/일, 초과 시 정액제 월 220만원 또는 종량제 11원/건. 개발·심사 시연 규모에선 무료 한도로 충분할 전망이라 비용 리스크는 낮다. 자세한 내용은 대표 대화 로그(2026-07-23) 참고.
- **D17/D18 신규 편입** — 국가유산청 공방정보, 기상청 코스별 날씨. 둘 다 이번에 새로 발견돼 대표가 즉시 키를 발급받았다. **날씨(D18)는 대표가 M14로 채택 확정**(2026-07-23)했으며, **AI 5축 스코어링에는 넣지 않고** 점수 산출 이후 선택 레이어의 재정렬(rerank) 레이어로만 반영한다(§15.8). D17 공방정보는 M14의 **실내 대안 후보**(우천 시)로도 연계된다(§15.8.4).

---

## 5. DB 스키마 (PostgreSQL 16 + PostGIS 3)

### 5.1 ERD 개요

```
users ──1:1── user_profiles ──┐
  │                           │ (tags/vector)
  │                           ▼
  └──1:N── saved_routes ──N:1── routes ──1:N── route_segments ──N:1── places
                                  │                                     │
                                  │                                     ├──1:N── reviews
                                  │                                     ├──1:N── congestion_snapshots
                                  │                                     └──N:N── local_merchants (근접 매핑)
                                  │
                                  └──1:N── route_congestion_snapshots (뷰/집계)

festivals ──(지역/좌표)──▶ places
raw_ingest_log ──(원문 보관)──▶ 모든 배치 잡
```

### 5.2 DDL

```sql
-- =====================================================================
-- 0. 확장 및 공통
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- 상호/관광지명 부분검색
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- 참고: pgvector는 "선택" — 9.3절에서 채택 여부 논의

-- 공통 updated_at 트리거
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;


-- =====================================================================
-- 1. 사용자 / 온보딩 프로필
-- =====================================================================
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           CITEXT UNIQUE,              -- NULL 허용: 게스트 승격 전
    password_hash   TEXT,                       -- bcrypt/argon2id. 평문 절대 금지
    display_name    VARCHAR(40),
    is_guest        BOOLEAN NOT NULL DEFAULT FALSE,
    status          VARCHAR(16) NOT NULL DEFAULT 'active',  -- active|dormant|deleted
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_user_identity CHECK (is_guest = TRUE OR email IS NOT NULL)
);
CREATE INDEX idx_users_email ON users (email) WHERE status = 'active';
CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- 온보딩 결과. ★ tags 스키마는 08-interface-contract.md §1.5 OnboardingResult 정본을 따른다
CREATE TABLE user_profiles (
    user_id         UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,

    -- ★ raw_input 컬럼은 존재하지 않는다 (보안 S-H1 / 08 §6 E2 잠정 정본).
    --   근거: 이 컬럼을 SELECT하는 쿼리가 설계 전체에 0건이며(스코어링·필터·랭킹은 tags와
    --   tag_vector만 소비), 자유 서술에는 아동·건강·장애·종교 추론 정보가 스키마 방어 없이
    --   유입된다. 목적 없는 보관이므로 개인정보 최소수집 원칙에 따라 저장하지 않는다.
    --   원문은 태그 추출 후 메모리에서 폐기한다. 상세는 10.6절.
    input_source    VARCHAR(16) NOT NULL DEFAULT 'text',   -- text | chips | mixed

    -- 구조화 태그. 축(axis) 7종별 값 + 신뢰도 (08 §1.5 정본)
    -- 예: {"companion":[{"value":"family","label":"가족","confidence":0.94}],
    --      "flag":[{"value":"child_present","label":"아이 동반","confidence":0.94}],
    --      "mobility":[{"value":"walk","label":"도보","confidence":0.71}],
    --      "mood":[{"value":"calm","label":"한적함","confidence":0.66}],
    --      "spot_pref":[{"value":"local_cafe","label":"로컬 카페","confidence":0.66}],
    --      "accessibility":[{"value":"pet_friendly_required","label":"반려동물 동반 가능","confidence":0.95}],
    --      "congestion_pref":[{"value":"avoid_priority","label":"혼잡 회피 우선","confidence":0.8}]}
    -- ※ confidence는 표시·진단 참고용. 스코어링 입력·하드필터 임계로 사용 금지 (08 §1.6)
    -- ※ accessibility 중 wheelchair_friendly·stroller_friendly는 저장 시 제외 (08 §1.7 E3)
    tags            JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- S_fit 코사인 유사도용 태그 이진 벡터. 36차원, 원소는 0.0 또는 1.0
    -- 축 순서는 tag_axis_registry가 규정 (고정 순서 필수). LLM이 수치를 주입할 경로 없음
    tag_vector      REAL[],                                 -- 36차원 이진 (08 §1.1)

    -- 5축 스코어링 가중치. {congestion, profile_fit, distance, local_exposure, trust}, 합=1.0
    -- 서버 룰이 산출 (02 §2.2 가산표 + 정규화). tag_vector와 별개 개념 — 이름 혼동 금지
    scoring_weights JSONB NOT NULL DEFAULT '{}'::jsonb,

    vector_version  SMALLINT NOT NULL DEFAULT 1,            -- 축 정의 변경 시 증가

    -- 위치 정밀도 정책(3절): 시군구 코드만 저장. 정밀 좌표 미저장
    region_code     VARCHAR(10),                            -- 법정동/행정구역 코드 (체계 확인 필요)

    extracted_by    VARCHAR(24),                            -- 'llm-v1' | 'rule-v1' | 'hybrid-v1'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_profiles_tags   ON user_profiles USING GIN (tags jsonb_path_ops);
CREATE INDEX idx_profiles_region ON user_profiles (region_code);
CREATE TRIGGER trg_profiles_updated BEFORE UPDATE ON user_profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- 태그 축 레지스트리: 벡터 차원 순서를 코드가 아닌 DB가 규정 (AI팀-backend 계약의 물리적 근거)
CREATE TABLE tag_axis_registry (
    axis            VARCHAR(24) NOT NULL,       -- companion | flag | mobility | mood
                                                -- | spot_pref | accessibility | congestion_pref  (7종)
    value           VARCHAR(32) NOT NULL,       -- 영문 코드. couple | solo | walk | local_cafe ...
    vector_index    SMALLINT NOT NULL,          -- tag_vector 내 위치 (불변, 0~35)
    label_ko        VARCHAR(40) NOT NULL,       -- designer의 칩 UI 표시명 (칩 없는 축도 값은 보유)
    vector_version  SMALLINT NOT NULL DEFAULT 1,
    PRIMARY KEY (axis, value, vector_version),
    UNIQUE (vector_index, vector_version)
);


-- =====================================================================
-- 2. 장소 (관광지/스팟) — PostGIS 핵심 테이블
-- =====================================================================
CREATE TABLE places (
    id              BIGSERIAL PRIMARY KEY,
    source          VARCHAR(24) NOT NULL,       -- 'tourapi' | 'local_gov' | 'durunubi' | ...
    source_id       VARCHAR(64) NOT NULL,       -- 원천 시스템 고유 ID
    name            VARCHAR(120) NOT NULL,
    category        VARCHAR(32),                -- attraction | trail | cafe | craft | parking | festival_site
    region_code     VARCHAR(10),
    address         TEXT,

    -- ★ geography(Point,4326): 미터 단위 거리 계산이 그대로 되어 ST_DWithin 반경 검색이 정확
    geom            geography(Point, 4326) NOT NULL,

    -- 테마 플래그. D11 필드 형태 미확인 → 정규화 시점에 boolean으로 사상 (미확인은 NULL 유지)
    pet_allowed     BOOLEAN,
    barrier_free    BOOLEAN,
    wellness        BOOLEAN,
    parking_capacity INTEGER,

    -- 수용력: 로드밸런싱 임계치 계산의 분모 (8.2절). 미확인 시 카테고리 기본값 사용
    capacity_hint   INTEGER,

    popularity_score REAL,                      -- 0~1. 핫플/숨은길 구분에 사용
    is_hidden_gem   BOOLEAN GENERATED ALWAYS AS (popularity_score < 0.35) STORED,

    raw             JSONB,                      -- ★ P2 원칙: 원문 보관
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)
);
-- ★ 공간 인덱스 (GIST) — "내 주변 5km 스팟" 쿼리의 성능 근거
CREATE INDEX idx_places_geom     ON places USING GIST (geom);
CREATE INDEX idx_places_region   ON places (region_code, category);
CREATE INDEX idx_places_name_trgm ON places USING GIN (name gin_trgm_ops);
CREATE INDEX idx_places_hidden   ON places (region_code) WHERE is_hidden_gem = TRUE;


-- =====================================================================
-- 3. 경로 (코스)
-- =====================================================================
CREATE TABLE routes (
    id              BIGSERIAL PRIMARY KEY,
    slug            VARCHAR(64) UNIQUE NOT NULL,
    name            VARCHAR(120) NOT NULL,
    route_type      VARCHAR(16) NOT NULL,       -- 'hotspot' | 'hidden'  ← 1:1 비교의 좌/우
    region_code     VARCHAR(10) NOT NULL,
    source          VARCHAR(24),                -- 'durunubi' | 'generated'
    source_id       VARCHAR(64),

    total_distance_m INTEGER,
    est_duration_min INTEGER,
    difficulty      VARCHAR(16),                -- easy | normal | hard
    transport_mode  VARCHAR(16),                -- walk | bike | car | mixed

    -- ★ 지도 위 "끊기지 않는 선". D4가 좌표열을 제공하지 않으면 7.6절 대안으로 생성
    path            geography(LineString, 4326),
    path_source     VARCHAR(16) NOT NULL DEFAULT 'unknown',
                    -- 'public'(원천 제공) | 'snapped'(도로 스냅) | 'straight'(직선 연결, 품질 저하 표시)

    -- 로드밸런싱 그룹: 같은 group_key끼리 A/B/C/D 대안 관계 (8절)
    lb_group_key    VARCHAR(64),
    lb_rank         SMALLINT,                   -- 1=A(기본), 2=B, 3=C, 4=D
    daily_capacity  INTEGER,                    -- 1일 권장 안내 상한. NULL이면 카테고리 기본값

    theme_flags     JSONB DEFAULT '{}'::jsonb,  -- {"pet":true,"barrier_free":false,...}
    raw             JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_routes_path    ON routes USING GIST (path);
CREATE INDEX idx_routes_region  ON routes (region_code, route_type);
CREATE INDEX idx_routes_lbgroup ON routes (lb_group_key, lb_rank);
CREATE INDEX idx_routes_theme   ON routes USING GIN (theme_flags jsonb_path_ops);


CREATE TABLE route_segments (
    id              BIGSERIAL PRIMARY KEY,
    route_id        BIGINT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    seq             SMALLINT NOT NULL,          -- 0,1,2... 방문 순서
    place_id        BIGINT REFERENCES places(id) ON DELETE SET NULL,
    segment_type    VARCHAR(16) NOT NULL,       -- waypoint | poi | parking | rest
    -- 이 구간만의 경로선 (구간별 지도 하이라이트 / 병목 구간 표시용)
    path            geography(LineString, 4326),
    distance_m      INTEGER,
    duration_min    SMALLINT,
    note            TEXT,
    UNIQUE (route_id, seq)
);
CREATE INDEX idx_segments_route ON route_segments (route_id, seq);
CREATE INDEX idx_segments_path  ON route_segments USING GIST (path);
CREATE INDEX idx_segments_place ON route_segments (place_id);


-- =====================================================================
-- 4. 혼잡도 스냅샷 — R1 Plan B의 물리적 근거 (7.5절)
-- =====================================================================
CREATE TABLE congestion_snapshots (
    id              BIGSERIAL PRIMARY KEY,

    -- 대상은 장소 또는 지역 둘 중 하나 (D1 해상도가 미확인이므로 양쪽 모두 수용)
    place_id        BIGINT REFERENCES places(id) ON DELETE CASCADE,
    region_code     VARCHAR(10),

    observed_at     TIMESTAMPTZ NOT NULL,       -- 데이터 기준 시각
    horizon_min     SMALLINT NOT NULL DEFAULT 0,-- 0=현재, 60=1시간 후 예측

    -- 정규화된 지수. 원천 스케일이 무엇이든 0~100으로 사상해서 저장
    congestion_index REAL NOT NULL CHECK (congestion_index BETWEEN 0 AND 100),
    level           VARCHAR(8) NOT NULL,        -- 'low'(🟢) | 'mid'(🟡) | 'high'(🔴)

    -- ★ P3 원칙: 이 값이 어디서 왔는지를 반드시 함께 저장
    tier            CHAR(1) NOT NULL,           -- 'A' | 'B' | 'C'  (7.5절 Plan B 단계)
    source_dataset  VARCHAR(48),                -- 'D1' | 'D2+D3' | 'internal_model'
    confidence      REAL CHECK (confidence BETWEEN 0 AND 1),
    is_estimated    BOOLEAN NOT NULL DEFAULT FALSE,

    raw             JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_target CHECK (place_id IS NOT NULL OR region_code IS NOT NULL)
);
-- 최신 스냅샷 조회 최적화 (전광판 TOP10이 이 인덱스를 탄다)
CREATE INDEX idx_congestion_latest ON congestion_snapshots
    (place_id, horizon_min, observed_at DESC);
CREATE INDEX idx_congestion_region ON congestion_snapshots
    (region_code, observed_at DESC);
-- 동일 시점 중복 적재 방지 (배치 재시도 멱등성)
CREATE UNIQUE INDEX uq_congestion_point ON congestion_snapshots
    (COALESCE(place_id, -1), COALESCE(region_code, ''), observed_at, horizon_min, tier);


-- =====================================================================
-- 5. 리뷰 (동행자 유형별 체크 — 초안 3.2 4️⃣)
--    ※ N1(사진/EXIF 인증)은 설계하지 않음. verified_* 컬럼 자체를 만들지 않는다
-- =====================================================================
CREATE TABLE reviews (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    place_id        BIGINT REFERENCES places(id) ON DELETE CASCADE,
    route_id        BIGINT REFERENCES routes(id) ON DELETE CASCADE,

    companion_type  VARCHAR(16),                -- couple | solo | family | pet | parents
    rating          SMALLINT CHECK (rating BETWEEN 1 AND 5),
    -- 동행자 유형별 체크박스 응답: {"good_with_kids":true,"quiet":true,"parking_easy":false}
    checks          JSONB DEFAULT '{}'::jsonb,
    body            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_review_target CHECK (place_id IS NOT NULL OR route_id IS NOT NULL)
);
CREATE INDEX idx_reviews_place  ON reviews (place_id, created_at DESC);
CREATE INDEX idx_reviews_route  ON reviews (route_id, created_at DESC);
CREATE UNIQUE INDEX uq_review_user_place ON reviews (user_id, place_id)
    WHERE place_id IS NOT NULL;   -- 1인 1리뷰 (어뷰징 1차 방어)


-- =====================================================================
-- 6. 로컬 상권 (M5)
-- =====================================================================
CREATE TABLE local_merchants (
    id              BIGSERIAL PRIMARY KEY,
    source          VARCHAR(24) NOT NULL,       -- 'semas'(소상공인) | 'tourapi'
    source_id       VARCHAR(64) NOT NULL,
    name            VARCHAR(120) NOT NULL,
    industry_large  VARCHAR(40),                -- 업종 대분류
    industry_mid    VARCHAR(40),
    industry_small  VARCHAR(40),
    region_code     VARCHAR(10),
    address         TEXT,
    geom            geography(Point, 4326) NOT NULL,
    -- 추천 카드에 노출할 태그 (온보딩 태그와 매칭)
    match_tags      JSONB DEFAULT '{}'::jsonb,  -- {"couple":0.8,"family":0.3,"craft":1.0}
    raw             JSONB,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)
);
-- ★ 경로 주변 상점 검색의 핵심 인덱스: ST_DWithin(m.geom, r.path, 500)
CREATE INDEX idx_merchants_geom     ON local_merchants USING GIST (geom);
CREATE INDEX idx_merchants_industry ON local_merchants (region_code, industry_mid);
CREATE INDEX idx_merchants_tags     ON local_merchants USING GIN (match_tags jsonb_path_ops);


-- =====================================================================
-- 7. 저장한 코스 / 축제 / 배치 로그
-- =====================================================================
CREATE TABLE saved_routes (
    user_id     UUID   NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    route_id    BIGINT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    memo        TEXT,
    saved_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, route_id)
);
CREATE INDEX idx_saved_user ON saved_routes (user_id, saved_at DESC);

CREATE TABLE festivals (
    id          BIGSERIAL PRIMARY KEY,
    source_id   VARCHAR(64) UNIQUE NOT NULL,
    name        VARCHAR(160) NOT NULL,
    start_date  DATE, end_date DATE,
    region_code VARCHAR(10),
    venue       TEXT,
    geom        geography(Point, 4326),         -- 좌표 미제공 시 NULL (지오코딩 대기)
    raw         JSONB,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_festivals_period ON festivals (start_date, end_date);
CREATE INDEX idx_festivals_geom   ON festivals USING GIST (geom);

-- 배치 실행 이력 + 원문 보관 (P2 원칙, 장애 분석·재파싱 근거)
CREATE TABLE raw_ingest_log (
    id            BIGSERIAL PRIMARY KEY,
    job_name      VARCHAR(40) NOT NULL,
    dataset_code  VARCHAR(8),                   -- 'D1'..'D12'
    started_at    TIMESTAMPTZ NOT NULL,
    finished_at   TIMESTAMPTZ,
    status        VARCHAR(16) NOT NULL,         -- success | partial | failed | skipped
    http_status   INTEGER,
    record_count  INTEGER,
    error_message TEXT,
    payload_ref   TEXT                          -- 대용량 원문은 파일/객체스토리지 경로만 기록
);
CREATE INDEX idx_ingest_job ON raw_ingest_log (job_name, started_at DESC);
```

### 5.2.1 `tag_axis_registry` 정본 시드 (vector_version = 1, 36차원)

> 출처: `08-interface-contract.md` §1.4. **backend가 축을 임의로 만들지 않는다**는 원칙은 유지되며, 정본은 08이 확정했다. 코드는 인덱스 상수를 갖지 않고 이 테이블에서 조회한다.

| index | axis | value | label_ko |
|---|---|---|---|
| 0 | companion | `couple` | 연인 |
| 1 | companion | `family` | 가족 |
| 2 | companion | `with_child` | 아이 동반 |
| 3 | companion | `with_parents` | 부모님 동반 |
| 4 | companion | `with_pet` | 반려동물 동반 |
| 5 | companion | `solo` | 혼자 |
| 6 | companion | `friends` | 친구 |
| 7 | flag | `child_present` | (칩 없음 — `with_child` 파생) |
| 8 | flag | `pet_present` | (칩 없음 — `with_pet` 파생) |
| 9 | mobility | `walk` | 도보 |
| 10 | mobility | `bike` | 자전거 |
| 11 | mobility | `car` | 차량/드라이브 |
| 12 | mobility | `transit` | 대중교통 |
| 13 | mobility | `any` | 무관 |
| 14 | mood | `calm` | 한적함 |
| 15 | mood | `lively` | 활기참 |
| 16 | mood | `healing` | 힐링 |
| 17 | mood | `romantic` | 로맨틱 |
| 18 | mood | `contemplative` | 사색 |
| 19 | mood | `unique` | 이색 체험 |
| 20 | mood | `family_friendly` | 가족 친화 |
| 21 | spot_pref | `local_cafe` | 로컬 카페 |
| 22 | spot_pref | `craft_shop` | 공방 |
| 23 | spot_pref | `traditional_market` | 전통시장 |
| 24 | spot_pref | `nature_view` | 자연경관 |
| 25 | spot_pref | `photo_spot` | 포토스팟 |
| 26 | spot_pref | `restaurant` | 맛집 |
| 27 | spot_pref | `walking_trail` | 산책로 |
| 28 | spot_pref | `festival` | 축제/이벤트 |
| 29 | accessibility | `parking_required` | 주차 필요 |
| 30 | accessibility | `stroller_friendly` | 유모차 접근 |
| 31 | accessibility | `wheelchair_friendly` | 휠체어 접근 |
| 32 | accessibility | `pet_friendly_required` | 반려동물 동반 가능 |
| 33 | congestion_pref | `avoid_priority` | 혼잡 회피 우선 |
| 34 | congestion_pref | `indifferent` | 혼잡도 무관 |
| 35 | congestion_pref | `unspecified` | (칩 없음 — 미언급 기본값) |

**슬라이스 규약** (registry에서 조회, 코드 하드코딩 금지)

| 용도 | 인덱스 범위 | 비고 |
|---|---|---|
| `S_fit` 코사인 유사도의 사용자 벡터 `u` / 코스 벡터 `v` | **14~28** (mood + spot_pref, 15차원) | 양쪽 동일 슬라이스 |
| 하드필터 (AI `score_routes` 내부에서 수행) | **29~32** (accessibility) | `candidates`의 4개 bool과 대응 |
| 가중치 가산 판정 (02 §2.2) | 7·8(flag), 21~23(local 계열), 16·18(mood), 33(congestion_pref) | — |

**민감정보 마스킹 (08 §1.7 E3)**: `tags`·`tag_vector`를 DB에 반영할 때 **index 30(`stroller_friendly`)·31(`wheelchair_friendly`)은 0으로 마스킹**한다. 이 두 값은 세션(Redis) 한정으로만 유지되어 해당 요청의 하드필터에 쓰이고 영구 저장되지 않는다.

### 5.3 대표적 공간 쿼리 3종 (GIST 인덱스가 실제로 어떻게 쓰이는지)

```sql
-- (1) 경로 주변 500m 로컬 상점 — M5 "로컬 스팟 매핑"의 실체
SELECT m.id, m.name, m.industry_mid,
       ST_Distance(m.geom, r.path)::int AS dist_m
FROM   local_merchants m
JOIN   routes r ON r.id = :route_id
WHERE  ST_DWithin(m.geom, r.path, 500)          -- ← idx_merchants_geom (GIST) 사용
ORDER BY dist_m
LIMIT  20;

-- (2) 내 주변 한적한 숨은 스팟 — M3 후보 생성
SELECT p.id, p.name, ST_Distance(p.geom, :user_point::geography)::int AS dist_m
FROM   places p
WHERE  ST_DWithin(p.geom, :user_point::geography, 10000)   -- ← idx_places_geom
  AND  p.is_hidden_gem = TRUE
  AND  (:pet_required = FALSE OR p.pet_allowed = TRUE)
ORDER BY dist_m
LIMIT  50;

-- (3) 전광판 TOP10 — 최신 스냅샷만 (LATERAL로 place당 1건)
--     ★ tie-break 필수: uq_congestion_point가 tier를 유니크 키에 포함하므로
--       동일 (place_id, observed_at, horizon_min)에 tier가 다른 두 행이 합법적으로 공존한다.
--       tie-break가 없으면 어느 행이 뽑힐지 비결정적 → 한 화면에 신뢰도가 다른 값이 섞인다 (QA J5)
SELECT p.id, p.name, c.congestion_index, c.level, c.tier, c.source_dataset, c.observed_at
FROM   places p
JOIN   LATERAL (
         SELECT * FROM congestion_snapshots cs
         WHERE  cs.place_id = p.id AND cs.horizon_min = 0
         ORDER  BY cs.observed_at DESC,            -- ← idx_congestion_latest
                   cs.tier ASC                     -- ★ 'A' < 'B' < 'C' → 최상 신뢰 tier 우선
         LIMIT 1
       ) c ON TRUE
WHERE  p.popularity_score > 0.7
ORDER BY c.congestion_index DESC
LIMIT  10;
```

#### 5.3.1 Tier 혼재 처리 규칙 (QA J5 — Major, backend 자체신고 #3 실재 확인)

**문제**: Tier 강등/승격이 배치 중간에 발생하면 같은 시각·같은 place에 tier가 다른 두 행이 남는다. 초판은 (a) 쿼리에 tie-break가 없고, (b) `data_freshness`가 응답당 1개 블록이라 tier를 단일 표기했다. 그 결과 **화면 표기가 사실과 달라진다** — 이는 이 문서의 **P3 원칙("모든 혼잡도 값은 출처·신선도·신뢰등급을 함께 전달")을 정면으로 깨는 결함**이며, 정직한 데이터 표기를 설계 가치로 삼은 §7.5의 서사를 무너뜨린다.

| # | 규칙 | 적용 지점 |
|---|---|---|
| T1 | **행 선택 결정론화**: `ORDER BY observed_at DESC, tier ASC` tie-break를 혼잡도 조회 쿼리 **전부**에 적용 (전광판·장소 상세·compare 주입) | §5.3-(3), §7.5 `compute()` |
| T2 | **item별 tier 필수 노출**: 혼잡도를 포함하는 모든 응답 item은 `congestion.tier`를 개별로 갖는다. 응답 단위 블록만으로 tier를 표기하지 않는다 | §6.0, §6.2 B1/C1/D1 |
| T3 | **`data_freshness.tier`는 집계값**: 응답 내 item tier가 모두 같으면 그 값, 다르면 **`"mixed"`**. `mixed`일 때 `notice`에 "항목마다 데이터 신뢰도가 다릅니다"를 담고 designer는 item 배지를 참조하게 한다. 허용값은 `A`\|`B`\|`C`\|`mixed`\|`none` | §6.0 |
| T4 | **`none` 처리**: 스냅샷이 없는 place는 tier `none`, `index`는 중립값, `level`은 표시하지 않는다. 비교(§6.2 D1)에서는 혼잡도 축을 제외하고 verdict 템플릿도 `none` 분기를 쓴다 | §6.2 D1, §7.7 |

> `uq_congestion_point`에서 `tier`를 빼지 않는 이유: tier를 유니크 키에서 제거하면 강등 시 UPSERT가 **기존 Tier A 실측 행을 Tier C 추정치로 덮어쓴다.** 원본을 지우지 않는다는 §7.3 안전장치 1번과 충돌한다. 따라서 **행은 공존시키되 읽기 시점에 결정론적으로 고른다**(T1)가 올바른 해법이다.

---

## 6. REST API 명세

### 6.0 공통 규약

- Base: `/api/v1`
- 응답 봉투: 성공은 리소스 그대로, 실패는 `{"error":{"code":"...","message":"...","detail":{}}}`
- 인증: `Authorization: Bearer <access_token>` (10절).
- **게스트 식별은 `HttpOnly`·`Secure`·`SameSite=Lax` 쿠키로만 수행한다.** 클라이언트는 `guest_id` 값을 알지 못하며, 프론트는 `credentials: 'include'`만 하면 된다.
  - **`X-Guest-Id` 헤더 수용은 삭제됐다** (보안 S-H4 / QA J4). 헤더·body·쿼리로 전달된 `guest_id`는 **무조건 무시하고 `400 GUEST_ID_NOT_ACCEPTED` + 보안 로그 플래그**로 처리한다.
  - 삭제 근거: 헤더 방식은 프론트 JS가 값을 읽을 수 있어야 하는데, 같은 값을 HttpOnly 쿠키로 규정한 §10.2와 **동시에 성립할 수 없다.** 구현자가 이 모순을 해소하는 가장 쉬운 길은 HttpOnly를 포기하는 것이고, 그 순간 XSS·공유기기·로그를 통해 guest_id가 유출 가능해진다. 설계에서 잡지 않으면 구현에서 자동으로 취약해지는 항목이다.
  - `guest_id`는 요청 로그·URL·에러 리포트에 **기록하지 않는다.**
- 정밀 좌표는 **body로만** 수신한다 (§3.1 L1). 쿼리스트링 수신 엔드포인트를 만들지 않는다.
- 페이지네이션: `?cursor=&limit=` (커서 방식, limit 기본 20 / 최대 100)
- **모든 혼잡도 포함 응답은 `data_freshness` 블록을 반드시 동봉하고, 각 item도 자기 `congestion.tier`를 갖는다** (P3 원칙 + §5.3.1 T2/T3).

```jsonc
"data_freshness": {
  "tier": "A",                 // A|B|C|mixed|none  ← mixed = 응답 내 item별 tier 혼재 (J5)
  "source": "D1",
  "observed_at": "2026-07-22T14:00:00+09:00",
  "is_estimated": false,
  "notice": null               // Tier B/C/mixed일 때 화면에 띄울 안내 문구
}
```

> `tier`가 `mixed`이면 **응답 단위 표기를 신뢰하지 않고 item별 `congestion.tier` 배지를 정본으로 읽는다.** designer는 두 자리를 모두 렌더한다 (08 §2.2 tier 매핑표).

### 6.1 엔드포인트 목록

| # | 화면 | Method | Path | 인증 | 설명 |
|---|---|---|---|---|---|
| A1 | 온보딩 | POST | `/api/v1/onboarding/analyze` | guest 가능 | 자연어/칩 입력 → 태그 추출 (저장 없음, 미리보기) |
| A2 | 온보딩 | POST | `/api/v1/onboarding/profile` | guest 가능 | 태그 확정 저장 (게스트는 Redis, 회원은 DB) |
| A3 | 온보딩 | GET | `/api/v1/onboarding/tag-schema` | 공개 | 칩 UI가 쓸 태그 축/라벨 목록 (designer 의존) |
| B1 | 홈 | GET | `/api/v1/congestion/board` | 공개 | 혼잡도 전광판 TOP N |
| B2 | 홈 | GET | `/api/v1/congestion/places/{place_id}` | 공개 | 특정 장소 혼잡도 시계열 |
| B3 | 홈 | GET | `/api/v1/festivals` | 공개 | 진행/예정 축제 배너 |
| C1 | 추천 | GET | `/api/v1/places` | 선택 | 여행지 추천 목록 (필터/정렬). **`region_code` 기반만. 좌표 파라미터 없음** |
| C1b | 추천 | POST | `/api/v1/places/search` | 선택 | **좌표 기반 "내 근처" 조회. 좌표는 body 수신**(§3.1 L1, S-H2) |
| C2 | 추천 | GET | `/api/v1/places/{place_id}` | 공개 | 장소 상세 + 주변 로컬 상점. **`viewed` 카운터는 §8.2 dedupe 규칙을 통과한 경우만 계상** |
| C3 | 추천 | GET | `/api/v1/places/{place_id}/merchants` | 공개 | 주변 상점만 |
| D1 | AI 경로 | POST | `/api/v1/routes/compare` | 선택 | **핵심.** 핫플 vs 숨은길 1:1 비교 리포트 |
| D2 | AI 경로 | GET | `/api/v1/routes/{route_id}` | 공개 | 경로 상세 (좌표열 포함) |
| D3 | AI 경로 | GET | `/api/v1/routes/{route_id}/alternatives` | 공개 | 로드밸런싱 대안 B/C/D |
| E1 | 저장코스 | GET | `/api/v1/me/routes` | 필수 | 저장한 코스 목록 |
| E2 | 저장코스 | POST | `/api/v1/me/routes` | 필수 | 코스 저장 |
| E3 | 저장코스 | DELETE | `/api/v1/me/routes/{route_id}` | 필수 | 저장 해제 |
| E4 | 저장코스 | POST | `/api/v1/routes/{route_id}/reviews` | 필수 | 동행자 유형별 리뷰 작성 |
| F1 | 인증 | POST | `/api/v1/auth/signup` | 공개 | 회원가입 (게스트 승격 포함) |
| F2 | 인증 | POST | `/api/v1/auth/login` | 공개 | 로그인 |
| F3 | 인증 | POST | `/api/v1/auth/refresh` | refresh | 액세스 토큰 갱신 |
| F4 | 인증 | POST | `/api/v1/auth/logout` | 필수 | refresh 무효화 |
| G1 | 운영 | GET | `/api/v1/health` | 공개 | 헬스체크 (DB/Redis/최신배치 시각) |

### 6.2 주요 엔드포인트 상세

#### A1. POST `/api/v1/onboarding/analyze` — 자연어 → 태그

```jsonc
// Request
{
  "text": "6세 아이랑 반려견이 함께 걷기 편하고 주차 넉넉한 곳",
  "chips": ["아이와 함께", "반려동물 동반"],
  "region_code": "26350"            // 선택. 시군구 단위 (3절 정책)
}
```
```jsonc
// Response 200  (08 §1.5 OnboardingResult 정본 구조)
{
  "tags": {
    "companion":       [{"value": "family",                "label": "가족",             "confidence": 0.94}],
    "flag":            [{"value": "child_present",         "label": "아이 동반",        "confidence": 0.94},
                        {"value": "pet_present",           "label": "반려동물 동반",     "confidence": 0.95}],
    "mobility":        [{"value": "walk",                  "label": "도보",             "confidence": 0.71}],
    "mood":            [{"value": "calm",                  "label": "한적함",           "confidence": 0.66}],
    "spot_pref":       [{"value": "walking_trail",         "label": "산책로",           "confidence": 0.58}],
    "accessibility":   [{"value": "pet_friendly_required", "label": "반려동물 동반 가능", "confidence": 0.95},
                        {"value": "parking_required",      "label": "주차 필요",        "confidence": 0.88}],
    "congestion_pref": [{"value": "unspecified",           "label": "미언급",           "confidence": 1.0}]
  },

  // ★ 36차원 이진 벡터. 원소는 0.0 또는 1.0만 허용 (confidence를 넣지 않는다)
  //   index:  0 1 2 3 4 5 6 | 7 8 | 9 …12 13 | 14 …20 | 21 …28 | 29 30 31 32 | 33 34 35
  "tag_vector": [
    0,1,1,0,1,0,0,   // 0~6   companion  : family(1), with_child(2), with_pet(4)
    1,1,             // 7~8   flag       : child_present, pet_present
    1,0,0,0,0,       // 9~13  mobility   : walk
    1,0,0,0,0,0,1,   // 14~20 mood       : calm(14), family_friendly(20)
    0,0,0,0,0,0,1,0, // 21~28 spot_pref  : walking_trail(27)
    1,0,0,1,         // 29~32 accessibility : parking_required(29), pet_friendly_required(32)
    0,0,1            // 33~35 congestion_pref : unspecified(35)
  ],
  "vector_version": 1,

  // 5축 가중치. tag_vector와 완전히 다른 개념 — 합 = 1.0
  "scoring_weights": {
    "congestion": 0.25, "profile_fit": 0.30, "distance": 0.15,
    "local_exposure": 0.15, "trust": 0.15
  },

  "extraction_confidence": 0.87,    // 추출 전체 1개. 진단·로그 전용
  "extracted_by": "hybrid-v1",
  "fallback_used": false            // true = LLM 장애로 룰 기반으로 처리됨
}
```

> **정본 참조**: `tags`의 축(7종)·값 집합·`tag_vector` 차원 순서는 `08-interface-contract.md` §1.4/§1.5가 정본이며, backend는 `tag_axis_registry` 테이블로 물리 고정한다. **backend가 임의로 축을 만들지 않는다.**
> **주의 3가지**
> 1. `tag_vector`는 **이진**이다. 초판이 예시로 든 "confidence를 원소로 넣은 12차원 벡터"는 폐기됐다 — LLM self-report confidence를 코사인 유사도 가중치로 쓰는 것은 근거 없는 가중이다 (08 §1.3).
> 2. `confidence`(값 단위)와 `extraction_confidence`(전체 1개)는 **표시·진단 참고용**이며 스코어링 입력·하드필터 임계·자동 재질의 트리거로 쓰지 않는다 (08 §1.6).
> 3. `unmatched_note`는 **내부 진단 로그 전용**이다. 이 응답과 DB에 담지 않으며 화면에도 노출하지 않는다 (보안 S-M2).
> **저장 시 마스킹**: A2(`/onboarding/profile`)로 확정 저장할 때 `tag_vector[30]`(유모차)·`[31]`(휠체어)은 0으로 마스킹하고 `tags.accessibility`에서도 제외한다 (§5.2.1, 08 §1.7 E3).

#### B1. GET `/api/v1/congestion/board`

```
GET /api/v1/congestion/board?region_code=26&limit=10&horizon_min=0
```
```jsonc
// Response 200
{
  "items": [
    {
      "place_id": 1032, "name": "해운대해수욕장", "region_code": "26350",
      "congestion_index": 87.4, "level": "high", "level_emoji": "🔴",
      "trend": "rising",                       // rising|flat|falling (직전 스냅샷 대비)
      "observed_at": "2026-07-22T14:00:00+09:00",
      "alternative_route_id": 551              // 이 핫플의 숨은길 대안 (M3 진입점)
    }
  ],
  "data_freshness": {
    "tier": "B", "source": "D2+D3",
    "observed_at": "2026-07-22T14:00:00+09:00",
    "is_estimated": true,
    "notice": "실시간 예측 데이터 지연으로 최근 방문 통계 기반 추정치를 표시합니다."
  }
}
```

#### C1 / C1b. 여행지 추천 목록

```
# C1 — 지역 기반 (좌표 없음)
GET /api/v1/places?region_code=26350&theme=pet_friendly&sort=personalized&limit=20
```
```jsonc
// C1b — 좌표 기반 "내 근처". ★ 좌표는 body로만 받는다 (§3.1 L1 / 보안 S-H2)
POST /api/v1/places/search
{
  "region_code": "26350",
  "near": {"lat": 35.159, "lng": 129.160},   // 소수점 3자리(약 110m)로 반올림된 값만 수신
  "theme": "pet_friendly",
  "sort": "personalized",
  "limit": 20
}
```
> **왜 GET을 쓰지 않는가**: 쿼리스트링 좌표는 Nginx access log의 `$request`에 `guest_id` 쿠키와 **같은 라인에** 남는다. 그러면 "위치정보를 저장·로깅하지 않는다"는 §3의 설계 결론이 사실과 달라진다. 앱 미들웨어는 Nginx보다 뒷단이라 이를 막을 수 없다. **소수점 4자리 초과 좌표를 수신하면 3자리로 절삭한 뒤 처리하고, 원본 정밀도는 어디에도 남기지 않는다.**
```jsonc
// Response 200
{
  "items": [{
    "id": 2041, "name": "달맞이길 공방거리", "category": "craft",
    "address": "부산 해운대구 ...",
    "location": {"lat": 35.1587, "lng": 129.1804},
    "distance_m": 1240,
    "congestion": {"index": 24.1, "level": "low", "tier": "B"},
    "themes": {"pet_allowed": true, "barrier_free": null, "wellness": false},
    "is_hidden_gem": true,
    "match_score": 0.82,                       // 온보딩 태그 대비 적합도 (AI팀 산출)
    "match_reasons": ["반려동물 동반 가능", "혼잡도 낮음", "주차 여유"],
    "review_summary": {"count": 12, "avg_rating": 4.3,
                       "top_checks": ["good_with_pets", "parking_easy"]},
    "nearby_merchant_count": 7
  }],
  "next_cursor": "eyJpZCI6MjA0MX0="
}
```
> `themes.barrier_free: null`은 **"데이터 미확인"**을 뜻한다. false(없음)와 구분한다. 화면에서도 회색 처리해야 한다 (designer 전달 사항).

#### D1. POST `/api/v1/routes/compare` — 1:1 대조 리포트 (핵심)

```jsonc
// Request
{
  "origin":      {"region_code": "26350"},     // 또는 {"lat":..,"lng":..} (opt-in, 소수점 3자리)
  "destination": {"place_id": 1032},           // 사용자가 가려던 핫플
  "profile":     {"use_saved": true},          // 또는 인라인 {tag_vector, scoring_weights, vector_version}
  "transport_mode": "car",
  "departure_at": "2026-07-26T10:00:00+09:00"
}
```
> **인라인 프로필 검증**: `use_saved=false`로 `tag_vector`를 직접 넘기는 경우 **길이 36 / 원소 ∈ {0.0, 1.0} / `vector_version` 일치**를 서버가 검증하고 위반 시 `400`으로 거절한다. `scoring_weights`는 5키 전부 존재 + 각 0~1 + 합 1.0±0.01을 검증한다 (보안 S-M1 경계값).
```jsonc
// Response 200  — 08 §2.2 정본표(34필드) 준수
{
  "comparison_id": "cmp_01J...",               // (1) cmp_ 접두 ULID
  "generated_at": "2026-07-22T15:02:11+09:00", // (2)
  "hotspot": {                                 // (3) hidden과 동일 키 구조
    "route_id": 900,                           // (4) int (routes PK)
    "name": "해운대 메인 코스",                  // (5)
    "route_type": "hotspot",                   // (6) hotspot | hidden
    "congestion": {
      "index": 87.4,                           // (7) 0~100
      "level": "high",                         // (8) low | mid | high  ← 영문 enum
      "tier": "B",                             // (9) A | B | C | none
      "source": "D2+D3",                       // (10)
      "observed_at": "2026-07-22T14:00:00+09:00"  // (11) ISO8601 | null
    },
    "total_distance_m": 14200,                 // (12) ★ 미터 int (km float 폐기)
    "est_duration_min": 52,                    // (13)
    "bottleneck_segments": [                   // (14) 객체 배열
      {"seq": 2, "name": "해운대로 진입부", "delay_min": 18}
    ],
    "spot_fit": {                              // (15~18) ★ AI 산출
      "score": 0.31,
      "matched_tags": [],                                       // registry value 영문 코드
      "unmatched_tags": ["pet_friendly_required","parking_required"],
      "matched_spots": []                                       // [{place_id,name,category,matched_tags}]
    },
    "review_trust": {                          // (19~21) backend 산출
      "count": 214,                            // 전체 리뷰 수
      "companion_matched_count": 6,            // 동행 유형 일치 리뷰 수 (reviews.companion_type)
      "coldstart": false                       // count < 3 이면 true
    },
    "path_geojson": {"type": "LineString", "coordinates": [[129.16,35.15], "..."]},  // (22)
    "path_source": "public"                    // (23) public | snapped | straight
  },
  "hidden": {
    "route_id": 551, "name": "달맞이 숨은길 코스", "route_type": "hidden",
    "congestion": {"index": 22.8, "level": "low", "tier": "B",
                   "source": "D2+D3", "observed_at": "2026-07-22T14:00:00+09:00"},
    "total_distance_m": 16800, "est_duration_min": 61,
    "bottleneck_segments": [],
    "spot_fit": {
      "score": 0.86,
      "matched_tags": ["pet_friendly_required","parking_required","calm"],
      "unmatched_tags": [],
      "matched_spots": [
        {"place_id": 2041, "name": "달맞이길 공방거리", "category": "craft",
         "matched_tags": ["craft_shop","calm"]}
      ]
    },
    "review_trust": {"count": 31, "companion_matched_count": 19, "coldstart": false},
    "path_geojson": {"type": "LineString", "coordinates": ["..."]},
    "path_source": "public",
    "local_merchants": [                       // (24) hidden 전용
      {"id": 88, "name": "○○공방", "industry_mid": "공예", "dist_from_path_m": 120}
    ],
    "load_balancing": {                        // (25) hidden 전용 — §8절, 08 §3.5
      "applied": true,
      "reason": "primary_over_threshold",      // primary_over_threshold | primary_amber_distributed
                                               // | time_shift | region_expanded | no_alternative
      "original_route_id": 550,                // applied=true일 때만
      "assigned_rank": "B",
      "notice": "이 코스에 방문 요청이 몰려 비슷한 분위기의 다른 코스를 안내합니다.",
      "suggested_departure": null              // reason=time_shift일 때만 ISO8601
    }
  },
  "verdict": {                                 // (26~30) ★ backend 템플릿 조립 (§7.7). LLM 미사용
    "congestion_delta": -64.6,                 // (26) 절대 포인트 (hidden − hotspot)
    "congestion_delta_pct": -74,               // (27) 상대 % (음수 = 낮음). 화면 델타 카드가 쓰는 값
    "duration_delta_min": 9,                   // (28)
    "fit_delta": 0.55,                         // (29)
    "headline": "9분 더 걸리지만 혼잡도는 65p 낮고, 맞춤 조건 3개를 만족합니다."   // (30)
  },
  "scoring_weights_used": {                    // (31) ★ AI 산출. 5키 합 1.0
    "congestion": 0.25, "profile_fit": 0.30, "distance": 0.15,
    "local_exposure": 0.15, "trust": 0.15
  },
  "score_breakdown": {                         // (32) ★ AI 산출. 양쪽 모두 포함
    "hotspot": {"congestion": 0.13, "profile_fit": 0.09, "distance": 0.14,
                "local_exposure": 0.03, "trust": 0.11, "total": 0.50},
    "hidden":  {"congestion": 0.23, "profile_fit": 0.26, "distance": 0.11,
                "local_exposure": 0.13, "trust": 0.09, "total": 0.82}
  },
  "data_freshness": {                          // (33~34)
    "tier": "B",                               // A|B|C|mixed|none — item tier 혼재 시 "mixed"
    "source": "D2+D3",
    "observed_at": "2026-07-22T14:00:00+09:00",
    "is_estimated": true,
    "notice": "혼잡도는 최근 방문 통계 기반 추정치입니다."
  }
}
```

**소관 분리 (08 §2.1)**

| 구분 | 필드 | 주체 |
|---|---|---|
| 값 산출 | `spot_fit.*`(15~18), `scoring_weights_used`(31), `score_breakdown`(32) | **ai-optimization-engineer** |
| 값 산출 + 직렬화 | 그 외 전부 — 봉투·혼잡도·거리·리뷰·경로·로드밸런싱·`verdict` | **backend** |

> **단위·enum 규약**: 거리는 항상 **미터(int)**, enum은 항상 **영문**이다. `총 {km}` 표기와 `여유/보통/혼잡` 한국어 라벨은 designer가 화면에서 변환한다. **API에 한국어를 넣지 않는다.**
> **`congestion.level` 임계(잠정, 근거 없는 가정값)**: `index < 33` → `low`, `33 ≤ index < 66` → `mid`, `66 ≤` → `high`. 3등분이며 실측 확보 시 보정한다.
> **`congestion_delta_pct` 산식**: `round((hidden.index − hotspot.index) / max(hotspot.index, 1) × 100)`. 위 예시는 (22.8−87.4)/87.4 = −74%. **화면 델타 카드는 `_pct`를 쓰고 `congestion_delta`(절대 p)와 혼용하지 않는다** (QA m3).
> **`tier == "none"`인 경우**: 해당 축을 비교에서 제외하고 `level`을 표시하지 않으며, verdict는 §7.7의 `none` 분기 템플릿을 쓴다.
> **designer 전달 사항**: 모바일 좌우 비교 화면은 `hotspot`/`hidden` 두 객체의 **동일 키 구조**를 전제로 그리면 된다. 키 이름이 좌우 대칭이다.

#### F2. POST `/api/v1/auth/login`

```jsonc
// Request  { "email": "user@example.com", "password": "••••••••" }
// Response 200
{
  "access_token": "eyJhbGciOi...",   // 30분
  "token_type": "Bearer",
  "expires_in": 1800,
  "user": {"id": "uuid", "display_name": "서연", "has_profile": true}
}
// refresh_token 은 body에 넣지 않고 HttpOnly·Secure·SameSite=Lax 쿠키로 내려준다 (10.2절)
```

---

## 7. 공공데이터 배치 수집 파이프라인

### 7.1 부서 간 인터페이스 계약 (ai-optimization-engineer)

backend는 아래 **2개 함수의 시그니처만 정의**하고 구현은 AI팀에 넘긴다. 정본은 `08-interface-contract.md` §1.5·§3.2·§5.1이다.

> **초판 대비 변경 3가지**
> 1. 초판의 단일 가중치 벡터 컬럼(폐기된 이름)을 → `tag_vector`(36차원 이진) + `scoring_weights`(5축)로 분리.
> 2. `score_routes`가 프로필 **전체**를 받는다. 초판은 벡터 하나만 넘겨 AI의 하드필터·5축 가중치 입력을 충족하지 못했다 (QA J1).
> 3. **`build_verdict`는 AI 계약에서 빠졌다.** LLM 호출이 아니라 backend 템플릿 조립으로 확정됐고 **소관도 backend로 이관**됐다 → §7.7.

```python
# src/ai_contract.py  (인터페이스 정의 전용 — 실제 구현은 ai-optimization-engineer)
from typing import TypedDict

class TagValue(TypedDict):
    value: str            # 영문 코드 (tag_axis_registry.value)
    label: str            # 한국어 표시명 (registry.label_ko와 동일해야 함)
    confidence: float     # 0~1. 표시·진단 참고용 — 임계 판정/스코어링 사용 금지

class OnboardingResult(TypedDict):
    tags: dict[str, list[TagValue]]      # key = 축 이름 7종. 모든 축이 여기에 평탄화된다
    tag_vector: list[float]              # 36차원, 원소는 0.0 또는 1.0 (이진)
    vector_version: int                  # 현재 1
    scoring_weights: dict[str, float]    # 5키(congestion/profile_fit/distance/
                                         #     local_exposure/trust), 합 1.0
    extraction_confidence: float         # 추출 전체 1개. 진단·로그 전용
    unmatched_note: str | None           # 내부 진단 전용 — 저장·화면 노출 금지 (S-M2)
    extracted_by: str                    # "llm-v1" | "rule-v1" | "hybrid-v1"
    fallback_used: bool

def extract_tags(text: str | None, chips: list[str]) -> OnboardingResult:
    """M1. 자연어+칩 → 태그/벡터/가중치.
    계약: (1) 외부 API 장애 시에도 반드시 결과를 반환하고 fallback_used=True로 표시할 것
         (2) tag_vector의 차원 순서는 tag_axis_registry(vector_version)를 따르고,
             길이 36 / 원소 ∈ {0.0, 1.0}을 만족할 것 (backend가 반환값을 검증해 위반 시 거절)
         (3) scoring_weights는 5키 전부 존재 + 합 1.0±0.01
         (4) 입력 원문을 외부로 전송하는 경우 legal 검토 대상 — 전송 여부를 문서화할 것
         (5) 입력 원문(text)은 호출자가 응답 직후 메모리에서 폐기한다. AI 구현체도
             원문을 자체 로그·캐시에 남기지 않는다 (S-H1)"""
    ...

class RouteScore(TypedDict):
    route_id: int
    score: float                         # 5축 가중합 (로드밸런싱 페널티 미포함)
    spot_fit: float                       # 0~1. backend 선택 레이어가 그대로 재사용한다
    matched_tags: list[str]              # registry value 영문 코드
    unmatched_tags: list[str]
    matched_spots: list[dict]            # [{place_id:int, name:str, category:str,
                                         #   matched_tags:list[str]}]
    score_breakdown: dict[str, float]    # 5축별 점수 + total
    reasons: list[str]

def score_routes(profile: OnboardingResult,          # tag_vector·scoring_weights·tags 전체
                 candidates: list[dict],             # backend 공간쿼리 결과 (필수 키는 7.1.1)
                 congestion: dict[int, float],       # route_id(int) -> 0~100
                 ) -> list[RouteScore]:
    """M3. 하드필터 + 순수 스코어링.
    계약: (1) candidates 밖의 route_id 반환 금지
         (2) 하드필터(accessibility, registry index 29~32)는 이 함수 내부에서만 수행한다.
             backend는 공간·인기도 필터만 담당한다 — 필터 책임 경계를 겹치지 않는다
         (3) ★ 로드밸런싱 페널티를 적용하지 않는다. 이 함수는 LB를 모른다 (08 §3.2)
         (4) S_fit의 사용자 벡터 u와 코스 벡터 v는 tag_vector index 14~28 슬라이스를 쓴다"""
    ...
```

#### 7.1.1 `candidates` dict 필수 키 (backend가 채워 AI에 전달)

| 키 | 타입 | 용도 |
|---|---|---|
| `route_id` | int | 식별자 |
| `has_parking` / `pet_friendly` / `stroller_ok` / `wheelchair_ok` | bool | 하드필터 (registry index 29~32 대응) |
| `total_distance_m` / `baseline_distance_m` | int | `S_dist`의 `detour_ratio` |
| `local_spot_count` | int | `S_local` |
| `review_count` / `companion_matched_count` | int | `S_trust` |
| `course_tag_vector` | float[] | `S_fit` 코사인 — **tag_vector와 동일 36차원, 동일 registry 순서** |
| `popularity_percentile` | float | 후보 풀 판정 (backend가 이미 필터링하지만 AI 설명용) |

#### 7.1.2 M3 파이프라인 단일화 (08 §3.2 — 페널티 이중 적용·순환 제거)

```
[1] backend : 후보 생성(공간쿼리) + 혼잡도 주입 + candidates dict 구성
      ↓ (단방향)
[2] AI      : 하드필터(accessibility) → score_routes() → list[RouteScore]
              ★ 이 레이어에는 로드밸런싱 페널티가 없다 (순수 스코어링)
      ↓ (단방향)
[3] backend : select_route_with_balancing(scored, user_ctx) — LB 적용 지점 (유일)
              ★ score_routes()를 재호출하지 않는다. [2]의 spot_fit을 그대로 재사용
      ↓
[4] backend : build_verdict() 템플릿 조립 (§7.7)
```

- **AI의 `score_adjusted = Score(c) × (1 − overload_ratio × PENALTY_COEFF)`는 폐기됐다.** 스코어링 레이어와 선택 레이어에서 페널티가 **이중 적용**되기 때문이다.
- **backend의 `profile_fit(r, ...)` 재호출도 폐기됐다.** QA가 지적한 순환의 원인이다. `select_route_with_balancing`의 입력은 `list[RouteScore]`이며 fit은 `RouteScore.spot_fit`을 그대로 쓴다.
- **페널티는 선택 레이어에서 단 한 번만 적용한다.** 이것이 M6 설계의 핵심 불변식이다.

### 7.2 배치 잡 목록

| Job | 대상 | 주기(설계 제안) | 멱등성 키 | 실패 시 |
|---|---|---|---|---|
| `job_congestion` | D1 (→ 실패 시 D2/D3) | **1시간** (D1이 실시간 API인 경우). 아니면 7.5절 강등 | `(place_id, observed_at, horizon, tier)` | 3회 재시도 → Tier 강등 |
| `job_places` | D5, D11 | 주 1회 (일요일 03:00) | `(source, source_id)` UPSERT | 이전 데이터 유지 (staleness 표기) |
| `job_courses` | D4 (두루누비) | 주 1회 (일요일 04:00) | `(source, source_id)` | 이전 데이터 유지 |
| `job_merchants` | D7, D8 | 월 1회 (1일 03:00) | `(source, source_id)` | 이전 데이터 유지 |
| `job_festivals` | D9 | 일 1회 (05:00) | `source_id` | 이전 데이터 유지 |
| `job_geocode` | 좌표 없는 축제/장소 | 일 1회 (05:30) | `place_id` | 좌표 NULL 유지 (지도 미표시) |
| `job_lb_capacity` | routes.daily_capacity 재계산 | 일 1회 (02:00) | `route_id` | 기본값 유지 |
| `job_cache_warm` | 전광판 TOP10 Redis 예열 | 10분 | — | 캐시 미스 허용 |

> 주기는 **전부 설계 제안**이다. D1~D9의 실제 갱신 주기·쿼터가 확인되면 재조정한다 (12절 Q-D1~Q-D9).

### 7.3 수집 잡 공통 구조 (의사코드)

```python
def run_ingest_job(job: JobSpec):
    log = start_ingest_log(job.name, job.dataset_code)
    try:
        # 1) 쿼터 가드: 남은 일일 호출량을 Redis에서 확인 (실제 쿼터 = 확인 필요)
        if not quota_guard.try_acquire(job.dataset_code, cost=job.est_calls):
            log.finish("skipped", "daily quota exhausted"); return

        # 2) 호출 (지수 백오프 재시도)
        raw_pages = []
        for page in job.pages():
            raw = http_get_with_retry(
                url=job.url, params=page.params,
                headers={"Authorization": f"Bearer {settings.public_api_key}"},  # ENV
                retries=3, backoff=[2, 8, 30], timeout=10,
            )
            raw_pages.append(raw)

        # 3) 원문 보관 (P2). 파싱 실패해도 원문은 남는다
        payload_ref = archive_raw(job.name, raw_pages)

        # 4) 정규화 → 스테이징 테이블 → 검증 → 본 테이블 UPSERT (트랜잭션)
        rows = job.normalize(raw_pages)
        assert_sanity(rows, job)          # 행수 급감(>50%)·좌표 범위 이탈 시 예외
        with db.transaction():
            upsert(job.target_table, rows, conflict_key=job.idempotency_key)

        # 5) 캐시 무효화 + 성공 기록
        cache.invalidate(job.cache_tags)
        log.finish("success", record_count=len(rows), payload_ref=payload_ref)

    except QuotaExceeded:
        log.finish("skipped", "quota");            alert("quota", job)
    except SchemaMismatch as e:
        # 필드 스펙 미확인(R1)에서 가장 흔할 실패. 기존 데이터 절대 삭제하지 않음
        log.finish("failed", f"schema: {mask_secrets(e)}");  alert("schema_change", job)
    except Exception as e:
        # ★ str(e)를 그대로 넘기지 않는다 — 보안 S-H6. 아래 7.3.1 참조
        log.finish("failed", mask_secrets(e));     alert("ingest_failed", job)
        if job.dataset_code == "D1":
            congestion_tier.demote()               # ★ 7.5절 Plan B 발동
```

#### 7.3.1 시크릿 마스킹 강제 규칙 (보안 S-H6 — 필수)

**초판의 결함**: `log.finish("failed", str(e))`가 예외 문자열을 통째로 `raw_ingest_log.error_message`에 저장했다. `requests`/`httpx`/`aiohttp` 계열의 예외 문자열에는 **요청 URL이 그대로 포함되는 것이 일반적**이고(ConnectionError·HTTPStatusError·Timeout), 공공데이터포털 관례상 API 키는 `?serviceKey=` **쿼리 파라미터**다(§12.5에서 backend 스스로 그렇게 예측했다).

```
결과:  배치 타임아웃 1회 →
       raw_ingest_log.error_message = "...GET https://apis.data.go.kr/...?serviceKey=<평문 키>..."
       → 운영 DB에 API 키가 평문 영구 저장 → DB 백업·운영자 조회·로그 수출로 계속 확산
```

침해가 필요 없는 **정상 운영만으로 발생하는 유출**이며, 키 유출은 되돌릴 수 없다(로테이션이 유일한 대응). §10.4가 "URL 쿼리스트링 로깅 금지"를 **선언**했으나 강제 지점이 없어 의사코드가 그 선언을 스스로 위반하고 있었다.

| # | 강제 지점 (코드 위치) | 규칙 |
|---|---|---|
| K1 | `infra/http_client.py` | **모든 외부 HTTP 호출은 이 클라이언트를 경유한다.** 예외를 잡아 URL·메시지에서 `serviceKey`·`apiKey`·`api_key`·`authKey`·`access_token`·`Authorization`·`password` 값을 `***`로 치환한 뒤 **재raise**. 직접 `requests`/`httpx` 호출 금지 |
| K2 | `log.finish()` 내부 | 저장 **직전에 동일 마스킹을 한 번 더** 적용(이중 방어). 새 코드 경로가 생겨도 DB로 새지 않는다 |
| K3 | `archive_raw()` | **응답 본문만** 저장한다. 요청 URL을 함께 남겨야 하면 키 파라미터 제거 후 저장 |
| K4 | `alert()` | Slack/메일 전송 페이로드에도 K1 마스킹을 적용. 외부 채널이 두 번째 확산 경로다 |
| K5 | `middleware/request_log.py` | 응답 에러 로깅 시 동일 마스킹. 스택트레이스 외부 노출 금지(§10.5)와 함께 적용 |
| K6 | 배치 설계 | 포털이 지원하면 **키를 쿼리스트링이 아닌 헤더로** 전송한다. Q-D9 확인 시 이 항목을 함께 확인 대상에 넣는다 |

```python
# infra/secret_mask.py — K1~K5가 공유하는 단일 구현
SECRET_PARAM_KEYS = ("serviceKey", "apiKey", "api_key", "authKey",
                     "access_token", "Authorization", "password", "token")

def mask_secrets(obj) -> str:
    """URL 쿼리 파라미터·헤더·JSON 키에서 시크릿 값을 ***로 치환한 문자열을 돌려준다.
       예외 객체를 받으면 str(obj)에 적용한다. 반환값만 로깅·저장·알림에 사용한다."""
```

> **회귀 테스트 필수**: 배치 타임아웃을 인위적으로 유발한 뒤 `raw_ingest_log.error_message`에 키 문자열이 남지 않는지 확인한다 (QA 회귀 항목).

**핵심 안전장치 4가지**
1. **원본을 지우지 않는다** — 수집 실패 시 기존 데이터를 유지하고 `staleness`만 올린다. 화면이 빈 상태가 되는 일이 없다.
2. **sanity check** — 행 수가 직전 대비 50% 이상 급감하거나 좌표가 대한민국 bbox를 벗어나면 커밋을 거부한다. 잘못된 데이터로 덮어쓰는 것이 없는 것보다 나쁘다.
3. **쿼터 가드** — Redis 카운터로 일일 호출량을 선차감한다. 쿼터 소진 시 잡을 건너뛰고 캐시로 버틴다.
4. **스키마 변경 감지** — 필드 스펙이 미확인이므로 정규화 단계에서 필수 필드 결측 시 `SchemaMismatch`로 즉시 중단하고 알림을 보낸다.

### 7.4 시연 안전장치 (심사 대비)

공모전 시연 중 공공 API 장애가 나도 화면이 비지 않도록:
- `SEED_SNAPSHOT_ENABLED=true` 환경변수 시, 최신 정상 수집분을 스냅샷 파일로 고정해 DB에 상시 보유.
- 모든 조회 API는 DB만 읽으므로, **외부 API가 전부 죽어도 화면은 정상 동작**한다 (단 `data_freshness.notice`에 신선도 안내가 붙는다).
- 이는 데이터 위조가 아니라 "마지막 정상 수집분 사용"이며, 화면에 출처·시각이 항상 표기된다.

### 7.5 ★ R1 Plan B — 집중률 예측 데이터 실패 시 3-Tier 강등

> PRD R1: "예측 데이터가 실시간 API로 제공되는지, 통계 리포트/다운로드 형태인지 **확인 필요**." M2·M3가 여기 걸린 SPOF.
> **설계 원칙: D1이 어떤 형태든(실시간 API / 파일 다운로드 / 아예 없음) 서비스가 성립해야 한다.**

#### Tier 정의

| Tier | 발동 조건 | 데이터 원천 | congestion_index 산출 | 화면 표기 |
|---|---|---|---|---|
| **A** | D1이 **실시간 REST API**로 확인됨 | D1 | 원천 값을 0~100으로 정규화 | "실시간 예측" (표기 없음) |
| **B** | D1이 **파일/리포트 형태**이거나, 실시간 API가 24시간 이상 응답 없음 | D1 정적 스냅샷(수동/주기적 ETL) + D2 + D3 | 아래 B식 | "최근 통계 기반 추정치" |
| **C** | D1 자체를 확보 불가 | D2/D3 + **자체 관측 신호** | 아래 C식 | "서비스 내 관측 기반 추정치" |

#### Tier B 산출식 (외부 통계 + 시간 프로파일)

```
base(place)       = normalize(D2 지역 방문자수 또는 D3 수요강도)      # 0~100
dow_factor(t)     = 요일 계수     (D2 과거치에서 요일별 평균비로 산출)
hour_factor(t)    = 시간대 계수   (D1 스냅샷 또는 D2 시간해상도가 있으면 산출,
                                   없으면 관광지 카테고리 기본 프로파일 사용)
season_factor(t)  = 성수기 계수   (D2 월별 평균비)
event_boost(t)    = 1 + 0.25 × (반경 3km 내 진행 중 축제 수, 상한 2건)   # D9

congestion_index_B = clip( base × dow_factor × hour_factor × season_factor × event_boost, 0, 100 )
confidence_B       = 0.6   (기본)
```
> `hour_factor`의 카테고리 기본 프로파일은 **가정값**이며, D1/D2 실데이터 확보 시 대체한다 (Q-D1).

#### Tier C 산출식 (외부 통계 최소 + 자체 관측)

D1을 아예 못 쓰는 최악의 경우. **서비스 자체 트래픽을 관측 신호로 쓴다** — 이는 M6 로드밸런싱 카운터와 동일한 데이터를 재활용하므로 추가 수집 비용이 0이다.

> ★ **이 신호는 조작 가능하다.** 아래 입력은 전부 §8.2의 Redis 카운터이며, **§8.2.1 dedupe·비인증 미계상·이상 급증 감지를 통과한 값만** Tier C 산출에 들어간다. 그 전제가 없으면 반복 호출만으로 특정 관광지를 "혼잡"으로 만들 수 있다 (보안 S-H7).

```
demand_signal(place) = 0.5 × norm(최근 3h 상세조회 수)      # ← dedupe 후 값. 비인증 조회는 0
                     + 0.3 × norm(최근 3h 경로안내 발급 수)
                     + 0.2 × norm(최근 7d 저장 수)          # Redis 카운터 (8절)

static_prior(place)  = norm(D2/D3가 있으면 그 값, 없으면 places.popularity_score × 100)

congestion_index_C = clip( 0.55 × static_prior + 0.45 × demand_signal × time_profile(t), 0, 100 )
confidence_C       = 0.35
is_estimated       = TRUE   (필수)
```

#### 강등/승격 상태 머신

```python
class CongestionTierController:
    """Redis key: congestion:tier  (값 'A'|'B'|'C'), congestion:tier:fail_count"""

    DEMOTE_AFTER_FAILS   = 3       # 연속 실패 3회 → 한 단계 강등
    PROMOTE_AFTER_OK     = 2       # 연속 성공 2회 → 한 단계 승격
    HARD_STALE_HOURS     = 24      # A 데이터가 24h 넘게 낡으면 강제 B

    def on_ingest_failure(self):
        n = redis.incr("congestion:tier:fail_count")
        if n >= self.DEMOTE_AFTER_FAILS:
            cur = self.current()
            nxt = {"A": "B", "B": "C", "C": "C"}[cur]
            if nxt != cur:
                redis.set("congestion:tier", nxt)
                alert(f"congestion tier demoted {cur} -> {nxt}")
            redis.set("congestion:tier:fail_count", 0)

    def on_ingest_success(self):
        n = redis.incr("congestion:tier:ok_count")
        redis.delete("congestion:tier:fail_count")
        if n >= self.PROMOTE_AFTER_OK and self.current() != "A":
            redis.set("congestion:tier", "A")     # 원천이 살아나면 즉시 복귀
            redis.set("congestion:tier:ok_count", 0)

    def compute(self, place, t):
        tier = self.current()
        if tier == "A" and self.age_hours(place) > self.HARD_STALE_HOURS:
            tier = "B"
        return {"A": tier_a, "B": tier_b, "C": tier_c}[tier](place, t), tier

    # ※ 저장된 스냅샷을 읽을 때는 반드시 §5.3.1 T1의 tie-break를 적용한다:
    #   ORDER BY observed_at DESC, tier ASC  — 강등 전후 행이 공존할 수 있기 때문이다.
    #   응답 조립 시 item별 tier를 담고(T2), 응답 블록 tier는 혼재 시 "mixed"로 집계한다(T3).
```

#### Plan B가 주는 효과

- **M2(전광판)**: Tier가 무엇이든 TOP10 순위와 🔴🟡🟢 배지는 항상 만들어진다. 화면 구조가 바뀌지 않는다.
- **M3(1:1 비교)**: 비교의 본질은 **핫플과 숨은길의 상대적 차이**다. Tier B/C도 동일 산출식을 양쪽에 적용하므로 **상대 비교의 타당성은 유지**된다 (절대값의 신뢰도만 낮아진다).
- **심사 대응**: "예측 데이터가 없으면 어떻게 되나?"라는 질문에 3단계 강등 구조와 화면 표기 정책으로 답할 수 있다. 오히려 데이터 신뢰도를 정직하게 표기하는 것이 가점 요인이 될 수 있다.

### 7.6 D4(두루누비 좌표열) 미제공 시 대안

초안의 핵심 가치가 "끊기지 않는 선(Line)"이므로 별도 대안을 둔다.

| 상황 | 대응 | `routes.path_source` |
|---|---|---|
| 코스 좌표열 제공됨 | 그대로 LineString 저장 | `public` |
| 지점 목록만 제공됨 | 지도 SDK의 경로탐색 API로 스냅 (쿼터 확인 필요) | `snapped` |
| 둘 다 불가 | 지점 간 직선 연결 + **화면에 점선(dashed)으로 표시** | `straight` |

> `straight`인 경로를 실선으로 그리면 "실제 도로"로 오인된다. **designer에게 점선 스타일 필요를 전달한다.**
> 단 **점선은 `path_source` 전용 신호로 예약**한다. 숨은길/핫플 구분에 점선을 쓰면 숨은길이 항상 저품질 경로로 오인된다 — 코스 종류 구분은 색상 + 핀 형태로만 한다 (QA m4, designer 소관).

---

## 7.7 `build_verdict()` — 비교 헤드라인 템플릿 조립 (**backend 소관**)

> **소관 이관**: 초판은 이 함수를 AI 계약(§7.1)에 두고 `-> str` 자유 문자열을 반환하는 LLM 호출로 설계했다. **08 §5(D5)가 LLM 호출을 폐기하고 소관을 backend로 이관**했으므로, 이 절이 그 설계다.

### 7.7.1 LLM을 쓰지 않는 이유

| # | 근거 |
|---|---|
| 1 | **보안 S-H5 (High)** — 자유 문자열을 반환하는 2차 LLM 호출에는 AI §1.5의 방어 6계층이 **하나도 적용되지 않는다**(스키마 강제 불가·프롬프트 미설계·재검증 대상 없음). 입력에 공공데이터 유래 코스명·상호명이 들어가므로 **간접 프롬프트 인젝션 문자열이 화면 최상단 headline에 그대로 렌더**된다. 공격자는 LLM에 직접 입력할 필요 없이 상권정보 '상호' 필드에 지시문을 넣기만 하면 된다 |
| 2 | **필요가 없다** — `deltas`는 backend가 이미 계산한 수치다. 함수 시그니처가 스스로 LLM 불필요를 말하고 있다 |
| 3 | **QA J2** — 요청당 LLM 호출은 비용 추정에 없고, "경로 랭킹은 LLM 생성이 아니다"라는 차별화 서사를 스스로 깨며, 시연 중 LLM 장애 시 핵심 화면이 빈다(AI 폴백은 온보딩 전용) |

### 7.7.2 시그니처 (반환 타입 주의)

```python
# src/verdict.py  — backend 구현. ai_contract.py에 두지 않는다
class Verdict(TypedDict):
    congestion_delta: float       # 절대 포인트 (hidden − hotspot)
    congestion_delta_pct: int     # 상대 % (음수 = 낮음)
    duration_delta_min: int
    fit_delta: float
    headline: str

def build_verdict(hotspot: RouteScore, hidden: RouteScore, deltas: dict) -> Verdict:
    """M3 헤드라인. LLM을 호출하지 않는다.
       ★ 반환 타입이 str이 아니라 Verdict임에 주의 (초판에서 변경)."""
```

### 7.7.3 ★ 안전 규칙 (필수 — 임의로 되돌리지 말 것)

> **headline에는 수치·enum·개수만 삽입한다. 코스명·상호명·스팟명 등 외부 데이터 유래 문자열을 절대 삽입하지 않는다.**

이 한 줄로 간접 인젝션 표면이 **구조적으로 0**이 된다. "코스명을 넣어 문장을 자연스럽게 만드는 안"은 08 §5.4에서 명시적으로 폐기됐다 — 코스명은 공공데이터 유래 문자열이므로 인젝션·XSS 표면이 그대로 부활한다.

부수 규칙 3가지
1. 출력 길이 **상한 120자**. 초과 시 기본 템플릿으로 폴백.
2. 렌더는 **텍스트 노드로만** 한다. `dangerouslySetInnerHTML` 금지 (보안 S-M7, designer 전달).
3. 삽입 변수는 서버가 계산한 **int/float만** 허용한다. 문자열 변수를 템플릿에 추가하려면 security-engineer 재검토를 거친다.

### 7.7.4 템플릿 4종 (08 §5.3 정본)

| 조건 | 템플릿 |
|---|---|
| 기본 (혼잡도 우위 + 시간 열위) | `"{duration_delta_min}분 더 걸리지만 혼잡도는 {abs(congestion_delta):.0f}p 낮고, 맞춤 조건 {matched_count}개를 만족합니다."` |
| 혼잡도·시간 모두 우위 | `"혼잡도가 {abs(congestion_delta):.0f}p 낮고 이동 시간도 {abs(duration_delta_min)}분 짧습니다. 맞춤 조건 {matched_count}개를 만족합니다."` |
| 혼잡도 열위 또는 동등 | `"혼잡도 차이는 크지 않지만, 맞춤 조건 {matched_count}개를 만족하고 로컬 상점 {local_count}곳을 지납니다."` |
| `tier == "none"` (혼잡도 데이터 없음) | `"혼잡도 데이터가 없어 비교에서 제외했습니다. 맞춤 조건 {matched_count}개를 만족합니다."` |

- `matched_count = len(hidden.matched_tags)`
- `local_count = len(hidden.local_merchants)`
- 모두 backend가 보유한 수치다. 외부 호출이 발생하지 않으므로 **LLM 장애와 무관하게 항상 렌더된다.**

### 7.7.5 배치 문자열 위생 검사 (S-H5 잔여 방어)

headline에 외부 문자열을 넣지 않더라도, 코스명·상호명은 `*.name`·`matched_spots[].name`으로 **응답에 여전히 실린다.** 따라서 §7.3 `assert_sanity`에 문자열 위생 검사를 추가한다.

| 검사 | 내용 |
|---|---|
| 제어문자 제거 | `\x00-\x1f` 제거 후 적재 |
| 길이 상한 | `name` 120자, `address` 200자 초과 시 절단 |
| 지시문 패턴 플래그 | `ignore previous`, `system:`, `<script`, 백틱 연속 등 탐지 시 **차단이 아니라 로그 플래그**(공공데이터 정상 상호를 오탐 배제하지 않기 위함) |

---

## 8. 동적 로드밸런싱 설계 (M6 / R7)

### 8.1 문제 정의

숨은길을 추천할수록 그 숨은길이 붐빈다 (풍선효과). 초안 4절은 "임계치 초과 시 B/C/D로 분산"이라고만 했고 **지표·수치·대안 부족 시 동작**이 없다 (R7).

### 8.2 측정 지표와 임계치

**측정 지표**: `guidance_issued` — **경로 안내가 실제로 발급된 건수** (조회수가 아니다).
- 조회수는 탐색 행위여서 실제 방문과 상관이 약하다.
- `POST /routes/compare` 응답에서 hidden 코스가 제시된 시점, 그리고 `POST /me/routes`(저장) 시점을 가중 카운트한다.

```
load_ratio(route, t) = weighted_count(route, window=6h) / effective_capacity(route)

weighted_count = 1.0 × 안내발급수 + 2.0 × 저장수 + 0.3 × 상세조회수
                 (저장은 방문 의사가 더 강해 가중치 높임 — 계수는 가정값, 운영 데이터로 보정)

effective_capacity(route) = routes.daily_capacity × (6/24) × dow_factor
    routes.daily_capacity 우선순위:
      1) 원천 데이터에 수용력 정보가 있으면 사용        (확인 필요)
      2) 없으면 route_segments의 places.parking_capacity 합 × 3
      3) 그것도 없으면 카테고리 기본값
         (trail=300/일, craft=80/일, cafe=150/일 — ★ 전부 가정값, 근거 확보 필요)
```

**임계치 3단계**

| 상태 | load_ratio | 동작 |
|---|---|---|
| GREEN | < 0.6 | A 코스 그대로 안내 |
| AMBER | 0.6 ~ 0.85 | **확률적 분산**: A 60% / B·C·D 40%. (= 완전 차단이 아닌 소프트 분산 구간) |
| RED | > 0.85 | A 제외, B·C·D만 안내. **단 대안 풀이 비면 배제하지 않는다** — 8.4절 F3 정직 안내와 함께 원래 코스를 유지한다 |

> 0.6 / 0.85는 **가정값**이다. 실측 데이터가 없으므로 운영 초기 A/B 관측으로 보정해야 한다. 심사에서 "왜 0.6인가"를 물으면 "실측 전 초기값이며 보정 루프가 설계에 포함되어 있다"고 답하는 것이 정직하다.

> **"완전 배제"와 "완전 차단 금지"의 충돌 해소 원칙 (08 §3.4)**: 배제는 **대안이 실재할 때만** 성립한다. 대안 풀이 비면 배제하지 않고 정직하게 혼잡을 고지한다. 이로써 RED 배제 규칙과 "사용자를 완전 차단하지 않는다"는 원칙이 동시에 성립한다.

**2순위 임계 — capacity 미확보 코스용 상대 share (08 §3.4)**

`effective_capacity`를 산출할 수 없는 코스(`daily_capacity` NULL + `parking_capacity` 합산 불가)에는 절대 임계를 적용하지 않는다. **capacity 기본값이 전부 가정값이므로, 근거 없는 절대 수치로 판정하는 것보다 클러스터 내 상대 지표가 정직하다.**

```
share(route) = weighted_count(route, 6h) / Σ weighted_count(같은 lb_group_key 전체, 6h)

  share > 0.4  → AMBER 상당
  share > 0.6  → RED 상당
  (그룹 내 코스가 1개뿐이면 판정하지 않고 GREEN으로 둔다 — 분모가 자기 자신이라 무의미)
```

| 분기 | 조건 | 사용 지표 |
|---|---|---|
| 1순위 (절대) | `effective_capacity` 산출 가능 | `load_ratio` |
| 2순위 (상대) | capacity 미확보 | `share` |

0.4 / 0.6도 **가정값**이다.

### 8.2.1 ★ 카운터는 조작 가능한 신호다 — dedupe·이상탐지 전제 (보안 S-H7, 필수)

> **명문화**: **이 절의 `weighted_count`는 조작 가능한 신호이며, 아래 dedupe·미계상·이상탐지가 적용된다는 전제 하에서만 유효하다.** 전제가 빠지면 M2 전광판과 M6 로드밸런싱이 동시에 조작된다.

**왜 위험한가**: 카운터를 올리는 행위 중 상당수가 인증을 요구하지 않는다. `GET /places/{place_id}`(C2)는 **공개**, `POST /routes/compare`(D1)는 **선택**이고 레이트리밋은 IP 기준뿐이다. 그런데 이 카운터는 (a) Tier C 혼잡도(`demand_signal`)와 (b) `load_ratio`를 **동시에** 만든다.

| 시나리오 | 결과 |
|---|---|
| A. 혼잡도 부풀리기 | 특정 관광지 상세조회 반복 → 전광판에서 적색 표시 → 해당 상권에 실질적 불이익 |
| B. 로드밸런싱 조작 | 특정 코스 `load_ratio`를 0.85 초과로 밀어 **추천에서 제외**시키거나, 경쟁 코스를 눌러 자기 코스로 트래픽 유도 |
| C. 자기증폭 루프 | Tier C에서 `demand_signal`이 혼잡도를 만들고 그 혼잡도가 다시 LB 판단에 쓰여 조작 효과가 두 시스템에 전파 |

**방어 4종**

| # | 규칙 | 구현 |
|---|---|---|
| D1 | **주체 단위 dedupe** — 동일 주체·동일 route는 **시간당 1회만** 계상 | `SETNX lb:dedupe:{route_id}:{subject_hash}:{yyyymmddHH}` (TTL 2h). 실패(=이미 존재)면 카운터 증가를 건너뛴다. `subject_hash = HMAC(server_key, user_id 또는 guest_id)` — **원본 식별자를 Redis 키에 넣지 않는다** |
| D2 | **비인증 `viewed` 미계상** | `guest_id` 쿠키가 없는 요청의 상세조회는 **가중치 0**. 계상 대상은 `issued`(1.0)·`saved`(2.0)와 게스트/회원으로 식별된 `viewed`(0.3)뿐이다 |
| D3 | **이상 급증 감지** | `lb:cnt:*` 시간버킷 증가율이 **직전 6버킷 평균의 5배**를 넘으면 알람 + **해당 버킷을 Tier C 산출에서 제외**. 5배는 가정값 |
| D4 | **신뢰도 서열 인지** | `saved`(2.0)는 **인증 필수 엔드포인트(E2)** 라 신뢰도가 가장 높다. `viewed`(0.3)가 가장 조작이 쉬우므로 dedupe 통과분만 계상한다 |

```python
def record_guidance(route_id: int, kind: str, subject_id: str | None):
    """kind: 'issued' | 'saved' | 'viewed'
       subject_id: user_id 또는 guest_id. None이면 비인증 요청"""
    if kind == "viewed" and subject_id is None:
        return                                   # D2. 비인증 조회는 계상하지 않는다
    subject_hash = hmac_sha256(settings.counter_hmac_key, subject_id)[:16]
    bucket = now().strftime("%Y%m%d%H")
    if not redis.set(f"lb:dedupe:{route_id}:{subject_hash}:{bucket}",
                     1, nx=True, ex=7200):
        return                                   # D1. 같은 주체·같은 시간버킷은 1회만
    w = {"issued": 1.0, "saved": 2.0, "viewed": 0.3}[kind]
    pipe = redis.pipeline()
    pipe.incrbyfloat(f"lb:cnt:{route_id}:{bucket}", w)
    pipe.expire(f"lb:cnt:{route_id}:{bucket}", 7 * 3600)
    pipe.execute()
```

> **심사 대응**: "이 지표를 어떻게 신뢰하나"는 질문이 나올 가능성이 높은 지점이다. Tier C 화면 표기("서비스 내 관측 기반 추정치")와 **함께 이 방어 4종을 설명**할 수 있어야 한다.

### 8.3 구현 의사코드

```python
# 카운터 저장 위치: Redis (원자적 증가 + 자동 만료 + 분산 안전)
# 키:  lb:cnt:{route_id}:{yyyymmddHH}   (시간 버킷, TTL 7h)
# 슬라이딩 윈도 = 최근 6개 시간 버킷 합산
# ※ record_guidance()는 8.2.1로 이동했다 (dedupe·비인증 미계상 포함)

def load_ratio(route_id: int) -> float | None:
    """capacity를 산출할 수 없으면 None을 반환한다 → 호출자가 share 분기로 넘어간다"""
    buckets = [ (now() - timedelta(hours=i)).strftime("%Y%m%d%H") for i in range(6) ]
    keys = [f"lb:cnt:{route_id}:{b}" for b in buckets]
    total = sum(float(v or 0) for v in redis.mget(keys))
    total = exclude_anomalous_buckets(route_id, total)   # 8.2.1 D3
    cap = effective_capacity(route_id)                   # DB 캐시, 일 1회 재계산
    return None if cap is None else total / max(cap, 1.0)


def lb_state(route_id: int, group_total: float) -> str:
    """GREEN | AMBER | RED. 절대(1순위) → 상대 share(2순위) 순으로 판정한다 (8.2)"""
    ratio = load_ratio(route_id)
    if ratio is not None:
        return "RED" if ratio > 0.85 else "AMBER" if ratio >= 0.6 else "GREEN"
    share = weighted_count_6h(route_id) / max(group_total, 1.0)
    return "RED" if share > 0.6 else "AMBER" if share > 0.4 else "GREEN"


def select_route_with_balancing(scored: list[RouteScore], user_ctx) -> BalancedChoice:
    """A/B/C/D 분산 선택. ★ LB 페널티가 적용되는 유일한 레이어 (7.1.2 파이프라인 [3]).

       ★ 입력이 primary_route_id가 아니라 AI가 반환한 list[RouteScore]다.
         score_routes()를 재호출하지 않으며, profile_fit()도 재계산하지 않는다.
         fit은 RouteScore.spot_fit을 그대로 재사용한다 — 초판의 재호출은
         순환이자 중복 연산이었다 (QA C3 / 08 §3.2, §3.7)."""
    primary_route_id = user_ctx.primary_route_id
    group_total = sum(weighted_count_6h(s["route_id"]) for s in scored)

    # 1) 각 후보의 상태 평가 + 사용자 프로필 적합도 필터
    evaluated = []
    for s in scored:
        fit = s["spot_fit"]                    # ★ 재계산 없음. AI 반환값 재사용
        if fit < 0.4:
            continue          # ★ 분산을 위해 취향에 안 맞는 코스를 밀어넣지 않는다
        state = lb_state(s["route_id"], group_total)
        evaluated.append((s, state, fit))

    if not evaluated:
        return fallback_no_alternative(primary_route_id, user_ctx)   # 8.4절

    primary = next((e for e in evaluated if e[0]["route_id"] == primary_route_id), None)

    # 2) 상태별 분기
    if primary and primary[1] == "GREEN":
        return BalancedChoice(primary[0], applied=False)

    if primary and primary[1] == "AMBER":
        if random.random() < 0.6:
            return BalancedChoice(primary[0], applied=False)
        pool = [e for e in evaluated if e[0]["route_id"] != primary_route_id]
        if not pool:
            return BalancedChoice(primary[0], applied=False)
        return BalancedChoice(weighted_pick(pool), applied=True,
                              reason="primary_amber_distributed")

    # RED (또는 primary가 후보에서 탈락)
    pool = [e for e in evaluated if e[1] != "RED"]
    if not pool:
        # ★ 대안 풀이 비면 배제하지 않는다 — 8.4절 F3 정직 안내와 함께 원래 코스 유지
        return fallback_all_congested(evaluated, user_ctx)      # 8.4절
    return BalancedChoice(weighted_pick(pool), applied=True,
                          reason="primary_over_threshold")


def weighted_pick(pool):
    """여유가 많고(1-ratio) 취향에 맞는(fit) 코스일수록 뽑힐 확률이 높다.
       결정론적 1등 고정이 아니라 확률 추출 — 그래야 2위 코스로 다시 쏠리지 않는다."""
    weights = [ max(0.05, 1 - load_pressure(s["route_id"])) * fit
                for (s, _, fit) in pool ]
    return random.choices([p[0] for p in pool], weights=weights, k=1)[0]
```

#### 8.3.1 read-then-decide 비원자성 — **허용 오차로 확정** (QA m1, 설계 결정 기록)

**현상**: `load_ratio()` 읽기 → 상태 분기 → 선택 사이에 락이 없고, `record_guidance()`는 선택 후 별도 호출이다. 따라서 동시 요청 N개가 **같은 ratio를 읽고 모두 GREEN 판정**을 받을 수 있다. 임계치 초과분이 순간적으로 흘러간다.

**판정: 허용 오차다. 새 설계를 도입하지 않는다.** 근거 4가지 (QA 재검증 일치)

| # | 근거 |
|---|---|
| 1 | **오차 상한이 분모 대비 무시 가능하다.** 오차는 "판정~카운트 반영 사이 동시 요청 수"인데, 윈도가 **6시간**이고 `effective_capacity`가 **일 단위**에서 파생된다. 초 단위 동시성 오차가 6시간 누적 분모에 주는 영향은 사실상 0이다 |
| 2 | **AMBER가 자연 완화 장치다.** AMBER 구간은 60% 확률 분산이므로, 경계 부근에서 동시 요청이 몰려도 확률적으로 분산이 시작된다 |
| 3 | **RED 판정은 카운터가 이미 반영된 뒤 걸린다.** 초과분이 흘러도 다음 요청부터 즉시 RED가 적용된다 — 오차가 누적되지 않고 자기 교정된다 |
| 4 | **공모전 시연 및 초기 트래픽 규모에서 사용자 체감 영향이 없다.** 정합성 대가로 요청 경로에 분산 락을 넣는 것이 손해다 |

**정밀 제어가 필요해질 경우의 경로 (각주)**: Redis Lua 스크립트로 `read + 상태판정 + incr`를 한 트랜잭션으로 원자화한다. 트래픽이 capacity에 실제로 근접하는 규모가 되면 그때 도입한다. **지금 도입하지 않는 것이 설계 결정이다.**

### 8.4 대안 부족 시 폴백 (R7 핵심 보강)

대안 경로가 4개씩 확보되지 않는 지역이 많다. **대안이 없을 때 규칙이 무너지지 않게** 3단계 폴백을 둔다.

```python
def fallback_all_congested(evaluated, user_ctx):
    """★ 여기서 원래 코스를 배제하지 않는다 — 대안이 실재할 때만 배제가 성립한다 (08 §3.4)"""
    head = evaluated[0][0]                      # RouteScore
    # F1. 시간대 분산 — 공간 대안이 없으면 시간 축으로 분산한다
    off_peak = find_offpeak_windows(head["route_id"], next_hours=12)
    if off_peak:
        return BalancedChoice(
            head, applied=True, reason="time_shift",
            notice=f"지금은 붐빕니다. {off_peak[0].label}에 방문하면 훨씬 여유롭습니다.",
            suggested_departure=off_peak[0].start)

    # F2. 반경 확대 — 인접 시군구까지 넓혀 후보 재탐색 (1회만)
    wider = search_alternatives_in_adjacent_regions(user_ctx, radius_km=30)
    if wider:
        return BalancedChoice(wider[0], applied=True, reason="region_expanded",
            notice="인근 지역의 한적한 코스를 함께 제안합니다.")

    # F3. 정직한 안내 — 억지로 다른 곳을 밀지 않고, 원래 코스도 배제하지 않는다
    return BalancedChoice(head, applied=False, reason="no_alternative",
        notice="현재 이 지역에는 여유로운 대안 코스가 없습니다. "
               "혼잡을 감안해 방문 시간을 조정해 보세요.")
```

> **설계 판단**: F3에서 "대안 없음"을 사용자에게 그대로 말한다. 취향에 안 맞는 코스를 억지로 분산 배정하면 서비스 신뢰가 무너지고, 결국 사용자가 다시 핫플로 돌아간다. `profile_fit < 0.4` 컷도 같은 이유다.

### 8.5 로드밸런싱 관측

```
lb:cnt:{route_id}:{hour}      # 가중 카운터 (TTL 7h)
lb:applied:{yyyymmdd}         # 분산 적용 횟수 (일별, 리포트용)
lb:fallback:{reason}:{yyyymmdd}  # 폴백 사유별 집계 → 대안 부족 지역 발굴
```
`lb:fallback:no_alternative` 집계는 **"대안 코스를 새로 발굴해야 하는 지역" 목록**이 되어 B2G 리포트(초안 6절)의 실제 근거가 된다.

---

## 9. Redis 캐싱 전략

### 9.1 키 설계

| 키 패턴 | 내용 | TTL | 갱신 주체 |
|---|---|---|---|
| `cong:board:{region}:{horizon}` | 전광판 TOP N 직렬화 결과 | 300s | `job_cache_warm` (10분) + 배치 후 무효화 |
| `cong:place:{place_id}:{horizon}` | 장소별 최신 혼잡도 | 300s | 조회 시 lazy fill |
| `cong:tier` | 현재 Tier ('A'/'B'/'C') | 없음 (영속) | TierController |
| `cong:tier:fail_count` / `ok_count` | 강등/승격 카운터 | 1h | TierController |
| `places:list:{hash(query)}` | 추천 목록 페이지 | 120s | lazy fill |
| `route:detail:{route_id}` | 경로 상세 + GeoJSON (무거움) | 3600s | 배치 후 무효화 |
| `route:cand:{region}:{vecver}` | 후보 경로 집합 (공간쿼리 결과) | 600s | lazy fill |
| `cmp:ctx:{profile_hash}:{hash(req)}` | compare **중간 산출물만** (§9.2.1 화이트리스트) | 300s | lazy fill |
| `lb:cnt:{route_id}:{hour}` | 로드밸런싱 카운터 | 7h | `record_guidance` |
| `ratelimit:{scope}:{id}:{win}` | 레이트리밋 카운터 | 60s | 미들웨어 |
| `session:guest:{guest_id}` | 게스트 온보딩 프로필 | **24h** | A2 |
| `refresh:{jti}` | refresh 토큰 화이트리스트 | 14d | 인증 |
| `quota:{dataset}:{yyyymmdd}` | 공공 API 일일 호출량 | 25h | 배치 |

### 9.2 캐싱 정책 3원칙

1. **혼잡도 TTL은 짧게(300s), 경로 상세는 길게(3600s).** 혼잡도는 변하고 경로 지오메트리는 안 변한다.
2. **캐시 미스 시 DB 폴백, DB 실패 시에도 stale 캐시를 그대로 내보낸다** (stale-while-error). 심사 시연 중 순간 장애로 화면이 비는 것을 막는다.
3. **compare 결과 캐시 키에 로드밸런싱 결과를 포함하지 않는다.** 캐시하면 모든 사용자가 같은 코스를 받아 분산이 무력화된다. → **`cmp:ctx:*`는 혼잡도·후보집합까지만 캐시하고, 최종 route 선택은 매 요청 수행한다.**
4. **개인화 산출물은 캐시하지 않으며, 캐시 키에 프로필 신원을 반드시 포함한다.** → §9.2.1.

### 9.2.1 ★ compare 캐시 규약 (보안 S-H3 — 개인화 결과 교차 서빙 차단)

**초판의 결함**: 키가 `cmp:{hash(req)}`였다. D1 request body는 `{origin, destination, profile:{use_saved:true}, transport_mode, departure_at}`인데, **`use_saved=true`이면 body에 사용자를 구분하는 정보가 하나도 없다.** 사용자 A와 B가 같은 목적지·교통수단·출발시각으로 요청하면 `hash(req)`가 **동일**해진다. 그런데 응답에는 개인화 산출물이 들어 있다.

```
결과: 인기 목적지에 표준 파라미터로 요청하면 직전에 같은 조합으로 요청한
      타인의 개인화 결과를 그대로 수신한다.
      → spot_fit.matched_tags / matched_spots / verdict.headline 에서
        타인이 반려동물을 동반하는지, 유모차·휠체어가 필요한지(= 육아·장애 정보)를 유추 가능.
      능동 공격 없이 정상 요청만으로 발생한다.
```

또한 초판은 §9.1(키 이름이 "compare 응답 캐시"로 읽힘)과 §9.2-③("혼잡도·후보집합까지만 캐시")이 **서로 모순**이었다. 구현자가 §9.1만 보고 구현하면 사고가 난다. 아래로 **한쪽으로 정리한다.**

**규약 1 — 키에 프로필 신원 포함 (필수)**

```
cmp:ctx:{profile_hash}:{hash(req)}

profile_hash = sha256(tag_vector || vector_version || canonical(scoring_weights))[:16]
```

- **`tag_vector` 기반 해시를 채택한 이유**: 취향이 완전히 동일한 사용자끼리는 산출물이 같으므로 공유가 무해하고, **캐시 적중률도 유지**된다. `subject_hash`(사용자별)로 키를 나누면 안전하지만 적중률이 사실상 0이 된다.
- 게스트/비로그인·프로필 미보유 요청은 `profile_hash = "anon"`을 쓰되, 이 경우 개인화 필드가 애초에 산출되지 않으므로 안전하다.

**규약 2 — 캐시 대상 화이트리스트 (이 목록 밖은 캐시 금지)**

| 캐시 **가능** | 캐시 **금지** |
|---|---|
| 후보 경로 집합 (공간쿼리 결과) | `spot_fit.*` (score/matched_tags/unmatched_tags/matched_spots) |
| 혼잡도 스냅샷 (`congestion.*`) | `score_breakdown`, `scoring_weights_used` |
| 경로 지오메트리 (`path_geojson`, `path_source`) | `verdict.*` (headline 포함) |
| `local_merchants` (경로 고정 데이터) | `load_balancing.*` (캐시하면 분산 무력화 — 원칙 ③) |
| `review_trust.*` (사용자 무관) | `comparison_id`, `generated_at` |

**규약 3 — 응답 헤더**: compare 응답에 `Cache-Control: private, no-store`를 설정한다. 중간 프록시·CDN이 개인화 응답을 공유 캐시에 담지 못하게 한다.

> **회귀 테스트 필수**: 서로 다른 프로필의 두 계정이 **동일 파라미터**로 compare를 호출했을 때 `spot_fit`·`verdict`가 각자의 프로필대로 다르게 나오는지 확인한다 (QA 회귀 항목).

```python
def get_congestion_board(region, horizon, limit):
    key = f"cong:board:{region}:{horizon}"
    if (hit := redis.get(key)):
        return json.loads(hit)
    try:
        data = query_board_from_db(region, horizon, limit)
        redis.setex(key, 300, json.dumps(data))
        return data
    except DatabaseError:
        if (stale := redis.get(key + ":stale")):     # 장기 보관 사본 (TTL 24h)
            return {**json.loads(stale), "degraded": True}
        raise
```

### 9.3 혼잡도 스냅샷 갱신 주기 정리

```
[배치 job_congestion]  1시간마다 (Tier A 기준)
        │ UPSERT
        ▼
[congestion_snapshots]  영구 보관 (시계열 분석·요일 계수 산출에 재사용)
        │
        ▼
[job_cache_warm]  10분마다 전광판 TOP10을 Redis에 선적재
        │
        ▼
[API 응답]  TTL 300s. 사용자 체감 지연 최대 5분
```
> D1의 실제 갱신 주기가 1시간보다 길면(예: 일 1회) 배치 주기를 낮추고 TTL은 유지한다. 잦은 호출은 쿼터만 소모한다.

---

## 10. 인증/인가 및 시크릿 관리

> PRD N7: **회원 인증의 상세 구현은 논스코프**. 아래는 설계 수준이며, 실제 구현 시 security-engineer 경유가 필수다.

### 10.1 가입/로그인 방식 (R5 반영 — 게스트 우선)

PRD R5는 "심사위원이 회원가입 없이 즉시 체험하지 못하면 완성도 평가에서 불리하다"고 지적했다. **backend는 게스트 우선 설계를 권고한다.**

```
[첫 방문]
   │
   ├─▶ [게스트 체험]  guest_id(UUIDv4) 발급 → HttpOnly·Secure·SameSite=Lax 쿠키
   │      온보딩 결과를 Redis session:guest:{id} 에 24h 보관 (DB 미기록)
   │      M1~M6 전 기능 사용 가능. 저장(E1~E4)만 제한
   │
   └─▶ [회원가입]  email + password (argon2id 해시)
          게스트였다면 Redis 프로필을 user_profiles로 승격 이관 (아래 10.1.1 규칙 준수)
```

**게스트 제한**: 코스 저장, 리뷰 작성만 막는다. **핵심 시연 경로(온보딩 → 전광판 → 추천 → AI 경로 비교)는 로그인 없이 전부 동작한다.**

> 이 설계는 개인정보 최소수집에도 유리하다 — 게스트는 이메일조차 수집하지 않는다.
> **정책 확정**: 게스트 경로 도입 여부(Q-I3)는 08 §6 E1에서 **"도입한다"**로 잠정 정본 확정됐다. 프로필은 **서버 Redis 24h + 회원가입 시 승격**(본 절 채택). designer 배너 문구는 "체험 모드 — 24시간 임시 보관되며, 가입하시면 그대로 이어집니다"로 통일한다 — 초판 designer 문구("결과가 저장되지 않습니다")는 사실과 달라 개인정보 고지 관점에서도 부정확했다 (QA J3).

### 10.1.1 ★ 게스트 승격 규칙 (보안 S-H4 / QA J4 — 필수)

**공격 시나리오 (초판 설계에서 성립했던 것)**

```
1. 공격자가 정상적으로 게스트 체험을 시작한다.
2. POST /api/v1/auth/signup 호출 시 X-Guest-Id: <피해자의 guest UUID> 를 지정한다.
3. 서버가 그 헤더 값으로 session:guest:{피해자}를 조회해
   공격자 계정의 user_profiles로 이관한다.
4. 공격자가 자기 계정에서 피해자의 온보딩 태그를 열람한다.
```

`guest_id`가 UUIDv4라 무작위 대입은 비현실적이므로 이 시나리오는 **guest_id 유출을 선행 조건**으로 한다. 문제는 **초판 설계가 그 선행 조건을 스스로 만들었다**는 점이다 — §6.0은 `X-Guest-Id` 헤더(= 프론트 JS가 값을 알아야 함)를, §10.2는 HttpOnly 쿠키(= JS가 읽을 수 없음)를 규정했다. **두 규정은 동시에 성립할 수 없고**, 구현자가 이를 해소하는 가장 쉬운 길은 HttpOnly를 포기하는 것이다. 그 순간 XSS·브라우저 확장·공유 기기·로그를 통해 guest_id가 실제로 유출 가능해진다.

| # | 규칙 |
|---|---|
| **G1** | **`X-Guest-Id` 헤더 수용을 삭제한다.** 게스트 식별은 HttpOnly 쿠키 단일 경로. 프론트는 `credentials: 'include'`만 하면 되므로 **기능 손실이 없다** |
| **G2** | 승격 시 서버는 **쿠키에서 읽은 guest_id만** 사용한다. body/header/query의 guest_id는 무조건 무시하고 `400` + 보안 로그 플래그 |
| **G3** | **원자적 1회성 소비**: 승격은 Redis **`GETDEL session:guest:{id}`**로 수행한다. 조회와 삭제를 분리하면 동시 요청 시 하나의 프로필이 두 계정으로 이관될 수 있고, 같은 guest_id로 여러 계정이 반복 승격 가능해진다 |
| **G4** | **승격 직후 guest_id 재발급**: 기존 쿠키를 즉시 만료시키고 새 값을 발급한다 (세션 고정 방어) |
| **G5** | 승격 대상 `user_id`가 **방금 생성된 계정**인지 검증한다. 기존 계정에 임의 프로필을 덮어쓰는 경로를 만들지 않는다 |
| **G6** | `guest_id`를 요청 로그·URL·에러 리포트에 **기록하지 않는다** |
| **G7** | (선택) 게스트 세션 생성 시 `hash(IP 대역 + UA)`를 함께 저장하고 승격 시 대조한다. **불일치는 차단이 아니라 로그 플래그로만** — 모바일 IP 변동 오탐을 피한다 |

```python
def promote_guest_profile(new_user_id: UUID, request) -> bool:
    guest_id = request.cookies.get("guest_id")          # G2. 쿠키만 신뢰
    if request.headers.get("X-Guest-Id") or request.body.get("guest_id"):
        log.security("guest_id_in_untrusted_channel", user=new_user_id)
        raise BadRequest("GUEST_ID_NOT_ACCEPTED")       # G1/G2
    if not guest_id:
        return False
    raw = redis.getdel(f"session:guest:{guest_id}")     # G3. 원자적 읽기+삭제
    if raw is None:
        return False                                    # 이미 소비됐거나 만료
    assert_recently_created(new_user_id)                # G5
    upsert_user_profile(new_user_id, json.loads(raw))
    issue_new_guest_cookie(response)                    # G4. 세션 고정 방어
    return True
```

> **회귀 테스트 필수**: (a) `X-Guest-Id` 헤더로 타인 프로필 이관 시도가 400으로 거절되는지, (b) 같은 guest_id로 두 계정이 연속 승격을 시도할 때 두 번째가 실패하는지.

### 10.2 토큰 전략

| 토큰 | 저장 위치 | 수명 | 비고 |
|---|---|---|---|
| access_token (JWT) | 메모리(JS 변수) | 30분 | `sub`, `exp`, `jti`, `scope`. **XSS 대비 localStorage 금지** |
| refresh_token | HttpOnly + Secure + SameSite=Lax 쿠키 | 14일 | Redis 화이트리스트(`refresh:{jti}`). 로그아웃/재발급 시 회전(rotation) |
| guest_id | **HttpOnly + Secure + SameSite=Lax 쿠키 (유일 경로)** | 24시간 | 개인 식별 정보 미포함 (랜덤 UUIDv4). **`X-Guest-Id` 헤더 등 JS가 읽는 경로를 만들지 않는다** (§10.1.1 G1). 승격 시 `GETDEL`로 1회 소비 + 재발급 |

- **Refresh Token Rotation**: 재발급 시 기존 jti 폐기. 폐기된 jti 재사용 감지 시 해당 사용자 전체 세션 무효화 (탈취 대응).
- JWT 서명: HS256(단일 서버) → 서비스 분리 시 RS256. 서명키는 ENV.

### 10.3 인가 규칙

| 리소스 | 규칙 |
|---|---|
| `/me/*` | `token.sub == 리소스 소유자`. **path의 user_id를 신뢰하지 않고 토큰의 sub만 사용** |
| 리뷰 수정/삭제 | 작성자 본인만 |
| 배치 트리거 엔드포인트 | **외부 노출하지 않음** (내부 네트워크 전용). 필요 시 별도 관리자 스코프 |

> **정정 — `/me/*` IDOR 자체신고는 오탐이었다.** 초판 §13이 "`/me/*`에서 path/body의 user_id를 신뢰하면 IDOR가 발생한다"를 리스크로 신고했으나, **QA·보안 양쪽이 실재하지 않음으로 판정**했다. 근거: (a) 위 표가 이미 "path의 user_id를 신뢰하지 않고 토큰의 sub만 사용"으로 올바르게 규정했고, (b) §6.1의 `/me/*` 엔드포인트(E1·E2·E3)에 **`user_id` path param이 애초에 존재하지 않는다** — `DELETE /me/routes/{route_id}`의 path 변수는 route_id뿐이다. **추가 완화 조치는 불필요하다.**
> 다만 같은 자체신고에 함께 적힌 **게스트 승격 쪽 우려는 실재했고 오히려 더 실질적이었다** → §10.1.1에서 해소했다.

### 10.4 시크릿 관리 — 하드코딩 금지 원칙

> **원칙: 소스 코드와 git 저장소에 시크릿 값이 존재해서는 안 된다. 예외 없다.**

| 시크릿 | 저장 위치 | 금지 사항 |
|---|---|---|
| 공공데이터 API 키 | 환경변수 (`PUBLIC_DATA_API_KEY`) | 코드 리터럴 금지, **URL 쿼리스트링 로깅 금지 — 강제 지점은 §7.3.1 K1~K6** (예외 문자열·알림·원문보관 경유 유출 포함) |
| 지도 SDK 키 | 클라이언트 노출 불가피 → **도메인 허용목록(referrer restriction) 필수** | 서버 키와 클라이언트 키를 혼용 금지 |
| DB 접속정보 | 환경변수 / 시크릿 스토어 | 접속 문자열 통째 커밋 금지 |
| JWT 서명키 | 환경변수 (32바이트 이상 랜덤) | 기본값(`"secret"` 등) 금지 |
| LLM API 키 (채택 시) | 환경변수. **서버에서만 호출**, 클라이언트 직접 호출 금지 | 프론트 번들 포함 금지 |

**강제 수단 (구현 단계 적용)**
- `.env.example`만 커밋하고 `.env`는 `.gitignore`.
- pre-commit 훅에 `gitleaks` 또는 `detect-secrets`.
- 애플리케이션 부팅 시 필수 ENV 미설정이면 **즉시 종료**(fail-fast). 기본값으로 몰래 뜨지 않는다.
- 로깅 미들웨어에서 `Authorization`, `serviceKey`, `apiKey`, `password` 키를 마스킹.
- **선언과 강제 지점의 괴리를 없앤다** — 위 규칙들은 §7.3.1의 `infra/secret_mask.py` **단일 구현**을 K1~K6 여섯 지점에서 호출하는 방식으로만 성립한다. 규칙을 문장으로만 적어두면 §7.3 의사코드가 그랬듯 스스로를 위반한다.

### 10.6 온보딩 원문(`raw_input`) 미저장 결정 (보안 S-H1 / 08 §6 E2)

**결정: 자유 서술 원문을 영구 저장하지 않는다.** `user_profiles.raw_input` 컬럼을 DDL에서 제거했다(§5.2).

| 근거 | 내용 |
|---|---|
| 1. 목적 없는 보관 | **이 컬럼을 SELECT하는 쿼리가 설계 전체에 0건이다.** 데이터 흐름은 `원문 → tags/tag_vector`이고 스코어링·하드필터·랭킹은 전부 `tags`와 `tag_vector`만 소비한다. 이용 목적이 없는 채 저장만 되는 구조는 개인정보보호법의 **목적 명확화·최소수집 원칙 위반 소지**다 |
| 2. 가장 위험한 데이터가 가장 통제가 약한 곳에 | 자유 서술은 enum으로 강제되는 `tags`와 달리 무엇이 들어올지 통제할 수 없다 — "6세 아이"(아동), "휠체어 타는 어머니"(제3자 건강·장애 = 민감정보), "성당 근처"(종교 추론). **어떤 스키마 방어도 걸리지 않는다** |
| 3. 누적형 사고 | 침해가 없어도 위험하다. 1년치가 쌓인 뒤 유출·내부자 조회가 발생하면 유출되는 것은 "취향 태그"가 아니라 **"누가 몇 살 아이를 키우고 가족 중 누가 휠체어를 쓰는지"의 원문 텍스트 집합**이다 |
| 4. 안내 문구는 통제가 아니다 | "민감한 내용은 적지 마세요" 가이드는 자유 서술을 유도하는 온보딩 UX와 정면 충돌한다. **실효 통제는 입력 차단이 아니라 저장 차단**이다 |

**처리 규칙**

| # | 규칙 |
|---|---|
| R1 | 원문은 `extract_tags()` 호출 후 **메모리에서 폐기**한다. 요청 로그·에러 리포트·APM에 본문을 남기지 않는다 (`middleware/request_log.py`가 `text` 필드를 마스킹) |
| R2 | 저장되는 것은 `tags`·`tag_vector`·`scoring_weights`·`region_code`·`input_source`뿐이다 — 전부 **enum·수치로 의미가 통제된 값**이다 |
| R3 | `unmatched_note`도 저장하지 않는다 (내부 진단 로그 전용, S-M2) |
| R4 | `tag_vector[30]`(유모차)·`[31]`(휠체어)는 저장 시 0으로 마스킹, 세션 한정 사용 (08 §1.7 E3) |
| R5 | **재추출 목적으로 보관이 필요해지면** (대표가 E2를 뒤집는 경우) 다음을 모두 충족해야 한다: (a) 목적 문서화, (b) `raw_input_expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '30 days'` + 일 1회 파기 배치, (c) 컬럼 레벨 암호화(pgcrypto 또는 앱 레벨), (d) 개인정보처리방침에 보유기간 명시, (e) 저장 전 PII 정규식 스크러빙(전화·이메일·주민번호). **5개 중 하나라도 빠지면 저장하지 않는다.** |

> **트레이드오프 (대표 판단 대상)**: 미저장의 대가는 `vector_version`이 올라갔을 때 **기존 사용자 프로필을 재추출할 수 없다**는 점이다. 대안은 사용자에게 온보딩을 다시 요청하는 것이며, 축 변경이 잦지 않을 MVP 단계에서는 감당 가능한 비용으로 판단했다.

### 10.5 재사용 인프라 컴포넌트 (별도 모듈로 분리)

| 모듈 | 책임 |
|---|---|
| `middleware/request_log.py` | 요청 ID 부여, 응답시간, **민감 필드 마스킹**(`text`·`lat`/`lng`/`near`·`guest_id`), 정밀좌표 미로깅. **Nginx 단 로그 설정(§3.1 L3)과 함께여야 유효** |
| `infra/secret_mask.py` | 시크릿 마스킹 단일 구현. §7.3.1 K1~K6이 공유 |
| `middleware/rate_limit.py` | Redis 슬라이딩 윈도. 기본 60req/min/IP, `compare` 10req/min, `auth/login` 5req/5min |
| `middleware/error_envelope.py` | 예외 → 표준 에러 응답. **스택트레이스 외부 노출 금지** |
| `infra/quota_guard.py` | 공공 API 일일 쿼터 선차감 |
| `infra/http_client.py` | 재시도/백오프/타임아웃/circuit breaker |
| `infra/cache.py` | get-or-set, stale-while-error, 태그 무효화 |

---

## 11. 기술 스택 결정 권고 및 비MVP 처리

### 11.1 R2 — Node vs Python (제안, 결정은 대표/planning-lead)

초안은 Backend를 Node.js/Express로, NLP를 KoNLPy/OpenAI로 병기했다. **KoNLPy는 Python 라이브러리라 Node에 그대로 붙지 않는다.**

| 안 | 구성 | 장점 | 단점 |
|---|---|---|---|
| **안1 (권고)** | **Python / FastAPI 단일 스택** | AI팀 산출물(NLP·스코어링)이 같은 프로세스에서 함수 호출로 붙음. KoNLPy·numpy 사용 자유. 배포 대상 1개. 8주 일정에서 통합 비용 최소 | Node 대비 I/O 동시성 처리 경험이 팀에 없을 수 있음 (FastAPI는 async라 실무상 충분) |
| 안2 | Node/Express + 별도 Python NLP 서비스 | 초안 유지. 프론트(Next.js)와 언어 통일 | **서비스 2개 = 배포·모니터링·장애지점 2배.** 1인 스튜디오 + 8주에 부담 |
| 안3 | Node 단일 + LLM API만 사용 | 가장 단순 | KoNLPy 포기. LLM 장애 시 오프라인 폴백 구현이 어려워짐 (심사 시연 리스크) |

**권고: 안1 (FastAPI).** 근거 3가지
1. 이 서비스의 차별점(M1 NLP, M3 스코어링, M6 밸런싱)이 **전부 Python 생태계 쪽**이다. 언어 경계를 넘는 비용이 반복 발생한다.
2. **오프라인 폴백**(LLM 장애 시 룰 기반 태그 추출)이 같은 프로세스에서 즉시 가능하다 — 심사 시연 안전성에 직결.
3. PostGIS·Redis·배치 스케줄링(APScheduler/Celery) 모두 Python 생태계가 성숙하다.

> 프론트엔드는 초안대로 Next.js를 유지한다. 프론트/백 언어 통일은 이 프로젝트에서 실익이 작다 (BFF나 SSR 데이터 페칭을 공유할 계획이 없음).

### 11.2 R6 — 지도 SDK 1종 채택 권고

> **⚠️ 정정 (2026-07-24)**: 아래 원 권고(Kakao)는 "대회 요강이 Kakao/NAVER SDK를 필수 요구한다"는 **틀린 전제** 위에 있었다. 진짜 공고문(`_공모전_공고문-원본.md`) 확인 결과 필수 API는 한국관광공사 OpenAPI뿐이고, 지도 SDK는 완전 자유 선택이다. 대표가 **Tmap 단일화를 결정**했다 — 이미 Tmap 키 발급·실호출 검증 완료(§15.3.1), Kakao는 도메인 승인 단계에서 활성화 보류 중이었다(`OPEN_MAP_AND_LOCAL` 서비스 미활성화, 403). Tmap JS SDK(`Tmapv2`/`Tmapv3`) 공식 문서로 마커(`Marker`, 클러스터링, 애니메이션)·폴리라인(`Polyline`, `drawPolyline`)·커스텀 오버레이(`GroundOverlay`) 전부 지원 확인됨 — 카카오맵의 4대 역할(지도표시/마커/경로선/오버레이)을 대체하는 데 기능적 결손 없음.
>
> **최종 채택: Tmap 단일화.** `MapProvider` 구현체를 Tmap 하나로 채운다. 아래 원 문단은 이력 보존을 위해 남긴다.

**Kakao Map JS SDK를 제안**한다. 근거: 국내 관광 좌표·장소 데이터와의 정합성, 한국어 지오코딩, 레퍼런스 양. **2026-07-23 요금 조사로 근거 보강됨** — 아래 11.2.1.

> **단, 로고·저작권 표기 의무 조항은 여전히 확인 필요 (Q-M2, Tmap 기준으로 재확인 필요).**
>
> **설계 방어**: 지도 관련 코드는 `MapProvider` 인터페이스 뒤로 격리해 SDK 교체 비용을 낮춘다 (마커 표시/폴리라인 그리기/좌표 변환 3개 메서드) — **이 판단이 정확히 지금 상황에서 유효했다.**

#### 11.2.1 지도 표시·경로탐색 API 요금 실측 비교 (2026-07-23, 각사 공식 요금 페이지 직접 확인)

**지도 표시(M4)**

| | 무료 이용량 | 초과 요금 |
|---|---|---|
| Kakao Maps JS SDK | 30만 건/일 | 0.1원/건 |
| Naver Dynamic Map | 600만 건/월 | 0.1원/건 |

Kakao·Naver 둘 다 넉넉하다. **Kakao를 유지 권고** — 국내 관광 데이터 정합성·레퍼런스 양이라는 원 근거는 요금과 무관하게 유효하고, 요금도 밀리지 않는다.

**경로탐색(M10, D16)**

| | 무료 이용량 | 초과 요금 | 비고 |
|---|---|---|---|
| Tmap Route API (SK) | 1,000건/일 (일일 리셋, 이월 안 됨) | 11원/건 (또는 정액 월 220만원) | **대회 요강 5.2절 명시 항목** |
| Kakao Mobility 자동차 길찾기 | 10,000건/일 (일일 리셋) | 8원/건 | 별도 가입(카카오맵과 다른 상품) |
| Naver Directions 5 (경유지 ≤5) | **60,000건/월** (월 단위 총량, 이월 안 되나 하루 몰아쓰기 가능) | 5원/건 | |
| Naver Directions 15 (경유지 ≤15) | 3,000건/월 | 20원/건 | 다중 경유지 필요시만 |

**결론**: 순수 비용·쿼터만 보면 Naver Directions 5가 가장 유연하고 Kakao Mobility가 가장 저렴하지만, **D16을 Tmap으로 유지한다** — 대회 요강이 "Kakao/NAVER Maps SDK **및** Tmap Route API 연동"을 명시 요건으로 못박았기 때문이다(가격이 아니라 심사 체크리스트 준수가 채택 근거). 개발·시연 규모(하루 1,000건 미만 예상)에서는 Tmap 무료 한도로 충분해 비용 리스크는 낮다.

Q-M1(무료 쿼터)은 이걸로 해소됐다. **비상업/공모전 이용 허용 여부는 각사 이용약관 별도 확인 필요**(요금 페이지엔 없음, Q-M1b로 신설).

### 11.3 비MVP 처리 (PRD 6.2-⑦)

#### N1 — 현장 사진 인증 + EXIF 위치 검증: **구현 설계하지 않음**

DB 스키마에도 관련 컬럼(`verified_visit`, `photo_url`, `exif_lat` 등)을 **일부러 만들지 않았다.** 스키마에 자리를 만들어 두면 다음 단계에서 자동으로 구현 대상이 되기 때문이다.

**제한 사항 (사실 기술)**
- EXIF GPS 태그는 편집이 용이하다. 동시에 다수 SNS·메신저는 업로드 시 EXIF를 제거한다. → **위조는 못 막고 정상 사용자만 실패**하는 조합이 될 수 있다.
- 브라우저 Geolocation API는 개발자도구·가상 위치 도구로 변조 가능하다. 웹에는 네이티브 앱의 무결성 검증(Play Integrity, App Attest)에 해당하는 수단이 없다.
- 초안의 "인증 완료 시 할인 쿠폰 지급"은 **금전적 가치가 걸린 위조 유인**을 만든다. 인증 신뢰도가 낮은 상태에서 보상을 붙이면 어뷰징이 구조적으로 발생한다.

**향후 대안 (설계 아님, 방향만)**
1. **상점 QR / 단기 코드**: 상점에 회전 코드를 두고 스캔. 위조 난도가 오르고 상점 제휴 동기도 생긴다.
2. **서버측 IP 지오 교차검증**: 클라이언트 신고 좌표와 서버 관측 IP 대역의 지역 일치 여부를 보조 신호로만 사용 (모바일 캐리어 IP 특성상 단독 근거로는 부적합).
3. **보상 분리**: 인증에 금전 보상을 붙이지 않고 비금전 배지만 부여해 위조 유인을 제거.

#### N2~N5 처리

| 항목 | 처리 |
|---|---|
| N2 쿠폰 | 스키마·API 없음. 제휴 계약이 선행 조건 |
| N3 오디오 가이드 | D13 수집 안 함. 화면 자리만 (designer) |
| N4 Tmap 실주행 | 외부 네비 앱 **딥링크**로 대체 (서버 개발 불필요). 키·과금 확인 대상 아님 |
| N5 PWA | manifest/service worker 설계 없음 |
| N8 배포 | 인프라 설계 없음. 참고로 목표 구성은 EC2 + Nginx + Docker Compose(app/worker/postgis/redis) 수준이며, 이는 **후속 프로젝트 범위** |

---

## 12. ★ 확인 필요 항목 집계

> PRD 2.3 완료 조건: "확인 필요 항목이 한 곳에 집계되어 대표가 무엇을 결정해야 하는지 한눈에 보일 것."
> **우선순위: P0 = 이게 없으면 MVP가 성립하지 않음 / P1 = 설계 변경이 필요해짐 / P2 = 품질 영향**

### 12.1 공공데이터 (D)

| ID | 확인 항목 | 우선 | 막히는 것 | 확인 방법(제안) |
|---|---|---|---|---|
| **Q-D1** | **"관광지 집중률 방문자 추이 예측 정보"가 실시간 REST API인가, 통계 리포트/파일 다운로드인가** | **P0** | M2, M3, Tier A 성립 여부 | 한국관광 데이터랩/공공데이터포털에서 해당 데이터 상세 페이지 확인 |
| Q-D2 | D1의 응답 필드명·값 범위·집중률 정의(비율? 등급? 절대인원?) | P0 | 정규화 로직 확정 | 위와 동일 |
| Q-D3 | D1의 공간 해상도 (관광지 단위 / 시군구 단위) | P0 | `congestion_snapshots` 대상 결정 | 위와 동일 |
| Q-D4 | D2(지역별 방문자수)의 최소 시간 해상도와 공개 지연(lag) | P0 | Tier B 산출식 성립 | 데이터랩 확인 |
| Q-D5 | **D4(두루누비)가 코스 좌표열(polyline)을 제공하는가** | **P0** | 지도 위 "선" 표현 (7.6절) | 두루누비 API 명세 확인 |
| Q-D6 | D7(소상공인 상권) 반경 검색 지원 여부, 일일 쿼터 | P1 | M5 수집 방식 (반경검색 vs 전량적재) | 소상공인시장진흥공단 API 문서 |
| Q-D7 | D11(반려동물/무장애/웰니스) 필드가 boolean인가 서술문인가 | P1 | `places.pet_allowed` 정규화 | TourAPI 명세 |
| Q-D8 | D9(축제)가 좌표를 제공하는가, 주소만인가 | P1 | 지오코딩 잡 필요 여부·쿼터 | 표준데이터 명세 |
| Q-D9 | 전 데이터셋의 **일일 호출 쿼터**와 신청→승인 소요 기간 | P0 | 배치 주기 확정, 일정 산정 | 공공데이터포털 신청 화면 |
| Q-D10 | 전 데이터셋의 **공모전/재배포 이용 허용 범위** (이미지 포함) | P1 | legal 4차 게이트 | 각 데이터 이용약관 |
| Q-D11 | 좌표계 (WGS84 / GRS80 TM / KATEC) | P1 | 변환 로직 필요 여부 | 각 명세 |
| Q-D12 | D12(주차장) 데이터셋 출처 특정 (초안 내에서도 미기재) | P2 | 페르소나1 "주차 넉넉" 근거 | 공공데이터포털 검색 |

### 12.2 지도 SDK / 외부 (M)

| ID | 확인 항목 | 우선 | 막히는 것 |
|---|---|---|---|
| ~~Q-M1~~ | ~~Kakao(또는 NAVER) Maps JS SDK 무료 쿼터~~ | — | **해소 (2026-07-23)** — 11.2.1절, 양사 모두 넉넉함 확인 |
| Q-M1b | 지도·경로탐색 API의 **비상업/공모전 이용 허용 여부** (각사 이용약관) | P0 | 요금 페이지엔 없음, 약관 별도 확인 필요 |
| Q-M2 | 지도 SDK 로고·저작권 표기 의무 | P1 | designer 화면 하단 영역 |
| ~~Q-M3~~ | ~~경로탐색(길찾기) API의 별도 키·과금 여부~~ | — | **해소 (2026-07-23)** — 11.2.1절. Tmap/Kakao Mobility/Naver Directions 전부 별도 가입·과금 체계 확인됨 |

### 12.3 법률/개인정보 (L) — legal-counsel 4차 게이트 입력

| ID | 확인 항목 | 우선 | 비고 |
|---|---|---|---|
| Q-L1 | 비저장 1회성 정밀 좌표 수신도 위치정보법 신고 대상인가 | P0 | 3절 정책 확정에 필요. **§3.1 L1~L5 적용 이전 상태(로그 잔류)를 "수집"으로 볼 것인지도 함께 질의** |
| ~~Q-L2~~ | ~~`user_profiles.raw_input` 보존 기간·파기 정책~~ | — | **해소됨 — 저장하지 않기로 결정**(§10.6). 보유기간 질의 자체가 소멸. 대표가 E2를 뒤집으면 R5 조건 5종과 함께 재개 |
| Q-L3 | 온보딩 원문을 외부 LLM API로 전송 시 국외이전 고지·동의 요건 | P0 | AI팀 LLM 채택 여부와 연동 |
| Q-L4 | 동행자 구성(가족·반려동물) 태그의 개인정보 해당 여부 | P1 | `user_profiles.tags` |

### 12.4 내부 결정 대기 (I)

| ID | 결정 항목 | 결정 주체 | 현재 backend 제안 |
|---|---|---|---|
| Q-I1 | Node vs Python 스택 | 대표 / planning-lead | **Python/FastAPI 단일 스택** (11.1절) |
| Q-I2 | 지도 SDK 1종 | 대표 / planning-lead | **Kakao** (Q-M1 확인 조건부) |
| Q-I3 | 게스트 체험 경로 도입 여부 | ~~대표 / planning-lead~~ → **08 §6 E1 잠정 확정** | **도입한다.** 서버 Redis 24h + 회원가입 시 승격(10.1절). 승격 규칙은 10.1.1. 대표가 뒤집으면 재검토 |
| Q-I4 | 위치 정밀도 정책 | legal 판정 후 planning-lead | **시군구 기본 + 정밀좌표 비저장 opt-in**(3절) + **body 수신·3자리 반올림·Nginx 로그 제외**(3.1절) |
| Q-I5 | 온보딩 태그 축·값 집합 확정 | ~~ai-optimization-engineer~~ → **`08-interface-contract.md` §1.4로 확정됨** | **해소됨.** 축 7종 + 36차원 시드가 정본으로 확정되어 §5.2.1에 수록. backend는 `tag_axis_registry`로 물리 고정만 한다 |
| Q-I6 | 로드밸런싱 임계치 0.6 / 0.85 | 운영 데이터 확보 후 보정 | 초기 가정값 (8.2절) |
| Q-I7 | `daily_capacity` 카테고리 기본값 (trail=300 등) | 근거 확보 필요 | **전부 가정값** (8.2절) |

### 12.5 이 문서에서 "가정"으로 표시한 것 (사실 아님)

- 배치 주기(7.2절 표) — 실제 갱신 주기 확인 전 임시값
- Tier B/C 산출식의 계수(0.55/0.45, 0.5/0.3/0.2, event_boost 0.25) — 실측 전 초기값
- 로드밸런싱 가중치(안내 1.0 / 저장 2.0 / 조회 0.3), 절대 임계치(0.6/0.85), 수용력 기본값
- **2순위 상대 share 임계(0.4/0.6)** — 절대 임계와 마찬가지로 실측 전 초기값
- **이상 급증 감지 배수(직전 6버킷 평균의 5배)** — 가정값
- **`congestion.level` 임계(33/66 3등분)** — 근거 없는 3등분이며 실측 후 보정 대상
- `hour_factor` 카테고리별 시간 프로파일
- 외부 API 인증 방식(`Authorization: Bearer`)의 구체 형태 — 실제로는 `serviceKey` 쿼리 파라미터일 가능성이 높으나 **확인되지 않아 의사코드에만 사용**

---

## 13. 핸드오프 노트

```
[다음 부서가 알아야 할 것]
1. 온보딩 태그는 user_profiles.tags(JSONB) + tag_vector(REAL[], 36차원 이진) + scoring_weights(JSONB, 5축)로
   나뉘어 저장된다 — 두 개는 다른 개념이며 축 순서는 tag_axis_registry(§5.2.1 36행 시드)가 규정한다.
   자유서술 원문은 저장하지 않는다(§10.6). compare 응답 좌우 객체는 동일 키 구조라 designer가 대칭으로 그린다.
2. verdict.headline은 LLM이 아니라 backend 템플릿 조립이며 소관도 backend로 이관됐다(§7.7).
   headline에 코스명·상호명 등 외부 데이터 문자열을 넣지 않는 것이 인젝션 방어의 핵심이므로 되돌리지 말 것.
   화면 델타 카드는 congestion_delta_pct(상대 %)를 쓰고 congestion_delta(절대 p)와 혼용하지 않는다.
3. 확인 필요 항목은 12절에 집계했다. Q-I5(태그 축)·Q-L2(원문 보존)는 해소됐고, Q-D1(집중률이 실시간 API인가)과
   Q-D5(두루누비 좌표열 제공 여부)가 MVP 성립을 좌우하는 두 급소로 남아 있다 — 대표 확인 대기.
```

### QA가 특히 확인해야 할 리스크 지점 (3줄)

1. **캐시 교차 서빙 (재검증 최우선)** — `cmp:ctx:{profile_hash}:{hash(req)}`로 키를 바꾸고 개인화 필드를 캐시 화이트리스트에서 제외했다(§9.2.1). **서로 다른 프로필의 두 계정이 동일 파라미터로 compare를 호출했을 때 `spot_fit`·`verdict`가 각각 다르게 나오는지**가 통과 조건이다.
2. **게스트 승격 원자성** — `X-Guest-Id` 수용을 삭제하고 `GETDEL` 1회 소비 + 승격 후 재발급으로 바꿨다(§10.1.1). 헤더로 타인 프로필 이관 시도가 400으로 거절되는지, 동일 guest_id의 2회차 승격이 실패하는지 확인 필요. **`/me/*` IDOR는 오탐으로 정정됐다 — path에 user_id가 없다.**
3. **Tier 혼재 + 시크릿 마스킹** — 혼잡도 조회 전부에 `ORDER BY observed_at DESC, tier ASC` tie-break가 적용됐는지, `data_freshness.tier`가 혼재 시 `mixed`로 나오는지(§5.3.1). 배치 타임아웃을 인위 유발했을 때 `raw_ingest_log.error_message`에 `serviceKey` 값이 남지 않는지(§7.3.1).

---

## 14. 재작업 반영 내역 (3차 게이트 v1.1)

### 14.1 08 정본 §7.2 backend 지시 12건

| # | 정본 지시 | 반영 위치 | 어떻게 고쳤는가 |
|---|---|---|---|
| **B1** | 폐기된 가중치 벡터 컬럼 → `tag_vector REAL[]`, `scoring_weights JSONB` 추가 | §5.2 DDL | `user_profiles`에서 해당 컬럼 삭제 → `tag_vector REAL[]`(36차원 이진, 주석에 이진 제약 명시) + `scoring_weights JSONB NOT NULL`(5키 합 1.0) 두 컬럼으로 분리. 두 개가 다른 개념임을 주석과 §13 핸드오프에 명시 |
| **B2** | `tag_axis_registry`에 `flag`·`congestion_pref` 추가 + 36행 시드 수록 | §5.2 DDL, **§5.2.1 신설** | 테이블 주석의 축 목록을 7종으로 교체(`companion`/`flag`/`mobility`/`mood`/`spot_pref`/`accessibility`/`congestion_pref`), `vector_index` 주석을 `tag_vector 내 위치(0~35)`로 수정. §5.2.1을 신설해 36행 시드 전체 + 슬라이스 규약(S_fit 14~28, 하드필터 29~32, 가중치 가산 축) + index 30·31 마스킹 규칙 수록 |
| **B3** | §6.2 A1의 12차원 confidence 벡터 → 36차원 이진 벡터 | §6.2 A1 | 응답 예시를 08 §1.5 정본 구조로 전면 교체: `tags` 7축(`flag`·`congestion_pref` 포함, 영문 코드 + label_ko), `tag_vector` 36차원 **이진**(인덱스 구간 주석 포함), `scoring_weights` 5축, `extraction_confidence` 신설. confidence를 벡터 원소로 쓰던 예시 폐기 + 그 이유를 주석으로 명시. `unmatched_note` 미노출·미저장 규칙 추가 |
| **B4** | §7.1 `ai_contract.py` 전면 교체 + `build_verdict` backend 이관 | §7.1, **§7.1.1·§7.1.2 신설**, **§7.7 신설** | `OnboardingResult`를 08 §1.5 8필드 정본으로 교체. `score_routes(profile, candidates, congestion)`로 시그니처 변경(프로필 전체 전달, 하드필터 AI 단일화, LB 페널티 금지 계약 명시). `RouteScore`에 `matched_spots`·`score_breakdown` 추가. `build_verdict`를 **ai_contract.py에서 제거**하고 §7.7(backend 소관)로 이동. §7.1.1에 `candidates` 필수 키 8종, §7.1.2에 4단계 단방향 파이프라인 신설 |
| **B5** | §6.2 D1 응답을 08 §2.2 정본 34필드로 갱신 | §6.2 D1 | 응답 예시를 34필드 전수 반영(번호 주석 부기): `congestion`에 `source`·`observed_at` 추가, `level` 영문 enum, `tier`에 `none` 허용, `spot_fit.matched_spots` 신설, `review_trust.coldstart` 신설, `verdict.congestion_delta_pct` 신설(m3 해소), `scoring_weights_used`·`score_breakdown`(양쪽) 신설, `data_freshness` 구조화 + `mixed`. 소관 분리표·단위 규약·`_pct` 산식·`none` 처리 규칙 부기. Request에 인라인 프로필 경계값 검증 규칙 추가 |
| **B6** | headline 템플릿 4종 + 안전 규칙 문서화 | **§7.7 신설** (§7.7.3~7.7.4) | LLM 미사용 근거 3종, `-> Verdict` 시그니처(반환 타입 변경 주의 표기), **안전 규칙**(수치·enum·개수만 삽입, 코스명·상호명 절대 금지, 120자 상한, 텍스트 노드 렌더, 문자열 변수 추가 시 보안 재검토), 템플릿 4종(기본/양쪽 우위/혼잡 열위/`tier==none`) 표로 수록. §7.7.5에 배치 문자열 위생 검사 추가 |
| **B7** | §8.2~8.3 2순위 상대 share + `profile_fit()` 재호출 제거 + RED 예외 | §8.2, §8.3, §8.4 | §8.2에 2순위 상대 share 분기(0.4/0.6, 그룹 1개면 미판정) 추가, RED 행에 "대안 풀이 비면 배제하지 않는다" 명시 + 충돌 해소 원칙 부기. §8.3에서 **`select_route_with_balancing`의 입력을 `list[RouteScore]`로 변경**하고 `profile_fit()` 재호출 삭제 → `RouteScore.spot_fit` 재사용. `lb_state()` 분리(절대→상대 폴백). §8.4 `fallback_all_congested`를 `evaluated` 기반으로 수정하고 원 코스 유지 주석 추가 |
| **B8** | §8.2 dedupe·비인증 미계상·이상탐지·"조작 가능" 명문화 | **§8.2.1 신설**, §7.5 Tier C | 조작 시나리오 3종(혼잡도 부풀리기/LB 조작/자기증폭 루프) 기술 후 방어 4종 표(D1 `SETNX lb:dedupe:{route}:{subject_hash}:{hour}` TTL 2h / D2 비인증 `viewed` 가중치 0 / D3 6버킷 평균 5배 초과 시 알람+Tier C 제외 / D4 신뢰도 서열)로 정리. `record_guidance()`를 dedupe·subject_hash(HMAC) 포함 버전으로 교체하고 §8.3에서 이동. **절 서두에 "조작 가능한 신호이며 dedupe·이상탐지가 전제된다"를 명문화.** §7.5 Tier C 산출식에도 동일 전제 부기 |
| **B9** | §5.3·§6.0·§7.5 tie-break + item별 tier + `mixed` | §5.3-(3), **§5.3.1 신설**, §6.0, §7.5 | 전광판 LATERAL 쿼리에 `ORDER BY observed_at DESC, tier ASC` 추가 + 왜 필요한지 주석. §5.3.1 신설: T1(전 조회 쿼리 tie-break) / T2(item별 tier 필수) / T3(`data_freshness.tier` 집계, 혼재 시 `mixed`) / T4(`none` 처리) + **`uq_congestion_point`에서 tier를 빼지 않는 이유**(강등 시 Tier A 실측 행이 덮어써지므로 §7.3 안전장치와 충돌). §6.0 `data_freshness` 스키마에 `mixed`·`none` 반영. §7.5 `compute()`에 tie-break 주석 |
| **B10** | §6.0·§10.1~10.2 `X-Guest-Id` 삭제, `GETDEL` 승격, 재발급 | §6.0, §10.1, **§10.1.1 신설**, §10.2 | §6.0 공통 규약에서 `X-Guest-Id` 문구 삭제 → 쿠키 단일 경로 + 헤더/body/query 전달 시 `400 GUEST_ID_NOT_ACCEPTED` + 보안 로그. §10.1.1 신설: 공격 시나리오 4단계, "두 규정이 동시 성립 불가"라는 근본 원인, 규칙 G1~G7(헤더 삭제/쿠키만 신뢰/`GETDEL` 원자적 1회 소비/승격 후 재발급/신규 계정 검증/로그 금지/IP·UA 대조는 플래그만) + 의사코드. §10.2 토큰 표의 guest_id 행 갱신 |
| **B11** | §12.4 Q-I5 확정 처리, Q-I3에 E1 반영 | §12.4, §10.1 | Q-I5를 "08 §1.4로 확정됨 — 해소"로 갱신(축 7종+36행 시드가 §5.2.1에 수록됨을 명기). Q-I3를 "08 §6 E1 잠정 확정 — 도입한다"로 갱신하고 결정 주체를 08로 이관. Q-I4에 §3.1 강제 수단 반영. §10.1에도 E1 확정 사실 + designer 배너 문구 통일 지시 부기 |
| **B12** | §8.3 m1 비원자성을 "허용 오차 + 근거"로 명시 기록 | **§8.3.1 신설** | 현상 기술 후 **"허용 오차로 확정, 새 설계 미도입"**을 설계 결정으로 명시. 근거 4종 표(윈도 6h·일 단위 capacity 대비 오차 무시 가능 / AMBER 60% 확률 분산이 자연 완화 / RED는 카운터 반영 후 걸려 자기 교정 / 초기 트래픽 규모에서 체감 0). 정밀 제어가 필요해질 때의 Lua 원자화 경로를 각주로 남기고 **"지금 도입하지 않는 것이 설계 결정"**임을 명기 |

### 14.2 보안 High 6건 (backend 담당분)

| # | 지적 | 반영 위치 | 어떻게 고쳤는가 |
|---|---|---|---|
| **S-H1** | `raw_input` 무기한 저장 — SELECT 쿼리 0건 | §5.2 DDL, **§10.6 신설**, §12.3 | **DDL에서 컬럼 자체를 제거**하고 그 자리에 미저장 사유 주석을 남겼다(08 E2 잠정 정본 채택). §10.6에 근거 4종(목적 없는 보관/스키마 방어 부재/누적형 사고/안내문구는 통제가 아님)과 처리 규칙 R1~R5, 재저장 시 충족해야 할 5조건(목적 문서화·30일 TTL·컬럼 암호화·방침 명시·PII 스크러빙)을 기록. 트레이드오프(vector_version 변경 시 재추출 불가)도 정직하게 병기. Q-L2를 "해소됨"으로 갱신 |
| **S-H2** | 정밀좌표가 GET 쿼리스트링 → Nginx 로그에 guest_id와 함께 잔류 | §3 표, **§3.1 신설**, §6.1, §6.2 C1 | 좌표 수신을 **body 전용**으로 전환: `GET /places`는 `region_code` 전용, 좌표 조회는 **`POST /api/v1/places/search` 신설**(엔드포인트 표에 C1b 추가). §3.1에 강제 수단 L1~L5(전송 방식/소수점 3자리 반올림/Nginx `$uri`만 기록·미설정 시 배포 차단/앱 로그 마스킹/Referer·히스토리 차단) 표로 명시. §3 표의 "로그에도 미기록"을 **"앱·웹서버·프록시 전 계층에서"**로 정정. **D1이 이미 body로 받던 설계 내부 비대칭도 해소** |
| **S-H3** | `cmp:{hash(req)}` — `use_saved=true`면 해시 동일 → 개인화 결과 교차 서빙 | §9.1, **§9.2.1 신설**, §9.2 | 캐시 키를 **`cmp:ctx:{profile_hash}:{hash(req)}`**로 변경(`profile_hash = sha256(tag_vector‖vector_version‖scoring_weights)[:16]`, 게스트는 `anon`). subject 단위가 아니라 **프로필 단위** 해시를 택한 이유(동일 취향 공유는 무해 + 적중률 유지)를 명기. 캐시 대상 **화이트리스트 표**(가능: 후보집합·혼잡도·지오메트리·상점·review_trust / 금지: `spot_fit`·`score_breakdown`·`verdict`·`load_balancing`·`comparison_id`) 신설. `Cache-Control: private, no-store` 추가. **9.1↔9.2 모순은 9.1의 키 이름을 `cmp:ctx:*`로 바꾸고 화이트리스트를 명시해 한쪽으로 정리** |
| **S-H4** | `X-Guest-Id` 헤더와 HttpOnly 쿠키가 동시 성립 불가 | §6.0, **§10.1.1 신설**, §10.2 | B10과 동일 조치. 특히 **"모순을 방치하면 구현자가 HttpOnly를 포기해 자동으로 취약해진다"**는 인과를 문서에 남겨 되돌림을 방지. 승격 1회성은 `GETDEL` 원자 연산으로 강제(G3) |
| **S-H6** | `log.finish("failed", str(e))` → 예외 URL의 `serviceKey`가 운영 DB에 평문 | §7.3 의사코드, **§7.3.1 신설**, §10.4, §10.5 | 의사코드의 `str(e)`를 **`mask_secrets(e)`**로 교체(SchemaMismatch 분기 포함). §7.3.1 신설: 유출 경로 설명(HTTP 예외 문자열에 URL 포함 + 포털 관례상 `?serviceKey=`) + **강제 지점 K1~K6 표**(http_client 재raise 전 마스킹·`log.finish` 저장 직전 이중 마스킹·`archive_raw`는 본문만·`alert` 페이로드·request_log·가능하면 키를 헤더로) + `infra/secret_mask.py` 단일 구현. §10.4에 강제 지점 참조 + "선언과 강제 지점의 괴리를 없앤다" 항목 추가, §10.5 모듈 표에 `secret_mask.py` 등재 |
| **S-H7** | 무인증 `GET /places/{id}`가 Tier C·`load_ratio`를 만들어 반복 호출로 조작 가능 | **§8.2.1 신설**, §7.5, §6.1 | B8과 동일 조치. 추가로 §6.1 엔드포인트 표의 C2 행에 "dedupe 통과분만 계상" 명기, §7.5 Tier C 산출식 위에 "dedupe·비인증 미계상·이상탐지를 통과한 값만 사용" 전제 부기, 심사 대응 문구(조작 방지 장치를 Tier C 표기와 함께 설명) 추가 |

### 14.3 QA 자체신고 3건 재판정

| 항목 | QA 재판정 | 반영 위치 | 조치 |
|---|---|---|---|
| **비원자성** (자체신고 #1 / m1) | **Minor 유지 적정** — 격상 불필요 | §8.3.1 | 새 설계를 넣지 않고 **"허용 오차 + 근거"를 설계 결정으로 명시 기록**. 근거 4종 + Lua 원자화 각주 (= B12) |
| **`/me/*` IDOR** (자체신고 #2) | **오탐** — `/me/*`에 `user_id` path param이 애초에 없다 | §10.3, §13 리스크 3줄 | §10.3에 **정정 블록**을 추가해 "실재하지 않음 + 추가 완화 불필요"를 근거(인가 규칙이 이미 `token.sub`만 사용 / E1~E3 path에 route_id뿐)와 함께 기록. §13 리스크 항목에서도 IDOR 우려를 삭제하고 오탐 정정 사실로 대체. **같은 신고에 붙어 있던 게스트 승격 우려는 실재했으므로 §10.1.1로 분리 해소** |
| **Tier 혼재** (자체신고 #3 / J5) | **Major 확정** — 실재 | §5.3-(3), §5.3.1, §6.0, §7.5 | tie-break·item별 tier·`mixed` 3종으로 해소(= B9). 이 결함이 **본 문서 P3 원칙과 §7.5 정직성 서사를 정면으로 깨는 문제**임을 §5.3.1 서두에 명기 |

### 14.4 완료 기준 자체 확인

08 §7 공통 완료 기준의 금지 문자열 5종을 `grep`으로 실측한 결과 **전부 0건**이다.

| # | 금지 문자열 (본 표에서는 검증을 위해 분철 표기) | 대체된 정본 이름 | 실측 |
|---|---|---|---|
| 1 | `weight` + `_vector` | `tag_vector` / `scoring_weights` (분리) | **0건** |
| 2 | `verified` + `_review_count` | `review_trust.count` | **0건** |
| 3 | `실방문` + ` 인증` | `review_trust.companion_matched_count` | **0건** |
| 4 | `hotspot` + `_course` | `hotspot` (봉투 키) | **0건** |
| 5 | `distance` + `_km` | `total_distance_m` (미터 int) | **0건** |

> **분철 표기 이유**: 이 표에 금지 문자열을 그대로 적으면 그 자체가 grep에 잡혀 완료 기준을 스스로 위반한다. 검증 가능성을 유지하기 위해 `+`로 분철했다.
> **유지 대상**: §11.3의 `verified_visit`·`photo_url`·`exif_lat`는 **"이 컬럼들을 일부러 만들지 않았다"는 N1 차단 근거 서술**로만 등장하며 08 §4.3 제거 대상이 아니므로 그대로 둔다.

---

## 15. 스코프 개정 증분 (M8~M12 / M14 / M15 / M16) — v1.2·v1.3·v1.4·v1.5

> **배경**: 2026-07-23 대표 지시 "대회 공식 개발 체크리스트를 먼저 따라"로 요강 §5.2 체크리스트가 스코프 상위 기준이 됐다. 기존 후순위 N1·N3·N4가 **M8·M9·M10으로 승격**됐고, 이미 본 문서에 설계돼 있던 두루누비·축제는 **M11·M12로 정정 등재**된다(PRD §3.2, R10). **v1.3에서 M14(날씨 연동 경로 보정)가 §15.8에 추가**됐다. **v1.4에서 M15(지도 위 혼잡도 히트맵/오버레이)가 §15.9에 추가**됐다 — 기존 M2 혼잡도 예측(D1)을 지도에 색상으로 시각화하는 프론트/디자인 증분이며 **새 데이터셋·새 배치·새 tier·새 테이블이 전부 불필요**하다. **v1.5에서 M16(여행지 목적지 검색 입력)이 §15.10에 추가**됐다 — 지명 자동완성(구조화 입력)으로 목적지를 고르면 기존 `region_code` 필터로 후보 생성 범위를 좁히는 진입점이며, 온보딩 LLM·08 스코어링 계약과 무관하다. 신규 자원은 `regions` 조회 테이블 1개뿐이다.
> 이 절은 **증분**이다. §1~§14의 기존 설계·08 계약을 바꾸지 않고 그 위에 얹는다.

### 15.0 08 정본 불가침 확인 (먼저 읽을 것)

M8~M10은 `08-interface-contract.md`가 확정한 **compare 34필드·태그(`tag_vector`/`scoring_weights`)·`review_trust` 계약 표면 밖**에 있다. 아래를 **명시적으로 보장**한다.

| 08 계약 요소 | M8~M10의 영향 | 판정 |
|---|---|---|
| `review_trust.count` / `review_trust.companion_matched_count` (08 §2.2 #19·#20) | M8 방문 인증 값을 **여기에 주입하지 않는다.** M8은 `reviews` 테이블·스코어링과 무관한 독립 배지 | **불가침 유지** |
| `tag_vector` / `scoring_weights` (08 §1) | M8~M10은 태그·가중치를 산출·소비하지 않는다 | **불가침 유지** |
| compare 응답 34필드 (08 §2.2) | M8·M9는 compare 응답에 **필드를 추가하지 않는다.** M10은 기존 `path`·`path_source`(#22·#23) 값을 **채우는 방식만 개선**(스키마 변경 없음) | **불가침 유지** |
| `build_verdict` 템플릿 안전 규칙 (08 §5) | M8~M10 데이터 유래 문자열(오디오 제목·장소명 등)을 headline에 삽입하지 않는다 | **불가침 유지** |

> **J6(N1 잔재) 재발 방지**: QA가 힘들게 끊어놓은 "인증 → review_trust" 의존을 다시 만들지 않는다. M8은 **`visit_verifications`라는 별도 테이블 + 독립 배지 API**로만 존재하며, compare/스코어링/`reviews`와 **조인되지 않는다**. 이 원칙 위반은 곧 J6 회귀이므로 QA 재검수 최우선 항목이다(§15.7).

---

### 15.1 M8 — 웹 Geo-location + 사진 방문 인증

#### 15.1.1 설계 원칙 (R10 제약의 흡수)

| # | 원칙 | 설계 반영 |
|---|---|---|
| V1 | **보조 신호일 뿐 절대 지표가 아니다** | 결과는 `verified` 배지 표시에만 쓴다. 신뢰도·랭킹·스코어링 입력이 아니다(§15.0). 화면에도 "약한 현장 신호"로 표기 |
| V2 | **금전 보상 미결합** | 인증에 할인·포인트 등 **금전 유인을 붙이지 않는다.** 비금전 배지만 부여한다(상세는 §15.6 검증). 금전 유인이 없으면 위조할 동기 자체가 최소화된다 |
| V3 | **EXIF 불신 — 서버 수신 좌표만 신뢰** | 위치 검증은 **브라우저 Geolocation이 보낸 좌표를 서버가 받은 시점**의 값으로만 한다(§3/§3.1 좌표 처리 패턴 재사용). **사진의 EXIF 메타데이터는 파싱·신뢰하지 않는다.** 사진은 "시각적 증거"일 뿐 위치 소스가 아니다 |
| V4 | **개인정보 최소수집** | 제출 좌표는 요청 body로만 받아 **거리 계산 직후 폐기**하고 **원좌표를 저장하지 않는다**(§3 정밀좌표 비저장 정책 승계). DB엔 계산된 거리·결과만 남긴다. 사진 원본은 오브젝트 스토리지에 **단기 TTL**로만 두고 참조만 DB에 둔다(§10.6 `raw_input` 미저장 정신) |

#### 15.1.2 DB 스키마 — `visit_verifications` (신규, 독립 테이블)

```sql
-- =====================================================================
-- 15. 방문 인증 배지 (M8) — 독립 기능. reviews·review_trust·스코어링과 무관.
--     ※ 원좌표(lat/lng) 컬럼을 일부러 만들지 않는다 — §3 비저장 정책 + 최소수집.
--        서버가 거리(distance_m)만 계산해 남기고 제출 좌표는 응답 후 폐기한다.
--     ※ EXIF 컬럼(exif_lat 등)도 만들지 않는다 — EXIF는 신뢰 소스가 아니다(V3).
-- =====================================================================
CREATE TABLE visit_verifications (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID   NOT NULL REFERENCES users(id)  ON DELETE CASCADE,  -- 배지는 식별 주체 필요
    place_id        BIGINT NOT NULL REFERENCES places(id) ON DELETE CASCADE,

    -- 판정 결과 (배지 표시에만 사용)
    status          VARCHAR(16) NOT NULL,      -- 'verified' | 'rejected' | 'expired'
    distance_m      INTEGER NOT NULL,          -- ★ 서버가 계산한 거리만 저장 (원좌표 미저장)
    threshold_m     INTEGER NOT NULL,          -- 판정에 쓴 임계값 (place별/카테고리 기본값)

    -- 사진: 오브젝트 스토리지 참조만. 원본 바이너리는 DB에 넣지 않는다.
    photo_ref       TEXT,                      -- 예: 's3://.../visit/{uuid}.jpg'. 파기 후 NULL
    photo_expires_at TIMESTAMPTZ,              -- 단기 TTL(예: now()+7d). 배치가 만료분 파기

    -- 신뢰 시각 = 서버 수신 시각(V3). 클라이언트 신고 시각은 신뢰하지 않는다.
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_visit_status CHECK (status IN ('verified','rejected','expired'))
);
CREATE INDEX idx_visit_user_place ON visit_verifications (user_id, place_id, submitted_at DESC);
-- 배지 표시용: 특정 사용자·장소의 최신 verified 1건 조회
CREATE INDEX idx_visit_badge ON visit_verifications (user_id, place_id)
    WHERE status = 'verified';
```

> **왜 원좌표를 저장하지 않나**: 식별자(user_id)와 결합된 정밀 좌표는 개인위치정보다(§3.1 S-H2와 동일 논리). 거리 판정은 **수신 시점 1회로 끝나므로** 좌표를 보관할 목적이 없다. 보관하지 않으면 "위치정보를 축적하지 않는다"고 말할 수 있어 R4 리스크가 준다.

#### 15.1.3 API 엔드포인트

| # | 화면 | Method | Path | 인증 | 설명 |
|---|---|---|---|---|---|
| H1 | 스팟/배지 | POST | `/api/v1/visits/verify` | 필수 | **인증 제출.** `multipart/form-data`: 사진 파일 + 좌표(JSON part, body). 서버가 거리 판정 후 배지 반환 |
| H2 | 스팟/배지 | GET | `/api/v1/visits/status?place_id={id}` | 필수 | 특정 장소의 내 인증 상태 조회 |
| H3 | 마이 | GET | `/api/v1/me/visits` | 필수 | 내 방문 인증 배지 목록 (커서 페이지네이션) |

```jsonc
// H1 요청 (multipart/form-data)
//   part "photo": (binary, image/jpeg|png, 최대 8MB — 확인 필요)
//   part "meta" : application/json ↓  ★ 좌표는 body로만 (§3.1 L1). 쿼리스트링 금지
{ "place_id": 12345, "lat": 35.159, "lng": 129.160 }   // 소수점 3자리 반올림 권장(§3.1 L2)

// H1 응답 200
{
  "place_id": 12345,
  "status": "verified",          // verified | rejected
  "distance_m": 84,              // 서버 계산값 (원좌표는 응답에 없음·미저장)
  "threshold_m": 150,
  "badge": { "granted": true, "kind": "visit_checkin", "granted_at": "2026-07-23T14:20:00+09:00" },
  "notice": "현장에서 받은 위치로 확인한 약한 인증입니다. 정확도를 보장하지 않습니다."  // V1 한계 고지
}
```

> **응답 봉투는 08 compare 계약과 무관**하다(H1~H3은 08 §2.2 표에 없는 신규 엔드포인트). `review_trust`·`spot_fit` 등 어떤 08 필드도 건드리지 않는다.

#### 15.1.4 검증 로직 의사코드

```python
DEFAULT_RADIUS_M = 150          # 임계값. place.verify_radius_m 있으면 우선. 전부 가정값(확인 필요)
PHOTO_TTL_DAYS   = 7            # 사진 단기 보관 (개인정보 최소수집)

def verify_visit(user, place_id, submitted_coord, photo) -> dict:
    place = places.get(place_id) or abort(400, "PLACE_NOT_FOUND")

    # (rate limit·dedupe는 §15.1.5에서 이 함수 진입 전에 통과) 
    # 1) 위치 검증: 서버가 '지금 받은' 좌표로만 판정한다 (V3). EXIF는 읽지 않는다.
    d = haversine_m(submitted_coord, place.geom)         # PostGIS ST_Distance로도 가능
    threshold = place.verify_radius_m or DEFAULT_RADIUS_M
    status = "verified" if d <= threshold else "rejected"

    # 2) 사진은 '시각적 증거'로만 단기 보관. 위치 판정에 쓰지 않는다.
    photo_ref = None
    if photo:
        photo_ref = object_store.put(photo, prefix="visit/",
                                     max_bytes=8*1024*1024)   # EXIF 미파싱. 필요 시 저장 전 EXIF strip
    # 3) 원좌표는 저장하지 않는다 — 거리·결과만 남긴다 (V4)
    row = visit_verifications.insert(
        user_id=user.id, place_id=place_id, status=status,
        distance_m=int(d), threshold_m=threshold,
        photo_ref=photo_ref,
        photo_expires_at=now() + timedelta(days=PHOTO_TTL_DAYS),
        submitted_at=now(),                                    # 신뢰 시각 = 서버 수신 시각
    )
    submitted_coord = None                                     # 명시적 폐기 (메모리에서 제거)

    # 4) 배지: verified면 부여. ★ review_trust·스코어링에 반영하지 않는다 (J6 재발 금지)
    return {"place_id": place_id, "status": status, "distance_m": int(d),
            "threshold_m": threshold,
            "badge": {"granted": status == "verified", "kind": "visit_checkin"},
            "notice": WEAK_AUTH_NOTICE}
```

배치 잡 1건 추가: `job_visit_photo_purge` (일 1회) — `photo_expires_at < now()`인 행의 오브젝트 스토리지 원본을 삭제하고 `photo_ref = NULL` 처리(§10.6 파기 규칙과 동일 정신).

#### 15.1.5 rate limiting / 조작 방지 (반복 인증 시도 차단)

기존 §8.2.1의 `SETNX` dedupe·HMAC subject 패턴을 재사용한다.

| 규칙 | 수단 | 값(가정) |
|---|---|---|
| 동일 사용자·동일 스팟 **성공 재인증 잠금** | `SETNX visit:done:{user_hash}:{place_id}` TTL 24h. 존재하면 신규 제출 거절(기존 배지 반환) | 24h |
| 동일 사용자·동일 스팟 **시도 횟수 제한** | `INCR visit:try:{user_hash}:{place_id}:{yyyymmdd}` — 일 5회 초과 시 `429` | 일 5회 |
| 전역 사용자 제출 레이트리밋 | 기존 `ratelimit:{scope}:{id}:{win}` 미들웨어 재사용 | 분당 N회 |
| `user_hash` | `HMAC(server_key, user_id)` — 원 식별자를 카운터 키에 노출하지 않음(§8.2.1과 동일) | — |

#### 15.1.6 ★ 한계 명시 (과신 금지 — R10이 못박은 핵심)

이 기능은 **조작을 막지 못한다.** 설계가 이를 숨기지 않는다.

- **브라우저 Geolocation은 스푸핑 가능**하다. 개발자도구·가상 위치 앱으로 임의 좌표를 보낼 수 있고, 웹에는 네이티브 앱의 무결성 검증(Play Integrity/App Attest)에 해당하는 수단이 없다.
- **서버 수신 좌표도 결국 클라이언트 신고값**이다. 서버가 "받은 시점"을 신뢰한다는 것은 시각의 신뢰일 뿐, 좌표 자체의 진위를 보장하지 않는다.
- **사진도 진위를 증명하지 못한다.** 우리는 EXIF 위치·시각을 신뢰하지 않으므로(V3), 사진이 "그 시각 그 장소에서 찍혔음"을 증명하지 못한다. 사전 촬영·재사용을 막지 못한다.
- **결론**: 그래서 **보조 신호 + 비금전 배지**로만 설계했다(V1·V2). 절대 지표로 승격하거나 금전 유인을 붙이면 위조 유인이 생겨 즉시 무너진다. 강화가 필요하면 §11.3 N1 "향후 대안"(상점 QR, 서버측 IP-지오 교차검증)을 별도 스코프로 검토한다.

---

### 15.2 M9 — 오디오 가이드 API 연동

#### 15.2.1 데이터셋 (§4 검증표 D13 갱신 반영)

'관광지 오디오 가이드(오디)'를 §4 표 **D13에 `확인필요(M9 승격)`으로 등재**했다. **실재·필드 스펙·URL 형태 모두 미검증**이며 추측으로 채우지 않는다(§15.5 Q-D13). 특히 스트리밍 URL이 상시 공개 URL인지, 서명·만료 URL인지가 캐시 TTL을 좌우한다.

#### 15.2.2 API 엔드포인트

| # | 화면 | Method | Path | 인증 | 설명 |
|---|---|---|---|---|---|
| I1 | 스팟 상세 | GET | `/api/v1/places/{place_id}/audio-guides` | 공개 | 스팟별 오디오 가이드 목록 + 스트리밍 URL |

```jsonc
// I1 응답 200
{
  "place_id": 12345,
  "guides": [
    { "id": "audio_...", "title": "해운대 이야기 1부", "lang": "ko",
      "duration_sec": 180, "stream_url": "https://.../a.mp3", "url_expires_at": null }
  ],
  "data_freshness": { "source": "관광지 오디오 가이드(오디)", "cached_at": "..." }
}
```

> 오디오 **바이트는 서버가 프록시하지 않는다.** 메타데이터 + 원천 스트리밍 URL만 전달하고 재생은 클라이언트가 원천 URL로 직접 한다(대역폭·저작권 재배포 리스크 회피). 원천 URL의 재배포 허용 여부는 확인 필요(§15.5 Q-D13).

#### 15.2.3 캐싱 전략 (Redis, 기존 §9 패턴)

| 키 패턴 | 내용 | TTL | 갱신 |
|---|---|---|---|
| `audio:place:{place_id}` | 스팟별 가이드 목록 직렬화 | **3600s (상시 URL 가정)** / **서명 URL이면 만료 − 여유분**으로 단축 | lazy fill |

- 배치 수집 옵션: 메타데이터를 `job_audio`(주 1회, 확인 필요 주기)로 선적재해 읽기 경로에서 외부 API를 부르지 않게 한다(§P1 준수). 스트리밍 URL이 만료형이면 배치 선적재가 불가하므로 **요청 시 조회 + 짧은 TTL 캐시**로 전환한다 — 이 분기는 Q-D13 확인 후 확정.

---

### 15.3 M10 — Tmap Route API 연동

요강 §5.2가 "Kakao/NAVER Maps SDK **및** Tmap Route API 연동"으로 병기하므로, 지도 표시 SDK(Kakao, R6/§11.2 확정)와 **별개로 경로탐색 엔진**을 붙인다. 대회 요강이 **실연동**을 요구하는지 딥링크로 충분한지 **확실치 않아 두 안을 모두 설계하고 우선순위만 (a)로 둔다**(§15.5 Q-M4).

#### 15.3.1 안 (a) — Tmap Route API 직접 호출 (**우선순위 1**)

Tmap 경로탐색을 호출해 **경로 좌표열(polyline)과 거리·소요시간을 받아온다.** 이는 §7.6의 `snapped` 대안(지점 목록만 있을 때 도로 스냅)의 실체이며, **D4(두루누비) 좌표열 미제공 시의 급소(Q-D5)를 메우는 경로**이기도 하다.

| # | Method | Path | 인증 | 설명 |
|---|---|---|---|---|
| J1 | POST | `/api/v1/routes/directions` | 선택 | 출발/도착/경유 좌표 + 이동수단 → 경로 좌표열·거리·시간 |

```jsonc
// J1 요청 (좌표는 body — §3.1 L1)
{ "origin": {"lat":35.16,"lng":129.16}, "destination": {"lat":35.17,"lng":129.13},
  "waypoints": [], "mode": "pedestrian" }   // mode: pedestrian | car (Tmap 지원 범위 확인 필요)

// J1 응답 200  ★ 기존 스키마(08 #22·#23)와 동형 — path_geojson·path_source만 채운다
{ "path_geojson": { "type":"LineString", "coordinates": [[129.16,35.16], ...] },
  "path_source": "snapped",          // Tmap 유래 = snapped (public/straight와 동일 신호 체계)
  "total_distance_m": 2140, "est_duration_min": 28,
  "provider": "tmap", "data_freshness": { "cached_at": "..." } }
```

- **읽기 경로 외부 호출 최소화(§P1)**: 두 방식 병행. ① **배치 선스냅** — `job_route_snap`(주 1회)이 좌표열 없는 `routes`를 Tmap으로 스냅해 `routes.path`(`path_source='snapped'`)에 적재. compare/지도 읽기는 DB만 읽는다. ② **애드혹 요청**(J1) — 사용자 지정 임의 경로는 요청 시 호출하되 **`route:dir:{hash(origin,dest,mode)}` 캐시(TTL 1h)** + 실패 시 폴백(안 b 또는 `straight` 직선).

**외부 Tmap 엔드포인트 실호출 검증됨 (2026-07-24)** — J1 내부에서 실제로 호출할 SK Open API 주소가 실호출로 확정됐다:
- 자동차 경로: `POST https://apis.openapi.sk.com/tmap/routes?version=1` (⚠️ 일부 문서에 `/tmap/tmap/routes`로 잘못 표기된 경우가 있음 — **실제로는 `tmap`이 한 번만 들어간다.** 잘못된 경로로 호출하면 `403 MISSING_AUTHENTICATION_TOKEN`이 뜨는데 이건 인증 실패가 아니라 게이트웨이가 경로를 못 찾는다는 뜻이라 헷갈리기 쉽다)
- 헤더: `Accept: application/json`, `Content-Type: application/json`, `appKey: {발급받은 키}` (쿼리스트링이 아니라 헤더로 전달 — data.go.kr의 `serviceKey` 쿼리스트링 방식과 다르다)
- 요청 바디: `startX/startY/endX/endY`(경도/위도), `reqCoordType`/`resCoordType: "WGS84GEO"`, `searchOption`, `sort`
- 실제 테스트(서울시청→강남역)로 200 응답과 정상 경로 데이터(좌표열·거리·시간) 확인됨. Q-M5(과금)는 §11.2.1에서 이미 해소, **Q-M6(좌표계)도 이걸로 해소** — WGS84 경위도를 그대로 받는다.
- **좌표는 3자리 반올림 후 캐시 키에 사용**(§3.1 L2, 개인위치 잔류 최소화).
- **좌표계**: Tmap 입출력 좌표계(WGS84 여부) 미확인 — 변환 필요할 수 있음(§15.5 Q-M6).

`MapProvider` 인터페이스(§11.2)와 별도로 **`RouteProvider` 인터페이스**(`get_directions(origin, dest, waypoints, mode)`)를 두어 Tmap 교체·폴백 비용을 낮춘다.

#### 15.3.2 안 (b) — 딥링크 안내 (폴백/대체)

기존 §11.3 N4 방식. Tmap 앱을 목적지 파라미터로 여는 딥링크만 제공(서버 개발 불필요). **안 (a)의 API 키 미발급·쿼터 초과·장애 시 자동 폴백**으로도 쓴다. 요강이 실연동을 필수로 보지 않는 것으로 확인되면 이 안으로 축소 가능.

#### 15.3.3 API 키·과금 요건

R6/Q-M3의 연장선이다. **Tmap Route API 키 발급 요건·일일 쿼터·비상업(공모전) 이용 조건·과금이 전부 확인 필요**(§15.5 Q-M5). 확인 전까지 안 (a)를 확정하지 않으며 안 (b)를 안전망으로 유지한다.

---

### 15.4 M11 / M12 — 정정 등재 (신규 설계 아님)

PRD §3.2 지적대로 이 둘은 **이미 본 문서에 설계돼 있다.** 새로 설계하지 않고 소재만 등재한다.

| M | 기능 | 이미 설계된 위치 (본 문서) |
|---|---|---|
| **M11** 두루누비(걷기·자전거 코스) | 데이터셋: **§4 D4** / 저장: **§5.2 `routes`**(`path`·`path_source`·`route_segments`) / 배치: **§7.2 `job_courses`**(주 1회) / 좌표열 미제공 대안: **§7.6** / 확인필요: **§12.1 Q-D5**(polyline 제공 여부, P0) |
| **M12** 전국문화축제/공연행사 | 데이터셋: **§4 D9(·D10)** / 저장: **§5.2 `festivals`** DDL / 배치: **§7.2 `job_festivals`**(일 1회)·`job_geocode`(좌표 미제공 시) / 홈 배너 API: **§6.1 B3 `GET /festivals`** / 로드밸런싱 가점: **§7.5 `event_boost`** / 확인필요: **§12.1 Q-D8**(좌표 제공 여부) |

> 결론: **M11·M12는 증분 설계 불필요.** 기존 설계가 그대로 MVP 요건을 충족한다. 두 항목이 M-테이블에 누락됐던 것은 표기 누락이었을 뿐 설계 누락이 아니었다.

---

### 15.5 확인 필요 신규 항목 (M8~M10) — §12 집계 증분

> §12 집계표의 연장. 기존 Q-ID 번호는 건드리지 않고 이어붙인다.

| ID | 확인 항목 | 우선 | 막히는 것 | 담당 게이트 |
|---|---|---|---|---|
| **Q-D13** | 오디오 가이드(오디) 데이터셋 실재·필드 스펙, **스트리밍 URL이 상시 URL인지 서명·만료 URL인지**, 재배포 허용 여부 | P1 | M9 캐싱 전략·배치 가능 여부(§15.2) | 데이터/법률 |
| **Q-M4** | 요강이 Tmap을 **실연동 필수**로 요구하는지, 딥링크로 충족되는지 | P1 | M10 안 (a)/(b) 확정(§15.3) | 대표/planning |
| **Q-M5** | Tmap Route API **키 발급 요건·일일 쿼터·비상업(공모전) 이용 조건·과금** | **P0** | M10 안 (a) 성립(§15.3.3) | 대표(키 발급)/법률 |
| **Q-M6** | Tmap 입출력 **좌표계**(WGS84 여부), 지원 이동수단(도보/차량) 범위 | P1 | 좌표 변환 로직·mode 매핑(§15.3.1) | 데이터 |
| **Q-M7** | M8 인증 **임계값(150m)·사진 최대 크기(8MB)·사진 TTL(7일)** 적정값 | P2 | 판정 정확도·보관정책(§15.1) | 운영/법률 |
| **Q-L5** | M8 브라우저 Geolocation 좌표(요청 body·비저장·거리만 저장)가 **위치정보법 수집·신고 대상인지** | **P0** | M8 설계 확정(§15.1.2) | **legal 4차 게이트** |
| **Q-L6** | M8 **방문 사진의 초상권·타인 얼굴 포함 처리**, 오브젝트 스토리지 보관·파기(7일 TTL)의 개인정보 적정성 | **P0** | M8 사진 보관정책 확정 | **legal 4차 게이트** |
| **Q-L7** | 인증 **배지가 "인증"이라는 표현을 쓸 때 소비자 오인 소지**(약한 신호를 강한 것으로 표시) | P1 | 배지 문구·고지(§15.1.3 notice) | legal/QA |

> **가정값 표기(사실 아님)**: M8 임계 150m·사진 8MB·TTL 7일, M9 캐시 3600s, M10 애드혹 캐시 1h·좌표 3자리 반올림 — **전부 실측·확인 전 초기 가정값**이다(§12.5 연장).

---

### 15.6 ★ `쿠폰` 미결합 검증 (R10 제약 2 — grep 직접 확인 결과)

R10은 "M8을 쿠폰(N2)과 절대 결합하지 말라 — 금전 유인이 위조 유인을 만든다"고 못박았다. 이를 **grep으로 실측 검증**했다.

- **검증 명령**: 본 문서에서 `쿠폰` 문자열 위치 전수 조회.
- **결과** (전수 4개소): **서두 읽기가이드(N2 후순위 명시)·§11.3의 N1 위조유인 근거·§11.3 N2 처리행·본 §15.6 검증 서술**에만 존재하며, **M8 설계 본문(§15.1.1~§15.1.6)에는 0건**이다.
- **설계 반영**: M8 인증에는 어떤 할인·포인트·쿠폰 발급 로직도 **연결하지 않았다**(V2). `visit_verifications` 스키마·H1~H3 API·검증 의사코드 어디에도 금전 보상 필드·엔드포인트가 없다. 배지는 **비금전**이다.
- **결론**: R10 제약 2 충족. N2(쿠폰)가 향후 도입되더라도 M8과 결합해서는 안 된다는 것을 스키마·API 분리로 구조적으로 보장한다.

---

### 15.7 §15 핸드오프 노트 (증분)

```
[다음 부서가 알아야 할 것 — M8~M12 증분]
1. M8은 review_trust/스코어링과 무관한 독립 배지다(visit_verifications 별도 테이블). J6(인증→신뢰도)
   의존을 다시 만들지 않았다 — QA는 compare/스코어링/reviews에 M8 값이 새어드는지 최우선 재검수.
2. legal-counsel 재검토 필수(R10): Q-L5(브라우저 Geolocation 거리만 저장의 위치정보법 해당 여부),
   Q-L6(방문 사진 초상권·7일 TTL 보관 적정성), Q-L7(약한 인증을 "인증"으로 표기 시 오인). M9 원천
   오디오 URL 재배포 허용(Q-D13)도 이용약관 확인 대상.
3. security-engineer 재검토 필수: M8은 스푸핑 불가 기능이 아니다(§15.1.6) — 사진 업로드(용량·타입·
   EXIF strip·오브젝트스토리지 접근권한), rate-limit/dedupe(§15.1.5), 사진 파기 배치가 점검 대상.
   Tmap 키(M10)는 §10.4 시크릿 하드코딩 금지·ENV 규칙 적용 대상.
```

---

### 15.8 M14 — 날씨 연동 경로 보정 (rerank)

> **한 줄 요약**: 강수확률이 높으면 **실외형 코스의 노출 순위를 낮추고 실내형 대안(카페·공방·전시)을 우선 노출**한다. 단 이것은 **AI 5축 스코어링을 건드리지 않고**, M6(로드밸런싱)과 똑같이 **점수 산출 이후 backend 선택 레이어에서 단 1회 적용하는 재정렬(rerank) 레이어**다. M6 **다음 단계**(§7.1.2 [3.5])에 끼운다.

#### 15.8.0 08 정본 불가침 확인 (먼저 읽을 것) — 타협 불가 4제약

M14는 `08-interface-contract.md`가 확정한 계약을 **한 글자도 바꾸지 않는다.** 대표가 못박은 4제약을 아래처럼 구조로 보장한다.

| 제약 (지시서) | M14의 처리 | 판정 |
|---|---|---|
| **① AI 5축 스코어링(`scoring_weights`) 불가침 — 날씨는 6번째 축 금지** | 날씨는 `score_routes()`에 **입력으로 들어가지 않는다.** `scoring_weights`(5키·합1.0)에 `weather` 키를 추가하지 않는다. rerank는 점수가 **다 나온 뒤** 별도 함수에서 순위만 조정한다 | **불가침 유지** |
| **② rerank 레이어로 설계 (M6 패턴)** | §7.1.2 파이프라인의 **선택 레이어 [3] 다음 [3.5]**에 `apply_weather_rerank()`를 둔다. M6과 동일하게 **선택 레이어 단 1회 적용**, `score_routes()` 재호출 없음, `spot_fit` 재사용(§15.8.5) | **패턴 준수** |
| **③ compare 34필드 불가침 — additive-only** | 기존 34필드의 **이름·타입·의미를 하나도 바꾸지 않는다.** 신규 필드(`*.weather`, `hidden.weather_rerank`)만 추가하며 전부 "**M14 신규 추가**"로 표시(§15.8.8) | **불가침 유지** |
| **④ D18 스키마 미검증 — 필드명 "가정"** | D18은 키만 발급, 실호출 안 함. SKY/PTY 코드·POP 필드명·발표주기는 **전부 "가정"**으로 표기(§15.8.6·§15.8.9) | **가정 표기 준수** |

> **왜 6번째 축이 아니라 rerank인가**: 5축 스코어링은 "이 코스가 이 사용자에게 얼마나 맞는가"라는 **취향·혼잡·거리의 함수**다. 날씨는 사용자·코스의 고정 속성이 아니라 **조회 시점의 외생 변수**이고 몇 시간 뒤면 바뀐다. 이를 스코어링 공식에 섞으면 (a) 어렵게 확정한 5축 계약(08 §1·§2)을 다시 흔들고, (b) 같은 코스가 날씨에 따라 스코어가 출렁여 `score_breakdown` 재현성이 깨진다. rerank로 분리하면 스코어는 안정적이고 날씨는 **표시 가능한 사유와 함께** 순위에만 반영된다 — M6가 혼잡을 다룬 방식과 정확히 같다(08 §3.2·§3.7의 "페널티 1회 적용" 불변식).

#### 15.8.1 파이프라인 삽입 위치 (§7.1.2 확장 — [3.5] 신설)

```
[1] backend : 후보 생성(공간쿼리) + 혼잡도 주입 + candidates dict 구성
      ↓ (단방향)
[2] AI      : 하드필터 → score_routes() → list[RouteScore]   ★ 날씨 입력 없음·페널티 없음(순수 스코어링)
      ↓ (단방향)
[3] backend : select_route_with_balancing(scored) → (choice, acceptable_pool)   ★ M6 혼잡 재정렬 (LB 1회 적용)
      ↓ (단방향)
[3.5] backend : apply_weather_rerank(choice, acceptable_pool, weather, cand) → choice'   ★ M14 날씨 재정렬 (1회 적용)
      ↓
[4] backend : build_verdict() 템플릿 조립 (§7.7)
```

- **[3.5]는 [2]의 스코어링을 절대 재호출하지 않는다.** `spot_fit`은 `RouteScore.spot_fit`을 그대로 재사용한다(M6와 동일 불변식 — 08 §3.2·§3.7).
- **M6가 통과시킨 `acceptable_pool`(비-RED·`fit≥0.4`) 안에서만 재정렬한다.** → 날씨 때문에 **혼잡한 코스로 되돌리는 일이 없다**(M6 로드밸런싱 불변식 보존). 이것이 두 rerank의 결합 원칙이다: **혼잡 필터가 먼저, 날씨는 그 결과 안에서만.**
- [3]의 반환을 `(choice, acceptable_pool)`로 확장한다. `acceptable_pool`은 M6가 **이미 계산해 둔** 평가 리스트(§8.3 `evaluated`의 비-RED·`fit≥0.4` 부분)를 그대로 노출할 뿐 **재계산이 아니다.** `lb_state()`를 다시 부르지 않는다.

#### 15.8.2 실외/실내 판별 — `course_tag_vector` registry 슬라이스에서 산출

지시서대로 **AI가 이미 확정한 태그 축(`mood`/`spot_pref`)에서만** 판별한다. 코스의 `course_tag_vector`(36차원, §3.3 candidates 필수 키, registry 순서)를 쓰며, **코드는 인덱스 상수를 갖지 않고 `tag_axis_registry`에서 조회**한다(§5.2.1 슬라이스 규약과 동일 원칙).

| 신호 | registry 축·값 (index) | 가중 |
|---|---|---|
| 실외 강노출 | `spot_pref`: `nature_view`(24), `walking_trail`(27) | 1.0 (비를 그대로 맞는 코스) |
| 실외 약노출 | `spot_pref`: `photo_spot`(25) | 0.5 (야외 비중 높으나 실내 혼재 가능) |
| 실내 상쇄/대안 신호 | `spot_pref`: `local_cafe`(21), `craft_shop`(22), `traditional_market`(23) | −0.5 (실내 비중이 있으면 노출도 하향) |
| 보조 힌트(자연·정적) | `mood`: `calm`(14), `healing`(16), `contemplative`(18) | 실외 신호가 **이미 있을 때만** ×1.15 증폭 (단독으로는 실외 판정 안 함) |

> **왜 mood 단독으로 실외 판정하지 않나**: `mood`(한적함/힐링/사색)는 실내 카페에서도 성립한다. 실외 여부의 **1차 근거는 `spot_pref`**이며 mood는 이미 실외인 코스의 노출도를 미세 조정하는 보조 신호로만 쓴다. 이렇게 해야 실내 코스를 우천에 잘못 강등하지 않는다.

#### 15.8.3 재정렬 규칙 + 임계치 (전부 가정값 — 근거 명시)

강수확률(POP, 0~100%)을 **3구간**으로 나눈다. **M6의 GREEN/AMBER/RED 3구간을 의도적으로 그대로 미러링**해 코드베이스 패턴 일관성을 유지한다.

| 구간 | POP 임계 (가정값) | 동작 | M6 대응 |
|---|---|---|---|
| `clear` | POP < **30** | 재정렬 없음. 날씨 배지만 표시 | GREEN |
| `soft` | **30** ≤ POP < **60** | **순위 변경 안 함.** "우산 챙기세요" 수준의 **안내만** 표시(과잉 개입 방지) | AMBER(소프트) |
| `advise_indoor` | POP ≥ **60** | 현재 선택이 **실외 강노출**이면 `acceptable_pool` 내 **더 실내형인 대안으로 스왑 시도** + 실내 대안 카드 노출 | RED(대안 전환) |

**임계치 근거 (가정값이며 보정 루프 대상 — E5와 동일 정신)**:
- POP는 기상청 정의상 "예보 구간에 0.1mm 이상 강수가 있을 확률"이다.
- **60%**: 일반적으로 우산 지참을 권하는 실무 경계로 통용된다(강수 가능성 "높음"). 실외 코스를 실내로 유도할 만한 확신 구간.
- **30%**: 그 미만은 "가능성 있음"에 그쳐 실외 일정을 바꿀 근거로 약하다 → 무개입.
- **이 30/60은 실측·A/B 검증 전 초기 가정값**이다. D18 실호출로 POP 분포를 본 뒤 보정한다(§15.8.9 Q-W1). 근거 없는 확정값으로 서술하지 않는다.
- **스왑 발동 추가 조건**: 대상 코스의 `outdoor_exposure ≥ OUTDOOR_MIN`(가정 0.5) 일 때만. 이미 실내형이면 우천이어도 재정렬 불필요.

#### 15.8.4 실내 대안 후보 소싱 (M5 로컬 스팟 + D17 공방 연계)

우천 시 노출할 실내 대안은 **새 데이터를 만들지 않고 기존 자산을 재사용**한다.

- **1순위 — 코스 대체**: `acceptable_pool` 안에서 `outdoor_exposure`가 더 낮은 hidden 코스로 스왑(§15.8.5). M6가 이미 혼잡·취향을 통과시킨 후보라 안전하다.
- **2순위 — 실내 스팟 카드**: hidden 코스 경로 주변 **500m 실내 업종**을 §5.3 (1)번 쿼리(`ST_DWithin(m.geom, r.path, 500)`)로 뽑아 `industry_mid`가 카페/공방/전시/실내관 계열인 것만 필터. **D17(국가유산청 공방정보)** 를 `places.category='craft'`로 병합해 우천 대안 후보에 포함한다(§4 D17, §15.4 연계).
- 이 2순위 결과가 compare 응답의 `weather_rerank.indoor_alternatives`(§15.8.8)로 직렬화된다.

#### 15.8.5 rerank 의사코드 — 선택 레이어 단일 패스 (`score_routes` 미재호출)

```python
# 실외 노출 판별 — registry에서 인덱스 조회(코드 상수 금지). course_tag_vector(36차원)에서만 산출.
OUTDOOR_STRONG = registry_idx("spot_pref", ["nature_view", "walking_trail"])   # {24, 27}
OUTDOOR_SOFT   = registry_idx("spot_pref", ["photo_spot"])                       # {25}
INDOOR_SIGNAL  = registry_idx("spot_pref", ["local_cafe","craft_shop","traditional_market"])  # {21,22,23}
MOOD_HINT      = registry_idx("mood",      ["calm","healing","contemplative"])   # {14,16,18}

# 임계·계수 — 전부 가정값(§15.8.3 근거). KMA 강수확률(POP) 0~100.
POP_SOFT, POP_ADVISE = 30, 60
OUTDOOR_MIN = 0.5

def outdoor_exposure(v: list[float]) -> float:
    """0~1. 코스가 '비를 맞는' 정도. spot_pref(1차)+mood(보조 증폭)에서만 산출 — 스코어링 축 아님."""
    strong = sum(v[i] for i in OUTDOOR_STRONG)
    soft   = sum(v[i] for i in OUTDOOR_SOFT) * 0.5
    indoor = sum(v[i] for i in INDOOR_SIGNAL) * 0.5
    base   = strong + soft - indoor
    if base > 0 and any(v[i] for i in MOOD_HINT):     # mood는 이미 실외일 때만 증폭
        base *= 1.15
    return max(0.0, min(base / 2.0, 1.0))             # 분모 2 = strong 2개 만점 가정

def weather_band(pop: int) -> str:
    if pop >= POP_ADVISE: return "advise_indoor"      # M6 RED 대응
    if pop >= POP_SOFT:   return "soft"               # M6 AMBER 대응
    return "clear"                                     # M6 GREEN 대응

def apply_weather_rerank(choice, acceptable_pool, weather, cand):
    """[3.5] M6 다음 단계. 선택 레이어 단일 패스.
       ★ score_routes()·profile_fit()를 재호출하지 않는다. spot_fit·M6 선택 결과를 재사용.
       ★ acceptable_pool(M6가 통과시킨 비-RED·fit≥0.4) 밖으로 나가지 않는다 → 혼잡 코스로 안 되돌림."""
    w = weather.get(choice.route_id)                   # {condition, precip_probability, ...} | None
    if w is None or w.get("precip_probability") is None:
        return annotate(choice, band="unknown", applied=False)   # 날씨 없음 → 정직하게 무개입
    pop  = int(w["precip_probability"])
    band = weather_band(pop)
    if band != "advise_indoor":                        # clear/soft는 순위 변경 없음(배지·안내만)
        return annotate(choice, band, applied=False, pop=pop)

    exposure = outdoor_exposure(cand[choice.route_id]["course_tag_vector"])
    if exposure < OUTDOOR_MIN:                          # 이미 실내형 → 재정렬 불필요
        return annotate(choice, band, applied=False, pop=pop)

    # ★ M6가 통과시킨 pool 안에서 '더 실내형' 대안만 후보로 (혼잡 재유입 없음)
    indoor_pool = [s for s in acceptable_pool
                   if s["route_id"] != choice.route_id
                   and outdoor_exposure(cand[s["route_id"]]["course_tag_vector"]) < exposure]
    if not indoor_pool:                                 # 실내 코스 대안 없음 → 스왑 안 하고 고지만
        return annotate(choice, band, applied=False, pop=pop, no_indoor_alt=True)

    # 실내 성향(낮은 exposure) + 취향적합(spot_fit) 가중 확률 추출 — M6 weighted_pick와 동형, 가중만 교체
    picked = weather_weighted_pick(indoor_pool, cand)   # weight = spot_fit × (1 - exposure)
    return annotate(BalancedChoice(picked, applied=True), band, applied=True, pop=pop,
                    original_pick_route_id=choice.route_id)
```

- `annotate()`는 순위를 바꾸지 않을 때도 `weather_rerank` 응답 블록(§15.8.8)을 채운다 — 화면이 "왜 이 순위인지"를 항상 설명할 수 있게(P3 원칙과 동일).
- **read-then-decide 비원자성**은 M14에 무관하다 — rerank는 카운터를 증가시키지 않는 순수 함수다(부작용 없음).

#### 15.8.6 데이터셋 D18 + DB 스키마 (`weather_snapshots`, 신규)

혼잡도(`congestion_snapshots`)와 동일한 **원문 보관(P2)·출처/신선도 동반(P3)** 패턴을 그대로 따른다. **필드명은 전부 D18 미검증 가정**이다.

```sql
-- =====================================================================
-- 16. 날씨 스냅샷 (M14) — congestion_snapshots와 동일 패턴. rerank 입력.
--     ※ 필드명은 D18(기상청) 실호출 전까지 전부 "가정"(§15.8.9 Q-D18).
--     ※ 개인정보 없음(공개 기상 데이터). 좌표·식별자 결합 이슈 무관.
-- =====================================================================
CREATE TABLE weather_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    -- 대상은 코스/장소/지역 중 하나 (D18 해상도 미확인이므로 셋 다 수용)
    route_id        BIGINT REFERENCES routes(id) ON DELETE CASCADE,
    place_id        BIGINT REFERENCES places(id) ON DELETE CASCADE,
    region_code     VARCHAR(10),

    base_at         TIMESTAMPTZ NOT NULL,        -- 기상청 발표 기준시각 (가정: baseDate+baseTime)
    forecast_at     TIMESTAMPTZ NOT NULL,        -- 예보 대상 시각

    condition       VARCHAR(12) NOT NULL,        -- clear|cloudy|rain|snow|shower (SKY/PTY 매핑, 가정)
    precip_probability SMALLINT CHECK (precip_probability BETWEEN 0 AND 100),  -- POP, 가정 필드
    temp_c          REAL,                        -- 선택. 화면 보조 표시용

    -- P3: 출처·신선도. 기상청 실측/예보 = tier 'A'. 데이터 없으면 행을 만들지 않는다
    tier            CHAR(1) NOT NULL DEFAULT 'A',
    source_dataset  VARCHAR(8) NOT NULL DEFAULT 'D18',
    raw             JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_weather_target CHECK (route_id IS NOT NULL OR place_id IS NOT NULL OR region_code IS NOT NULL)
);
-- 코스별 최신 예보 조회 (rerank·화면 배지가 이 인덱스를 탄다)
CREATE INDEX idx_weather_route  ON weather_snapshots (route_id, forecast_at DESC);
CREATE INDEX idx_weather_region ON weather_snapshots (region_code, forecast_at DESC);
-- 동일 대상·동일 예보시각 중복 적재 방지 (배치 재시도 멱등성)
CREATE UNIQUE INDEX uq_weather_point ON weather_snapshots
    (COALESCE(route_id,-1), COALESCE(place_id,-1), COALESCE(region_code,''), forecast_at);
```

- **SKY/PTY → `condition` 매핑(가정)**: 기상청 단기예보는 하늘상태(SKY: 맑음/구름많음/흐림)와 강수형태(PTY: 없음/비/비눈/눈/소나기)를 별도 코드로 준다고 알려져 있으나 **D18이 같은 코드 체계인지 미검증**이다. 실호출 후 매핑표를 확정한다(§15.8.9 Q-D18).
- **rerank가 실제로 쓰는 값은 `precip_probability`(POP) 하나**다. `condition`·`temp_c`는 화면 표시 보조.

배치 잡 1건 추가 — §7.2 표 연장:

| Job | 대상 | 주기(설계 제안) | 멱등성 키 | 실패 시 |
|---|---|---|---|---|
| `job_weather` | D18 | **3시간** (기상청 발표주기 가정) | `(route_id, forecast_at)` UPSERT | 이전 스냅샷 유지(staleness 표기) + Tier 강등 없이 "날씨 데이터 없음"으로 rerank 무개입 |

읽기 경로는 §P1대로 **외부 API를 직접 부르지 않는다** — `job_weather`가 DB에 선적재하고 Redis를 예열한다.

#### 15.8.7 API 엔드포인트 + 캐싱 (Redis, TTL 넉넉히)

| # | 화면 | Method | Path | 인증 | 설명 |
|---|---|---|---|---|---|
| K1 | AI 경로 비교 / 스팟 | GET | `/api/v1/weather/course/{route_id}` | 공개 | 코스 날씨 요약(현재+근접 예보). rerank가 쓰는 것과 동일 데이터 |
| K2 | 홈(선택) | GET | `/api/v1/weather?region_code={code}` | 공개 | 지역 날씨 배지용(선택 기능) |

```jsonc
// K1 응답 200
{
  "route_id": 551,
  "weather": {
    "condition": "rain",              // clear|cloudy|rain|snow|shower (SKY/PTY 매핑, 가정)
    "precip_probability": 70,          // POP 0~100 (가정 필드)
    "temp_c": 22.4,
    "forecast_at": "2026-07-23T15:00:00+09:00",
    "base_at": "2026-07-23T14:00:00+09:00",
    "tier": "A",
    "source": "기상청 관광코스별 상세 날씨(D18)"
  },
  "data_freshness": { "source": "D18", "cached_at": "2026-07-23T14:05:00+09:00" }
}
```

**캐싱 (기존 §9 패턴, TTL 넉넉히 — 날씨는 몇 시간 단위 갱신이면 충분)**

| 키 패턴 | 내용 | TTL | 갱신 |
|---|---|---|---|
| `weather:course:{route_id}` | 코스 날씨 요약 직렬화 | **10800s (3h)** — 기상청 발표주기에 정렬. 최대 6h staleness까지 rerank에 무해하다고 판단 | `job_weather`(3h) 예열 + lazy fill |
| `weather:region:{region_code}` | 지역 날씨(K2용) | **10800s (3h)** | 동일 |

- TTL을 넉넉히(3h) 잡은 근거: rerank의 판단 단위가 POP 30/60 **구간**이라, 몇 % 흔들려도 구간이 잘 안 바뀐다. 분 단위 신선도가 불필요하고, 공공 API 쿼터·부하를 아낀다.
- 캐시 미스 시 DB(`weather_snapshots` 최신 `forecast_at`) 폴백 → 그래도 없으면 **rerank 무개입**(clear로 취급)하고 화면엔 "날씨 정보 없음" 표기. **날씨가 없다고 비교 자체가 실패하지 않는다.**

#### 15.8.8 compare 응답 신규 필드 (★ additive-only — 08 34필드 불가침)

08 §2.2 **34필드는 이름·타입·의미를 하나도 바꾸지 않았다.** 아래는 **전부 "M14 신규 추가"** 이며, 08에 존재하지 않는 새 키다(충돌 없음 확인 §15.8.10).

| 신규 필드 경로 | 타입 | 값 / enum | 산출 주체 | 표시(designer) |
|---|---|---|---|---|
| `hotspot.weather` **(M14 신규)** | object\|null | ↓ 하위 4키. 데이터 없으면 `null` | backend | 코스 카드에 날씨 배지 |
| `hidden.weather` **(M14 신규)** | object\|null | 〃 (양쪽 동일 키 구조) | backend | 〃 |
| `*.weather.condition` **(M14 신규)** | string | `clear\|cloudy\|rain\|snow\|shower` (가정) | backend | 아이콘 |
| `*.weather.precip_probability` **(M14 신규)** | int\|null | POP 0~100 (가정 필드) | backend | `강수 {n}%` |
| `*.weather.forecast_at` **(M14 신규)** | string | ISO8601(+09:00) | backend | 예보 기준시각 |
| `*.weather.tier` **(M14 신규)** | string | `A`(기상청) \| `none`(데이터 없음) | backend | 신선도 배지 |
| `hidden.weather_rerank` **(M14 신규)** | object | ↓ (M6 `hidden.load_balancing`과 형제로 배치) | backend | 실내 대안 배너 |

```jsonc
// hidden.weather_rerank  (★ M14 신규. hidden.load_balancing과 동일 위치·동일 위상)
"weather_rerank": {
  "applied": true,                    // 순위를 실제로 바꿨는지 (advise_indoor + 대안 존재 시 true)
  "band": "advise_indoor",            // clear | soft | advise_indoor | unknown
  "precip_probability": 70,           // POP (가정 필드)
  "threshold_soft": 30,               // 가정값 (§15.8.3)
  "threshold_advise": 60,             // 가정값
  "original_pick_route_id": 550,      // applied=true일 때만: 날씨로 밀려난 실외 코스
  "indoor_reason": "강수확률 70%로 실외 코스보다 실내 중심 코스를 먼저 추천합니다. 실내 대안 3곳을 함께 제안합니다.",
  "indoor_alternatives": [            // §15.8.4 소싱: 경로 500m 실내 업종 + D17 공방
    { "place_id": 8801, "name": "…", "category": "cafe",  "dist_from_path_m": 120 },
    { "place_id": 8842, "name": "…", "category": "craft", "dist_from_path_m": 240 }
  ]
}
```

- **`indoor_reason` 안전 규칙 (08 §5.3 `build_verdict` 규칙 승계 — 필수)**: `indoor_reason` 문자열에는 **수치·개수만** 삽입한다. **코스명·상호명·스팟명 등 외부 데이터 유래 문자열을 넣지 않는다.** 실제 실내 스팟 이름은 `indoor_alternatives[].name`으로 **구조화해 내려보내고 designer가 텍스트 노드로만 렌더**한다(`spot_fit.matched_spots`와 동일 패턴). 이 한 줄로 간접 프롬프트 인젝션·XSS 표면이 0이 된다.
- `applied=false`여도 `band`/`precip_probability`는 채운다 — 화면이 "왜 순위가 그대로인지"를 설명(P3).
- **08의 `data_freshness`(#33·#34)에는 손대지 않는다.** 날씨 신선도는 `*.weather.tier`·`*.weather.forecast_at`이라는 **별도 신규 필드**로 전달한다(혼동·계약 침범 방지).

#### 15.8.9 확인 필요 신규 항목 (M14) — §12·§15.5 집계 증분

| ID | 확인 항목 | 우선 | 막히는 것 | 담당 게이트 |
|---|---|---|---|---|
| **Q-D18** | D18 실재·필드 스펙(코스/장소 식별자 키), **SKY/PTY 코드 체계**, **POP 필드명**, 발표주기(3h 가정 맞는지), 쿼터 | **P0** | `weather_snapshots` 매핑·`job_weather` 확정(§15.8.6) | 데이터(키 발급됨, 실호출 필요) |
| **Q-D18b** | D18의 **코스 식별자가 우리 `routes`와 어떻게 매칭**되는지(코드 대조표 필요 여부). 매칭 안 되면 `place_id`/`region_code` 해상도로 대체 | **P0** | rerank 대상 키(§15.8.6 target) | 데이터 |
| **Q-W1** | POP 임계 **30/60**·`OUTDOOR_MIN` 0.5의 적정값 (실측 POP 분포로 보정) | P2 | rerank 민감도(§15.8.3) | 운영/AI(보정 루프) |
| **Q-W2** | 우천 판단에 POP만으로 충분한지, **강수량(PCP)·`condition`도 반영**할지 | P2 | rerank 입력 확장 여부 | 데이터/기획 |

> **가정값 표기(사실 아님)**: POP 임계 30/60, `OUTDOOR_MIN` 0.5, 발표주기·캐시 TTL 3h, `condition` enum, SKY/PTY 매핑 — **전부 실호출·보정 전 초기 가정값**이다(E5·§12.5 연장).

#### 15.8.10 ★ 08 계약 불변 검증 (grep 직접 확인 결과)

지시서 완료 기준: **`scoring_weights`와 compare 34필드 기존 이름들이 이번 M14 수정에서 값이 바뀌지 않았는지** 실측으로 확인했다.

**검증 방법 (2가지 — 단순 카운트 대조는 함정이 있어 병행)**:
1. **git diff 삭제/변경 라인 검사** — 이것이 결정적 근거다. `git diff`에서 **보호 문자열을 포함한 라인 중 삭제(`-`)·수정된 라인이 0건**임을 확인했다. 즉 기존 **정의·값 라인이 하나도 바뀌지 않았다.** M14의 모든 변경은 **순수 추가(additive-only)**다.
2. **원시 출현 횟수 대조** — 단, 원시 카운트는 **§15.8 자신이 보호 문자열을 참조·서술하면서 자연 증가**한다(예: 본 §15.8.10 검증표가 `scoring_weights`를 여러 번 인용). 따라서 카운트 증가 = "M14가 계약을 바꿨다"가 **아니다.** 증가분은 전량 §15.8의 참조·불가침 서술에서 나온다.

| 보호 문자열 | M14 전 | M14 후 | 증가분 판정 |
|---|---|---|---|
| `scoring_weights` | 22 | 32 | 증가분 전량 §15.8·v1.3노트의 **"weather를 여기에 넣지 않는다"는 불가침 서술**. 정의(§5.2 DDL)·산출 로직 **무수정** |
| `scoring_weights_used`(08 #31) | 4 | 5 | 증가 1 = §15.8.10 인용. compare 필드 **무수정** |
| `spot_fit`(08 #15~18) | 16 | 24 | 증가분 = rerank가 **재사용**한다는 서술. 정의 **무수정** |
| `review_trust`(08 #19~21) | 15 | 16 | 증가 1 = §15.8 인용. M14는 신뢰도와 무관 |
| `companion_matched_count`(08 #20) | 5 | 6 | 증가 1 = 인용. **무수정** |
| `congestion_delta_pct`(08 #27) | 5 | 6 | 증가 1 = 인용. **무수정** |
| `total_distance_m`(08 #12) | 6 | 7 | 증가 1 = 인용. **무수정** |
| `data_freshness`(08 #33·#34) | 13 | 16 | 증가분 = "손대지 않는다"·별도필드 분리 서술. 정의·구조 **무수정** |
| `load_balancing`(08 #25) | 3 | 6 | 증가분 = "weather_rerank를 형제로 둔다"는 위치 서술 |
| `score_breakdown`(08 #32) | 7 | 9 | 증가분 = 인용. **무수정** |
| `path_geojson`/`path_source`(08 #22·#23) | 5 / 11 | 6 / 12 | 각 +1 = 인용. **무수정** |

> **결론**: git diff 검사 결과 **보호 문자열이 있는 기존 라인의 삭제·수정은 0건**이다. `scoring_weights`(5축 스코어링 계약)와 compare 34필드의 **이름·타입·의미·값은 이번 M14 수정으로 하나도 바뀌지 않았다.** 원시 카운트 증가는 전량 §15.8의 참조·불가침 서술에서 발생했다. M14는 오직 **신규 필드 추가(`*.weather`, `hidden.weather_rerank`) + 신규 rerank 레이어([3.5]) + 신규 테이블(`weather_snapshots`)** 뿐이다.

#### 15.8.11 §15.8 핸드오프 노트 (M14 증분)

```
[다음 부서가 알아야 할 것 — M14 날씨 rerank]
1. 날씨는 5축 스코어링(scoring_weights)에 절대 안 들어간다 — score_routes() 다음, M6 선택 레이어
   [3.5]에서만 1회 적용하는 rerank다. AI(02)는 건드릴 것 없음(스코어링 공식 불변). QA는 weather가
   score_routes/scoring_weights/compare 34필드에 새어드는지 최우선 확인 — 08 계약 불변이 완료기준.
2. designer가 그릴 것: (a) 코스 카드의 '날씨 배지'(condition 아이콘 + 강수 {POP}% + tier),
   (b) 우천 시 '실내 대안 추천 배너'(hidden.weather_rerank) — M6 분산안내 배너(J7)와 동일 위치·동형
   컴포넌트로, indoor_reason 문구 + indoor_alternatives 카드 리스트(텍스트 노드 렌더). band 3상태
   (clear=배지만 / soft=우산 안내 / advise_indoor=대안 배너) 중 최소 advise_indoor를 목업에 렌더.
3. legal/data: D18 실호출 전이라 POP·SKY/PTY 필드명은 전부 가정(Q-D18/Q-D18b, P0). 날씨는 공개
   기상데이터라 개인정보 이슈는 낮으나, D18 이용약관상 출처표기 의무는 footer(J8-c)에 함께 반영.
```

---

### 15.9 M15 — 지도 위 혼잡도 히트맵/오버레이 (지도 시각화)

> **한 줄 요약**: 기존 M2(§6.1 B1 전광판)가 "TOP N 리스트"용이었다면, M15는 **지도 뷰포트(bounding box) 안의 스팟만** 골라 **좌표 + 강도(0~100) + 신뢰등급(tier)** 배열로 내려주어 지도에 색상 오버레이로 칠하는 기능이다. **D1(집중률 예측)을 그대로 재사용**하며 — 이미 적재된 `congestion_snapshots` + `places`만 읽는다. **새 데이터셋·새 배치잡·새 tier 체계·새 테이블을 만들지 않는다.** M4(지도)의 프론트/디자인 증분이고 AI 스코어링·08 계약 표면 밖이다.

#### 15.9.0 배경·해석 확정 + 08/개인정보 불가침 확인 (먼저 읽을 것)

대표 요청 "지도에 실시간으로 몰리는 정도를 보고 싶다"에 대해 두 해석 중 **(A)를 채택하고 (B)를 명시적으로 기각**한다(PRD §3.2 M15, 대표 승인).

| 해석 | 내용 | 판정 | 근거 |
|---|---|---|---|
| **(A) 채택** | 기존 M2 **예측 혼잡도(D1)** 를 지도에 색상 오버레이로 시각화 | **설계함(§15.9)** | 이미 있는 통계 예측치의 표현 방식만 바꾼다. 개인정보·신규 수집 없음 |
| **(B) 기각** | 실사용자 위치를 **상시 추적**해 지도에 실시간 표시 | **설계하지 않는다** | 개인위치정보 상시 수집 = 위치정보법·개인정보보호법 재검토 유발, 표본이 작아 통계적으로 무의미. 대표가 비용·무의미함을 근거로 명시 기각 |

> **B는 이 문서 어디에도 설계하지 않는다.** M15가 다루는 "몰리는 정도"는 **개인의 실시간 위치가 아니라 D1이 산출한 관광지/지역 단위 통계 예측치**다. 이 구분이 §15.9.5(개인정보 아님 근거)의 핵심이다.

M15는 `08-interface-contract.md`가 확정한 계약을 **한 글자도 바꾸지 않는다.** 지시서가 못박은 제약을 아래처럼 구조로 보장한다.

| 08 계약 요소 | M15의 영향 | 판정 |
|---|---|---|
| `tag_vector` / `scoring_weights` (08 §1) | M15는 태그·가중치를 **산출·소비하지 않는다.** 온보딩·스코어링과 무관 | **불가침 유지** |
| compare 34필드·5축 스코어링 (08 §2) | M15는 `/routes/compare`를 호출하지도, 그 응답 필드를 만들지도 않는다. **별도 조회 엔드포인트**다 | **불가침 유지** |
| `congestion.tier`(08 §2.2 #9) `A/B/C/none` 매핑 | M15는 이 tier 값을 **그대로 좌표에 붙여 내려줄 뿐** 새 tier를 만들지 않는다(지시 2번) | **재사용, 불변** |
| `build_verdict` 안전 규칙 (08 §5) | M15 응답에 headline·자유문장이 없다. 스팟명은 `name`으로 구조화해 내려보내고 designer가 텍스트 노드로만 렌더 | **해당 없음/원칙 승계** |

#### 15.9.1 엔드포인트 설계 — bounding box 조회 (전국 일괄 전송 금지)

기존 전광판(B1)은 `region_code` + `limit`로 "TOP N 리스트"를 줬다. M15는 **지도에 보이는 영역만** 받아오도록 **뷰포트 bbox 기반**으로 설계한다.

| # | 화면 | Method | Path | 인증 | 설명 |
|---|---|---|---|---|---|
| **B4** | 홈/지도 | GET | `/api/v1/congestion/heatmap` | 공개 | **지도 오버레이용.** 뷰포트 bbox 안의 스팟 좌표 + 강도(0~100) + tier 배열 |

```
GET /api/v1/congestion/heatmap
      ?bbox=129.05,35.10,129.25,35.22      # minLng,minLat,maxLng,maxLat (WGS84)
      &zoom=13                              # 슬리피맵 zoom (LOD 결정)
      &horizon_min=0                        # 0=현재 예측, 60=1h 후 (congestion_snapshots.horizon_min 재사용)
```

- **`bbox`는 "지도 뷰포트(사용자가 보고 있는 지도 영역)"이지 사용자 기기의 위치가 아니다.** 부산을 보려고 팬(pan)해도 사용자가 부산에 있다는 뜻이 아니므로 개인위치정보가 아니다(§15.9.5). 다만 방어적으로 **수신 즉시 그리드로 스냅**해 처리·로깅하므로 로그에도 거친 셀 경계만 남는다(§3.1 로깅 최소화 정신 승계).
- **전국 일괄 전송 방지 2중 장치**: (1) bbox 밖 스팟은 공간 인덱스 단계에서 잘린다. (2) `zoom`으로 **LOD(level of detail)** 를 나눠, 넓게 볼 때는 개별 스팟 수백 개가 아니라 지역 집계점만 준다.

**LOD 규칙 (zoom 임계·셀 크기 전부 가정값 — §15.9.7 Q-HM2)**:

| LOD | zoom 조건(가정) | 데이터 소스 | 좌표 | 목적 |
|---|---|---|---|---|
| `region` | zoom < **11** (시·도/전국 뷰) | `congestion_snapshots` **region_code 타깃** 행(이미 스키마가 수용, §5 DDL `chk_target`) | 지역 대표점(centroid) | 넓은 화면에서 포인트 폭증 방지 |
| `place` | zoom ≥ **11** (구·동 뷰) | `congestion_snapshots` **place_id 타깃** 행 + `places.geom` | 스팟 정밀 좌표 | 개별 스팟 히트포인트 |

- **`region` 집계는 D1이 지역 단위 값을 주는지에 의존**한다 — 안 주면 place 스냅샷을 서버에서 셀 단위로 클러스터링해 대체한다(§15.9.7 Q-HM3). 새 배치가 아니라 **읽기 시점 집계**다.
- **상한 가드**: `MAX_POINTS = 300`(가정값). 초과 시 `place` LOD에서 `popularity_score DESC`로 상위만 반환하고 `truncated:true` + `hint:"zoom_in"`을 준다. 클라가 bbox를 좁히면 자연히 해소된다.

#### 15.9.2 응답 스키마 (예시 JSON)

```jsonc
// GET /api/v1/congestion/heatmap 응답 200 (place LOD)
{
  "level_of_detail": "place",         // "place" | "region"
  "bbox_snapped": [129.05, 35.10, 129.25, 35.25],  // 그리드 스냅된 실제 조회 영역(캐시 키와 일치)
  "cell_grid_deg": 0.05,              // 스냅 그리드 셀 크기(가정값)
  "horizon_min": 0,
  "points": [
    {
      "place_id": 1032,
      "name": "해운대해수욕장",
      "lat": 35.1587, "lng": 129.1604,
      "congestion_index": 87.4,       // ★ 강도. 0~100 (D1 정규화값, congestion_snapshots.congestion_index 그대로)
      "level": "high",                // low | mid | high (08 §2.2 임계 승계: <33 low / <66 mid / ≥66 high, 가정)
      "tier": "B",                    // A | B | C | none (08 §2.2 #9 그대로. 새 tier 안 만듦)
      "observed_at": "2026-07-24T14:00:00+09:00"
    },
    {
      "place_id": 2041,
      "name": "달맞이길 공방거리",
      "lat": 35.1587, "lng": 129.1804,
      "congestion_index": 24.1, "level": "low", "tier": "B",
      "observed_at": "2026-07-24T14:00:00+09:00"
    },
    {
      "place_id": 3120,
      "name": "청사포",
      "lat": 35.1601, "lng": 129.1988,
      "congestion_index": 50.0, "level": null, "tier": "none",  // ★ 데이터 없음 → level 미표시(§5.3.1 T4)
      "observed_at": null
    }
  ],
  "truncated": false,                 // MAX_POINTS 초과로 상위만 반환했는지
  "data_freshness": {                 // §5.3.1·08 §2.2 #33 패턴 그대로
    "tier": "mixed",                  // 응답 내 최악 tier 또는 mixed. item별 tier가 정본(§5.3.1 T2)
    "source": "D1",
    "observed_at": "2026-07-24T14:00:00+09:00",
    "notice": "관광지 집중률 예측(D1) 기반 예측 혼잡도입니다. 실시간 실측이 아닙니다."
  }
}
```

```jsonc
// region LOD 예시 (zoom < 11) — points 원소만 다르다
{
  "level_of_detail": "region",
  "points": [
    { "region_code": "26350", "name": "해운대구", "lat": 35.163, "lng": 129.163,
      "congestion_index": 71.2, "level": "high", "tier": "B",
      "place_count": 14,             // 이 지역 집계에 포함된 스팟 수(참고용)
      "observed_at": "2026-07-24T14:00:00+09:00" }
  ],
  "data_freshness": { "tier": "B", "source": "D1", "observed_at": "...", "notice": "..." }
}
```

> **P3 원칙 승계**: 모든 point는 자기 `tier`를 개별로 갖고(§5.3.1 T2), 응답에는 `data_freshness` 블록을 동봉한다. `tier:"none"`인 point는 `level:null`·`observed_at:null`이며 designer는 색을 칠하지 않고 "데이터 없음" 회색으로 처리한다(§5.3.1 T4). **강도 배열을 "실시간"으로 명명하지 않는다** — R1대로 예측 혼잡도다.

#### 15.9.3 공간 쿼리 (기존 §5.3 재사용 — 새 스키마 없음)

`places.geom`의 GIST 인덱스(`idx_places_geom`)와 `congestion_snapshots`의 최신 스냅샷 LATERAL 조인을 **§5.3-(3) 전광판 쿼리 그대로** 쓴다. 달라지는 것은 `WHERE`의 인기도 필터가 **bbox 교차 조건으로 바뀌는 것뿐**이다.

```sql
-- M15 place LOD — 뷰포트 bbox 안의 스팟 + 최신 예측 혼잡도 (tie-break 필수: §5.3.1 T1)
SELECT p.id, p.name,
       ST_Y(p.geom::geometry) AS lat, ST_X(p.geom::geometry) AS lng,
       c.congestion_index, c.level, c.tier, c.observed_at
FROM   places p
JOIN   LATERAL (
         SELECT * FROM congestion_snapshots cs
         WHERE  cs.place_id = p.id AND cs.horizon_min = :horizon
         ORDER  BY cs.observed_at DESC, cs.tier ASC   -- ★ 08 §2.2·§5.3.1 T1 tie-break 승계
         LIMIT 1
       ) c ON TRUE
WHERE  p.geom && ST_MakeEnvelope(:min_lng, :min_lat, :max_lng, :max_lat, 4326)::geography
                                                  -- ← idx_places_geom (GIST) 사용, bbox 교차
ORDER BY p.popularity_score DESC                  -- MAX_POINTS 상한 가드용
LIMIT  :max_points;                               -- 300 (가정값)
```

- `&&` bbox 연산자가 GIST 인덱스를 그대로 타므로 **새 인덱스가 필요 없다.**
- `tier="none"` 스팟도 보이게 하려면 위 INNER LATERAL을 `LEFT JOIN LATERAL`로 바꾸고 스냅샷 없는 place에 `tier='none', level=NULL, index=중립값`을 채운다(§5.3.1 T4). 지도에선 스팟이 있는데 색만 없는 상태로 정직하게 표현된다.
- region LOD는 위 쿼리의 소스를 `congestion_snapshots`의 `region_code` 타깃 행으로 바꾸고 좌표를 지역 centroid로 준다(D1 지역 해상도 확인 대상 — Q-HM3).

> **새로 만들지 않은 것(지시 2번 준수)**: 새 배치잡 없음(기존 `job_congestion`이 채운 스냅샷을 읽기만 함), 새 tier 없음(A/B/C/none 그대로), 새 테이블·새 인덱스 없음(`places`+`congestion_snapshots`+`idx_places_geom` 재사용).

#### 15.9.4 캐싱 — 그리드 스냅으로 히트율 극대화 (기존 §9 혼잡도 캐시 패턴 재사용)

지도 팬/줌마다 bbox가 미세하게 달라져 **원본 bbox를 그대로 캐시 키에 넣으면 히트율이 거의 0**이 된다. 그래서 **뷰포트 bbox를 고정 그리드에 스냅**한 뒤 캐시한다. 두 방식 중 **(B) 타일 방식을 권고**하고 (A)를 단순 폴백으로 둔다.

| 방식 | 키 설계 | 히트율 | 채택 |
|---|---|---|---|
| **(B) 타일/셀 단위 (권고)** | 공간을 고정 그리드 셀로 나눠 **셀별로** 캐시. 요청은 bbox와 겹치는 셀들의 캐시를 조립. `cong:heat:{lod}:{horizon}:{cell_row}:{cell_col}` | **높음** — 팬하면 새로 보이는 셀만 미스, 나머지는 히트 (슬리피맵 타일과 동형) | ★ |
| (A) 스냅-bbox 단위 (폴백) | bbox를 그리드 경계로 바깥 스냅 → 스냅된 bbox 4좌표를 키에. `cong:heat:{lod}:{horizon}:{snapW}:{snapS}:{snapE}:{snapN}` | 중간 — 같은 스냅 영역 내 팬만 히트 | 구현 단순 시 |

**캐시 키 정본(§9.1 표 연장 — 혼잡도 TTL "짧게" 원칙 §9.2-1 승계)**:

| 키 패턴 | 내용 | TTL | 갱신 |
|---|---|---|---|
| `cong:heat:{lod}:{horizon}:{cell_row}:{cell_col}` | 셀 하나의 히트포인트 배열 직렬화 | **300s** — `cong:board`(§9.1)와 동일. 예측 혼잡도는 자주 안 변하고 배치 주기(T-1h 가정)보다 짧다 | lazy fill + 인기 셀은 `job_cache_warm` 예열 후보 |

- **그리드 셀 크기(가정값)**: `place` LOD = **0.05°**(위도 약 5.5km), `region` LOD = **0.5°**. zoom band별로 스냅 격자를 다르게 잡아, 각 zoom에서 화면당 조회 셀 수가 일정하게 유지된다(전부 §15.9.7 Q-HM2 보정 대상).
- **stale-while-error 승계(§9.2-2)**: 캐시 미스 → DB 폴백, DB 실패 시에도 stale 캐시를 그대로 낸다. 시연 중 순간 장애로 지도 오버레이가 통째로 비는 것을 막는다.
- **개인화 없음 → 프로필 신원을 키에 넣지 않는다(§9.2-4와 무관·안전)**: M15 응답은 **모든 사용자에게 동일한 공개 통계**다. compare(§9.2.1 S-H3)처럼 개인화 교차서빙 위험이 **구조적으로 없다** — 캐시를 공유해도 안전하다.

#### 15.9.5 ★ "개인정보 아님" 근거 (법률/보안 재검토 불요)

이번 증분이 **07-legal·06-security 재검토를 새로 요구하지 않는 이유**를 명시한다.

| 판정 근거 | 내용 |
|---|---|
| **① 반환값은 개인 위치가 아니다** | B4가 내려주는 강도(`congestion_index`)는 **D1이 산출한 관광지/지역 단위 통계 예측치**다(R1: KT 이동통신 집계를 ML 학습한 예측). 특정 개인의 위치·이동이 아니라 **집계·익명화된 예측 지수**다 |
| **② 사용자 좌표를 수집·저장하지 않는다** | 요청의 `bbox`는 **지도 뷰포트(보고 있는 화면 영역)**이지 사용자 기기 GPS가 아니다. 부산 지도를 봐도 사용자가 부산에 있다는 정보가 아니다. 응답·DB·로그 어디에도 사용자 좌표·식별자·기기 정보가 없다 |
| **③ 인증 불요·개인화 없음** | 공개 엔드포인트다. 프로필·세션과 무관하고 모든 사용자에게 동일 응답이다. 개인화 교차서빙(S-H3) 표면 자체가 없다 |
| **④ 방어적 로깅 최소화** | bbox는 개인정보가 아니지만, 방어적으로 **수신 즉시 그리드 스냅** 후 처리하므로 Nginx 로그에도 거친 셀 경계만 남는다(§3.1 로깅 최소화 정신 승계) |
| **⑤ B안(실사용자 위치 추적) 미설계** | 개인위치정보 상시 수집이 되는 (B)는 §15.9.0에서 명시 기각했다. **M15는 그 수집 표면을 만들지 않으므로** 위치정보법상 위치기반서비스사업자 신고 검토(R4)를 새로 유발하지 않는다 |

> **결론**: M15는 **이미 검토를 마친 D1 예측 데이터의 표현 방식(리스트 → 지도)만 바꾸는 증분**이다. 새 개인정보 수집 항목이 0건이므로 06/07 게이트의 개인정보·위치정보 수집 범위 판정을 **다시 열지 않는다.** (단 D1 출처표기 의무는 기존 footer(J8-c)에 이미 반영되어 있으며 지도 오버레이에도 동일 승계.)

#### 15.9.6 ★ 08 계약 불변 검증 (grep 직접 확인 결과)

지시서 완료 기준: **이번 M15 증분이 compare 34필드·5축 스코어링(`scoring_weights`)과 무관함**을 실측 확인했다.

- **구조적 근거**: M15는 신규 GET 엔드포인트(B4) + 캐시 키 + 기존 쿼리 재사용뿐이다. `tag_vector`·`scoring_weights`를 **산출·소비하지 않고**, `/routes/compare`를 호출하지도 그 응답 필드를 만들지도 않는다. 새 테이블·새 tier·새 배치가 없다.
- **원시 카운트 대조(M15 편집 전 → 후)**: 아래 증가분은 **전량 §15.9의 참조·불가침 서술에서 발생**했다(M14 §15.8.10과 동일 논리 — 카운트 증가 = 계약 변경이 아님).

| 보호 문자열 | M15 전 | 증가 원인 | 판정 |
|---|---|---|---|
| `scoring_weights` (08 §1) | 30 | §15.9.0 "산출·소비하지 않는다"는 불가침 서술만 | 정의·산출 로직 **무수정** |
| `tag_vector` (08 §1) | 36 | §15.9.0 불가침 서술만 | **무수정** |
| `spot_fit`/`review_trust`/`congestion_delta_pct` (08 §2.2 compare) | 40 | §15.9.0 "compare 응답 필드를 만들지 않는다" 서술만 | compare 34필드 **무수정** |

> **결론**: `scoring_weights`(5축 스코어링)와 compare 34필드의 **이름·타입·의미·값은 M15로 하나도 바뀌지 않았다.** M15는 오직 **신규 조회 엔드포인트(B4) + 캐시 키(§9.1 연장) + 기존 `places`/`congestion_snapshots` 재사용 쿼리** 뿐이다. `08-interface-contract.md` 파일은 열지도 수정하지도 않았다.

#### 15.9.7 확인 필요 신규 항목 (M15) — §12·§15.5·§15.8.9 집계 증분

| ID | 확인 항목 | 우선 | 막히는 것 | 담당 게이트 |
|---|---|---|---|---|
| **Q-HM1** | D1 집중률 예측의 **공간 해상도** — 관광지(place) 단위인가, 지역(region) 단위도 주는가 | P1 | region LOD 성립 여부(§15.9.1). 기존 R1/C3와 연동 | 데이터(키 발급 후) |
| **Q-HM2** | LOD zoom 임계(**11**), 그리드 셀 크기(**0.05°/0.5°**), **MAX_POINTS 300**, 캐시 TTL 300s 적정값 | P2 | 히트율·포인트 밀도 튜닝(§15.9.1·§15.9.4) | 운영(보정 루프) |
| **Q-HM3** | region 집계 스냅샷이 `congestion_snapshots.region_code` 타깃으로 **실제 적재되는지**(안 되면 place 클러스터링으로 대체) | P1 | 저zoom 전국뷰 데이터 소스(§15.9.3) | 데이터 |

> **가정값 표기(사실 아님)**: LOD zoom 임계 11, 그리드 셀 0.05°/0.5°, MAX_POINTS 300, 캐시 TTL 300s, level 임계 33/66(08 승계) — **전부 실측·보정 전 초기 가정값**이다(E5·§12.5·§15.5·§15.8.9 연장).

#### 15.9.8 §15.9 핸드오프 노트 (M15 증분)

```
[다음 부서가 알아야 할 것 — M15 지도 혼잡도 오버레이]
1. 새 데이터/배치/tier/테이블 0건 — 기존 D1(congestion_snapshots)+places를 bbox로 잘라 좌표+강도로
   내려주는 신규 GET 엔드포인트(B4) + 캐시 키뿐이다. 08 계약(scoring_weights·compare 34필드) 불변,
   개인정보 신규 수집 0건이라 06/07 재검토 불요(§15.9.5·§15.9.6). B(실사용자 위치추적)는 미설계.
2. designer가 그릴 것(색 매핑): 각 point는 {lat, lng, congestion_index(0~100), level(low/mid/high),
   tier(A/B/C/none)}. 색은 congestion_index 0~100을 연속 그라디언트(예: 초록→노랑→빨강)로 매핑하되
   level 3구간 배지 색과 정합시킬 것. ★ tier="none"이면 level=null·observed_at=null → 색 칠하지 말고
   회색/투명 처리(§5.3.1 T4). data_freshness.notice("예측 혼잡도, 실측 아님")를 지도 위에 고지.
3. 지도 팬/줌마다 B4가 호출되므로 프론트는 뷰포트 bbox+zoom을 넘기고, 저zoom은 region 집계점(place_id
   대신 region_code·place_count 포함), 고zoom은 개별 스팟이 온다. truncated:true면 "확대해서 보기" 안내.
```

---

### 15.10 M16 — 여행지(목적지) 검색 입력 (지명 자동완성)

> **한 줄 요약**: 사용자가 "어디로 갈지"를 **타이핑하면 매칭되는 지명(시/도·시군구) 또는 관광지명**을 자동완성 후보로 내려주고, 사용자가 하나를 고르면 그 지역의 `region_code`(관광지를 고르면 그 관광지의 `region_code`)가 **M2 전광판·M3 경로비교·M5 로컬스팟의 후보 생성 범위를 좁히는 필터**로 흘러간다. **자유 텍스트 NLP가 아니라 구조화된 지명 매칭**이며 — `places.name`은 이미 존재하는 trigram 인덱스(`idx_places_name_trgm`)를 그대로 쓰고, 지명↔`region_code` 매핑만 신규 `regions` 조회 테이블로 보완한다. **온보딩(동행·분위기) 태그 파이프라인·08 스코어링 계약과 무관하며, 후보 생성(candidate generation) 단계에서 지역을 좁히는 역할만 한다.**

#### 15.10.0 배경 + 08/스코어링 불가침 확인 (먼저 읽을 것)

**빠져 있던 것**: backend는 `region_code` 필터링을 이미 갖고 있었다(`GET /api/v1/places?region_code=`(C1), `GET /api/v1/congestion/board?region_code=`(B1), compare의 `destination`(D1)). 그러나 **사용자가 목적지를 검색·입력하는 진입점이 어느 화면에도 없었다** — 온보딩은 동행자·분위기만 물었고 "어디로"는 묻지 않았다(PRD §3.2 M16). M16은 그 진입점 하나를 채우는 증분이며, **뒤단의 필터는 새로 만들지 않고 이미 있는 `region_code` 파라미터를 그대로 활용**한다.

**제약 1 — 자유 텍스트 NLP 금지, 구조화 입력으로 설계**한다. "부산 갈래" 같은 문장을 LLM으로 해석하지 않는다. 사용자가 타이핑한 조각(예: `해운`)을 이미 존재하는 `places`/`regions` 테이블의 지명과 **SQL 매칭(파라미터 바인딩)**해 후보를 돌려준다. 이 방식이 (a) 지명 정확도가 높고, (b) **LLM 호출이 0건이라 프롬프트 인젝션·국외이전·비용·지연 표면이 전부 없으며**(SQL 바인딩이라 SQL 인젝션도 없음), (c) 온보딩 LLM 파이프라인과 완전히 분리된다.

M16은 `08-interface-contract.md`가 확정한 계약을 **한 글자도 바꾸지 않는다.** 지시서 제약을 아래처럼 구조로 보장한다.

| 08/AI 계약 요소 | M16의 영향 | 판정 |
|---|---|---|
| M1 온보딩 태그 스키마·LLM 파이프라인 (`tag_axis_registry`, A1 `/onboarding/analyze`) | M16은 **온보딩을 호출하지도, 태그를 산출·소비하지도 않는다.** 목적지는 태그가 아니라 별개의 구조화 필터다 | **불가침 유지** |
| `tag_vector` / `scoring_weights` (08 §1) | M16은 벡터·가중치를 만들지도 읽지도 않는다. **후보 생성 단계의 WHERE 조건(지역 좁히기)**일 뿐, 스코어링 단계에 개입하지 않는다 | **불가침 유지** |
| `score_routes(candidates)` 계약 (08 §3.2, 02 §3.1) | AI는 **여전히 backend가 넘겨준 candidates만 스코어링**한다. M16은 그 candidates 풀을 지역으로 좁혀 넘길 뿐, `score_routes` 시그니처·연산에 손대지 않는다 | **불가침 유지** |
| compare 34필드·5축 스코어링 (08 §2.2) | M16은 `/routes/compare`에 필드를 추가하지 않는다. 기존 `destination`/`origin`에 `region_code`가 이미 수용된다(§6.2 D1) | **불가침 유지** |

> **핵심 경계**: 목적지 검색은 파이프라인 `[1. 후보 생성(backend)]` 단계의 입력을 좁히는 것이다(02 §3.1). `[2. 하드필터]`·`[3. 스코어링(score_routes)]`·`[4. 선택/로드밸런싱]`은 전혀 바뀌지 않는다. AI는 여전히 넘겨받은 candidates만 본다.

#### 15.10.1 지명 자동완성 엔드포인트 (신규 C4)

| # | 화면 | Method | Path | 인증 | 설명 |
|---|---|---|---|---|---|
| **C4** | 홈/추천 진입 | GET | `/api/v1/destinations/autocomplete` | 공개 | 타이핑 조각 → 매칭 지명(region) + 관광지명(place) 후보 배열 |

```
GET /api/v1/destinations/autocomplete
      ?q=해운          # 사용자가 타이핑한 조각 (서버에서 trim, 64자 초과 절단, 제어문자 제거)
      &limit=8         # 후보 상한 (가정값 8)
      &types=region,place   # 선택. 기본 둘 다. region만/place만으로도 조회 가능
```

- **`q`는 최소 1자(한글)/2자(영문 로마자)부터 조회**(가정값 — Q-DS2)한다. 그 미만이면 빈 배열을 즉시 반환해 전체 테이블 스캔을 막는다.
- **인증 불요·개인화 없음**: 지명 사전 조회이므로 프로필·세션과 무관하고 모든 사용자에게 동일 응답이다. 응답을 캐시 공유해도 안전하다(§15.10.5). 개인위치정보를 받지 않는다 — `q`는 사용자가 친 텍스트일 뿐 기기 GPS가 아니다.
- **정렬**: (1) region을 place보다 위로(넓은 단위 우선), (2) 접두 일치(`name ILIKE q||'%'`)를 부분 일치보다 위로, (3) `place_count`(지역) / `popularity_score`(관광지) 내림차순.

**응답 스키마 (예시 JSON)**:

```jsonc
// GET /api/v1/destinations/autocomplete?q=해운 응답 200
{
  "query": "해운",
  "suggestions": [
    {
      "type": "region",              // "region" | "place"
      "region_code": "26350",        // ★ 후보 생성 필터로 그대로 넘어가는 값 (§15.10.3)
      "name": "해운대구",             // 표시명(짧은)
      "full_name": "부산광역시 해운대구", // 조상 포함(중복 지명 구분용, 예: 전국 여러 "중구")
      "level": "sigungu",            // "sido" | "sigungu"
      "centroid": {"lat": 35.163, "lng": 129.163},  // 선택 시 지도 이동/heatmap bbox 기준점 (M15 재사용)
      "place_count": 214             // 이 지역의 추천 스팟 수 (표시 "추천 214곳" + 정렬 키)
    },
    {
      "type": "place",
      "place_id": 1032,              // 관광지를 직접 고른 경우 compare의 destination.place_id로 사용 가능
      "region_code": "26350",        // ★ 이 관광지가 속한 지역 코드 → 후보 생성 필터로 사용
      "name": "해운대해수욕장",
      "region_name": "부산 해운대구", // 소속 지역 보조표기
      "category": "attraction",
      "location": {"lat": 35.1587, "lng": 129.1604}
    }
  ]
}
```

- **선택 결과의 해석 규약**:
  - `type:"region"` 선택 → `region_code`를 그대로 후보 필터로 사용. compare에서는 이 지역의 대표 핫플을 backend가 자동 선정(§15.10.3).
  - `type:"place"` 선택 → `region_code`로 지역을 좁히고, **동시에** 그 `place_id`를 compare의 `destination.place_id`(사용자가 가려던 핫플)로 바로 쓸 수 있다. "관광지를 콕 집어 검색 → 그 관광지 vs 숨은길 비교"가 자연히 성립한다.

#### 15.10.2 신규 스키마 — `regions` 조회 테이블 (지명↔코드 매핑, 유일한 신규 자원)

**부족한 것 명시**: 관광지명 자동완성은 **기존 자원으로 즉시 된다** — `places.name` + 이미 있는 `idx_places_name_trgm`(§5.2 DDL 335행) GIN trigram 인덱스가 `ILIKE '%해운%'`를 가속한다. 그러나 **시/도·시군구 지명 → `region_code` 매핑 테이블이 없다.** 현재 `region_code VARCHAR(10)`는 여러 테이블에 흩어져 있을 뿐 이름을 조회할 사전 테이블이 없다(§5.2 275·309행 주석 "체계 확인 필요"). 그래서 지명 자동완성에는 **`regions` 조회 테이블 1개가 신규로 필요**하다.

```sql
-- =====================================================================
-- 16. 지역 사전 (M16) — 지명 자동완성 + region_code 표시명 조회 전용.
--     읽기 위주 참조 테이블. 온보딩·스코어링·compare 계약과 무관.
--     places.region_code / user_profiles.region_code 와 "동일 코드 체계"여야 한다(Q-DS1).
-- =====================================================================
CREATE TABLE regions (
    region_code  VARCHAR(10) PRIMARY KEY,        -- 법정동/행정구역 코드 (체계·자릿수 확정은 Q-DS1)
    name         VARCHAR(60)  NOT NULL,          -- 표시명(짧은)  예: "해운대구"
    full_name    VARCHAR(120) NOT NULL,          -- 조상 포함     예: "부산광역시 해운대구" (동명 구분)
    level        VARCHAR(12)  NOT NULL,          -- 'sido' | 'sigungu'  (읍면동은 MVP 미포함 — Q-DS3)
    parent_code  VARCHAR(10)  REFERENCES regions(region_code),  -- 시도 롤업 (해운대구 → 부산)
    centroid     geography(Point, 4326),         -- 선택 시 지도 이동/M15 region LOD centroid 공유
    place_count  INTEGER NOT NULL DEFAULT 0,     -- 배치 갱신. 자동완성 정렬 + "추천 N곳" 표기
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 부분일치(ILIKE '%..%')용 trigram + 접두일치(LIKE '..%')용 btree 병행
CREATE INDEX idx_regions_fullname_trgm ON regions USING GIN (full_name gin_trgm_ops);
CREATE INDEX idx_regions_name_trgm     ON regions USING GIN (name gin_trgm_ops);
CREATE INDEX idx_regions_name_prefix   ON regions (name text_pattern_ops);  -- 'q%' 접두 가속
CREATE INDEX idx_regions_parent        ON regions (parent_code);
```

- **시드 소스 (확인 필요 — Q-DS1)**: `region_code`가 어느 표준 체계인지(법정동코드 vs 행정동코드 vs 지역코드)가 §5.2에서 이미 "확인 필요"였다. `regions`는 **`places.region_code`와 정확히 같은 체계로 시드해야** 조인·필터가 성립한다. 표준 행정구역 코드 공개 데이터(행정안전부 계열)에서 시/도·시군구 2계층만 추출해 시드하는 것을 기본안으로 하되, **정확한 코드 체계·자릿수 규칙은 API 키 발급 후 `places` 실데이터의 `region_code`와 대조해 확정**한다(추측으로 채우지 않는다).
- **`place_count`·`centroid` 갱신**: `places`를 `region_code`로 GROUP BY 하여 개수·centroid(`ST_Centroid`)를 주기 배치로 채운다. 신규 배치잡 `job_regions_rollup`(주 1회, `job_places` 직후) 1개만 추가하면 된다.
- **M15 시너지**: 이 `centroid`·`place_count`는 M15(§15.9.3·§15.9.7 Q-HM3)가 "region LOD 집계 좌표를 D1이 안 주면 서버 클러스터링으로 대체"라고 남긴 미결 항목을 **부분 해소**한다 — region centroid를 `regions`에서 바로 읽을 수 있다. (M15 계약 자체는 불변, 조회 소스만 넉넉해짐.)

#### 15.10.3 후보 생성 필터링 흐름 — 기존 `region_code`로 그대로 좁힌다 (신규 필터 0건)

목적지가 선택되면 프론트가 `selected_destination = {region_code, place_id?}`를 세션에 들고, **이미 존재하는 엔드포인트에 `region_code`를 넘기기만** 하면 M2·M3·M5 후보 집합이 그 지역으로 좁혀진다. 새 필터·새 파라미터를 만들지 않는다.

| 대상 | 목적지 미선택(전국) | 목적지 선택 후(지역 좁힘) | 사용 파라미터 |
|---|---|---|---|
| **M2 전광판** | `GET /congestion/board`(전국 TOP N) | `GET /congestion/board?region_code=26350` | **기존 B1 `region_code`** (신규 0) |
| **M3 경로 추천/비교** | (목적지 없이는 1:1 대조 불성립 — 아래 註) | `POST /routes/compare {destination:{place_id 또는 region_code}}` | **기존 D1 `destination`** (신규 0) |
| **M5 로컬 스팟** | `GET /places`(전국) | `GET /places?region_code=26350` | **기존 C1 `region_code`** (신규 0) |
| M15 지도 오버레이 | 현재 뷰포트 | 선택 지역 `centroid`로 지도 이동 후 bbox 조회 | 기존 B4 `bbox`(+regions.centroid) |

**M3 후보 생성과 destination의 결합 (02 §3.1 `get_courses(destination)` 대응)**:
- `type:"place"` 선택 → `destination.place_id`가 곧 `hotspot_baseline`(사용자가 가려던 핫플)이 되고, `candidates`(숨은길 후보 풀)는 그 place의 `region_code` 안에서 인기도 하위로 뽑는다(02 §3.1 `get_courses(destination, ...)` 그대로).
- `type:"region"` 선택 → 특정 핫플이 지정되지 않았으므로 backend가 **그 지역의 인기도 최상위 place를 `hotspot_baseline`으로 자동 선정**하고, 같은 지역의 인기도 하위를 `candidates`로 뽑는다. (선정 규칙은 기존 §3.1 `get_top_popularity_course(destination)`가 이미 담당 — region 스코프로 호출만 하면 됨.)
- 어느 경우든 **`score_routes(profile, candidates, congestion)` 시그니처·연산은 불변**이다. 목적지는 `candidates`를 만드는 backend 공간·인기도 필터에만 작용한다(하드필터·스코어링이 아니다).

#### 15.10.4 온보딩과의 관계 — 목적지는 "선택", 온보딩과 직교(순서 무관)

**결론: 목적지 검색과 온보딩(동행·분위기)은 서로 독립한 두 축이며, 목적지는 홈 진입점에 두되 필수가 아닌 선택으로 설계한다. 단 M3 경로 비교(compare) 진입 시점에는 목적지가 필수다.**

| 축 | 정체 | 역할 단계 | 없을 때 |
|---|---|---|---|
| **목적지(M16)** | 구조화 필터 (`region_code`) | 후보 생성의 **WHERE**(어디를 볼지) | 전국 스코프로 자연 폴백 — 순위 산출은 깨지지 않음 |
| **온보딩 태그(M1)** | 스코어링 가중치 (`scoring_weights`) | 후보 **정렬**(무엇을 위로 올릴지) | 기본 가중치로 콜드스타트 처리(02 §2.1, 이미 설계됨) |

두 축은 **직교**하므로 순서에 강제 의존이 없다. 근거와 정책:

1. **목적지 = 선택(optional).** 근거: (a) **R5 즉시 체험** — 심사위원이 가입/온보딩 없이 홈에서 바로 "전국 예측혼잡도 TOP10"을 봐야 진입장벽이 낮다. 목적지를 필수 게이트로 막으면 (온보딩 + 목적지) 2단 관문이 생겨 R5와 정면 충돌한다. (b) 목적지는 candidate의 WHERE라, 없으면 전국 스코프로 폴백될 뿐 랭킹 로직이 깨지지 않는다.
2. **"전국 TOP10을 계속 보여줄지 vs 목적지 선택을 유도할지"에 대한 답 = 둘 다.** 목적지 미선택 시 **전국 TOP10을 유지**하되, 홈 상단에 **"어디로 떠나세요?" 검색바를 상시 노출**해 선택을 유도한다. 선택하면 그 지역으로 좁힌 전광판/추천으로 전환된다. (전국 유지 = 이탈 방지, 검색바 상시 노출 = 대표 요구인 "이용자가 목적지를 써서 그 지역을 추천받는" 서사 충족.)
3. **순서 무관.** 목적지를 먼저 골라도(→ 지역 좁힘 후 취향으로 정렬), 온보딩을 먼저 해도(→ 취향 프로필 후 목적지로 좁힘) 결과 파이프라인은 동일하다. 권고 기본 UX: **홈 검색바(목적지) → 지역 결과 → "내 취향 맞춤" CTA로 온보딩**. 하지만 강제하지 않는다.
4. **예외 — M3 compare는 목적지 필수.** 1:1 대조 리포트는 "사용자가 가려던 곳(hotspot) vs 숨은길"이라는 대비가 본질이므로, `destination` 없이는 성립하지 않는다. 따라서 **compare 진입 버튼은 목적지가 선택돼야 활성화**된다(전광판 아이템의 `alternative_route_id`로 진입하는 경로는 그 아이템의 place가 곧 destination이므로 이미 충족).

> 요약: **탐색(홈/전광판/로컬스팟) = 목적지 선택적, 경로 비교 = 목적지 필수, 온보딩과는 순서 자유·독립.**

#### 15.10.5 캐싱 (기존 §9 패턴 재사용, 신규 키 1종)

| 키 패턴 | 내용 | TTL | 갱신 |
|---|---|---|---|
| `dest:ac:{normalized_q}:{types}:{limit}` | 자동완성 후보 배열 직렬화. `normalized_q`=소문자·trim·공백정규화 | **600s** — 지명 사전은 거의 안 변한다 | lazy fill |

- **개인화 없음 → 프로필 신원을 키에 넣지 않는다.** 모든 사용자에게 동일한 공개 지명 사전이므로 compare(§9.2.1 S-H3)의 교차서빙 위험이 **구조적으로 없다**(M15와 동일 논리).
- 짧은 `q`(1~2자)는 후보가 많아 캐시 효율이 높다 — 상위 트래픽 접두어 몇 개가 대부분을 흡수한다.

#### 15.10.6 ★ 08/스코어링 계약 불변 검증 (grep 직접 확인 결과)

지시서 완료 기준: **이번 M16 증분이 08 정본, compare 34필드, 5축 스코어링(`scoring_weights`)을 바꾸지 않았음**을 실측 확인했다.

- **구조적 근거**: M16은 신규 GET 엔드포인트(C4) + 신규 조회 테이블(`regions`) + 신규 롤업 배치(`job_regions_rollup`) + 캐시 키뿐이다. `tag_vector`·`scoring_weights`를 **산출·소비하지 않고**, 온보딩 LLM 파이프라인을 호출하지 않으며, `score_routes` 시그니처와 compare 응답 필드를 만들지도 바꾸지도 않는다.
- **원시 카운트 대조(M16 편집 전 → 후)**: 아래 baseline은 M16 편집 직전 `grep -oF | wc -l` 실측값이다. 증가분은 **전량 §15.10의 참조·불가침 서술에서 발생**했다(M14·M15와 동일 논리 — 카운트 증가 = 계약 변경이 아님).

| 보호 문자열 | M16 편집 전 count | 증가 원인 | 판정 |
|---|---|---|---|
| `scoring_weights` (08 §1) | 38 | §15.10.0 "산출·소비하지 않는다" 불가침 서술만 | 정의·산출 로직 **무수정** |
| `tag_vector` (08 §1) | 42 | §15.10.0 불가침 서술만 | **무수정** |
| `spot_fit` (08 §2.2 compare) | 25 | (M16 서술에서 불변) | compare 34필드 **무수정** |
| `review_trust` (08 §2.2 compare) | 17 | (M16 서술에서 불변) | **무수정** |
| `congestion_delta_pct` (08 §2.2) | 7 | (M16 서술에서 불변) | **무수정** |
| `build_verdict` (08 §5) | 10 | (M16 서술에서 불변) | LLM 미사용 헤드라인 조립 **무수정** |

> **결론**: `scoring_weights`(5축 스코어링)·`tag_vector`·compare 34필드의 **이름·타입·의미·값은 M16으로 하나도 바뀌지 않았다.** `08-interface-contract.md`와 `02-ai-strategy.md` 파일은 **열지도 수정하지도 않았다**(SHA-1 불변 확인). M16은 오직 **신규 조회 엔드포인트(C4) + `regions` 테이블 + 롤업 배치 + 캐시 키**뿐이며, `score_routes`는 여전히 넘겨받은 `candidates`만 스코어링한다.

#### 15.10.7 확인 필요 신규 항목 (M16) — §12 집계 증분

| ID | 확인 항목 | 우선 | 막히는 것 | 담당 게이트 |
|---|---|---|---|---|
| **Q-DS1** | `region_code`의 표준 코드 체계·자릿수(법정동/행정동/지역코드 중 무엇) — `regions` 시드가 `places.region_code`와 **동일 체계**여야 조인 성립 | **P0** | `regions` 시드·자동완성 지역 후보 전체(§15.10.2) | 데이터(키 발급 후 실데이터 대조) |
| **Q-DS2** | 자동완성 최소 질의 길이(한글 1자/영문 2자), `limit` 기본 8 적정값 | P2 | 응답 밀도·전체스캔 방지 튜닝(§15.10.1) | 운영(보정) |
| **Q-DS3** | 읍/면/동(3계층) 자동완성 포함 여부 — MVP는 시도·시군구 2계층만 | P2 | `regions.level` 범위, 시드 규모 | 스코프(대표 판단) |
| **Q-DS4** | 로마자/영문 검색("Busan", "Haeundae") 지원 여부 — 미지원 시 한글만 | P3 | `regions`에 로마자 컬럼 추가 필요 여부 | 스코프 |

> **가정값 표기(사실 아님)**: 최소 질의 길이(한글 1자/영문 2자), `limit` 8, 캐시 TTL 600s, 정렬 우선순위(region>place, 접두>부분) — **전부 실측·보정 전 초기 가정값**이다(E5·§12.5 연장).

#### 15.10.8 §15.10 핸드오프 노트 (M16 증분)

```
[다음 부서가 알아야 할 것 — M16 목적지 검색]
1. 신규 = C4 GET /destinations/autocomplete + regions 조회 테이블 + job_regions_rollup 배치 + 캐시 키뿐.
   관광지명은 기존 places.name+idx_places_name_trgm 재사용, 지명↔code 매핑만 regions 신설(Q-DS1 P0:
   코드 체계가 places.region_code와 같아야 함). 08/scoring_weights/tag_vector/compare 34필드 전부 불변,
   온보딩 LLM·score_routes 미개입 — 후보 생성 WHERE만 좁힌다.
2. designer가 그릴 것: (a) 홈 상단 "어디로 떠나세요?" 검색바(상시 노출) + 타이핑 시 자동완성 드롭다운
   — region 후보(full_name·"추천 N곳")를 place 후보 위에, 접두일치 우선. (b) 목적지 선택 시 전광판/추천이
   그 지역으로 좁혀지는 상태, 미선택 시 전국 TOP10 유지. (c) 목적지 미선택 시 compare 진입 버튼 비활성.
   자유 텍스트 문장 입력창이 아니라 "지명 고르는 자동완성"임을 UI로 분명히 할 것(NLP 아님).
3. 온보딩과 독립·순서 자유: 목적지=선택(탐색), compare=필수. 목적지=WHERE(지역), 온보딩=정렬(취향).
   designer는 둘을 한 흐름에 억지로 묶지 말고 각각 진입 가능하게(검색바 / "내 취향 맞춤" CTA) 배치.
```
