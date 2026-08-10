# 08-interface-contract — 숨은길 (SUMUENGIL) 부서 간 인터페이스 정본

- **작성**: planning-lead
- **작성일**: 2026-07-22
- **근거**: `00-PRD.md` §6.1 (부서 간 합의 필요 인터페이스 3건은 planning-lead가 취합 시 조정), `04-qa-report.md` C1/C2/C3·J6/J7/J8, `06-security-report.md` S-H5/S-H7/S-M2/S-M8/S-M10

---

## 0. 권위 선언 (먼저 읽을 것)

> **이 문서는 `01-backend-design.md`, `02-ai-strategy.md`, `03-design-spec.md`보다 상위 권위를 갖는다.**
>
> 세 문서의 서술이 본 문서와 충돌하면 **본 문서가 정본**이며, 각 부서는 자기 문서를 본 문서에 맞춰 수정한다. 본 문서에 없는 사항은 각 부서 문서가 계속 유효하다.
>
> 본 문서를 변경하려면 planning-lead의 개정이 필요하며, 개정 시 §8 개정 이력에 행을 추가한다. 부서가 자기 문서에서 본 문서의 계약을 임의로 바꾸지 않는다.

**본 문서가 확정하는 범위**: QA Critical 3건(C1·C2·C3) + Major J6 + 보안 S-H5, 총 5건. 그 외 Major/Minor/High 항목은 각 부서의 개별 재작업 대상이며 본 문서는 계약면에 영향을 주는 부분만 반영한다.

**용어**: "산출 주체"는 값을 계산하는 부서, "직렬화 주체"는 API 응답에 담는 부서다. 두 개가 다를 수 있다.

---

## 1. 결정 D1 — `weight_vector` (QA C1)

### 1.1 결정

**두 개념 모두 실재한다. 단, 이름이 충돌하고 있었으므로 분리해 명명한다.**

| 정본 이름 | 정체 | 차원/형태 | 생성 주체 | 저장 위치 |
|---|---|---|---|---|
| **`tag_vector`** | 사용자 태그의 고정순서 이진 벡터. `S_fit` 코사인 유사도 계산용 | **36차원 `float[]`, 각 원소 0.0 또는 1.0** | **서버 룰**(LLM 아님) — AI가 반환한 `tags`를 `tag_axis_registry` 순서로 평탄화 | `user_profiles.tag_vector REAL[]` |
| **`scoring_weights`** | 5축 스코어링 가중치 (congestion / profile_fit / distance / local_exposure / trust) | **5키 `dict[str,float]`, 합=1.0** | **서버 룰**(LLM 아님) — `02-ai-strategy.md` §2.2 가산표 + 정규화 | `user_profiles.scoring_weights JSONB` |

- **`weight_vector`라는 이름은 폐기한다.** 두 부서가 같은 이름으로 서로 다른 것을 가리켰던 것이 C1의 근본 원인이다.
- `tag_axis_registry` 테이블·`vector_index` 컬럼은 **그대로 유지**한다. 컬럼명 `weight_vector` → `tag_vector`로만 변경.

### 1.2 근거

1. **보안팀 평가를 채택했다.** 06 §4.3은 "`weight_vector`는 LLM 출력이 아니라 서버 결정론 규칙이 산출한다 — 좋은 설계이며 정확히 평가되어야 한다"고 판정했다. 이 성질(LLM이 수치를 주입할 경로가 없음)은 두 벡터 모두에 대해 유지된다.
2. **DB가 축 순서를 규정하는 구조가 실질적 가치가 있다.** 코드가 아니라 `tag_axis_registry`가 순서를 갖고 있으면 `vector_version` 증가만으로 축 변경 이력이 관리된다. backend가 이미 만든 물리적 근거를 버릴 이유가 없다.
3. **AI의 5축은 벡터가 아니라 가중치다.** 이름이 비슷할 뿐 의미도 차원도 다르므로 병존시키되 이름을 분리하는 것이 유일하게 모순 없는 해법이다.

### 1.3 폐기된 안

| 폐기안 | 폐기 사유 |
|---|---|
| backend가 `weight_vector`를 걷어내고 `tags` 직접 소비 | 매 요청마다 JSONB를 파싱해 코사인 유사도를 계산해야 하고, 축 순서가 코드에 하드코딩된다. 보안팀이 평가한 "서버 룰이 산출하는 통제된 파생값" 구조도 사라진다 |
| `weight_vector` 원소값에 confidence(0.94 등)를 넣는 안 (backend §6.2 A1 예시) | **LLM self-reported confidence를 코사인 유사도의 가중치로 쓰는 것은 근거 없는 가중이다.** AI 문서 스스로 §1.3에서 "self-reported confidence는 실제 정확도와 상관이 약해 참고용일 뿐"이라 명시했다. 이를 스코어링 실입력으로 승격시킬 수 없다 → **원소는 이진 0/1** |
| AI가 5축 가중치를 `weight_vector`라는 이름으로 반환 | 차원(5)이 `tag_axis_registry`와 무관해 backend DDL·`vector_index`가 전부 무의미해진다 |

### 1.4 `tag_axis_registry` 정본 시드 (vector_version = 1, 36차원)

| index | axis | value (정본, 영문) | label_ko (designer 칩 표시명) |
|---|---|---|---|
| 0 | `companion` | `couple` | 연인 |
| 1 | `companion` | `family` | 가족 |
| 2 | `companion` | `with_child` | 아이 동반 |
| 3 | `companion` | `with_parents` | 부모님 동반 |
| 4 | `companion` | `with_pet` | 반려동물 동반 |
| 5 | `companion` | `solo` | 혼자 |
| 6 | `companion` | `friends` | 친구 |
| 7 | `flag` | `child_present` | (칩 없음 — `with_child`에서 파생) |
| 8 | `flag` | `pet_present` | (칩 없음 — `with_pet`에서 파생) |
| 9 | `mobility` | `walk` | 도보 |
| 10 | `mobility` | `bike` | 자전거 |
| 11 | `mobility` | `car` | 차량/드라이브 |
| 12 | `mobility` | `transit` | 대중교통 |
| 13 | `mobility` | `any` | 무관 |
| 14 | `mood` | `calm` | 한적함 |
| 15 | `mood` | `lively` | 활기참 |
| 16 | `mood` | `healing` | 힐링 |
| 17 | `mood` | `romantic` | 로맨틱 |
| 18 | `mood` | `contemplative` | 사색 |
| 19 | `mood` | `unique` | 이색 체험 |
| 20 | `mood` | `family_friendly` | 가족 친화 |
| 21 | `spot_pref` | `local_cafe` | 로컬 카페 |
| 22 | `spot_pref` | `craft_shop` | 공방 |
| 23 | `spot_pref` | `traditional_market` | 전통시장 |
| 24 | `spot_pref` | `nature_view` | 자연경관 |
| 25 | `spot_pref` | `photo_spot` | 포토스팟 |
| 26 | `spot_pref` | `restaurant` | 맛집 |
| 27 | `spot_pref` | `walking_trail` | 산책로 |
| 28 | `spot_pref` | `festival` | 축제/이벤트 |
| 29 | `accessibility` | `parking_required` | 주차 필요 |
| 30 | `accessibility` | `stroller_friendly` | 유모차 접근 |
| 31 | `accessibility` | `wheelchair_friendly` | 휠체어 접근 |
| 32 | `accessibility` | `pet_friendly_required` | 반려동물 동반 가능 |
| 33 | `congestion_pref` | `avoid_priority` | 혼잡 회피 우선 |
| 34 | `congestion_pref` | `indifferent` | 혼잡도 무관 |
| 35 | `congestion_pref` | `unspecified` | (칩 없음 — 미언급 기본값) |

**축 이름 정본**: `companion` / `flag` / `mobility` / `mood` / `spot_pref` / `accessibility` / `congestion_pref`.
- `spot_preference`(AI) → **`spot_pref`로 통일**(backend 표기 채택). 이유: DB 컬럼·API 키에서 짧은 쪽이 유리하고 의미 손실이 없다.
- `congestion_preference` → **`congestion_pref`**로 통일하고 **레지스트리 축에 정식 편입**(backend §5.2 축 목록에 없던 누락 보완).

**슬라이스 규약** (코드가 인덱스 상수를 갖지 않도록 registry에서 조회):
- `S_fit` 코사인 유사도의 사용자 벡터 `u` = **index 14~28 슬라이스**(mood + spot_pref, 15차원)만 사용. 코스 태그 벡터 `v`도 동일 슬라이스.
- 하드 필터 = **index 29~32**(accessibility).
- 가중치 가산(§2.2) 판정 = index 7·8(flag), 21~23(local 계열 spot_pref), 16·18(mood), 33(congestion_pref).

### 1.5 `OnboardingResult` 정본 (backend §7.1 `ai_contract.py` 교체본)

```python
class TagValue(TypedDict):
    value: str            # 영문 코드 (tag_axis_registry.value)
    label: str            # 한국어 표시명 (registry.label_ko와 동일해야 함)
    confidence: float     # 0~1, 값 단위. 표시·진단 참고용 — 임계 판정/스코어링에 사용 금지

class OnboardingResult(TypedDict):
    tags: dict[str, list[TagValue]]      # key = 축 이름 7종. 모든 축이 평탄화되어 여기에만 들어간다
    tag_vector: list[float]              # 36차원, 원소는 0.0 또는 1.0 (이진)
    vector_version: int                  # 현재 1
    scoring_weights: dict[str, float]    # 5키, 합 1.0
    extraction_confidence: float         # 추출 전체 1개. 진단·로그 전용
    unmatched_note: str | None           # 내부 진단 전용 — 저장·화면 노출 금지 (보안 S-M2)
    extracted_by: str                    # "llm-v1" | "rule-v1" | "hybrid-v1"
    fallback_used: bool
```

**AI 반환값 10필드 중 `list[TagValue]`와 어긋났던 5개의 정본 형태**:

| 기존 (AI §1.3) | 정본 형태 | 비고 |
|---|---|---|
| `child_present`: 최상위 boolean | `tags["flag"]`에 `{"value":"child_present", ...}` 원소가 **존재하면 true, 없으면 false** | 최상위 boolean 폐기. `tag_vector[7]`이 동일 정보를 갖는다 |
| `pet_present`: 최상위 boolean | `tags["flag"]`의 `pet_present` 원소 존재 여부 | 동일 |
| `accessibility`: object, boolean 4개 | `tags["accessibility"]`: `list[TagValue]` — **true인 항목만 원소로 포함** | required·기본 false 폐기 → **보안 S-M8(허위 민감정보 생성) 동시 해소.** "미언급"과 "false"가 구조적으로 구분된다 |
| `confidence`: 추출 전체 1개 | 최상위 `extraction_confidence`로 **개명 후 유지** + `TagValue.confidence`(값마다 1개) **신설** | 아래 1.6 참조 |
| `unmatched_note`: string\|null | 최상위 유지. **단 DB 저장·화면 노출 금지, 내부 진단 로그 전용** | 보안 S-M2 권고 (c)안 채택 |

`congestion_pref`도 단일 enum이 아니라 `tags["congestion_pref"]`에 **원소 1개**로 담는다(`unspecified` 포함해 항상 1개). 이유: 축 구조 일관성 + `unspecified`가 "미언급"임을 명시적으로 남기는 AI의 원설계 의도를 보존.

### 1.6 confidence 해상도 정본

**값마다 1개(`TagValue.confidence`)를 정본으로 하고, 추출 전체 1개(`extraction_confidence`)도 별도 필드로 병존시킨다.**

- 근거: backend DDL 예시 `{"v":"couple","c":0.92}`를 채울 수 있어야 하고, designer가 저신뢰 태그를 흐리게 표시하는 등의 UI 여지가 생긴다.
- **사용 제한 (필수 준수)**: `confidence`는 **표시·진단 참고용이며, 스코어링 입력·하드필터 임계·자동 재질의 트리거로 사용하지 않는다.** AI §1.3이 스스로 밝힌 self-report의 신뢰도 한계를 계약으로 고정한 것이다.
- 룰 폴백(`extracted_by="rule-v1"`) 경로에서는 칩 직접 선택분에 `confidence = 1.0`을 부여한다.

### 1.7 잠정 정본 (대표 판단 시 변경 가능)

| 항목 | 잠정 정본 | 변경 트리거 |
|---|---|---|
| `accessibility` 중 `wheelchair_friendly`·`stroller_friendly`의 **영구 저장** | **저장하지 않는다.** `tags`·`tag_vector` DB 반영 시 이 2개 인덱스는 0으로 마스킹하고, 세션(Redis) 한정으로만 하드필터에 사용 | 보안 S-M8 / 법률 민감정보 판정. 대표가 "영구 저장 + 별도 동의" 방침을 택하면 변경 |
| `raw_input` 저장 여부 | 본 문서는 결정하지 않는다 (보안 S-H1 소관). 단 **`raw_input`은 `OnboardingResult`에 포함되지 않는다** — 계약면에서는 이미 분리되어 있다 | S-H1 처리 결과 |

### 1.8 영향받는 부서와 수정 위치

| 부서 | 파일:절 | 수정 내용 |
|---|---|---|
| ai-optimization-engineer | `02-ai-strategy.md` §1.3 | JSON Schema를 1.5의 정본 구조로 재작성 (영문 코드 값, 축명 통일, 5필드 평탄화, accessibility는 true 항목만) |
| ai-optimization-engineer | `02-ai-strategy.md` §1.4, §1.7 | 시스템 프롬프트의 enum·필드명을 영문 코드로 교체. §1.7 칩→태그 매핑표를 registry 기준으로 실제 작성 |
| ai-optimization-engineer | `02-ai-strategy.md` §2.2 | 산출물 이름을 `scoring_weights`로 명시 |
| backend-engineer | `01-backend-design.md` §5.2 | `user_profiles.weight_vector` → `tag_vector`, `scoring_weights JSONB` 컬럼 추가. `tag_axis_registry` 축 목록에 `flag`·`congestion_pref` 추가 + 1.4 시드 36행 반영 |
| backend-engineer | `01-backend-design.md` §6.2 A1 | 12차원 confidence 벡터 예시를 **36차원 이진 벡터**로 교체 |
| backend-engineer | `01-backend-design.md` §7.1 | `ai_contract.py`를 1.5 정본으로 교체 |
| designer | `03-design-spec.md` §3.4 | 칩 라벨을 registry `label_ko`와 1:1 일치시킴. mobility 4칩 + accessibility 4칩을 온보딩 2단계에 추가 (QA J9) |

---

## 2. 결정 D2 — 1:1 비교 리포트 필드 (QA C2)

### 2.1 결정

**응답 봉투·키 구조·타입·단위는 backend `01 §6.2 D1` 형식을 정본으로 한다. 필드 값의 산출은 AI가 담당한다.**

근거: (a) designer §5.2 모바일 비교 UI가 "좌우 대칭 동일 키 구조"를 전제로 이미 설계되어 있고, (b) 미터·영문 enum·int ID는 DB 스키마와 직결되며, (c) AI 형식(한국어 enum, km float, string ID)은 API 계약보다 화면 표기에 가까운 형태라 직렬화층에서 변환하는 편이 자연스럽다.

### 2.2 필드별 정본표

> "잠정" 표기가 없는 항목은 확정이다.

| # | 정본 필드 경로 | 타입 | 단위 / enum | 산출 주체 | 폐기된 표기 |
|---|---|---|---|---|---|
| 1 | `comparison_id` | string | `cmp_` 접두 ULID | backend | — |
| 2 | `generated_at` | string | ISO8601 (+09:00) | backend | — |
| 3 | `hotspot` / `hidden` | object | 두 객체는 **동일 키 구조** | backend | `hotspot_course` / `sumeungil_course` |
| 4 | `*.route_id` | **int** | routes PK | backend | `course_id`(string) |
| 5 | `*.name` | string | — | backend | — |
| 6 | `*.route_type` | string | `hotspot` \| `hidden` | backend | — |
| 7 | `*.congestion.index` | number | 0~100 | backend | (일치 — 유일하게 원래 맞았던 필드) |
| 8 | `*.congestion.level` | string | **`low` \| `mid` \| `high`** | backend | `혼잡`/`여유` (한국어) |
| 9 | `*.congestion.tier` | string | **`A` \| `B` \| `C` \| `none`** | backend | `confidence`: 실측/추정/데이터없음 |
| 10 | `*.congestion.source` | string | 데이터 출처 문자열 | backend | — |
| 11 | `*.congestion.observed_at` | string\|null | ISO8601 | backend | `snapshot_at` |
| 12 | `*.total_distance_m` | **int** | **미터** | backend | `route_summary.distance_km`(km float) |
| 13 | `*.est_duration_min` | int | 분 | backend | `route_summary.duration_min` |
| 14 | `*.bottleneck_segments` | array | `[{seq:int, name:string, delay_min:int}]` | backend | `["string"]` |
| 15 | `*.spot_fit.score` | float | 0~1 | **AI** | — |
| 16 | `*.spot_fit.matched_tags` | string[] | registry `value` 영문 코드 | **AI** | — |
| 17 | `*.spot_fit.unmatched_tags` | string[] | registry `value` 영문 코드 | **AI** | — |
| 18 | `*.spot_fit.matched_spots` | array | `[{place_id:int, name:string, category:string, matched_tags:string[]}]` | **AI** | 최상위 `matched_spots` |
| 19 | `*.review_trust.count` | int | 전체 리뷰 수 | backend | `trust.verified_review_count` (→ D4) |
| 20 | `*.review_trust.companion_matched_count` | int | 동행 유형 일치 리뷰 수 | backend | — |
| 21 | `*.review_trust.coldstart` | bool | `count < 3`이면 true | backend | `trust.coldstart_flag` |
| 22 | `*.path_geojson` | object | GeoJSON LineString | backend | — |
| 23 | `*.path_source` | string | `public` \| `snapped` \| `straight` | backend | — |
| 24 | `hidden.local_merchants` | array | `[{id, name, industry_mid, dist_from_path_m}]` | backend | — |
| 25 | `hidden.load_balancing` | object | §3.5 참조 | backend | — |
| 26 | `verdict.congestion_delta` | float | **절대 포인트** (hidden − hotspot) | backend | — |
| 27 | `verdict.congestion_delta_pct` | int | **상대 %** (음수 = 낮음) | backend | (신설 — QA m3 해소) |
| 28 | `verdict.duration_delta_min` | int | 분 | backend | — |
| 29 | `verdict.fit_delta` | float | 0~1 차 | backend | — |
| 30 | `verdict.headline` | string | **템플릿 조립** (§6) | backend | AI 생성 (폐기) |
| 31 | `scoring_weights_used` | object | 5키, 합 1.0 | **AI** | `user_weights_used` |
| 32 | `score_breakdown` | object | `{hotspot:{5축 점수+total}, hidden:{...}}` | **AI** | (hidden만 담던 것 → 양쪽으로 확장) |
| 33 | `data_freshness.tier` | string | `A`\|`B`\|`C`\|**`mixed`**\|`none` | backend | `data_freshness_warning`(null 고정) |
| 34 | `data_freshness.source` / `.observed_at` / `.notice` | string | — | backend | — |

**단위·enum 변환 규칙**
- **거리**: API는 항상 미터(int). 화면 표시는 designer가 `총 {m/1000, 소수1자리}km`로 환산. AI 문서의 km 표기는 폐기.
- **`congestion.level` 임계** (잠정 — 실측 후 보정): `index < 33` → `low`, `33 ≤ index < 66` → `mid`, `66 ≤ index` → `high`. 3등분이며 **근거 없는 가정값**이므로 문서에 그렇게 표기할 것.
- **`level` → 한국어 라벨 매핑** (designer 표시 전용): `low`=여유 / `mid`=보통 / `high`=혼잡. **API에 한국어를 넣지 않는다.**
- **`tier` ↔ 신뢰도 표기 매핑표** (AI의 3단계를 흡수):

| `tier` | 의미 | 화면 표기 (designer) |
|---|---|---|
| `A` | 실측 데이터 | 실측 |
| `B` | 통계·시간프로파일 기반 추정 | 추정 |
| `C` | 자체 관측 기반 추정, 저신뢰 | 추정(저신뢰) |
| `none` | 데이터 없음 → `index`는 중립값, `level`은 표시하지 않음 | 데이터 없음 |
| `mixed` | (`data_freshness.tier` 전용) 응답 내 item별 tier 혼재 | 항목별 배지 참조 |

`data_freshness.tier`는 **응답 내 최악 tier 또는 `mixed`**를 표기한다 (QA J5 연동). item별 tier는 각 객체의 `congestion.tier`가 정본이다.

### 2.3 designer "잠정 4지표" 매핑 정본

| designer 비교표 행 (03 §5.2) | 정본 필드 | 표시 형식 |
|---|---|---|
| 혼잡도 지수 | `congestion.index` + `congestion.level` + `congestion.tier` | 수치 + 한국어 라벨 배지 + **tier 배지(신설 필요)** |
| 이동 동선 | `total_distance_m` + `est_duration_min` + `bottleneck_segments` | `{km}km · {분}분`, 병목은 `name`만 나열 |
| 맞춤 스팟 | `spot_fit.score` + `spot_fit.matched_spots[].name` | 점수 + 스팟명 |
| 방문 신뢰도 → **"동행 유형 일치 리뷰"로 행 이름 변경** | `review_trust.companion_matched_count` / `review_trust.count` | `{일치}건 / 전체 {전체}건`. **D4 참조 — "인증" 표현 금지** |
| (신설) 델타 카드 | `verdict.congestion_delta_pct` | `↓71% 낮음` — **`_pct` 필드를 쓴다**(m3 해소) |
| (신설) 신선도 고지 | `data_freshness.notice` + `.tier` | 비교 카드 하단 고정 자리 |

### 2.4 폐기된 안

| 폐기안 | 폐기 사유 |
|---|---|
| AI §3.3 스키마(한국어 enum, km, string ID)를 정본화 | designer 대칭 렌더링 전제(backend 봉투)를 깨고, DB PK 타입(int)과 어긋나 직렬화층에 무의미한 변환이 생긴다. 한국어 enum은 i18n·비교 로직 모두에서 불리하다 |
| `confidence: 실측/추정/데이터없음`을 tier와 병존 | 같은 정보를 두 이름으로 내리면 화면과 API가 다시 갈라진다. tier 단일화 + 표시 매핑으로 해소 |
| `data_freshness_warning: null` | 응답당 1개 블록으로 tier 혼재를 표기할 수 없다(J5). 구조화된 `data_freshness` 객체로 대체 |

### 2.5 영향받는 부서와 수정 위치

| 부서 | 파일:절 | 수정 내용 |
|---|---|---|
| ai-optimization-engineer | `02-ai-strategy.md` §3.3 | 스키마 전체를 2.2 정본표로 교체. AI 산출 필드(15~18·31·32)만 자기 소관으로 남기고 나머지는 "backend 직렬화"로 표기 |
| ai-optimization-engineer | `02-ai-strategy.md` §3.2, §3.4 | `S_fit`의 `u`를 tag_vector 슬라이스(14~28)로 명시. `S_trust`·콜드스타트 임계를 `review_trust.count` 기준으로 변경 (D4) |
| backend-engineer | `01-backend-design.md` §6.2 D1 | 응답 예시를 2.2 정본표에 맞춰 갱신 (`congestion_delta_pct`·`spot_fit.matched_spots`·`review_trust.coldstart`·`data_freshness` 구조·`scoring_weights_used`·`score_breakdown` 추가) |
| backend-engineer | `01-backend-design.md` §5.3, §6.0, §7.5 | J5 tie-break(`ORDER BY observed_at DESC, tier ASC`) + item별 tier + `mixed` 허용 반영 |
| designer | `03-design-spec.md` §5.2 | "잠정 필드" 표기 삭제하고 2.3 매핑표로 확정. tier 배지 자리 + `data_freshness.notice` 자리 신설 |
| designer | `mockup/index.html` | 비교 화면·데스크톱 테이블(732행)에 tier 배지·신선도 고지 반영 |

---

## 3. 결정 D3 — M6 동적 로드밸런싱 (QA C3, 보안 S-H7)

### 3.1 결정 (통합안)

**backend §8의 절대 임계 골격을 정본으로 채택하고, AI §4.3의 소프트 페널티 철학을 AMBER 구간에 흡수한다. LB 페널티는 선택 레이어에서 단 한 번만 적용한다.**

### 3.2 파이프라인 단일화 — 순환 및 이중 적용 제거 (핵심)

```
[1] backend : 후보 생성 (공간쿼리) + 혼잡도 주입 + candidates dict 구성
      ↓  (단방향)
[2] AI      : 하드필터(accessibility) → score_routes() → list[RouteScore]
              ★ 이 레이어에는 로드밸런싱 페널티가 없다 (순수 스코어링)
      ↓  (단방향)
[3] backend : select_route_with_balancing(scored, ...) — LB 적용 지점 (유일)
              ★ score_routes()를 재호출하지 않는다. [2]가 반환한 spot_fit을 그대로 재사용
      ↓
[4] backend : build_verdict() 템플릿 조립 (§6)
```

- **AI `score_adjusted(c) = Score(c) × (1 − overload_ratio × PENALTY_COEFF)` (02 §4.3)는 폐기한다.** `score_routes()`는 LB를 모른다.
- **backend `profile_fit(r, weight_vector)` 재호출도 폐기한다.** QA가 지적한 순환의 원인이다. `select_route_with_balancing`의 입력은 `list[RouteScore]`이며 `fit`은 `RouteScore.spot_fit`을 그대로 쓴다.

**정본 시그니처** (backend §7.1 교체본과 연동):

```python
def score_routes(profile: OnboardingResult,          # ← tag_vector·scoring_weights·tags 전체 전달
                 candidates: list[dict],             # backend 공간쿼리 결과 (필수 키는 3.3)
                 congestion: dict[int, float],       # route_id(int) -> 0~100
                 ) -> list[RouteScore]:
    """M3. 하드필터 + 순수 스코어링. 로드밸런싱 페널티를 적용하지 않는다.
       계약: (1) candidates 밖의 route_id 반환 금지
            (2) 하드필터는 이 함수 내부에서만 수행 (backend는 공간·인기도 필터만)"""

# backend 소관 — AI 계약 아님
def select_route_with_balancing(scored: list[RouteScore], user_ctx) -> BalancedChoice: ...
```

`congestion` 키는 **`route_id: int`**로 확정한다(AI의 string `course_id` 폐기 — D2 #4와 동일 근거). QA J1의 시그니처 권고를 그대로 채택했다.

### 3.3 `candidates` dict 필수 키 (backend가 채워 AI에 전달)

| 키 | 타입 | 용도 |
|---|---|---|
| `route_id` | int | 식별자 |
| `has_parking` / `pet_friendly` / `stroller_ok` / `wheelchair_ok` | bool | 하드필터 (registry index 29~32 대응) |
| `total_distance_m` / `baseline_distance_m` | int | `S_dist`의 `detour_ratio` |
| `local_spot_count` | int | `S_local` |
| `review_count` / `companion_matched_count` | int | `S_trust` (D4) |
| `course_tag_vector` | float[] | `S_fit` 코사인 — **tag_vector와 동일 36차원, 동일 registry 순서** |
| `popularity_percentile` | float | 후보 풀 판정 (backend가 이미 필터링하지만 AI 설명용) |

### 3.4 임계·윈도 정본

| 항목 | 정본 | 비고 |
|---|---|---|
| 측정 지표 | `weighted_count = 1.0×안내발급 + 2.0×저장 + 0.3×상세조회` | backend §8.2 채택 |
| 윈도 | **6시간** (Redis 시간버킷 6개 합산) | backend 값 채택. AI의 3시간 폐기 |
| 1순위 임계 방식 | **절대** — `load_ratio = weighted_count / effective_capacity` | GREEN <0.6 / AMBER 0.6~0.85 / RED >0.85 (**전부 가정값**) |
| 2순위 임계 방식 (**AI안 흡수**) | `effective_capacity`를 산출할 수 없는 코스는 **클러스터 내 상대 share** 사용: `share > 0.4` → AMBER 상당, `share > 0.6` → RED 상당 | AI §4.2의 "실 트래픽 없는 신규 서비스에 절대 수치는 근거가 없다"는 지적이 타당하다. capacity 기본값(trail=300 등)이 전부 가정값이므로 capacity 미확보 코스에는 상대 지표가 더 정직하다 |
| AMBER 동작 | **확률적 분산 A 60% / 대안 40%** (backend) — 이것이 AI의 "소프트 페널티"에 해당하는 구간 | 완전 차단이 아니므로 AI 원칙 충족 |
| RED 동작 | A 제외. **단 대안 풀이 비면 배제하지 않는다** — §8.4 F3 정직 안내와 함께 원래 코스를 유지한다 | AI §4.3 "완전 차단하지 않음" 원칙을 조건부로 보존 |
| `profile_fit < 0.4` 컷 | 유지 (backend §8.3) | 분산을 위해 취향에 안 맞는 코스를 밀어넣지 않는다 |
| 대안 부족 폴백 | **backend 3단계** (F1 시간분산 → F2 반경확대 → F3 정직안내) | AI의 1단계는 F1에 흡수 |

**"완전 배제"와 "완전 차단 금지"의 충돌 해소 원칙**: 배제는 **대안이 실재할 때만** 성립한다. 대안 풀이 비면 배제하지 않고 정직하게 혼잡을 고지한다. 이로써 backend의 RED 배제와 AI의 원칙이 동시에 성립한다.

### 3.5 `load_balancing` 응답 객체 정본

```jsonc
"load_balancing": {
  "applied": true,
  "reason": "primary_over_threshold" | "primary_amber_distributed" | "time_shift"
          | "region_expanded" | "no_alternative",
  "original_route_id": 550,          // applied=true일 때만
  "assigned_rank": "B",
  "notice": "...",                    // 사용자 노출 문구 (designer J7이 렌더)
  "suggested_departure": "iso8601|null"  // reason=time_shift일 때만
}
```

### 3.6 카운터 조작 방지 (보안 S-H7 반영 — 필수)

1. **주체 단위 dedupe**: `SETNX lb:dedupe:{route_id}:{subject_hash}:{yyyymmddHH}` (TTL 2h)로 **동일 주체·동일 route는 시간당 1회만 계상**. `subject_hash = HMAC(server_key, user_id 또는 guest_id)`.
2. **비인증 `viewed`는 계상하지 않는다.** `guest_id` 쿠키가 없는 요청의 상세조회는 가중치 0. 계상 대상은 `issued`(1.0)·`saved`(2.0)와 게스트/회원 식별된 `viewed`(0.3)뿐이다.
3. **이상 급증 감지**: `lb:cnt:*` 시간버킷 증가율이 직전 6버킷 평균의 5배를 넘으면 알람 + 해당 버킷을 Tier C 산출에서 제외 (임계 5배는 가정값).
4. 8.2절에 **"이 지표는 조작 가능한 신호이며 dedupe·이상탐지가 전제된다"**를 명문화한다.

### 3.7 폐기된 안

| 폐기안 | 폐기 사유 |
|---|---|
| AI §4.3 `score_adjusted` (스코어링 내부 페널티) | backend 선택 레이어와 **이중 적용**된다. 페널티는 한 레이어에서만 적용한다는 것이 본 결정의 핵심 |
| backend §8.3 `profile_fit(r, weight_vector)` 재호출 | AI `score_routes`가 이미 LB 없는 fit을 반환하므로 재호출은 순환이자 중복 연산 |
| AI 3시간 윈도 | backend 6시간 버킷 구조와 병존 불가. 시연 규모에서 6h가 표본 부족을 덜 겪는다 |
| 절대 임계 단독 채택 | `daily_capacity` 기본값이 전부 가정값이라 capacity 미확보 코스에서 무근거 판정이 된다 → 2순위 상대 지표 병기 |

### 3.8 영향받는 부서와 수정 위치

| 부서 | 파일:절 | 수정 내용 |
|---|---|---|
| ai-optimization-engineer | `02-ai-strategy.md` §4 전체 | §4.1·4.2를 "3.4의 2순위 상대 지표 산출 담당"으로 축소. **§4.3 소프트 페널티 삭제**. §4.4는 backend F1으로 흡수됨을 명시 |
| ai-optimization-engineer | `02-ai-strategy.md` §3.1-4 | "다양성/로드밸런싱 재순위" 단계를 파이프라인에서 **삭제** (backend 소관으로 이관) |
| backend-engineer | `01-backend-design.md` §7.1 | `score_routes` 시그니처를 3.2 정본으로 교체 + `candidates` 필수 키(3.3) 명세 |
| backend-engineer | `01-backend-design.md` §8.2~8.3 | 2순위 상대 지표 분기 추가, `profile_fit` 재호출 제거(`RouteScore.spot_fit` 재사용), 3.6 dedupe 규칙 추가 |
| designer | `03-design-spec.md` §5.2, `mockup/index.html` | §5 J7 지시 참조 |

---

## 4. 결정 D4 — N1 잔재 제거 (QA J6) — **타협 없음**

### 4.1 결정

**`verified_review_count`, `실방문 인증 리뷰`, `방문 인증`, `인증 리뷰` 표현을 산출물 전체에서 제거한다.**

정본 필드는 `review_trust.count`(전체 리뷰 수) + `review_trust.companion_matched_count`(동행 유형이 일치하는 리뷰 수)이며, `reviews.companion_type` 컬럼만으로 산출 가능하다.

### 4.2 근거

N1(현장 사진 EXIF 인증)은 PRD가 구현하지 않기로 명시한 항목이다. 구현하지 않은 기능을 **스코어링 실입력이자 비교표의 우위 근거로 사용하는 것은 "없는 기능을 강점으로 주장"하는 것**이며, 심사 시연에서 지적당하면 프로젝트 전체의 정직성 서사(PRD 전반의 원칙, backend §11.3의 N1 차단, AI의 hallucination 억제 설계)가 함께 무너진다. backend는 `verified_*`/`photo_*`/`exif_*` 컬럼을 하나도 만들지 않는 방식으로 이미 올바르게 차단했다.

`companion_matched_count`가 대체재로 적절한 이유: (a) N1 없이 산출 가능, (b) "나와 같은 구성으로 다녀온 사람의 후기"라는 개인화 서사가 서비스 차별화에 오히려 더 부합, (c) 데이터가 없으면 0이 나오고 그것이 사실이다.

### 4.3 제거 대상 전수 (각 부서가 grep으로 0건을 확인할 것)

| 부서 | 위치 | 조치 |
|---|---|---|
| ai-optimization-engineer | `02 §3.3` `trust.verified_review_count` | → `review_trust.count`로 개명 |
| ai-optimization-engineer | `02 §3.3` `"source": "실방문 인증 리뷰"` / `"일반 후기(비인증)"` | → `source` 필드 자체 삭제 (두 값 모두 인증 유무를 전제) |
| ai-optimization-engineer | `02 §3.3` `trust.coldstart_flag` | → `review_trust.coldstart` |
| ai-optimization-engineer | `02 §3.4` 콜드스타트 `verified_review_count < REVIEW_MIN_THRESHOLD` | → `review_trust.count < 3` |
| ai-optimization-engineer | `02 §3.2` `S_trust` 정의 | 입력을 `count` + `companion_matched_count`로 재정의 |
| designer | `03 §5.2` 비교표 "방문 신뢰도" 행 | 행 이름 → **"동행 유형 일치 리뷰"**, 값 → `{companion_matched_count}건 / 전체 {count}건` |
| designer | `mockup/index.html` 700~701행 | `광고성 후기 위주` / `실방문 인증 리뷰` 문구 교체 |
| designer | `mockup/index.html` 732행 | 데스크톱 테이블 동일 수정 |

**"인증 방문 준비 중" 비활성 배지 처리**: PRD 6.4가 "자리만 비활성 상태로 표시"를 명시 허용했으므로 **배지 자체는 유지 가능**하다. 단 **비교표의 지표 행(우위 비교가 발생하는 자리) 안에는 두지 않는다.** 별도 영역으로 분리해 "향후 기능 예고"임이 분명하게 보이게 한다.

**content-marketer 전달**: 대외 문서·랜딩 카피에 "실방문 인증", "방문 인증", "인증 리뷰"를 쓰지 않는다.

---

## 5. 결정 D5 — `build_verdict()` (보안 S-H5, QA J2)

### 5.1 결정

**`build_verdict`를 LLM 호출로 구현하지 않는다. backend의 템플릿 문자열 조립으로 대체하며, 소관을 AI에서 backend로 이관한다.**

```python
class Verdict(TypedDict):
    congestion_delta: float
    congestion_delta_pct: int
    duration_delta_min: int
    fit_delta: float
    headline: str

def build_verdict(hotspot: RouteScore, hidden: RouteScore, deltas: dict) -> Verdict:
    """M3 헤드라인. LLM을 호출하지 않는다. 반환 타입이 str이 아니라 Verdict임에 주의."""
```

### 5.2 근거

1. **보안 S-H5**: `-> str` 자유 문자열을 반환하는 2차 LLM 호출에는 AI §1.5의 6개 방어 계층이 **하나도 적용되지 않는다**(스키마 강제 불가, 프롬프트 미설계, 재검증 대상 없음). 입력이 공공데이터 유래 상호명·코스명이므로 **간접 프롬프트 인젝션 문자열이 화면 최상단 headline에 그대로 렌더된다.**
2. **필요가 없다.** `deltas`는 backend가 이미 계산한 수치다. 함수 시그니처가 스스로 LLM 불필요를 말하고 있다.
3. **QA J2**: 요청당 LLM 호출은 AI §1.6 비용 추정에 없고, AI §0의 "경로 랭킹은 LLM 생성이 아니다"라는 차별화 서사를 스스로 깨며, 시연 중 LLM 장애 시 핵심 화면이 빈다(§1.7 폴백은 온보딩 전용).

### 5.3 headline 템플릿 정본

**안전 규칙 (필수)**: headline에는 **수치·enum·개수만** 삽입한다. **코스명·상호명·스팟명 등 외부 데이터 유래 문자열을 삽입하지 않는다.** 이 한 줄로 간접 인젝션 표면이 구조적으로 0이 된다.

| 조건 | 템플릿 |
|---|---|
| 기본 (혼잡도 우위 + 시간 열위) | `"{duration_delta_min}분 더 걸리지만 혼잡도는 {abs(congestion_delta):.0f}p 낮고, 맞춤 조건 {matched_count}개를 만족합니다."` |
| 혼잡도·시간 모두 우위 | `"혼잡도가 {abs(congestion_delta):.0f}p 낮고 이동 시간도 {abs(duration_delta_min)}분 짧습니다. 맞춤 조건 {matched_count}개를 만족합니다."` |
| 혼잡도 열위 또는 동등 | `"혼잡도 차이는 크지 않지만, 맞춤 조건 {matched_count}개를 만족하고 로컬 상점 {local_count}곳을 지납니다."` |
| `tier == "none"` (혼잡도 데이터 없음) | `"혼잡도 데이터가 없어 비교에서 제외했습니다. 맞춤 조건 {matched_count}개를 만족합니다."` |

- `matched_count = len(hidden.spot_fit.matched_tags)`
- 출력 길이 상한 120자. 초과 시 기본 템플릿으로 폴백.
- 렌더는 **텍스트 노드로만** 한다 (`dangerouslySetInnerHTML` 금지 — 보안 S-M7).

### 5.4 폐기된 안

| 폐기안 | 폐기 사유 |
|---|---|
| LLM 유지 + 방어 6종 추가 | 방어를 다 붙여도 자유 문자열 특성상 잔여 위험이 남고, 요청당 비용·지연·장애 노출이 새로 생긴다. 얻는 것(문장 다양성)이 잃는 것에 비해 작다 |
| headline에 코스명을 넣어 자연스럽게 만드는 안 | 코스명이 공공데이터 유래 문자열이므로 인젝션·XSS 표면이 그대로 부활한다 |

### 5.5 재검토 트리거 (보안팀 요구 반영)

`02-ai-strategy.md` §1.5 말미에 다음을 추가한다:
> **이 절의 방어는 온보딩 추출 호출에 한정된다. LLM 호출을 새로 추가하거나 LLM에 도구 권한을 부여하는 경우, 해당 호출에 대해 이 표를 개별적으로 충족시켜야 하며 security-engineer 재검토를 거친다.**

---

## 6. 대표 결정 대기 목록

> **설계 진행을 막지 않기 위해 전부 잠정 정본을 정해 두었다. 대표 판단 시 변경 가능.**

| # | 항목 | 잠정 정본 (지금 이대로 설계 진행) | 대표 판단이 필요한 이유 | 관련 |
|---|---|---|---|---|
| E1 | 게스트 체험 경로 도입 여부 (Q-I3) | **도입한다.** 프로필은 **서버 Redis 24h + 회원가입 시 승격**(backend §10.1 채택), designer 배너를 "체험 모드 — 24시간 임시 보관되며, 가입하시면 그대로 이어집니다"로 수정 | 정책 판단(심사위원 무가입 체험 vs 개인정보 최소수집) | QA J3 |
| E2 | `raw_input` 영구 저장 여부 | **저장하지 않는다** (보안 S-H1 1순위 권고 채택) | 재추출 목적 보관의 사업적 가치 vs 민감정보 누적 리스크 | S-H1 |
| E3 | `wheelchair_friendly`·`stroller_friendly` 영구 저장 | **저장하지 않는다** (세션 한정 필터) | 민감정보 판정 + 개인화 지속성 트레이드오프 | S-M8, D1 §1.7 |
| E4 | LLM 벤더 ZDR(zero-data-retention) 계약 | **미확인.** 확정 전까지 문서에 "확인 필요"로 유지하며 성과로 주장하지 않는다 | 비용·계약 판단 | S-M4, U7 |
| E5 | 로드밸런싱 임계값 0.6/0.85, capacity 기본값(trail=300 등) | **가정값으로 유지**하고 문서에 "실측 전 초기값 + 보정 루프 포함"으로 정직하게 표기 | 근거 데이터 확보 여부 | C3, Q-I6/I7 |
| E6 | 브랜드 로마자 표기 (SUMUENGIL vs Sumeungil) | **`Sumeungil`** (폴더명·로마자 표기법 일치) | 브랜드 결정 | R9 |
| E7 | 프론트/API 배포 오리진 동일 여부 | **동일 사이트 배포**(app./api. 서브도메인) 전제로 `SameSite=Lax` 유지 | 인프라 결정 | S-M5, U1 |

---

## 7. 부서별 수정 지시 목록 (다음 단계 위임용)

> 각 부서는 **본 문서를 먼저 읽고** 자기 문서를 여기에 맞춘다. 본 문서에 없는 사항을 임의로 바꾸지 않는다.
> 공통 완료 기준: 수정 후 자기 산출물에서 `weight_vector` / `verified_review_count` / `실방문 인증` / `hotspot_course` / `distance_km` 문자열이 **0건**임을 확인할 것.

### 7.1 ai-optimization-engineer (`02-ai-strategy.md`)

| # | 절 | 조치 | 근거 |
|---|---|---|---|
| A1 | §1.3 | JSON Schema를 §1.5 정본 구조로 재작성: 영문 코드 값, 축명 7종 통일, `child_present`/`pet_present`/`accessibility` 평탄화, accessibility는 **true 항목만** 포함, `congestion_pref`도 축으로 편입 | D1 |
| A2 | §1.3 | `TagValue.confidence`(값 단위) 신설 + `extraction_confidence`(전체 1개) 병존. **둘 다 스코어링·임계 판정에 사용 금지**를 명문화 | D1 §1.6 |
| A3 | §1.3 | `unmatched_note`를 **내부 진단 전용(저장·노출 금지)**으로 규정 | S-M2 |
| A4 | §1.4 | 시스템 프롬프트의 enum·필드명을 §1.4 registry 영문 코드로 전면 교체 | D1 |
| A5 | §1.5 | 말미에 §5.5 재검토 트리거 문장 추가. 계층3("300자 절단")의 목적을 **injection 방어 → 비용·DoS 방어**로 정정 | S-H5, S-L7 |
| A6 | §1.7 | 칩→태그 직접 매핑표를 registry 기준으로 **실제 작성**. `#반려동물 동반` → `flag:pet_present` + `accessibility:pet_friendly_required`처럼 accessibility까지 파급되는 규칙 명시 | QA J9 |
| A7 | §2.2 | 산출물 이름을 `scoring_weights`로 명시. `weight_vector` 표현 삭제 | D1 |
| A8 | §3.1 | 파이프라인 4단계("다양성/로드밸런싱 재순위")를 **삭제** — backend 소관 | D3 |
| A9 | §3.2 | `S_fit`의 `u`·`v`를 **tag_vector index 14~28 슬라이스**로 명시. `S_trust` 입력을 `count`/`companion_matched_count`로 재정의 | D1, D4 |
| A10 | §3.3 | 스키마 전체를 §2.2 정본표로 교체. AI 산출 필드만 자기 소관으로 남기고 나머지는 "backend 직렬화"로 표기 | D2 |
| A11 | §3.4 | 콜드스타트 임계를 `review_trust.count < 3`으로 변경. "인증" 표현 전면 삭제 | D4 |
| A12 | §4 | §4.3 **소프트 페널티 삭제**. §4.1·4.2는 "capacity 미확보 코스용 2순위 상대 지표 산출"로 축소. §4.4는 backend F1에 흡수됨을 명시 | D3 |
| A13 | (신설) | `score_routes` 정본 시그니처(§3.2)와 `candidates` 필수 키(§3.3)를 자기 문서에 반영 | D3, QA J1 |
| A14 | §1.6 | **비용 추정에서 compare 요청당 LLM 호출을 제외**(build_verdict가 LLM이 아니게 되었으므로). 온보딩 1건 기준임을 명시 | D5 |

### 7.2 backend-engineer (`01-backend-design.md`)

| # | 절 | 조치 | 근거 |
|---|---|---|---|
| B1 | §5.2 | `user_profiles.weight_vector` → **`tag_vector REAL[]`**, `scoring_weights JSONB` 컬럼 추가 | D1 |
| B2 | §5.2 | `tag_axis_registry` 축 목록에 `flag`·`congestion_pref` 추가 + **§1.4 시드 36행**을 문서에 수록 | D1 |
| B3 | §6.2 A1 | 12차원 confidence 벡터 예시를 **36차원 이진 벡터**로 교체. `tags` 구조를 §1.5 정본에 맞춤 | D1 |
| B4 | §7.1 | `ai_contract.py`를 §1.5 `OnboardingResult` + §3.2 `score_routes` + §5.1 `Verdict`로 전면 교체. **`build_verdict`를 AI 계약에서 제외하고 backend 소관으로 이동** | D1, D3, D5 |
| B5 | §6.2 D1 | 응답 예시를 §2.2 정본표로 갱신 (`congestion_delta_pct`, `spot_fit.matched_spots`, `review_trust.coldstart`, `data_freshness` 구조, `scoring_weights_used`, `score_breakdown` 추가) | D2 |
| B6 | (신설) | §5.3 헤드라인 템플릿 4종 + 안전 규칙(외부 문자열 미삽입, 120자 상한)을 문서화 | D5 |
| B7 | §8.2~8.3 | 2순위 상대 share 분기 추가. **`profile_fit()` 재호출 제거** → `RouteScore.spot_fit` 재사용. RED 시 대안 풀이 비면 배제하지 않음을 명시 | D3 |
| B8 | §8.2 | dedupe(`SETNX lb:dedupe:*`), 비인증 `viewed` 미계상, 이상 급증 감지, "조작 가능 신호임" 명문화 | S-H7 |
| B9 | §5.3, §6.0, §7.5 | 전광판 쿼리 `ORDER BY observed_at DESC, tier ASC` tie-break + item별 tier 포함 + `data_freshness.tier`에 `mixed` 허용 | QA J5 |
| B10 | §6.0, §10.1~10.2 | `X-Guest-Id` 헤더 수용 **삭제**(HttpOnly 쿠키 단일 경로), 승격을 `GETDEL`로 원자적 1회 소비, 승격 직후 guest_id 재발급 | QA J4, S-H4 |
| B11 | §12.4 | Q-I5(태그 축 확정)를 **본 문서로 확정됨**으로 갱신. Q-I3는 §6 E1 잠정 정본 반영 | D1, E1 |
| B12 | §8.3 | m1(read-then-decide 비원자성)을 "허용 오차 + 근거(윈도 6h·일 단위 capacity)"로 **설계 결정으로 명시 기록** | QA m1 |

### 7.3 designer (`03-design-spec.md` + `mockup/index.html`)

| # | 위치 | 조치 | 근거 |
|---|---|---|---|
| G1 | §3.4 | 칩 라벨을 §1.4 registry `label_ko`와 1:1 일치. **mobility 4칩(도보/자전거/차량·드라이브/대중교통) + accessibility 4칩(주차 필요/유모차 접근/휠체어 접근/반려동물 동반 가능)을 온보딩 2단계에 추가** | D1, QA J9 |
| G2 | §5.2 | "잠정 필드" 표기 삭제 → §2.3 매핑표로 확정. 라벨/포맷을 정본 필드에 맞춤 | D2 |
| G3 | §5.2 | **tier 배지 자리** 신설 (실측/추정/추정(저신뢰)/데이터 없음) + **`data_freshness.notice` 노출 자리** 신설 | D2, QA J5 |
| G4 | §5.2 | 비교표 4행 "방문 신뢰도" → **"동행 유형 일치 리뷰"**, 값은 `companion_matched_count / count`. "인증 방문 준비 중" 배지는 **비교표 밖 별도 영역**으로 이동 | D4 |
| G5 | §5.2 | 델타 카드는 `verdict.congestion_delta_pct`를 사용함을 명시 (`↓71% 낮음`) | QA m3 |
| G6 | §5.2 (신설) | **J7 — M6 분산 안내 배너 컴포넌트**를 AI 경로 비교 화면에 추가. `load_balancing.reason` 5종에 대응하는 상태 정의: `primary_over_threshold`/`primary_amber_distributed` → 분산 안내 배너, `time_shift` → 시간대 제안 카드(+`suggested_departure` 표기), `region_expanded` → 인근 지역 안내, `no_alternative` → 정직 안내. **목업에 최소 1개 상태를 실제 렌더**할 것 | QA J7 |
| G7 | 전 화면 (신설) | **J8 — 법률 요구 UI 4종 자리 확보**: (a) 온보딩 개인정보 수집 안내 문구 + 동의 체크박스, (b) LLM 국외이전 고지 — **자유 텍스트 입력 필드 활성화 이전**에 배치하고 미동의 시 **칩 전용 경로**로 유도(S-M10), (c) 전역 footer 공공데이터 출처 표기(이용약관상 의무일 가능성 — 우선순위 높음), (d) 지도 하단 우측 SDK 로고·저작권 표기 영역(최소 높이 확보). 문구는 `07-legal-review.md` §3 초안을 쓰되 **"확정 전 임시"** 표기. **스펙과 목업 양쪽에 반영** | QA J8, S-M10 |
| G8 | §3.6 | **실선/점선은 `path_source` 전용 신호로 예약**(점선 = 좌표열 미확보). 숨은길/핫플 구분은 색상 + 핀 형태로만. 목업 755~759행 수정 | QA m4 |
| G9 | §4-0️⃣ | 게스트 배너를 **"체험 모드 — 24시간 임시 보관되며, 가입하시면 그대로 이어집니다"**로 수정. 회원가입 화면에 "체험 중 만든 취향 프로필 이어받기" UX, 4️⃣ 화면에 게스트 저장 시도 시 로그인 유도 모달 추가 | QA J3, E1 |
| G10 | §9 | "모든 수치 데이터에 예시 데이터 캡션" 서술을 실제와 일치시킴 (전광판·비교 화면 개별 캡션 + 전역 footer) 또는 나머지 2화면에 캡션 추가 | QA m2 |
| G11 | `mockup/index.html` | 700~701행·732행 "실방문 인증 리뷰"/"광고성 후기 위주" 문구 교체 | D4 |

---

## 8. 개정 이력

| 판 | 일시 | 내용 | 작성 |
|---|---|---|---|
| v1 | 2026-07-22 | 최초 확정 — C1(D1)·C2(D2)·C3(D3)·J6(D4)·S-H5(D5) 5건 정본화 | planning-lead |

---

## 9. 핸드오프 노트

```
[다음 부서가 알아야 할 것]
1. 이 문서가 01/02/03 문서보다 상위 권위다 — 충돌 시 이 문서를 따르고, 자기 문서를 §7의
   부서별 지시 목록대로 수정한 뒤 `weight_vector`/`verified_review_count`/`실방문 인증`/
   `hotspot_course`/`distance_km` 문자열이 0건임을 확인해 보고할 것.
2. 계약의 뼈대 3줄: 태그는 `tag_vector`(36차원 이진, registry 순서)와 `scoring_weights`(5축)로
   분리했고, 비교 리포트는 backend 봉투(hotspot/hidden·int·미터·영문 enum)가 정본이며,
   로드밸런싱 페널티는 backend 선택 레이어 단 한 곳에서만 적용한다(AI §4.3 폐기).
3. `build_verdict`는 LLM이 아니라 backend 템플릿 조립으로 확정됐다 — headline에 코스명·상호명 등
   외부 데이터 문자열을 넣지 않는 것이 인젝션 방어의 핵심이므로 임의로 되돌리지 말 것.
```
