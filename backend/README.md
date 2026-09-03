# 숨은길 (Sumeungil) Backend — MVP-1 + MVP-2 + MVP-3 + MVP-4 + MVP-5

관광지 실시간 혼잡도 전광판 API. 공공데이터(한국관광공사 관광지별 방문자 집중률)를
서버에서 호출·정규화해 프론트가 그대로 렌더할 수 있는 형태로 내려준다.
MVP-2에서 지명→지역코드 변환(`/api/v1/regions/search`)을 additive로 추가했다.
MVP-3에서 온보딩 취향 추출(로컬 LLM, `/api/v1/onboarding/*`)을 additive로 추가했다.
MVP-4에서 로컬 스팟 배치 수집 + 프로필 맞춤 추천(`POST /api/v1/places/recommend`)을 additive로 추가했다.
MVP-5에서 핫플 vs 숨은길 1:1 대조 리포트(`POST /api/v1/compare`)를 additive로 추가했다 — 새 공공 API/데이터 없이 M2 board·M4 추천·M3 프로필·spot_fit을 재조립한다.

- 계약 정본: [`../01-interface-contract.md`](../01-interface-contract.md) (응답 스키마는 이 문서가 정본)
- 구현 범위: [`../00-impl-plan.md`](../00-impl-plan.md)

## 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/health`, `/api/v1/health` | 헬스체크 (config/upstream/cache 상태) |
| GET | `/api/v1/congestion/board` | 실시간 혼잡 전광판 (혼잡도 내림차순 TOP N) |
| GET | `/api/v1/congestion/forecast` | **한적한 날 예보** (관광지별 날짜별 예측 + best/worst day, 계약 부록 M) |
| GET | `/api/v1/regions/search` | 지명→지역코드 조회 (MVP-2, 검색창/지역 칩) |
| GET | `/api/v1/onboarding/tag-schema` | 온보딩 칩 UI 구성 소스 (MVP-3, registry 단일 소스) |
| POST | `/api/v1/onboarding/analyze` | 자유텍스트+칩 → 취향 태그 추출 (MVP-3, 로컬 LLM) |
| POST | `/api/v1/places/recommend` | 프로필 맞춤 로컬 스팟 추천 목록 (MVP-4, SpotCard[]) |
| POST | `/api/v1/compare` | 핫플 vs 숨은길 1:1 대조 리포트 (MVP-5, CompareSpot 대칭 + deltas + verdict) |
| GET | `/docs` | Swagger UI |

### `GET /api/v1/congestion/board`

쿼리 파라미터 (모두 선택):

| 파라미터 | 기본값 | 설명 |
|---|---|---|
| `area_cd` | `26` (부산) | 공공 API `areaCd` (시도, 법정동 2자리) |
| `sigungu_cd` | `26350` (해운대구) | 공공 API `signguCd` (시군구, 법정동 5자리) |
| `limit` | `10` | 반환 개수 (1~50, 초과 시 50 절삭) |

파라미터를 모두 생략하면 서버 기본 지역(부산 해운대구)으로 응답한다.
`congestion_level`(high/mid/low/unknown) 판정은 **백엔드 단독 소유** — 프론트는 재판정하지 않는다.

### `GET /api/v1/congestion/forecast` (계약 부록 M)

전광판이 버리던 원천의 **미래 날짜(baseYmd) 예측 행**을 시계열로 노출한다.

| 파라미터 | 기본값 | 설명 |
|---|---|---|
| `region_code` | **필수** | 법정동 시군구 5자리(예 `26350`). 형식 위반 → 400 `INVALID_REGION` |
| `spot_name` | 없음 | 특정 관광지만(이름매칭). 없으면 전광판 상위 `limit`곳 |
| `days` | `14` | 오늘 포함 조회 일수(1~35 클램프). **원천 실제 커버리지는 17일** |
| `limit` | `10` | 관광지 수(1~50 클램프) |

응답 `spots[].daily[]`는 **원천에 있는 날짜만** 담고(보간 없음), `best_day`/`worst_day`는 그 윈도우의
최저/최고다(비교할 날 2일 미만이면 null). `meta.notice`의 **예측치 고지 문구는 화면에 반드시 노출**한다.
캐시 TTL 6h(`FORECAST_CACHE_TTL_SEC`) — board(600s)와 키·TTL 모두 분리돼 전광판 동작은 불변.

### `GET /api/v1/regions/search` (MVP-2)

지명 조각으로 지역 후보를 반환한다. 프론트 검색창 타이핑/지역 칩이 이걸로 코드를 얻어
`/congestion/board`를 재호출한다. 계약 부록 A.1.

| 파라미터 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `q` | 예 | — | 지명 조각(예: `해운`, `경주`). 트림 후 1자 이상. 빈 값이면 400 |
| `limit` | 아니오 | `8` | 후보 최대 개수 (1~20, 범위 밖은 클램프) |

응답 예 (`q=경주`):

```jsonc
{
  "query": "경주",
  "items": [
    { "region_id": "47130", "label": "경상북도 경주시", "area_cd": "47", "sigungu_cd": "47130" }
  ]
}
```

- 매칭 0건이면 `items: []` + **HTTP 200** (에러 아님).
- 코드 소유는 backend. 프론트는 응답의 `area_cd`/`sigungu_cd`를 그대로 board 요청에 넘기기만 한다.
- 매칭은 `label`·별칭(aliases)에 대해 대소문자·공백 무시 substring, prefix 우선 랭킹.

### `GET /api/v1/onboarding/tag-schema` (MVP-3)

칩 UI 구성용 축·칩(값·라벨) 목록. 프론트는 칩을 **하드코딩하지 않고** 이 응답으로
구성한다. 정본은 `app/ai/tag_registry.py`(08 §1.4 registry 36행). 칩 없는 축
(`flag`)·파생값(`unspecified` 등)은 제외된다. 계약 부록 B.2.

- `axes[].axis` 영문 축명, `axes[].label` 한국어 축명, `axes[].select`(`single`|`multi`, UX 권고).
- `axes[].chips[]` = `{value(영문코드), label(한국어)}`. `congestion_pref`만 `single` 권고.

### `POST /api/v1/onboarding/analyze` (MVP-3)

자유 텍스트 + 칩(영문 코드 배열)으로 취향 태그(`OnboardingResult`)를 추출한다.
LLM 호출은 backend가 로컬 Ollama(개발 기본 `qwen3.5:4b-q4_K_M`)를 감싸서 수행하며,
프론트는 Ollama를 직접 부르지 않는다. 계약 부록 B.1/B.3.

요청 body (`text`·`chips` 둘 다 선택, 단 둘 다 비면 400):

```jsonc
{ "text": "6세 아이랑 반려견이랑 걷기 좋은 곳", "chips": ["with_child"], "region_code": "26350" }
```

- `text` 필드명이 정본. 운영 검증 스크립트 호환을 위해 `free_text` 별칭도 수용한다.
- 응답: `tags`(7축) + `tag_vector`[36] + `scoring_weights`(5축) + `extracted_by`
  (`llm-v1`|`rule-v1`|`hybrid-v1`) + `fallback_used`. **`unmatched_note`는 응답에서 제외**(내부 진단 전용).
- `tag_vector`·`scoring_weights`·registry 검증은 **서버(AI 레이어)가 소유** — LLM은 축별 태그 값만 반환.

에러/폴백 계약:

| 상황 | 응답 |
|---|---|
| `text`·`chips` 둘 다 빔 | `400 EMPTY_INPUT` |
| Ollama 장애/타임아웃/JSON 파싱 실패 | **200** + `extracted_by:"rule-v1"`, `fallback_used:true` (에러 아님 — 키워드+칩 폴백) |
| **인젝션 패턴 탐지**("지시 무시", "모든 태그 true" 등) | **200** + LLM 스킵 → 룰 폴백 강등(`rule-v1`, `fallback_used:true`). 과다추출 차단 |
| 룰 폴백조차 실패한 예기치 못한 오류 | `500 INTERNAL` |

**인젝션 처리 방침(보안)**: `app/api/onboarding.py`가 진입 시 `injection_guard.detect_injection_patterns(text)`로
탐지하고, 히트 시 LLM을 아예 태우지 않는 가드 프로바이더를 주입해 `onboarding_service`의
룰(키워드+칩) 폴백 경로로 강등한다. 키워드 폴백은 여행 키워드 부분일치만 하므로 명령문성
인젝션에서 태그가 거의 잡히지 않아 LLM 과다추출 표면이 구조적으로 사라진다. 로그에는
패턴명·입력 길이만 남기고 사용자 원문은 남기지 않는다.

**타임아웃 순서**(계약 B.6): backend→Ollama `OLLAMA_TIMEOUT_SEC`(기본 30초) < 프론트 fetch(60초).
Ollama 타임아웃 시 룰 폴백(200).

### `POST /api/v1/places/recommend` (MVP-4)

지역 + (선택) 온보딩 프로필을 받아 로컬 스팟을 스코어링해 정렬된 `SpotCard[]`를 내려준다.
프론트가 sessionStorage의 `OnboardingResult`를 `profile`에 그대로 실어 보내고, 백엔드가
**신뢰경계 재검증(C.4)** 후 스코어링·정렬한다. 프론트는 표시만 한다. 계약 부록 C.

요청 body:

```jsonc
{
  "region_code": "47130",       // 필수. = sigungu_cd(부록 A 체계). 누락/비숫자면 400 INVALID_REGION
  "profile": {                  // 선택. null이면 비개인화(혼잡도순) 목록
    "tag_vector": [ /* 36, 0.0|1.0 */ ], "vector_version": 1,
    "scoring_weights": {"congestion":..,"profile_fit":..,"distance":..,"local_exposure":..,"trust":..},
    "tags": { /* OnboardingResult.tags — accessibility 하드필터/표시에 소비 */ }
  },
  "category": "cafe",           // 선택. attraction|restaurant|cafe|craft|trail|nature|market|etc. null=전체
  "sort": "personalized",       // personalized(기본) | congestion | distance(MVP-4=congestion)
  "limit": 20                   // 1~50, 기본 20
}
```

응답: `{ region, personalized, items: SpotCard[], meta }`. `SpotCard`는 계약 C.2 그대로
(`id·name·category·region_code·address·location{lat,lng}·congestion·themes·is_hidden_gem·
match_score·match_reasons`). `personalized:false`면 `match_score`/`match_reasons`는 null.

**프로필 재검증(C.4, 신뢰경계 — 프론트 값을 그대로 믿지 않음)**:

| 검증 | 내용 | 위반 시 |
|---|---|---|
| V1 | `tag_vector` 길이 36 · 원소 0.0/1.0(이진) | **400 INVALID_PROFILE** (조작 신호, C.4a 권장) |
| V2 | `vector_version == 1` | 관대 폐기 → 비개인화 200(`personalized:false`) |
| V3 | `scoring_weights` 5키 · 각 0~1 · 합 1.0±0.01 | **400 INVALID_PROFILE** |
| V4 | `tags[].value`가 registry에 존재 | 개별 조용히 폐기 + `meta.rejected_tag_count` 증가(200) |
| V5 | 민감 태그(유모차/휠체어) | 이 요청 하드필터에만 사용, 로그·저장 안 함(MVP-4는 저장 자체 없음) |

**스코어링(C.5, 소관 분리)**: `match_score` = 아래 축을 `scoring_weights`로 가중합 후 활성 축만 재정규화(0~1).

| 축 | MVP-4 처리 | 소관 |
|---|---|---|
| `profile_fit` | `spot_fit` = 프로필 vs 스팟 태그벡터 **코사인**(registry slice idx 14~28: mood+spot_pref) | **AI** (`app/ai/spot_fit.py`) |
| `congestion` | M2(전광판) 스냅샷 조인 성공 시 `1−index/100` 가점, 매칭 없으면 축 제외(중립) | backend |
| `local_exposure` | `is_hidden_gem`이면 가점 | backend |
| accessibility | 사용자 요구 태그 vs 스팟 `themes` 충돌 시 감점(하드컷 아님), null 중립, 충족 시 `theme_match` | backend |
| `distance`·`trust` | MVP-4 중립(재정규화에서 제외) | backend |

`match_reasons.signals`(C.2.2): `low_congestion`·`hidden_gem`·`high_profile_fit`(spot_fit≥0.5)·
`theme_match`. `matched_tags`는 코사인에 기여한 registry 코드(프론트가 label로 변환).

### `POST /api/v1/compare` (MVP-5) — 핫플 vs 숨은길 1:1 대조

지역 + (선택) 프로필을 받아 **"그 지역에서 붐비는 유명 핫플(baseline)" vs "AI가 찾은 한적한 숨은길(추천)"**을
대칭 카드 2개 + 지표별 델타 + verdict headline으로 내려준다. **새 공공 API/데이터 없이 조각을 재조립**한다:
M2 board rank1(핫플) · M4 recommend 스코어링(숨은길) · M3 프로필 재검증(C.4) · spot_fit(적합도). 계약 부록 D.

요청 body:

```jsonc
{
  "region_code": "47130",   // 필수. = sigungu_cd. 누락/비숫자면 400 INVALID_REGION
  "profile": { /* C.3 ProfileInput = sessionStorage OnboardingResult. null이면 비개인화 */ },
  "hidden_id": 2838704,     // 선택. 추천 화면에서 탭한 숨은 스팟 고정. 없으면 auto(recommend top)
  "hotspot_id": null,       // 선택. "가려던 핫플" 고정. 없으면 M2 board rank1 auto
  "category": null          // 선택. hidden auto 선정 시 카테고리 필터
}
```

응답: `{ comparison_id, generated_at, region, hotspot, hidden, deltas, verdict, meta }`.

- **`hotspot`/`hidden`은 완전히 같은 키 구조(`CompareSpot`)** — 프론트 대칭 렌더 전제. 필드: `role·spot_id·
  name·category·congestion·themes·is_hidden_gem·match_score·match_reasons·source`. 부록 C.2 SpotCard의
  부분집합 + `role`(hotspot|hidden) + `source`(m2_board|local_store). 거리·경로·리뷰 필드는 **없다**(데이터 없음, MVP-6~7).
- **핫플 선정**: board rank1(혼잡도 최고). 스토어 이름매칭되면 `category`/`themes`/`match_score` enrich,
  미매칭이면 lean(`spot_id·category·match_score = null` — **없는 값을 지어내지 않는다**). 숨은길과 같은 스팟이면 board 차순위로 밀어 자기비교 방지.
- **숨은길 선정**: recommend 파이프라인 재사용(`sort:personalized`), 핫플과 다른 스팟 중 최상위. `hidden_id` 오면 그 스팟 고정.
- **`deltas`**: `congestion_diff`(hidden.index−hotspot.index) · `congestion_diff_pct`(상대% 반올림) ·
  `fit_diff`(match_score 차) · `matched_count`. **한쪽 index/score가 null이면 그 델타는 null**(지어내지 않음).
- **`verdict.headline`**: **backend 템플릿 4종 조립. LLM 미사용.** 수치·enum·개수만 삽입하고 **스팟 name/category 등
  외부 문자열을 절대 넣지 않는다**(간접 인젝션·XSS 표면 0, D.4.1). `template_id`로 어느 분기를 탔는지 표기(QA 검증용).

| `template_id` | 조건 | 템플릿 |
|---|---|---|
| `congestion_and_fit` | 혼잡도 델타 음수 + 프로필 매칭 有 | "붐비는 유명 스팟 대신 혼잡도 {abs%} 낮은 한적한 곳이에요. 맞춤 조건 {n}개를 만족합니다." |
| `congestion_only` | 혼잡도 델타 음수 + 매칭 無 | "붐비는 유명 스팟보다 혼잡도가 {abs%} 낮은 한적한 곳이에요." |
| `fit_only` | 혼잡도 델타 null + 매칭 有 | "한적한 숨은 곳으로, 맞춤 조건 {n}개를 만족합니다." |
| `hidden_gem_generic` | 그 외 / 120자 초과 폴백 | "유명 핫플 대신 붐비지 않는 숨은 곳을 찾았어요." |

> 혼잡도 델타가 양수(숨은길이 더 붐빔)면 "낮다"고 말하지 않고 fit/generic으로 폴백(과장 금지).

- **프로필 재검증**: 부록 C.4를 `recommend_service.validate_profile`로 **그대로 재사용**. 구조 위반(V1 길이/이진,
  V3 weights)은 `400 INVALID_PROFILE`, `vector_version` 불일치(V2)는 관대 폐기 후 비개인화 200.
- **에러**: `400 INVALID_REGION` / `400 INVALID_PROFILE` / `404 COMPARE_UNAVAILABLE`(핫플·숨은길 못 고름:
  board 비었거나 지역 스팟 0) / `500 INTERNAL`.
- **`comparison_id`**: `cmp_`+ULID(외부 의존 없이 자체 생성). **저장·재조회(`GET /compare/{id}`) 없음** — 추적용.
- `comparison_id`·`meta.distance_axis:false`·`meta.review_axis:false`는 MVP-5 고정.

**실호출 검증(2026-07-24, 경주 47130)**: 프로필(연인+로컬카페) → 핫플(마우나오션 혼잡 77.7 high) vs
숨은길(match 0.91, matched `calm`·`local_cafe`) 대칭 응답, verdict `fit_only`. 비개인화 → 델타 `-77%`, `congestion_only`.
프로필 조작(길이35/비이진/weights합) → 400 INVALID_PROFILE. headline 외부문자열 누출 0. serviceKey 로그 노출 0.

### 로컬 스팟 데이터 소스 — TourAPI 실호출 확정 (2026-07-24)

**확정 소스**: 한국관광공사 **국문 관광정보 서비스 KorService2**
`GET http://apis.data.go.kr/B551011/KorService2/areaBasedList2` (D8 계열).
데모 4지역에서 스팟(관광지·음식점·카페·쇼핑·문화시설·레포츠)이 실제로 나오는 것을 실호출로 확인.

> **중요(실호출로 확정)**: TourAPI는 혼잡도 API·법정동 코드와 **다른 자체 areaCode/sigunguCode**를
> 쓴다. `lDongSignguCd`(법정동)로는 0건이 나와, `KorService2/areaCode2`를 실호출해 매핑을 확정했다:
>
> | 지역 | 우리 region_code(법정동) | TourAPI areaCode | TourAPI sigunguCode |
> |---|---|---|---|
> | 부산 해운대구 | `26350` | `6` | `16` |
> | 경주시 | `47130` | `35` | `2` |
> | 강릉시 | `51150` | `32` | `1` |
> | 전주시 | `52111` | `37` | `12` |
>
> 매핑 정본: [`app/spots/region_map.py`](app/spots/region_map.py).

**원천 필드(실호출 확인)**: `title`·`mapx`(경도)·`mapy`(위도)·`contenttypeid`·`cat1/2/3`·
`contentid`(PK)·`addr1`·`firstimage`. 우리 `SpotCard`로 매핑하는 표는
[`app/spots/category_map.py`](app/spots/category_map.py):

- `contenttypeid` 39 → `restaurant` (cat3 `A05020900`=카페 → `cafe`)
- 38 → `A040102*`=`market`, `A040107*`=`craft`, 그 외 `etc`
- 28 → `A030227*`(걷기/둘레길)=`trail`, 그 외 `attraction`
- 12 → cat1 `A01`(자연)=`nature`, 그 외 `attraction`; 14(문화시설)=`attraction`
- 15(축제)·25(코스)·32(숙박) → 장소 카드로 부적합해 **수집 제외**

스팟 태그(registry mood+spot_pref)는 카테고리에서 결정론 매핑(예 cafe→`local_cafe`+`calm`,
craft→`craft_shop`+`unique`). accessibility/themes(반려·무장애·웰니스)는 원천 테마 서비스가
미인가(pet-tour 404) 상태라 **null(미확인)** — false와 구분해 두고 억지로 채우지 않는다.

**배치 수집 → 로컬 스토어**: `python -m app.spots.collector`가 4지역 × 5콘텐츠타입을 실호출해
[`app/spots/data/spots_seed.json`](app/spots/data/spots_seed.json)에 적재한다(추천 엔드포인트는
이 파일만 읽고 원천을 요청마다 때리지 않음 — 무료 1,000회/일 쿼터 방어).

**수집 결과(2026-07-24 실호출, 총 535개)**:

| 지역 | region_code | 수집 스팟 수 |
|---|---|---|
| 부산 해운대구 | `26350` | 96 |
| 경주시 | `47130` | 140 |
| 강릉시 | `51150` | 166 |
| 전주시 | `52111` | 133 |

카테고리 분포: attraction 257, restaurant 167, cafe 33, etc 35, nature 21, trail 11, market 9,
craft 2 (craft는 TourAPI가 공방을 명확히 분류하지 않아 희소 — 정직한 실측값). hidden_gem 180.

### 확정된 데모 지역 코드 (2026-07-24 KTO 실호출 검증)

아래 코드는 **추측이 아니라 KTO `tatsCnctrRatedList`를 실호출해 혼잡도 데이터가 실제로
나오는(count>0) 조합만 채택**했다. 데이터가 비는 조합은 사전에 넣지 않았다.
2023~2024 개편으로 **강원=51(구 42), 전북=52(구 45)** 신코드를 써야 데이터가 나온다.

| 지역(칩) | label | area_cd | sigungu_cd | 실데이터 확인 |
|---|---|---|---|---|
| **경주** | 경상북도 경주시 | `47` | `47130` | O (경주 보문·엑스포 등) |
| **전주** | 전북특별자치도 전주시 완산구 | `52` | `52111` | O (한옥마을·전동성당 등) |
| **강릉** | 강원특별자치도 강릉시 | `51` | `51150` | O (경포해변·월화거리 등) |
| **부산 해운대** | 부산광역시 해운대구 | `26` | `26350` | O (마린시티·해운대해변 등) |

추가 수록(데모 풍부화, 모두 실호출 확인): 서울 종로구 `11/11110`, 서울 중구 `11/11140`,
제주시 `50/50110`, 서귀포시 `50/50130`, 인천 중구 `28/28110`, 속초시 `51/51210`,
가평군 `41/41820`, 수원 장안구 `41/41111`, 공주시 `44/44150`, 여수시 `46/46130`,
통영시 `48/48220`, 창원 마산합포구 `48/48125`, 군산시 `52/52130`, 남원시 `52/52190`.
사전 정의는 [`app/regions/seed.py`](app/regions/seed.py) 참고.

> 전주시(시 레벨 `52110`)는 원천 데이터가 비어 있고 완산구(`52111`)/덕진구(`52113`)에만
> 데이터가 있다. 관광 핵심(한옥마을)이 있는 **완산구**를 "전주" 칩으로 채택했다.

## 환경변수

- **필수**: `PUBLIC_DATA_API_KEY` (공공데이터포털 일반 인증키). 없으면 부팅 즉시 종료(fail-fast).
- 선택: `DEFAULT_AREA_CD`, `DEFAULT_SIGUNGU_CD`, `CACHE_TTL_SEC`(기본 600), `UPSTREAM_TIMEOUT_SEC`(기본 8), `CORS_ORIGINS`(기본 `http://localhost:3000`).

**.env 로딩 순서**: `backend/.env` 가 있으면 사용, 없으면 자동으로 상위 `projects/sumeungil/.env` 를 참조한다.
따라서 별도 복사 없이도 상위 .env 의 키로 바로 뜬다. (`.env` 는 `.gitignore` 로 커밋 차단됨)

## 로컬 실행

```bash
cd projects/sumeungil-build/backend

# 1) 가상환경 + 의존성 (Windows Git Bash 기준: py 런처 사용)
py -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
#   (macOS/Linux) python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

# 2) 키 준비 — 아래 셋 중 하나
#    (a) 아무것도 안 함: 상위 projects/sumeungil/.env 를 자동 참조 (가장 간단)
#    (b) cp .env.example .env  후 PUBLIC_DATA_API_KEY 채우기
#    (c) 환경변수로 주입: export PUBLIC_DATA_API_KEY=...

# 3) (MVP-4) 로컬 스팟 배치 수집 → spots_seed.json (최초 1회 / 갱신 시)
./.venv/Scripts/python.exe -m app.spots.collector
#   -> 4지역 535개 적재. 추천 엔드포인트는 이 시드만 읽는다(원천 재호출 안 함).

# 4) 서버 기동 (:8000)
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
#   (macOS/Linux) uvicorn app.main:app --reload --port 8000
```

## 동작 확인

```bash
curl http://localhost:8000/health
curl "http://localhost:8000/api/v1/congestion/board?limit=5"
```

`/api/v1/congestion/board` 는 부산 해운대구의 실제 관광지 혼잡도(마린시티, 해운대해수욕장,
벡스코 등)를 혼잡도 내림차순으로 반환한다. 다른 지역 예시:

```bash
# 제주 서귀포시 (high/mid/low 다양)
curl "http://localhost:8000/api/v1/congestion/board?area_cd=50&sigungu_cd=50130&limit=100"
# 서울 종로구
curl "http://localhost:8000/api/v1/congestion/board?area_cd=11&sigungu_cd=11110"
```

MVP-2 지명 검색 → 그 코드로 board 재호출 (프론트가 하는 2단계):

```bash
# 1) 지명으로 코드 조회
curl "http://localhost:8000/api/v1/regions/search?q=경주"
#    -> items[0].area_cd=47, sigungu_cd=47130
# 2) 그 코드로 전광판
curl "http://localhost:8000/api/v1/congestion/board?area_cd=47&sigungu_cd=47130&limit=5"
```

MVP-3 온보딩 (로컬 품질 우선 기본값 `qwen3.5:4b-q4_K_M`):

```bash
# 최초 1회. 기존 모델과 품질 비교는 아래 benchmark_local_llms.py 참고.
ollama pull qwen3.5:4b-q4_K_M

# 칩 UI 소스
curl http://localhost:8000/api/v1/onboarding/tag-schema

# 취향 추출 (실측 3~7초) — Windows Git Bash는 한글이 깨질 수 있어 파일로 보내는 게 안전
printf '{"text":"6세 아이랑 반려견이랑 걷기 좋은 곳","chips":[]}' > body.json
curl -X POST http://localhost:8000/api/v1/onboarding/analyze \
  -H "Content-Type: application/json; charset=utf-8" --data-binary @body.json
#   -> extracted_by:"llm-v1", fallback_used:false, tags 7축 + tag_vector[36]

# 같은 한국어 관광 골든 케이스로 기존 7B/3B와 새 2B의 JSON 성공률·F1·지연 비교
python scripts/benchmark_local_llms.py --models qwen2.5:7b qwen3.5:2b-q4_K_M qwen3.5:4b-q4_K_M

# 빈 입력 -> 400 EMPTY_INPUT
curl -X POST http://localhost:8000/api/v1/onboarding/analyze \
  -H "Content-Type: application/json" -d '{"text":"","chips":[]}'
```

MVP-4 스팟 추천 (한글 body는 파일/urllib로 보내는 게 안전 — Git Bash 한글 깨짐 주의):

```bash
# 비개인화(프로필 없음) — 혼잡도 낮은 순
printf '{"region_code":"47130","limit":5}' > body.json
curl -X POST http://localhost:8000/api/v1/places/recommend \
  -H "Content-Type: application/json" --data-binary @body.json
#   -> personalized:false, items[].match_score:null

# 개인화 — profile은 온보딩 analyze 응답(sessionStorage OnboardingResult)을 그대로 실어 보낸다
#   경주 + "연인/로컬카페/공방" 취향이면 카페·공방 스팟이 상위로 정렬됨(match_score 내림차순).

# 조작 프로필(길이!=36 또는 비이진 벡터, weights 합!=1) -> 400 INVALID_PROFILE
printf '{"region_code":"47130","profile":{"tag_vector":[1,0,1],"vector_version":1,"scoring_weights":{"congestion":0.25,"profile_fit":0.3,"distance":0.15,"local_exposure":0.15,"trust":0.15},"tags":{}}}' > body.json
curl -X POST http://localhost:8000/api/v1/places/recommend \
  -H "Content-Type: application/json" --data-binary @body.json
```

## 구조

```
app/
  main.py                     앱 생성, CORS, 라우터 등록
  config.py                   .env 로드 + fail-fast (필수 키 검증)
  deps.py                     싱글턴 조립 (cache/repository/llm_provider) — 상용 교체 지점
  api/
    health.py                 GET /health, /api/v1/health
    congestion.py             GET /api/v1/congestion/board
    regions.py                GET /api/v1/regions/search  (MVP-2)
    onboarding.py             POST /api/v1/onboarding/analyze, GET /tag-schema (MVP-3)
                              HTTP 봉투 + 인젝션 게이팅. 추출 로직은 app/ai/ 소유
    places.py                 POST /api/v1/places/recommend (MVP-4) — HTTP 봉투, 스코어링은 서비스 소유
    compare.py                POST /api/v1/compare (MVP-5) — HTTP 봉투, 선정·델타·verdict는 서비스 소유
  ai/                         AI팀 소유 — LLM Provider·룰폴백·인젝션가드·태그조립·registry (MVP-3)
    onboarding_service.py     extract_onboarding_tags() 단일 진입점 (backend가 호출)
    llm_provider.py           LLMProvider 추상 + OllamaProvider (상용 CloudProvider 교체점)
    tag_registry.py           태그 축·값·라벨·벡터 인덱스 정본 (36차원)
    injection_guard.py        인젝션 패턴 탐지(차단 아님 — API가 게이팅)
    spot_fit.py               spot_fit 코사인 유사도 + matched_tags (MVP-4, AI 소관)
  services/
    congestion_service.py     레벨 판정 + 정렬 + rank + TOP N + 계약 직렬화
    region_service.py         지역 검색 결과 → 계약 A.1 직렬화 + limit 클램프 (MVP-2)
    recommend_service.py      프로필 재검증(C.4) + 스코어링·정렬 + SpotCard 조립 (MVP-4)
    compare_service.py        핫플(board rank1)·숨은길(recommend) 선정 + deltas + verdict 템플릿 조립 (MVP-5)
                              — recommend_service 헬퍼 재사용, LLM 미사용, headline에 외부문자열 미삽입
  repositories/
    congestion_repo.py        CongestionRepository 추상 + LiveCongestionRepository
                              (fetch-on-miss + 캐시 + stale 폴백)
    region_repo.py            RegionRepository 추상 + StaticRegionRepository
                              (seed 기반 검색, 상용 시 DB 교체) (MVP-2)
    spot_repo.py              SpotRepository 추상 + JsonSpotRepository (시드 로드, 상용 DB 교체) (MVP-4)
  regions/
    seed.py                   지역 사전 정적 상수 (실호출로 확정한 코드) (MVP-2)
  spots/                      MVP-4 로컬 스팟 수집·매핑
    region_map.py             법정동 region_code → TourAPI areaCode/sigunguCode (실호출 확정)
    category_map.py           TourAPI 분류 → SpotCard category + 스팟 태그 + hidden_gem
    collector.py              배치 수집기 (python -m app.spots.collector) → data/spots_seed.json
    data/spots_seed.json      수집 결과 로컬 스토어(런타임 read-only)
  clients/
    kto_client.py             공공 API 호출·파싱 (envelope/flat 양형태 방어)
    tourapi_client.py         KorService2 areaBasedList2 호출·파싱 (MVP-4, serviceKey 로그 금지)
  cache/
    base.py                   Cache 추상 (Redis 드롭인 인터페이스)
    memory.py                 인메모리 TTL 구현
  schemas/
    congestion.py             응답 Pydantic 모델 = 01 계약 코드화
    regions.py                regions/search 응답 모델 = 계약 A.1 코드화 (MVP-2)
    places.py                 SpotCard + recommend 요청/응답 모델 = 계약 C.2/C.3 코드화 (MVP-4)
    compare.py                CompareSpot(대칭) + deltas/verdict + 요청 모델 = 계약 D.2/D.4 코드화 (MVP-5)
  util/
    time.py                   KST 시간 유틸
```

## 상용 확장 지점 (버리는 코드 없음)

- **캐시**: `MemoryCache` → `RedisCache` (동일 `Cache` 인터페이스, `deps.py` 한 줄 교체).
- **데이터**: `LiveCongestionRepository`(fetch-on-miss) → `DbCongestionRepository`(배치가 채운
  `congestion_snapshots` read). 엔드포인트·응답 계약 불변, `deps.py` 에서 교체.
- **지역 사전**: `StaticRegionRepository`(seed.py 상수) → `DbRegionRepository`(공식 법정동
  코드셋 테이블). 동일 `RegionRepository.search()` 시그니처, `deps.py` 에서 교체.
- **기능**: 같은 FastAPI 앱에 온보딩·경로비교·지도 라우터를 additive 로 얹음.

## 원천 API 필드 매핑 (실호출 확인)

| 우리 필드 | 원천 필드 | 비고 |
|---|---|---|
| `spot_name` | `tAtsNm` | 관광지명 |
| `congestion_rate` | `cnctrRate` | 문자열 → float, 0~100 클램프 |
| `base_date` | `baseYmd` | `YYYYMMDD` → `YYYY-MM-DD` |
| `region.area_name` | `areaNm` + `signguNm` | 코드→명 매핑을 원천 응답에서 획득 |

원천은 예측 데이터라 관광지별 여러 날짜를 준다 → **오늘에 가장 가까운 날짜** 한 벌만 골라
관광지별 1행으로 정규화한다.
