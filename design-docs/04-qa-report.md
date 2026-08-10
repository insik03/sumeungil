# 04-qa-report — 숨은길 (SUMUENGIL) 3차 게이트 검수

- **작성**: qa-reviewer
- **1차 작성일**: 2026-07-22 / **2차(재검수) 작성일**: 2026-07-22
- **검수 등급**: 약식 (CLAUDE.md 검수 경량화 규칙) — 대상이 코드가 아닌 설계 문서
- **검수 대상**: `00-PRD.md`, `01-backend-design.md`, `02-ai-strategy.md`, `03-design-spec.md`, `mockup/index.html`, `07-legal-review.md`, `08-interface-contract.md`
- **검수 방식**: 문서 대조(부서 간 인터페이스 계약) + 목업 실검증 + 시크릿 스캔

---

# 3차 게이트 재검수 — M8~M10 스코프 개정 (2026-07-23)

- **작성**: qa-reviewer / **작성일**: 2026-07-23
- **검수 등급**: **풀검수로 승격** (M8이 개인정보 = 위치 + 사진을 재도입하므로). 단 본 파이프라인 산출물은 코드가 아닌 설계 문서·목업이므로 실행 검증은 목업 구조 무결성·grep 실측·문서 대조로 수행.
- **검수 대상 (증분만)**: `01-backend-design.md §15`(M8~M12), `03-design-spec.md §13`(M8~M10), `mockup/index.html` 4/5/3 화면 변경분, 대조용 `08-interface-contract.md`(compare 34필드·태그 계약)·`02-ai-strategy.md`(이번 미수정 확인).
- **검증 방법**: 부서의 "격리했다/안 쓴다" 주장을 신뢰하지 않고 **직접 grep·git·파서로 실측**했다.

## 재검수 판정 (최상단)

> ## **Critical 0건 / Major 0건 / Minor 1건(N7) → 3차 게이트 통과 (QA 측)**
>
> M8~M10 스코프 개정분은 J6(N1 잔재) 회귀 없이, 08 정본 불가침·쿠폰 미결합·EXIF 비저장·시크릿 없음을 **실측으로 모두 확인**했다. 신규 Minor 1건(N7 — 동의 캡처가 backend API 스펙에 없음)은 구현 착수 전 반영 조건으로 넘긴다.
> **주의**: 직전 라운드의 미해결 **Major N1(전광판 B1 응답 tier 미반영, J5 잔여)** 는 이번 증분과 무관하게 **여전히 열려 있다** — 이번 개정으로 닫히지 않았다.

---

## A. J6 회귀 여부 (최우선) — **회귀 없음 확인**

`review_trust`·`companion_matched_count`·compare 34필드·AI 스코어링에 M8이 새어들었는지 직접 대조했다.

| 검증 지점 | 방법 | 결과 |
|---|---|---|
| `visit_verifications`가 다른 테이블과 JOIN되는가 | `01`에서 `visit_verif` 전수 grep | **JOIN 0건.** 자체 DDL(§15.1.2)·인덱스 2개·`insert` 1회에만 등장. `reviews`/`routes`/`compare` 어디와도 조인 안 됨 |
| M8 값이 `review_trust.count`/`.companion_matched_count`에 주입되는가 | §15.0 계약표 + §15.1.4 의사코드 4번 주석 대조 | **주입 없음.** 배지만 반환, `review_trust`·스코어링 미반영. 08 §2.2 #19·#20 불가침 유지 |
| `tag_vector`/`scoring_weights`를 M8~M10이 산출·소비하는가 | §15.0 계약표 | **없음.** 태그·가중치 파이프라인 밖 |
| compare 34필드에 M8/M9가 필드를 추가하는가 | §15.0 + `08` git diff | **추가 없음.** M10만 기존 `path`·`path_source`(#22·#23) 값을 채우는 방식 개선(스키마 불변) |
| `02-ai-strategy.md`가 이번에 수정됐는가 / M8 내용이 섞였는가 | `git diff HEAD`, `git log`, M8 키워드 grep | **미수정**(working tree clean, 최종 커밋은 이전 비주얼 톤 라운드). `visit_verif`/`방문 인증`/`geolocation`/`photo_ref` **0건** |
| designer가 인증을 비교 우위 근거로 쓰는가 | `03 §13.1.3` + 목업 `.pending-feature-note` | **안 씀.** 배지는 비교표 지표 행 **밖**에 유지, 문구도 "비교 지표 산정에는 반영되지 않습니다"로 정정 |

→ **J6 회귀 없음.** backend는 독립 테이블로 격리, designer는 지표 행 밖 유지 — 둘 다 주장대로 실재함을 실측 확인. "인증 → 신뢰도" 의존이 재생성되지 않았다.

## B. 쿠폰(N2) 미결합 — **직접 grep 재확인, 결합 0건**

| 문서 | `쿠폰` 실측 결과 |
|---|---|
| `01-backend-design.md` | 4개소 전부 후순위 명시·N1 위조유인 근거·N2 처리행·§15.6 검증 서술. **M8 본문(§15.1.1~15.1.6)·`visit_verifications` 스키마·H1~H3 API·의사코드에 0건.** 금전 보상 필드·엔드포인트 없음 |
| `03-design-spec.md` | 전부 "쿠폰 없음"·"결합하지 않는다" 문맥. M8 UI에 금전 요소 없음 |
| `mockup/index.html` | 5건 모두 주석(HTML `<!-- -->` 1·CSS `/* */` 1·JS `//` 3). **HTML+CSS+JS 주석 전부 제거 후 사용자 노출 텍스트에 `쿠폰` 0건**(파서 실측) |

→ R10 제약 2(금전 유인 미결합) 충족. designer/backend 주장 재확인 완료.

## C. 백엔드–디자인 인터페이스 정합성 (병렬 위임 대조)

| 대조 항목 | designer(§13, 목업) | backend(§15) | 판정 |
|---|---|---|---|
| M8 방문 인증 모달 3조건 | 동의 + 위치확인 + 사진첨부 3조건 충족 시 제출 활성(`updateVerifySubmit`) | H1 `POST /visits/verify` multipart: `photo` + meta`{place_id, lat, lng}` | 위치·사진 정합. **동의(consent)는 backend 스펙에 수신·기록 필드 없음 → N7(Minor)** |
| GPS 좌표 처리 이어붙임 | 위치확인 = **더미**(실 Geolocation 없음, 상태 텍스트만). backend 연동 필요 명시(§13.6 D8) | lat/lng를 **body로만**·소수3자리 반올림·거리계산 후 폐기(§3.1 L1/L2, §15.1.4) | **정합.** 동일 좌표 shape(body·3자리) 가정. 더미→실 API 전환 시 그대로 이어붙는 형태 |
| M9 오디오 필드·엔드포인트 | 순수 시각 시뮬레이션(`data-duration`/`data-current`), 음원 미연동 | I1 `GET /places/{id}/audio-guides` → `stream_url` 외 | **충돌 없음**(목업은 시뮬레이션, 필드 바인딩 없음). 양쪽 "미연동" 일치 |
| M10 Tmap 필드·엔드포인트 | `.btn--tmap` 버튼 + "backend 연동 후 반영" 캡션, 로고 미모사 | J1 `POST /routes/directions` + `RouteProvider`, 응답 08 #22·#23 동형 | **충돌 없음**(버튼에 필드 바인딩 없음). 양쪽 "실연동은 backend 후속" 일치 |

→ 병렬 위임에도 세 기능의 좌표·필드·엔드포인트 가정이 어긋나지 않는다. **유일한 간극은 동의 캡처(N7)** — 개인정보 재도입 기능이므로 legal 입력으로 명시 필요.

## D. EXIF/R3 제약 실제 준수 — **스키마 직접 확인, 준수**

- **EXIF 컬럼 미생성**: `01` 전체 `exif` grep — 전부 "**일부러 만들지 않았다**"는 차단 근거 서술(§11.3 N1, §15.1.2 주석, 의사코드 `EXIF 미파싱·strip`). `visit_verifications` DDL에 `exif_*` 컬럼 **0개**.
- **원좌표 비저장**: DDL은 `distance_m`·`threshold_m`만 저장, `lat`/`lng` 컬럼 없음. 의사코드가 `submitted_coord = None` 명시 폐기.
- **"보조 신호일 뿐 절대 신뢰 지표 아님" 명시**: §15.1.1 V1, §15.1.6(브라우저 Geolocation 스푸핑 가능·사진 진위 미증명 명문화), H1 응답 `notice`, designer 결과 모달 문구까지 3중 명시.

## E. 목업 실검증 (변경분) — **구조 무결성 통과**

Python 파서 + grep 실측(2026-07-23):

| 검증 | 결과 |
|---|---|
| 태그 균형 | div 220/220 · section 6/6 · span 110/110 · svg 10/10 **전부 균형** |
| 사용자 노출 `쿠폰` | **0건**(주석 3종 제거 후) |
| 외부 네트워크 참조 | http(s)/cdn/script src/link href/@import/fetch **실요청 0건**. 검출된 `http://www.w3.org/2000/svg` 2건은 SVG data URI xmlns 네임스페이스 문자열(요청 미발생) |
| 금지 문자열 | `실방문 인증`·`verified_review_count`·`weight_vector`·`hotspot_course` **각 0건** |
| M8/M9/M10 구현 존재 | `verifyModal`·`updateVerifySubmit`·`submitVerify`·`playAudioRow`·`btn--tmap` 모두 존재 |
| 반응형 | `viewport` meta 존재, `1024` 미디어쿼리·375 기준 존재 |

- **375px 렌더 한계**: 브라우저 실렌더는 수행 못 했다(툴 환경 제약). 대신 **코드 구조상 결함 소지 점검** — 캡처 모달은 `.verify-modal` max-width 420px·`max-height:88vh + 스크롤`로 375px 세로 오버플로를 스크롤로 흡수(§13.1.2), 태그 균형이 맞아 미close 태그발 레이아웃 붕괴 구조 없음. **레이아웃 깨짐 소지 미발견**(단정 아닌 구조 근거 판정).

## F. 시크릿 확인 — **하드코딩 없음**

- `01 §15`·`03 §13` 신규 구간 API 키/토큰/비밀번호/베어러 패턴 grep — **하드코딩 0건.** Tmap 키는 §10.4 ENV/시크릿 스토어 규칙 적용 대상 명시(§15.7). `08` git diff 빈 결과(정본 미변경).

---

## 새로 발견된 이슈 (N7~)

### N7 (Minor) — M8 동의(consent) 캡처가 backend H1 스펙에 없음
- **근거**: designer `03 §13.1.2`는 방문 인증 제출을 **동의 체크 필수 3조건 게이트**로 두는데, backend `01 §15.1.3` H1 요청 meta는 `{place_id, lat, lng}`뿐이라 **동의 수신·기록 필드가 없다.** 개인정보(위치+사진) 재도입 기능인데 서버가 동의 사실을 남기지 않는다.
- **재현**: `01 §15.1.3` H1 요청 스펙과 `03 §13.1.2` "동의 체크 + 위치 + 사진 3조건" 대조.
- **담당 부서**: backend-engineer(동의 수신/타임스탬프 기록 여부 결정) + legal-counsel(동의 기록 요건 판정 — Q-L5/Q-L6와 함께).
- **심각도 근거**: 현 단계는 설계 문서이고 legal 4차 게이트가 동의 요건을 판정 예정이므로 Minor. 단 **구현 착수 전 반드시 닫아야 함**.

> **추측 배제 주기록**: 위 A~F 외에 M9 재생시간 예시값(designer 3:20 vs backend 180s) 등은 전부 "예시 데이터"라 계약 불일치가 아니며 이슈로 만들지 않았다.

---

## 3차 게이트 통과 여부 (M8~M10 증분)

| 게이트 조건 | 이번 증분 |
|---|---|
| Critical | **0건** |
| Major | **0건** |
| Minor | 1건 (N7) |
| J6 회귀 없음 | **충족** (A항목 실측) |
| 08 정본 불가침 | **충족** (git diff 빈 결과 + §15.0 대조) |
| 쿠폰 미결합 | **충족** (B항목 grep) |
| 시크릿 없음 | **충족** (F항목) |

> ## **3차 게이트: 통과 (QA 측, M8~M10 증분)**
>
> 통과는 **이번 증분 한정**이다. 직전 라운드의 열린 **Major N1(전광판 B1 tier 미반영)** 은 그대로 남아 있어, 전체 설계 묶음의 "구현 착수 전 필수" 목록에 N1·N7이 함께 존재한다.

### 후속 처리 요청 (증분)
| 부서 | 항목 | 시점 |
|---|---|---|
| backend-engineer | **N7**(동의 수신/기록), Tmap 키 ENV 처리(§15.7) | 구현 착수 전 |
| legal-counsel | **Q-L5**(Geolocation 거리저장 위치정보법), **Q-L6**(사진 초상권·7일 TTL), **Q-L7**("인증" 표현 오인), **N7**(동의 기록 요건), M9 원천 오디오 URL 재배포(Q-D13) | **4차 게이트(필수)** |
| security-engineer | 사진 업로드(용량·타입·EXIF strip·오브젝트스토리지 접근권한), rate-limit/dedupe(§15.1.5), 사진 파기 배치(§15.1.4) | 재검토 |

---

## 재검수 핸드오프 노트 (M8~M10 증분)

```
[다음 부서가 알아야 할 것 — legal-counsel·security-engineer 우선]
1. legal 우선: M8은 위치+사진(개인정보) 재도입. Q-L5(거리만 저장의 위치정보법 해당), Q-L6(방문
   사진 초상권·7일 TTL), Q-L7("인증" 표현 오인 소지), N7(동의를 서버가 기록 안 함) 4건이 4차
   게이트 필수 판정 대상. M9 원천 오디오 URL 재배포 허용도 이용약관 확인.
2. security 우선: M8은 스푸핑 불가 기능이 아니다(§15.1.6 명시). 사진 업로드 검증·EXIF strip·
   오브젝트스토리지 접근권한·rate-limit/dedupe·사진 파기 배치가 점검 대상. J6 회귀 없음(실측).
3. content-marketer 유의: M8 "방문 인증"을 강한 인증/신뢰 지표로 홍보 금지(스푸핑 가능한 보조
   신호, 법률 문구 전부 "확정 전 임시"). N1·N7 미해결이므로 "완료/검증됨"으로 표현 말 것.
```

---

# 재검수 (2차) — 재작업 왕복 1회차

- **재검수 대상**: 1차 Critical 3건 + Major 9건 + Minor 5건의 해소 여부, 그리고 **재작업이 새로 만든 불일치**
- **재검증 제외** (1차 통과분, 재작업 미접촉): 목업 오프라인 요건 세부·시크릿 스캔·논스코프 N2~N8
- **채점 기준표**: `08-interface-contract.md` §7 부서별 수정 지시 목록 (AI 14건 / backend 12건 / designer 11건 = 37건)
- **검증 방법**: 부서의 "반영했다" 표를 신뢰하지 않고, 지시 37건 각각에 대해 **해당 문서의 실제 본문을 직접 열어 대조**했다. 금지 문자열은 grep으로 실측했다.

## 재검수 판정 (최상단)

> ## **Critical 0건 / Major 1건 / Minor 5건 → 3차 게이트 통과**

**통과 사유**: 1차 Critical 3건은 **전부 실질 해소**됐다. 08 정본이 확정한 계약(36차원 `tag_vector` 시드, 비교 리포트 34필드, 단방향 LB 파이프라인)이 세 부서 문서에 **문자 단위로 동일하게** 들어가 있음을 실측 확인했다. Major 9건 중 8건 해소, 1건(J5) 부분 해소다. 새로 발견된 5건은 전부 Minor이며, 구현 착수 전 각 부서가 한 줄씩 고치면 되는 수준으로 **대표 결재를 막을 근거가 되지 않는다.**

**부서 자기보고의 정확성**: 세 부서 모두 반영 내역표(01 §14 / 02 §9 / 03 §11)를 작성했고, 표의 주장과 실제 본문이 **어긋난 항목은 발견되지 않았다.** 특히 backend §14.4가 "금지 문자열을 표에 그대로 적으면 자기 완료 기준을 스스로 위반한다"며 분철 표기한 것, AI §9.3이 같은 이유로 식별자 원문을 회피 서술한 것은 완료 기준을 형식이 아니라 의미로 이해한 처리다.

---

## R1. Critical 3건 해소 검증 (주장 아닌 본문 대조)

### C1 — `tag_vector` / `scoring_weights` 분리 → **해소**

| 검증 항목 | 결과 | 근거 |
|---|---|---|
| 36행 registry 시드가 08 §1.4와 **완전 일치**하는가 | **일치** — index 0~35 전 행의 `axis`·`value`·`label_ko`를 1행씩 대조. 불일치 0건 | `01 §5.2.1` ↔ `08 §1.4` |
| 두 개념이 backend·AI 양쪽에 **같은 정의**로 들어갔는가 | **일치** — `tag_vector`=36차원 이진 0.0/1.0, `scoring_weights`=5키 합 1.0, 둘 다 "서버 룰 산출(LLM 아님)" | `01 §7.1` ↔ `02 §1.3` ↔ `08 §1.5` |
| `OnboardingResult` 8필드가 3자 동일한가 | **일치** — `tags`/`tag_vector`/`vector_version`/`scoring_weights`/`extraction_confidence`/`unmatched_note`/`extracted_by`/`fallback_used`. 필드명·타입 전부 동일 | `01 §7.1` ↔ `08 §1.5` |
| 5개 평탄화 필드 처리 | **일치** — `flag` 축 원소 존재 여부로 boolean 대체, accessibility는 **true 항목만** 배열 원소, `value_confidence`+`extraction_confidence` 병존 | `02 §1.3.1` ↔ `08 §1.5` |
| backend §6.2 A1 예시가 36차원 **이진**으로 교체됐는가 | **교체 확인** — 인덱스 구간 주석까지 붙은 36개 원소, 전부 0/1. 폐기된 12차원 confidence 벡터 없음 | `01 §6.2 A1` |
| LLM 프롬프트 enum이 영문 코드로 교체됐는가 | **교체 확인** — 7축 전부 영문 코드, "한국어로 답하지 마세요" 명시. 페르소나 워크스루 3건도 영문 출력 | `02 §1.4` |
| 금지 문자열 (구 가중치 벡터명) | **0건** (03 §11의 자기검증 보고 문장 1건 제외 — 실제 사용 아님) | grep 실측 |

**슬라이스 규약 3자 일치도 확인**: `S_fit` u·v = index 14~28(15차원), 하드필터 = 29~32, 가중치 가산 = 7·8 / 21~23 / 16·18 / 33 — 08 §1.4, 01 §5.2.1, 02 §3.2 세 곳의 숫자가 전부 같다.

### C2 — 비교 리포트 34필드 3자 일치 → **해소. 일치 필드 1개 → 34개**

**세어본 결과: 34필드 전부 이름·타입·단위·enum 충돌 0건.**

| 부서 | 상태 |
|---|---|
| backend `01 §6.2 D1` | 34필드를 **번호 주석 (1)~(34)까지 부기해 전수 수록**. 08 §2.2와 1:1 대조 가능 |
| AI `02 §3.3` | 자기 소관 6필드(`spot_fit.score` / `.matched_tags` / `.unmatched_tags` / `.matched_spots`, `scoring_weights_used`, `score_breakdown`)만 남기고, 나머지 28필드는 **"AI 소관이 아닌 필드(backend 직렬화)"로 명시 열거**하고 "08 §2.2가 유일한 정본"이라 선언. 한국어 enum·km·string ID 스키마 폐기 확인 |
| designer `03 §5.3` | "잠정 필드" 표기 **삭제 확인**. 6개 표시 행 전부 정본 필드 경로로 매핑. `level`·`tier` 한국어 라벨을 **표시 전용**으로 분리하고 "API에 한국어를 넣지 않는다" 명기 |

1차에서 불일치했던 12개 항목 개별 재확인:

| 1차 불일치 | 현재 | 확인 위치 |
|---|---|---|
| 비대칭 코스 객체명 | `hotspot`/`hidden` 대칭 키로 통일 | 01 D1, grep 0건 |
| `course_id`(string) | `route_id`(int)로 통일. `congestion` 키도 `dict[int,float]` | 01 §7.1, 02 §3.1 |
| `level` 한국어 enum | `low`/`mid`/`high` 영문. 임계 33/66 + "가정값" 표기까지 3자 동일 | 01 D1, 03 §5.3 |
| `confidence` 실측/추정/데이터없음 | `tier` A/B/C/none 단일화. AI가 "tier 산출에 관여하지 않음"을 명시 | 02 §3.3 |
| km float 거리 | `total_distance_m`(미터 int). 구 필드명 grep 0건 | 01 D1 |
| 병목 문자열배열 | `[{seq,name,delay_min}]` 객체배열 | 01 D1 (14) |
| 인증 리뷰 카운트 | `review_trust.{count, companion_matched_count, coldstart}` | 01 D1 (19~21) |
| `verdict` 필드 부재 | 5필드 전수 + `congestion_delta_pct` 신설(m3 해소) + 산식 명시 | 01 D1 (26~30) |
| `data_freshness_warning: null` | `data_freshness{tier,source,observed_at,is_estimated,notice}` + `mixed` 허용 | 01 §6.0, D1 (33~34) |
| `load_balancing` UI 없음 | 응답 객체 + `.lb-banner` 컴포넌트 + 목업 렌더 | 03 §3.7, 목업 802행 |
| `user_weights_used` | `scoring_weights_used`로 개명. 구명칭 사용처 0건 | 02 §3.3 |
| tier/신선도 표기 자리 없음 | `.tier-badge` 4종 + `.freshness-note` 신설, 모바일·데스크톱 각각 렌더 | 목업 470·480·837·879·899행 |

### C3 — 페널티 이중 적용·순환 제거 → **해소. 파이프라인 단방향 확인**

**"지웠다"는 주장이 아니라 의사코드 본문에서 확인한 것**:

| 확인 대상 | 결과 |
|---|---|
| backend `select_route_with_balancing`의 **입력 타입** | `list[RouteScore]`로 변경됨. `primary_route_id`만 받던 초판과 다름 (`01 §8.3`) |
| `profile_fit()` **재호출 실제 삭제 여부** | **삭제 확인.** 함수 본문이 `fit = s["spot_fit"]` + "재계산 없음, AI 반환값 재사용" 주석. 문서 전체에서 `profile_fit(` 호출 형태 0건 |
| AI `score_adjusted` **폐기 여부** | AI 문서에 함수 정의 0건. `02 §4.3`은 "폐기됐다"는 서술만 남음. `01`의 1회 등장도 폐기 사실 기술(1020행) |
| `score_routes` 계약에 LB 금지가 **명문화**됐는가 | 명문화. backend 계약 (3)항 "로드밸런싱 페널티를 적용하지 않는다. 이 함수는 LB를 모른다" — AI 문서 동일 문구 |
| 순환 잔존 여부 | **없음.** [1]backend 후보생성 → [2]AI 스코어링 → [3]backend LB선택 → [4]backend verdict. AI가 backend LB 결과를 재입력받는 경로가 어느 문서에도 없다. `01 §7.1.2`와 `02 §3.1`의 파이프라인 도식이 문자 단위로 동일 |
| 임계·윈도 통일 | 6시간 / 0.6·0.85 / share 0.4·0.6 — 01 §8.2, 02 §4.1~4.2, 08 §3.4 삼자 동일. AI 3시간 윈도 흔적 0건 |
| "완전 배제 vs 완전 차단 금지" 충돌 | 해소. RED 분기에서도 대안 풀이 비면 `fallback_all_congested()`로 원 코스를 유지한다는 것이 **의사코드로** 표현됨 (`01 §8.3`, `§8.4`) |

---

## R2. AI팀 요청 대조 2건

### B-1. `S_fit` 슬라이스 + `score_routes` 시그니처 ↔ backend §7.1 → **정확히 일치**

| 항목 | AI `02` | backend `01 §7.1` | 판정 |
|---|---|---|---|
| 시그니처 | `score_routes(profile: OnboardingResult, candidates: list[dict], congestion: dict[int,float]) -> list[RouteScore]` | 동일 (파라미터명·타입·순서·반환형 전부) | **일치** |
| `S_fit` 슬라이스 | `u`=`tag_vector[14:29]`, `v`=`course_tag_vector[14:29]` (§3.2) | 계약 (4)항 "u와 v는 tag_vector index 14~28 슬라이스를 쓴다" | **일치** |
| 하드필터 소관 | AI 내부 단일 수행 (§3.1-2) | 계약 (2)항 "backend는 공간·인기도 필터만 담당 — 필터 책임 경계를 겹치지 않는다" | **일치** |
| `candidates` 필수 키 | 8종 표 (§3.1) | 8종 표 (§7.1.1) | **일치** (단 N2 참조) |

backend 계약이 AI보다 조항이 2개 많으나(4항 vs 2항) **추가분이지 충돌이 아니다.**

### B-2. 클라이언트 인라인 벡터 주입 서버 검증 → **backend에 반영됨 (허용오차 1건 불일치)**

AI가 `02 §2.2` 말미에 (a)~(d) 규칙을 정의하고 "실제 강제 위치·구현은 backend 소관"이라 넘겼다. backend `01 §6.2 D1` **Request 블록**에 실제로 들어가 있다:

| AI 요구 | backend 반영 | 판정 |
|---|---|---|
| (a) 길이가 registry 차원(36)과 정확히 일치 | "길이 36" 검증 후 400 거절 | 반영 |
| (b) 원소가 0.0 또는 1.0, 소수·NaN·Inf·음수는 400 | 원소 집합 {0.0, 1.0} 검증 | 반영 |
| (c) `scoring_weights` 5키 + 0 이상 + 합 1.0, **재정규화 없이 400** | "5키 전부 존재 + 각 0~1 + 합 1.0±0.01" 검증, 400 거절 | 반영 (**허용오차 상이 → N4**) |
| (d) `vector_version` 화이트리스트 | `vector_version` 일치 검증 | 반영 |

---

## R3. backend가 보안 지시 대신 다른 해법을 택한 1건 — **반론 타당. 해소 인정**

**쟁점**: 보안/QA는 `uq_congestion_point`에서 `tier`를 빼라고 지적했으나, backend는 빼지 않고 "행 공존 + 읽기 시점 tie-break"를 택했다.

**반론 검토 결과 — 타당하다.** `uq_congestion_point`가 `(place_id, observed_at, horizon_min, tier)`인 상태에서 tier를 키에서 빼면, `job_congestion`의 UPSERT 멱등성 키도 함께 좁아진다(`01 §7.2` 표에 `(place_id, observed_at, horizon, tier)`로 명시). 그러면 Tier A→C 강등 시점에 **동일 (place, 시각)에 대해 기존 Tier A 실측 행이 Tier C 추정치로 덮어써진다.** 이는 `§7.3` 수집 잡 안전장치 1번("원본을 지우지 않는다")과 직접 충돌하며, 원본 소실은 tie-break 부재(비결정성)보다 회복 불가능한 손해다. **읽기 시점 결정론화가 올바른 해법이라는 backend 판단을 수용한다.**

**tie-break가 혼잡도 조회 경로 전부에 적용됐는가 — 규칙은 전부, 예시는 1곳 누락**:

| 혼잡도 조회 경로 | 적용 | 근거 |
|---|---|---|
| T1 규칙 자체 | "혼잡도 조회 쿼리 **전부**에 적용 (전광판·장소 상세·compare 주입)" — 범위 한정 없음 | `01 §5.3.1 T1` |
| 전광판 LATERAL 쿼리 | **SQL에 실제 반영** — `ORDER BY cs.observed_at DESC, cs.tier ASC` + 필요 이유 주석 | `01 §5.3-(3)` |
| `TierController.compute()` | 주석으로 T1 적용 지시 명기 | `01 §7.5` |
| C1b `/places/search` 응답 | item에 `congestion.tier` 포함 확인 | `01 §6.2 C1b` |
| D1 `/routes/compare` | `hotspot`/`hidden` 양쪽 `congestion.tier` 포함 | `01 §6.2 D1` (9) |
| **B1 `/congestion/board`** | **item에 `tier` 없음** — T2가 적용 지점으로 "§6.2 **B1**/C1/D1"을 명시 지목했는데 응답 예시에 반영되지 않음 → **J5 부분해소 (N1)** | `01 §6.2 B1` |

→ **한 군데 구멍이 있다.** 다만 원 문제(행 선택 비결정성)는 T1으로 해소됐고, 남은 것은 **전광판 item의 tier 표기 자리 누락**이다. 규칙(T2)은 이미 정확히 쓰여 있고 예시만 뒤처졌으므로 Critical이 아닌 Major로 둔다.

---

## R4. Major 9건 해소 상태표

| ID | 1차 심각도 | 해소 여부 | 근거 (파일:절) |
|---|---|---|---|
| **J1** `score_routes` 시그니처 불충족 | Major | **해소** | `01 §7.1` ↔ `02 §3.1` — 프로필 전체 전달, `congestion` 키 int 통일, 하드필터 AI 단일화. `candidates` 필수 키 8종 양쪽 동일 |
| **J2** `build_verdict` 미설계 + LLM 비용 미평가 | Major | **해소** | `01 §7.7` 신설(backend 소관 이관 + 템플릿 4종 + 120자 상한 + 외부문자열 삽입 금지) / `02 §1.6 [A14]`("그 외 요청당 LLM 호출은 없다") / `02 §1.5` 재검토 트리거 |
| **J3** 게스트 저장 위치·고지 모순 | Major | **해소** | `08 §6 E1` 잠정 정본(서버 Redis 24h + 승격) → `03 §4-0️⃣`·목업 583행 배너 "체험 모드 — 24시간 임시 보관되며, 가입하시면 그대로 이어집니다" + `.guest-context-banner` + `#loginModal` 승격 UX |
| **J4** `X-Guest-Id` + 승격 멱등성 | Major | **해소** | `01 §6.0`(헤더 수용 삭제 → `400 GUEST_ID_NOT_ACCEPTED`), `§10.1.1` 신설 G1~G7 + `redis.getdel()` 의사코드 + 승격 후 쿠키 재발급 + 회귀 테스트 2종 명시 |
| **J5** tier 혼재 | Major | **부분 해소** | T1~T4 규칙 신설·전광판 SQL tie-break·`mixed` 허용 확인. **단 §6.2 B1 응답 예시가 자기 규칙 T2 미반영** → 잔여(N1) |
| **J6** N1(EXIF) 잔재 | Major | **해소** | 아래 별도 검증 |
| **J7** M6 화면 부재 | Major | **해소** | 아래 별도 검증 |
| **J8** 법률 고지 UI 4종 | Major | **해소** | 아래 별도 검증 |
| **J9** 칩이 태그 축 절반 미커버 | Major | **해소** | 목업 615~641행: "동행·분위기" 7칩 + **"이동 수단" 4칩** + **"편의·접근성" 4칩** 신설. 라벨 전부 registry `label_ko`와 문자 일치. `02 §1.7-1` 칩→태그 매핑표 **32행 실제 작성**, 반려동물 칩이 `flag:pet_present` + `accessibility:pet_friendly_required`로 파급되는 규칙 명시 |

### J6 (N1 잔재) — grep 실측 결과 **0건 확인**

세 문서 + 목업 4개 파일 전수 grep:

| 금지 문자열 | 실사용 | 비고 |
|---|---|---|
| 인증 리뷰 카운트 필드명 | **0건** | 03 §11의 "0건임을 확인했다"는 자기보고 문장 1건뿐 |
| "실방문 인증" | **0건** | 03 §11 조치 기록 1건 (동일) |
| 비대칭 코스 객체명 / km 거리 필드명 | **0건** | — |
| `coldstart_flag` / `user_weights_used` | **0건** | 02 §9 대응표에 "→로 개명"이라는 이력 기술만 |
| 목업 내 "인증" 렌더 텍스트 | 2곳 | **비교 지표 행 밖** `.pending-feature-note`("현장 방문 사진 인증 기능은 준비 중이며, **위 비교 지표에는 반영되지 않습니다**") — 08 §4.3이 명시 허용한 처리. 4️⃣ 화면 비활성 버튼 2건도 PRD 6.4 허용범위 |

**대체 지표 `companion_matched_count`의 산출 가능성 — 검증 통과**: `reviews.companion_type` 컬럼만으로 산출 가능함을 `02 §3.4`가 명시하고, `01 §7.1.1` `candidates` 필수 키에 `review_count`/`companion_matched_count`가 backend 제공 항목으로 들어가 있으며, `01 §6.2 D1` 응답에 실제 값(6/214, 19/31)이 들어 있다. **N1 없이 산출되는 실재 지표다.** 목업 비교표 4번째 행도 "동행 유형 일치 리뷰 (review_trust.companion_matched_count / .count)"로 교체됐다(모바일·데스크톱 양쪽).

### J7 (M6 화면) — **렌더 확인. 시연 목적에 충분**

- 목업 802~808행 `.lb-banner` **실제 렌더 확인**: 제목("방문 분산 안내") + 본문 + 메타 라인(`load_balancing.reason: primary_over_threshold`, `assigned_rank: B`). 비교 화면 최상단, `.compare-list`(모바일)·`.compare-table`(데스크톱) **바깥 공통 영역**에 배치돼 브레이크포인트와 무관하게 항상 노출된다.
- 나머지 4종(`primary_amber_distributed` / `time_shift` / `region_expanded` / `no_alternative`)은 `03 §3.7` 표에 위치·형태·문구까지 정의되어 있으나 목업 미렌더.

**시연 충분성 판정: 충분하다.** J7의 원 문제는 "M6가 화면 어디에도 없어 존재를 증명할 수 없다"였다. 심사위원 질문("오버투어리즘을 해소한다면서 왜 특정 코스를 추천하나")에 대한 답은 **분산이 실제로 일어났음을 사용자에게 고지하는 화면 1개**로 성립하며, `primary_over_threshold`가 정확히 그 상태다. 정적 목업에 5종을 동시 나열하면 상태 전환 없이 배너가 5개 쌓여 시연 가치가 오히려 떨어진다. designer가 핸드오프 노트에 "나머지 4종은 프론트 구현 시 `reason` 값 전체를 다뤄야 한다"고 남긴 것도 적절한 인계다.

### J8 (법률 UI 4종) — **4종 전부 확인. S-M10 순서 강제는 실제 동작 코드**

| # | 항목 | 목업 위치 | 판정 |
|---|---|---|---|
| (a) | 개인정보 수집·이용 동의 | 590~601행 `.consent-card` + `#privacyCheckbox` | 렌더 + `onPrivacyConsentChange()`가 `#nextBtn` 비활성 토글. 초기 상태 비활성 |
| (b) | 국외이전 고지 | 602~611행 `.consent-card--transfer` | 아래 별도 검증 |
| (c) | 공공데이터 출처 | 1082행 전역 `.footer-legal` | 렌더 확인 |
| (d) | 지도 SDK 저작권 | 960행 `.map-sdk-credit` (최소 28px 자리) | 렌더 확인 |

**S-M10 순서 강제 — 문구가 아니라 동작한다:**

1. **DOM 순서**: `.consent-card`(a, 590행) → `.consent-card--transfer`(b, 602행) → `<textarea id="nlpInput">`(613행). "(b)가 자유입력창보다 먼저" 충족.
2. **초기 상태가 잠금**: textarea에 **`disabled` 속성이 HTML에 박혀 있다.** JS가 실행되지 않아도 잠긴 채로 남는 fail-safe 방향이다. placeholder도 "칩을 선택해 진행해주세요 (자유 입력은 국외이전 동의 후 사용 가능)"로 대체 경로를 안내한다.
3. **해제 경로가 단 하나**: 전 파일 검색 결과 `nlpInput`을 활성화하는 코드는 `agreeTransfer()` 내 1곳뿐이며, 이 함수는 "동의하고 자유 입력 사용하기" 버튼에서만 호출된다. 우회 경로 없음.
4. **미동의 경로가 막다른 길이 아니다**: `declineTransfer()`가 입력값 초기화 + 재잠금 + `.chip-row`로 `scrollIntoView` — 08 §7.3 G7이 요구한 "미동의 시 칩 전용 경로로 유도"가 구현돼 있다.

→ **문구만 있고 우회 가능한 상태가 아니다. 실효 있는 게이팅으로 판정한다.** 단 목업은 클라이언트 게이팅이며, 실제 서비스에서는 서버가 동의 없는 자유텍스트의 LLM 전송을 거절해야 한다 — 이는 구현 단계 backend 과제로 남긴다(`01 §12.3 Q-L3` 미해소 상태와 연결).

---

## R5. 새로 발견된 이슈 (재작업이 만든 것)

> Critical 승격 대상 없음. 각 항목은 한 줄~한 블록 수정으로 닫힌다.

### N1 (Major) — 전광판 응답 예시가 backend 자기 규칙 T2를 위반 [J5 잔여]
- **위치**: `01-backend-design.md §6.2 B1` ↔ `§5.3.1 T2`
- **문제**: T2는 "혼잡도를 포함하는 **모든** 응답 item은 `congestion.tier`를 개별로 갖는다"고 규정하고 **적용 지점으로 §6.2 B1을 명시 지목**했다. 그러나 B1 응답 예시의 item은 `congestion_index`·`level`·`level_emoji`·`trend`만 갖고 **`tier`가 없다.** 같은 문서의 C1b·D1 예시에는 들어가 있어 B1만 뒤처졌다.
- **왜 남겨두면 안 되는가**: J5의 원 시나리오가 정확히 "전광판 한 화면에 신뢰도가 다른 값이 섞인다"였다. 행 선택은 T1으로 결정론화됐으나, **전광판 item의 tier가 응답에 없으면 designer가 tier 배지를 렌더할 데이터를 받지 못한다.** 규칙과 예시가 어긋나면 구현자는 대개 예시를 따른다.
- **재현**: `01 §5.3.1` T2 행의 "적용 지점" 열을 읽고 `§6.2 B1` 응답 예시를 열면 `tier` 키가 없다.
- **수정안**: B1 `items[]`에 `"tier"`를 추가하고, `data_freshness.tier`가 item과 다를 수 있음(`mixed`)을 예시로 1건 보이면 더 좋다. designer도 1️⃣ 홈 전광판에 `.tier-badge` 자리를 확보해야 한다(현재 `.tier-badge`는 3️⃣ 비교 화면에만 존재).
- **담당**: backend-engineer (주) / designer (종)

### N2 (Minor) — AI 하드필터가 `candidates`에 없는 키를 참조
- **위치**: `02 §3.1-2` ↔ `01 §7.1.1` / `08 §3.3`
- **문제**: AI 하드필터 의사코드 마지막 줄이 `if c.travel_time_min > MAX_TRAVEL_TIME: continue`인데, `candidates` 필수 키 8종(AI·backend·08 셋 다 동일)에 `travel_time_min`이 **없다.** backend가 채워주지 않는 키다.
- **수정안**: `candidates` 필수 키에 `est_duration_min: int`를 추가하거나(3개 문서 동시 갱신 — 08 개정 필요), 해당 필터 줄을 삭제한다.
- **담당**: planning-lead(08 개정 판단) → backend-engineer + ai-optimization-engineer

### N3 (Minor) — `build_verdict()` 템플릿 변수가 `RouteScore`에서 유도 불가
- **위치**: `01 §7.7.4` ↔ `01 §7.1 RouteScore`
- **문제**: 시그니처는 `build_verdict(hotspot: RouteScore, hidden: RouteScore, deltas: dict)`인데 템플릿 변수 정의가 `local_count = len(hidden.local_merchants)`다. **`RouteScore` TypedDict에 `local_merchants` 키가 없다**(8키: `route_id`/`score`/`spot_fit`/`matched_tags`/`unmatched_tags`/`matched_spots`/`score_breakdown`/`reasons`). `local_merchants`는 응답 봉투 필드(08 §2.2 #24)이지 `RouteScore` 필드가 아니다. `matched_count = len(hidden.matched_tags)` 쪽은 정상이다.
- **영향**: "혼잡도 열위 또는 동등" 템플릿 1종이 구현 시 키 에러가 된다.
- **수정안**: `deltas`에 `local_count`를 담아 넘기거나 `build_verdict` 파라미터에 `local_merchants: list`를 추가한다.
- **담당**: backend-engineer

### N4 (Minor) — `scoring_weights` 합 허용오차가 두 문서에서 다름
- **위치**: `02 §2.2`(합 1.0, 허용오차 **1e-6**) ↔ `01 §6.2 D1 Request`·`§7.1 extract_tags` 계약 (3)항(합 **1.0±0.01**)
- **문제**: 1e-6과 0.01은 4자리 차이다. 정규화 후 float 오차만 통과시킬 것인지(1e-6), 클라이언트가 소수 둘째 자리로 반올림해 보낸 값도 통과시킬 것인지(±0.01)는 **다른 정책**이며, 구현자가 어느 쪽을 쓸지 알 수 없다.
- **수정안**: 08 §1.5 또는 §2.2에 단일 값을 못박는다. QA 의견은 **±0.01** — 08 §2.3이 designer에게 반올림 표시를 허용했고, 인라인 주입 경로에서 클라이언트가 정밀도를 보존한다고 가정할 근거가 없다.
- **담당**: planning-lead(택일) → backend-engineer + ai-optimization-engineer

### N5 (Minor) — 신선도 고지 노출 위치가 08 정본과 반대
- **위치**: `08 §2.3`("비교 카드 **하단** 고정 자리") ↔ `03 §5.3`("비교 카드 **상단** 고정 자리") / 목업 812행(`.freshness-note`가 `.compare-list` **위**)
- **문제**: designer가 08 정본을 말없이 뒤집었다. 데스크톱 테이블에서는 하단(899행)에 두어 **모바일과 데스크톱도 서로 반대**다.
- **영향 평가**: UI 배치 문제이며 데이터 계약에 영향 없음. 상단 배치가 "수치를 보기 전에 신뢰도를 먼저 안내"라는 점에서 정직성 원칙에는 오히려 부합한다.
- **수정안**: designer가 상단 배치를 유지하되 **08 §2.3 개정을 planning-lead에 요청**해 정본과 문서를 일치시킨다. 부서가 정본을 말없이 바꾸는 선례를 남기지 않는 것이 요점이다.
- **담당**: designer → planning-lead(08 개정)

### N6 (Minor) — 동의 (a)와 (b)가 상호 독립이라 스펙의 "순서가 계약" 서술과 어긋남
- **위치**: `03 §3.8` 설계 원칙("(b)가 (a)보다 먼저이면 안 된다") ↔ 목업 `agreeTransfer()`
- **문제**: `agreeTransfer()`가 `#privacyCheckbox` 상태를 전혀 보지 않는다. 사용자가 (a) 미체크 상태에서 (b)만 동의해도 자유입력이 열린다 — 즉 **(b)를 (a)보다 먼저 완료할 수 있다.**
- **왜 Minor인가**: S-M10의 실질 요건("자유서술이 해외로 나가기 전에 국외이전 동의")은 충족된다. 어긋나는 것은 designer 자신이 쓴 순서 서술이지 보안 요건이 아니다.
- **수정안**: `agreeTransfer()` 첫 줄에 개인정보 동의 여부 가드를 넣거나, §3.8 서술을 "(b)는 (a)보다 **아래에 배치**한다"(배치 순서 한정)로 정정한다.
- **담당**: designer

---

## R6. 1차 Minor 5건 처리 확인

| ID | 해소 여부 | 근거 |
|---|---|---|
| **m1** 비원자성 | **해소** | `01 §8.3.1` 신설 — "허용 오차로 확정, 새 설계 미도입"을 근거 4종 + Lua 원자화 각주와 함께 **설계 결정으로 명시 기록**. QA가 요구한 형태 그대로 |
| **m2** 예시 데이터 캡션 범위 | **해소** | 목업 `.sample-tag` 4건(685·725·798·982행) + 전역 footer. `03 §9` 서술도 실제와 일치하도록 정정 |
| **m3** 델타 절대/상대 혼용 | **해소** | `congestion_delta_pct` 신설 + 산식 명시(`01 §6.2 D1`), designer가 `_pct`를 쓴다고 명시(`03 §5.3`), 목업 "↓ 71% 낮음 (verdict.congestion_delta_pct)" — 82→24 기준 −70.7%≈−71%로 자체 정합 |
| **m4** 점선 의미 충돌 | **해소** | `03 §3.6`에 "실선/점선은 `path_source` 전용 신호로 예약" 명문화. 목업 930·934행 두 경로 **모두 실선**으로 수정, 범례(917~918행)에 실선/점선 의미 + 점선 렌더 예시 별도 표기 |
| **m5** 보안 리포트 미존재 | **해소** | `06-security-report.md` 존재 확인(76,171 bytes). APPROVALS.md에도 해소 기록 |

---

## R7. 목업 재검증 (변경분 한정)

| 항목 | 방법 | 결과 |
|---|---|---|
| 화면 수 | `grep -c class="screen` + id 목록 | **6개 유지** — `s-onboard`/`s-home`/`s-discover`/`s-compare`/`s-saved`/`s-tips` |
| 외부 네트워크 참조 | `grep -E "https?://ㅣ<script srcㅣ<link ㅣcdnㅣ@importㅣfetch(ㅣXMLHttpRequest"` | **0건** — 재작업으로 926→1158행 증가했으나 오프라인 요건 유지 |
| `<script>` | grep | 1개, 전부 인라인 (src 속성 없음) |
| 신규 컴포넌트 렌더 | grep | `.lb-banner`·`.tier-badge`(4종)·`.freshness-note`·`.consent-card`·`.consent-card--transfer`·`.footer-legal`·`.map-sdk-credit`·`.pending-feature-note`·`.guest-context-banner`·`#loginModal` **전부 렌더 확인** |
| 신규 JS 동작 | 스크립트 블록 정독 + DOM id 대조 | `onPrivacyConsentChange`/`agreeTransfer`/`declineTransfer`/`openLoginModal` — 참조 id(`privacyCheckbox`·`nextBtn`·`nlpInput`·`transferStatus`·`transferGate`·`loginModal`)가 **전부 실재**. 끊어진 참조 0건 |
| 칩 라벨 ↔ registry `label_ko` | 목업 615~641행 ↔ 08 §1.4 | **전부 문자 일치**. mobility 4칩·accessibility 4칩 신설 확인 |
| 시크릿 | 전면 재스캔 생략(재작업 미접촉 영역, 1차 통과분) | 신규 추가분에 키·토큰 리터럴 없음만 확인 |

---

## R8. 3차 게이트 통과 여부

| 게이트 조건 | 1차 | 재검수 |
|---|---|---|
| Critical 이슈 0건 | 미달 (3건) | **충족 — 0건** |
| Major | 9건 | 1건 (J5 잔여 = N1) |
| Minor | 5건 | 5건 (전부 신규. 1차 5건은 전량 해소) |
| 시크릿 하드코딩 0건 | 통과 | 통과 (유지) |
| 논스코프 침범 없음 | 조건부 (N1 잔재) | **충족** — J6 해소로 조건부 해제 |
| MVP 커버리지 | 조건부 (M6 화면 누락) | **충족** — J7 해소 |
| 목업 오프라인 요건 | 통과 | 통과 (유지) |

> ## **3차 게이트: 통과 (QA 측)**

**남은 Major 1건·Minor 5건은 "구현 착수 전 반영" 조건으로 넘긴다.** 전부 설계 문서의 예시·상수·배치 수준이며, 대표가 결재하는 대상(설계 묶음)의 정확성을 훼손하지 않는다. 다만 **N1은 구현 착수 전 반드시 닫아야 한다** — 규칙과 예시가 어긋난 채로 구현되면 J5가 그대로 되살아난다.

### 후속 처리 요청

| 담당 | 처리할 이슈 | 시점 |
|---|---|---|
| backend-engineer | **N1**(B1 응답에 item tier), N3(`local_count` 유도 경로) | 구현 착수 전 |
| designer | N1(홈 전광판 tier 배지 자리), N5(08 개정 요청), N6(가드 또는 서술 정정) | 구현 착수 전 |
| planning-lead | N2(`candidates` 키 추가 여부), N4(허용오차 택일), N5(08 §2.3 개정) | 08 차기 개정 시 일괄 |

**AI 최적화 정확도 회귀**: 1차와 동일하게 **해당 없음.** `02-ai-strategy.md`는 신규 설계이며 비교 대상 벤치마크가 존재하지 않는다. 재작업으로 스코어링 공식(§3.2)·가중치 가산표(§2.2)가 변경됐으나 **정확도 수치를 주장한 곳이 없고**, 임계값·계수는 전부 "가정값 / 실측 후 보정" 표기를 유지했다(§4 말미). 근거 없는 수치 제시 없음을 재확인했다.

---

## R9. 재검수 핸드오프 노트

```
[다음 부서가 알아야 할 것]
1. 3차 게이트 QA 통과(Critical 0). 08 정본이 세 문서에 실제로 동일하게 반영됐음을 본문 대조로 확인했다 —
   비교 리포트 일치 필드는 1개에서 34개 전부가 됐고, LB 페널티 순환도 의사코드 수준에서 제거됐다.
2. content-marketer 금지: (a) "동적 로드밸런싱 5종 상태 지원" — 목업은 1종만 렌더, 4종은 표 설계뿐,
   (b) "혼잡도 신뢰등급 전 화면 표기" — 전광판(B1) 응답에 item별 tier가 아직 없다(N1),
   (c) "실방문/방문 인증" 계열 표현 일체 — 미구현이며 08 §4가 전면 금지했다.
3. 임계값·capacity·비용·정확도는 전부 가정값이다. "검증된 수치"로 옮겨 쓰지 말 것.
```

---
---

# [이력] 1차 검수 (2026-07-22) — 원본 보존, 수정하지 않음


## 판정 (최상단)

> ## **Critical 3건 / Major 9건 / Minor 5건 → 3차 게이트 미통과 (재작업 필요)**

**미통과 사유**: Critical 3건은 전부 **부서 간 인터페이스 계약 불일치**다. 세 부서가 서로의 산출물을 보지 못한 채 병렬 작업한 결과, "AI가 정의 → backend가 저장 → designer가 표현"이라는 PRD 6.1절의 3개 합의 항목이 **실제로는 하나도 맞물리지 않는다.** 각 문서는 개별적으로 품질이 높으나, 이 상태로 대표가 결재하면 "설계 확정"이 아니라 "확정되지 않은 3개의 안"을 확정된 것으로 승인하게 된다.

**중요**: 이는 특정 부서의 과실이 아니라 **병렬 위임 구조의 예상된 산물**이다. PRD 6.1절도 "각자 자신의 안을 제시하고 planning-lead가 취합 시 조정한다"고 명시했다. 다만 **그 조정이 아직 수행되지 않았고**, 조정 없이 최종 결재로 넘어가면 안 된다는 것이 본 검수의 결론이다.

**재작업 왕복 예상**: 1회. Critical 3건은 모두 "누가 정본인지 정하고 나머지가 따라간다"로 해소 가능하며, 새 설계가 필요한 항목은 C3(M6 규칙 택일) 하나뿐이다.

---

## 1. 인터페이스 정합성 대조표 (A항목)

### 1.1 온보딩 태그 스키마 (PRD 6.1-(a))

| 요소 | AI (02 §1.3) — **정의 주체** | backend (01 §5.2 tag_axis_registry) — 수용 | designer (03 §3.4 칩) — 표현 | 일치 |
|---|---|---|---|---|
| 축 이름 | `spot_preference` | `spot_pref` | — | 불일치 |
| 값 표기 | 한국어 enum ("연인","가족") | 영문 코드 `value` + 별도 `label_ko` 컬럼 | 한국어 칩 라벨 | 불일치 |
| companion | 배열 7값 | (axis,value) 행 | 5값 칩 (`가족`,`친구` 없음) | 부분 |
| mobility | 배열 5값 (도보/자전거/차량/대중교통/무관) | (axis,value) 행 | **칩 없음** | 불일치 |
| mood | 배열 7값 | (axis,value) 행 | 칩 1값 (`힐링 산책`) | 부분 |
| spot_preference | 배열 8값 | (axis,value) 행 | 칩 2값 | 부분 |
| accessibility | **object, boolean 4개** | 배열 `[{v,c}]` 구조 전제 | **칩 없음** | 불일치 |
| congestion_preference | 단일 enum 3값 | 레지스트리 축 목록에 없음 | **칩 없음** | 불일치 |
| child_present / pet_present | 최상위 boolean | 축 구조로 표현 불가 | 칩으로 간접 | 불일치 |
| confidence | **추출 전체에 1개** | **값마다 1개** (`{"v":"couple","c":0.92}`) | — | 불일치 |
| `weight_vector` (12~24차원) | **정의 없음** | 필수 (`REAL[]` + `vector_index` 고정 순서) | — | 불일치 |
| `vector_version` | 정의 없음 | 필수 | — | 불일치 |
| `extracted_by` / `fallback_used` | 정의 없음 | 필수 | — | 불일치 |

→ **C1 (Critical)**

### 1.2 1:1 비교 리포트 필드 (PRD 6.1-(b))

| 개념 | backend (01 §6.2 D1) — 서빙 | AI (02 §3.3) — **산출 주체** | designer (03 §5.2) — 표현 | 일치 |
|---|---|---|---|---|
| 좌/우 객체 키 | `hotspot` / `hidden` | `hotspot_course` / `sumeungil_course` | 라벨 "핫플"/"숨은길" | 불일치 |
| 코스 식별자 | `route_id`: **int** | `course_id`: **string** | — | 불일치 |
| 혼잡도 값 | `congestion.index` 0~100 | `congestion.index` 0~100 | 82 / 24 표시 | **일치** |
| 혼잡도 등급 | `level`: low/mid/high | `level`: "혼잡"/"여유" | "혼잡"/"여유" + 도형 | 불일치 |
| 신뢰도 표기 | `tier`: A/B/C + `is_estimated` | `confidence`: 실측/추정/데이터없음 | **표기 자리 없음** | 불일치 |
| 거리 | `total_distance_m`: **미터 int** | `route_summary.distance_km`: **km float** | 텍스트 서술 | 불일치 |
| 소요시간 | `est_duration_min` | `route_summary.duration_min` | 텍스트 서술 | 부분 |
| 병목 | `[{seq,name,delay_min}]` 객체배열 | `["string"]` 문자열배열 | 텍스트 | 불일치 |
| 적합도 | `spot_fit{score,matched_tags,unmatched_tags}` | `matched_spots[]` + `score_breakdown` | "맞춤 스팟" 텍스트 | 불일치 |
| 신뢰도(리뷰) | `review_trust{count,companion_matched_count}` | `trust{verified_review_count,source,coldstart_flag}` | "실방문 인증 리뷰" | 불일치 |
| 헤드라인 | `verdict{congestion_delta,duration_delta_min,fit_delta,headline}` | **필드 없음** | "↓71% 낮음" 델타 카드 | 불일치 |
| 신선도 블록 | `data_freshness{tier,source,observed_at,notice}` | `data_freshness_warning: null` | 표기 자리 없음 | 불일치 |
| 경로 지오메트리 | `path_geojson` + `path_source` | 없음 (backend 소관) | SVG 플레이스홀더 | **일치** |
| 로드밸런싱 결과 | `load_balancing{applied,reason,notice}` | 없음 | **UI 없음** | 불일치 |
| 사용 가중치 노출 | 없음 | `user_weights_used` | 없음 | 불일치 |

**backend와 AI 사이에 이름·타입이 모두 일치하는 필드는 `congestion.index` 단 1개다.**

→ **C2 (Critical)**

### 1.3 함수 시그니처 3종 (01 §7.1)

| 시그니처 | AI 설계가 충족하는가 | 판정 |
|---|---|---|
| `extract_tags(text, chips) -> OnboardingResult` | **불충족.** 반환 TypedDict 5필드 중 `tags` 구조 불일치 + `weight_vector`/`vector_version`/`extracted_by`/`fallback_used` **4개 미정의**. 계약 (2)항("차원 순서는 tag_axis_registry를 따를 것")은 AI 문서에 언급조차 없음. 계약 (1)항(폴백 보장)·(3)항(외부전송 문서화)은 충족 | **C1** |
| `score_routes(weight_vector, candidates, congestion) -> list[RouteScore]` | **불충족.** AI의 Score(c)는 (a) 5축 가중치 W(02 §2.2 산출), (b) 코사인용 사용자 태그 이진벡터 u, (c) 하드필터용 accessibility boolean 4개를 **모두** 필요로 하는데 backend는 단일 `weight_vector` 하나만 전달. `congestion`은 `dict[int,float]`(route_id=int)인데 AI는 course_id=string | **J1 (Major)** |
| `build_verdict(hotspot, hidden, deltas) -> str` | **불충족.** AI 문서 어디에도 verdict/headline 생성 설계가 없음. 02 §3.3 리포트 스키마에도 해당 필드 없음 | **J2 (Major)** |

### 1.4 게스트/비회원 체험 (PRD R5)

| 항목 | backend (01 §10.1) | designer (03 §4-0️⃣) | 일치 |
|---|---|---|---|
| 도입 여부 | 도입 **권고** (Q-I3, 미확정) | 진입점 배치 (UI만) | 방향 일치 |
| 식별자 | `guest_id` UUID, HttpOnly 쿠키 (+ `X-Guest-Id` 헤더) | 명시 없음 | 부분 |
| 프로필 보관 위치 | **서버 Redis** `session:guest:{id}`, TTL 24h | **클라이언트 세션/로컬스토리지** | 불일치 |
| 사용자 고지 | "게스트는 저장/리뷰만 제한" | 배너 **"결과가 저장되지 않습니다"** | 모순 |
| 회원 승격 | Redis 프로필 → `user_profiles` 이관 | **승격 UX 없음** (저장 안 됨 고지와 충돌) | 불일치 |
| 저장 시도 시 로그인 유도 | E1~E4 인증 필수 | 4️⃣ 화면에 게스트 상태 처리 없음 | 불일치 |

→ **J3 (Major)**

---

## 2. 이슈 목록

### Critical (배포/결재 차단)

#### C1. 온보딩 태그 스키마가 3부서 간 맞물리지 않음 — `weight_vector`는 **어느 부서도 정의하지 않았다**
- **위치**: `02-ai-strategy.md §1.3` ↔ `01-backend-design.md §5.2 tag_axis_registry, §6.2 A1, §7.1 extract_tags` ↔ `03-design-spec.md §3.4`
- **문제**:
  1. backend는 `extract_tags()`가 `weight_vector: list[float]`(12~24차원)와 `vector_version`을 반환한다고 계약했고, DB 컬럼(`user_profiles.weight_vector REAL[]`)과 `tag_axis_registry.vector_index`로 물리적 근거까지 만들어 두었다. **그러나 AI 문서에는 weight_vector가 존재하지 않는다.** AI §2의 5축 가중치(congestion/profile_fit/distance/local_exposure/trust)는 **스코어링 가중치**이지 태그 벡터가 아니다 — 이름이 비슷할 뿐 의미도 차원도 다르다.
  2. backend는 "backend가 임의로 축을 만들지 않는다"고 명시했으나, §6.2 A1 응답 예시에서 이미 12차원 벡터를 제시해 사실상 축 순서를 암묵 정의했다. 이 예시가 정본으로 오해될 수 있다.
  3. 구조 불일치: backend `tags: dict[str, list[TagValue]]` vs AI 실제 반환값 — `child_present`(bool), `pet_present`(bool), `accessibility`(object), `confidence`(float), `unmatched_note`(str|null) **5개 필드가 list[TagValue]가 아니다.**
  4. confidence 해상도: backend는 값마다, AI는 추출 전체에 1개. backend DB 예시 `{"v":"couple","c":0.92}`를 채울 방법이 없다.
  5. 명칭: `spot_preference`(AI) vs `spot_pref`(backend). 값도 한국어(AI) vs 영문코드+label_ko(backend).
- **재현/근거**: AI §1.3 JSON Schema의 required 10개 필드와 backend §7.1 `OnboardingResult` TypedDict 5개 필드를 나란히 놓으면 교집합이 `tags`(이름만, 구조 불일치) 하나다.
- **수정안**:
  1. **AI팀이 정본**이다(PRD 6.1-(a)). AI가 §1.3 스키마를 유지하되 (1)값을 영문 코드로 바꾸고 한국어는 label로 분리, (2)축 이름 확정, (3)accessibility 4 boolean과 child/pet boolean을 (axis,value) 쌍으로 표현 가능한 형태로 평탄화, (4)**`weight_vector` 차원 정의표(축·값·인덱스 N개)를 명시적으로 산출**한다. 이 표가 그대로 `tag_axis_registry` seed가 된다.
  2. AI가 `vector_version`/`extracted_by`/`fallback_used` 3필드를 반환 규약에 추가한다.
  3. backend는 §6.2 A1의 12차원 예시를 AI 확정본으로 교체한다.
- **담당**: ai-optimization-engineer (주) / backend-engineer (종)

#### C2. 1:1 비교 리포트가 3자 전부 다른 계약을 쓰고 있음 — 일치 필드 1개
- **위치**: `01 §6.2 D1` ↔ `02 §3.3` ↔ `03 §5.2`
- **문제**: 1.2절 대조표 참조. 객체 키(`hotspot`/`hotspot_course`), ID 타입(int/string), 단위(m/km), 등급 enum(low·mid·high / 혼잡·여유), 신뢰도 체계(tier A/B/C / 실측·추정·데이터없음)가 전부 다르다. designer는 이 상황을 인지하고 "잠정 필드"라고 표기했으나(03 §5.2, D2), **정본이 확정되지 않은 상태 그대로 최종 결재 대상에 들어가 있다.**
- **왜 Critical인가**: M3는 PRD가 "창의성 축의 단일 최대 기여 기능, 프로젝트의 얼굴"로 규정한 MVP다. 이 상태로 승인되면 후속 구현 프로젝트가 **어느 문서를 API 스펙으로 삼아야 하는지 알 수 없다.** 대표는 "핵심 화면 데이터 계약 확정됨"으로 오인하게 된다.
- **수정안**: PRD 6.1-(b)에 따라 **필드 정의는 AI, 직렬화·키 구조는 backend**로 소유권을 분리한다.
  - AI가 02 §3.3을 backend의 `hotspot`/`hidden` 대칭 키 구조·미터 단위·영문 enum으로 재작성(backend 응답 봉투가 designer 모바일 대칭 렌더링의 전제이므로 backend 형식이 유리).
  - AI가 `verdict` 블록(→ J2도 함께 해소)과 `congestion.confidence`↔`tier` 매핑표(A=실측 / B=추정 / C=추정·저신뢰 / 데이터없음)를 추가.
  - designer가 4개 지표 라벨을 확정 필드에 재매핑하고, **tier/confidence 표기 UI와 `data_freshness.notice` 노출 자리**를 추가(현재 없음 — J5 참조).
- **담당**: ai-optimization-engineer (주) / backend-engineer, designer (종)

#### C3. M6 동적 로드밸런싱이 **서로 다른 두 규칙**으로 이중 정의됨
- **위치**: `01 §8 (8.2~8.4)` vs `02 §4 (4.1~4.4)`
- **문제**: 같은 MVP 기능에 대해 두 부서가 호환되지 않는 알고리즘을 각각 완결 설계했다.

| 항목 | backend §8 | AI §4 |
|---|---|---|
| 측정 지표 | `guidance_issued` 가중 카운트 (안내1.0/저장2.0/조회0.3) | 추천 노출수 + 길안내 요청수 |
| 임계 방식 | **절대** — 가중카운트 / effective_capacity | **상대** — share(c) = exposure(c)/클러스터합 |
| 임계값 | 0.6(AMBER) / 0.85(RED) | 0.4 (THRESHOLD_RATIO) |
| 윈도 | 6시간 (Redis 시간버킷) | 3시간 rolling |
| 분산 방식 | **선택 단계에서 확률 추출**, RED면 A **완전 배제** | **스코어 단계에서 소프트 페널티**, "완전 차단하지 않음"을 설계 원칙으로 선언 |
| 실행 위치 | `select_route_with_balancing()` (스코어링 **후**) | `score_adjusted(c)` (스코어링 **내부**) |
| 대안 부족 폴백 | 3단계 (시간분산→반경확대→정직안내) | 1단계 (시간분산 문구) |

- **왜 Critical인가**: (a) 두 설계를 그대로 구현하면 **페널티가 두 번 적용**되고, backend의 RED 완전배제가 AI의 "완전 차단 금지" 원칙과 정면 충돌한다. (b) backend `select_route_with_balancing`은 내부에서 `profile_fit`을 위해 AI의 `score_routes`를 재사용한다고 적혀 있는데, AI의 `score_routes`는 이미 LB 페널티를 포함하므로 **순환 구조**가 된다. (c) M6는 PRD 심사축 "사회적 가치"의 성공 기준이자 "심사위원이 반드시 질문할 지점"인데, 질문에 대한 답이 문서 안에 두 개 있다.
- **수정안**: planning-lead가 정본을 택일한다. QA 권고는 **backend §8을 골격으로 채택**(수용력 기반 절대 임계 + 3단계 폴백이 R7의 "대안 부족 시 동작"을 더 완전히 답한다), 단 **AI §4.3의 소프트 페널티 철학을 AMBER 구간에 흡수**(RED 완전배제는 유지하되 AMBER는 점수 감점으로 처리)한다. 임계치·윈도는 backend 값으로 통일하고, AI는 `score_routes`에서 LB 페널티를 제거해 순수 스코어링만 담당한다.
- **담당**: planning-lead(택일) → ai-optimization-engineer + backend-engineer(반영)

### Major (승인 전 해소 권장 / 구현 착수 전 필수)

#### J1. `score_routes()` 시그니처가 AI 스코어링의 입력 요구를 충족하지 못함
- **위치**: `01 §7.1` ↔ `02 §2.2, §3.1, §3.2`
- **문제**: AI 공식은 5축 가중치 W, 태그 이진벡터 u, accessibility boolean 4개(하드필터), detour_ratio, local_spot_count, 리뷰수를 요구하는데 backend는 `weight_vector` 하나 + candidates + congestion만 넘긴다. 또한 하드필터(02 §3.1-2)가 AI 내부에 있는데 backend는 후보 생성을 공간쿼리로 자기가 한다고 선언 — **필터 책임 경계가 겹친다.** `congestion` 키 타입도 int vs string 불일치.
- **수정안**: 시그니처를 `score_routes(profile: OnboardingResult, candidates: list[dict], congestion: dict[int,float]) -> list[RouteScore]`로 바꿔 프로필 전체를 넘기고, W 산출(02 §2.2)을 AI 내부에 둔다. `candidates` dict가 반드시 포함해야 할 키(pet_allowed/barrier_free/parking/거리/로컬상점수/리뷰수)를 backend가 명세한다. 하드필터는 AI 소관으로 단일화.
- **담당**: backend-engineer + ai-optimization-engineer

#### J2. `build_verdict()`가 AI 산출물에 존재하지 않음 + 요청당 LLM 호출 비용·장애가 미평가
- **위치**: `01 §7.1, §6.2 D1 verdict.headline` ↔ `02` (해당 없음)
- **문제**: backend는 `verdict.headline`을 "AI팀 산출물"로 명시했으나 AI 문서에 설계가 없다. 더 중요한 것은 **이것이 LLM 생성 문장이라면**: (a) AI §1.6 비용 추정은 온보딩 1건만 계산했고 compare 요청당 호출은 계산에 없다, (b) AI §0은 "경로 랭킹은 LLM 생성 아님"을 차별화 포인트로 삼았는데 핵심 화면 M3가 다시 LLM 런타임 의존이 된다, (c) 시연 중 LLM 장애 시 M3 헤드라인이 비는데 폴백이 없다(§1.7 폴백은 온보딩 전용).
- **수정안**: headline을 **템플릿 문자열 조립(LLM 미사용)**으로 설계할 것을 권고한다 — deltas가 이미 수치로 넘어오므로 "{duration_delta}분 더 걸리지만 혼잡도는 {congestion_delta}p 낮고, {n}개 조건을 만족합니다" 수준으로 충분하며 오프라인 시연 안전성과 §0의 "설명 가능한 AI" 서사에도 부합한다. LLM을 쓰기로 한다면 비용 재추정 + 폴백 템플릿을 반드시 병기한다.
- **담당**: ai-optimization-engineer

#### J3. 게스트 체험의 저장 위치가 서버(Redis) vs 클라이언트(localStorage)로 갈리고, 사용자 고지가 승격 설계와 모순
- **위치**: `01 §10.1, §9.1 session:guest:*` ↔ `03 §4-0️⃣`
- **문제**: 1.4절 대조표 참조. 특히 designer의 배너 문구 **"체험 모드 — 결과가 저장되지 않습니다"**는 backend의 "Redis 24h 보관 후 회원가입 시 DB 승격"과 사실관계가 다르다. 개인정보 고지 성격의 문구이므로 부정확하면 legal 리스크로도 번진다(07 §1-4 최소수집/동의 설계).
- **수정안**: backend 안(서버 Redis + 승격)을 정본으로 채택하고, designer가 (a) 배너를 "체험 모드 — 24시간 임시 보관되며, 가입하시면 그대로 이어집니다"로 수정, (b) 회원가입 화면에 "체험 중 만든 취향 프로필 이어받기" UX 추가, (c) 게스트가 저장/리뷰 시도 시 로그인 유도 모달을 4️⃣ 화면에 추가. 단 Q-I3(도입 여부)가 미확정이므로 **planning-lead 결정 선행**.
- **담당**: planning-lead(결정) → designer(주) / backend-engineer(종)

#### J4. 게스트 승격 경로 — `X-Guest-Id` 헤더 수용 + 승격 1회성 규칙 부재 (backend 자체신고 #2 **격상**)
- **위치**: `01 §6.0 공통 규약`("게스트는 X-Guest-Id 헤더"), `§10.1 승격`, `§10.2 guest_id 쿠키`
- **검증 결과**: backend가 신고한 `/me/*` IDOR 자체는 **실재하지 않는다** — §10.3이 "path의 user_id를 신뢰하지 않고 토큰의 sub만 사용"으로 이미 올바르게 규정했고, `/me/*` 엔드포인트에 path user_id가 아예 없다. **그러나 게스트 승격 쪽은 backend가 "확인 필요"로 남긴 것보다 실질적이다**:
  1. `guest_id`를 HttpOnly 쿠키로 내려놓고 동시에 **`X-Guest-Id` 헤더로도 수용**한다고 규정했다. 헤더는 클라이언트가 임의 설정 가능하므로 HttpOnly 쿠키의 보호 효과가 무력화된다. 타인의 guest_id를 알면 그 프로필(자연어 원문 `raw_input` 포함)을 읽고 **자기 계정으로 승격시켜 가져갈 수 있다.**
  2. 승격 처리에 **멱등성/1회성 소비 규칙이 없다.** 같은 guest_id로 여러 계정이 반복 승격 가능하다.
  3. guest_id가 UUIDv4라 추측은 비현실적이지만, 공유 링크·로그·에러 리포트에 한 번 노출되면 즉시 탈취 경로가 된다.
- **Critical이 아닌 이유**: 게스트 프로필에 개인식별정보가 거의 없고(이메일 미수집), 인증 상세 구현은 PRD N7 논스코프이며 실제 구현 시 security-engineer 경유가 이미 강제되어 있다.
- **수정안**: (a) `X-Guest-Id` 헤더 수용을 **삭제**하고 HttpOnly 쿠키 단일 경로로 통일, (b) 승격을 Redis `GETDEL`(원자적 읽기+삭제)로 1회성 소비 처리, (c) 승격 시 대상 user_id가 방금 생성된 계정인지 검증, (d) guest_id를 요청 로그·URL에 기록 금지 명시.
- **담당**: backend-engineer

#### J5. Tier 혼재 — 전광판 쿼리에 tier tie-break 없고 `data_freshness`가 응답당 1개 (backend 자체신고 #3 **실재 확인**)
- **위치**: `01 §5.2 uq_congestion_point`, `§5.3-(3) LATERAL 쿼리`, `§6.0 data_freshness`, `§7.5 TierController`
- **검증 결과**: **실제로 발생한다.** 근거 3단계:
  1. `uq_congestion_point`가 유니크 키에 `tier`를 포함한다 → 동일 (place_id, observed_at, horizon_min)에 tier가 다른 두 행이 **합법적으로 공존**한다.
  2. §5.3-(3) 전광판 쿼리는 `ORDER BY cs.observed_at DESC LIMIT 1`만 하고 tier 필터/tie-break가 없다 → 같은 시각 행이 둘이면 어느 것이 뽑힐지 비결정적. place마다 다른 tier가 뽑혀 **한 화면에 신뢰도가 다른 값이 섞인다.**
  3. `data_freshness`는 응답당 1개 블록이라 tier가 단일 표기된다 → **혼재 상황에서 표기가 사실과 달라진다.** 이는 backend 자신의 P3 원칙("모든 혼잡도 값은 출처·신선도·신뢰등급을 함께 전달")과 문서 전반의 정직성 원칙을 정면으로 깬다. 정직한 데이터 표기를 심사 가점 요인으로 삼은 설계(§7.5)에서 이 결함은 가치 훼손이 크다.
- **수정안**: (a) 전광판 쿼리에 `ORDER BY cs.observed_at DESC, cs.tier ASC`(A>B>C 우선) tie-break 추가, (b) 응답의 각 item에 tier를 개별 포함, (c) `data_freshness.tier`는 응답 내 **최악 tier**를 표기하거나 `"mixed"` 값을 허용, (d) designer는 item별 tier 배지 자리를 확보(현재 없음).
- **담당**: backend-engineer (주) / designer (종)

#### J6. N1(EXIF 인증) 잔재 — AI 스코어링과 designer 비교표가 **존재하지 않는 기능을 우위 근거로 사용**
- **위치**: `02 §3.3 trust.verified_review_count / "source":"실방문 인증 리뷰"`, `§3.4 콜드스타트`, `03 §5.2 방문 신뢰도 행`, `mockup/index.html:700-701, 732`
- **검증 결과**: backend는 N1을 **모범적으로 차단했다** — `reviews` 테이블에 `verified_visit`/`photo_url`/`exif_*` 컬럼을 일부러 만들지 않았고 그 이유까지 명시했다(§11.3). designer의 "인증 방문 준비 중" 비활성 배지도 PRD 6.4가 "자리만 비활성 상태로 표시"로 명시 허용한 범위 안이다.
- **그러나**: (a) AI는 `verified_review_count`를 **스코어링 S_trust의 실입력**으로 사용한다 — N1이 없으므로 이 값은 항상 0이거나 일반 리뷰 수를 "verified"라는 이름으로 오칭하게 된다. (b) designer 비교표와 목업의 "방문 신뢰도" 행은 핫플=`광고성 후기 위주` / 숨은길=`실방문 인증 리뷰`로 **숨은길의 우위 근거로 표시**된다. "준비 중" 주석이 붙어 있으나, 4개 지표 중 1개가 근거 없는 우위 주장인 것은 심사 시연에서 지적당할 지점이다.
- **수정안**: (a) AI가 `verified_review_count`→`review_count`로 개명하고 `trust.source`에서 "실방문 인증" 표현 제거, backend `review_trust{count, companion_matched_count}`와 정합. (b) designer가 "방문 신뢰도" 행을 **backend가 실제 제공하는 `companion_matched_count`(동행 유형이 일치하는 리뷰 수)** 기반으로 교체 — 이건 N1 없이도 `reviews.companion_type`으로 산출 가능하며 서비스 차별화에도 더 부합한다. (c) 목업 732행 데스크톱 테이블도 동일 수정.
- **담당**: ai-optimization-engineer + designer

#### J7. M6 로드밸런싱 결과가 **화면 어디에도 보이지 않음** (MVP 구멍)
- **위치**: `03-design-spec.md` 전체, `mockup/index.html` (실측: "분산/대안 코스/시간대" 문자열 **0건**)
- **문제**: backend는 `load_balancing{applied, reason, notice}`와 폴백 문구("지금은 붐빕니다. {시간대}에 방문하면 훨씬 여유롭습니다", "현재 이 지역에는 여유로운 대안 코스가 없습니다")를 응답에 담도록 설계했고, AI도 시간대 분산 메시지를 산출한다. **designer 스펙과 목업에는 이를 표시할 컴포넌트가 없다.** M6는 PRD가 "지정과제 오버투어리즘 해소에 대한 자기모순 해소 논리, 심사위원 반드시 질문할 지점"으로 규정한 MVP인데, 시연 화면에서 보이지 않으면 존재를 증명할 수 없다.
- **수정안**: designer가 AI 경로 비교 화면(§5.2)에 **분산 안내 배너 컴포넌트**를 추가한다 — `applied=true`일 때 "이 코스에 방문이 몰려 비슷한 분위기의 다른 코스를 안내합니다" / `reason=time_shift`일 때 시간대 제안 카드 / `no_alternative`일 때 정직 안내. 목업에도 최소 1개 상태를 렌더링한다.
- **담당**: designer

#### J8. legal-counsel이 요구한 UI 4종이 화면·목업에 전혀 없음
- **위치**: `07 §2 designer 조치사항` ↔ `03-design-spec.md`, `mockup/index.html` (실측: "동의/출처/개인정보/저작권/국외" 문자열 **0건**)
- **문제**: 07이 designer에게 명시 요구한 (a) 온보딩 개인정보 수집 안내 문구 + 동의 체크박스 영역, (b) LLM 국외이전 고지 자리, (c) 공공데이터 출처 표기(footer), (d) 지도 SDK 로고·저작권 표시 영역 — **4개 모두 스펙에도 목업에도 없다.** (a)(b)는 legal 주의 3건 중 2건(위치정보·국외이전)에 직결되고, (c)(d)는 공공데이터 이용약관·SDK 약관상 **의무 사항일 가능성이 높은** 항목이다.
- **정상 참작**: 07은 designer 산출 이후 작성됐을 가능성이 높아 designer가 인지하지 못한 상태였다. 과실이 아니라 **파이프라인 순서상 발생한 잔여 갭**이다.
- **수정안**: designer가 4개 영역의 자리(placeholder)만 스펙 + 목업에 추가한다. 문구는 07 §3 초안을 그대로 쓰되 "확정 전 임시" 표기. 지도 로고 영역은 §3.6에 "지도 하단 우측 SDK 저작권 표기 영역 최소 높이 확보"로 추가.
- **담당**: designer

#### J9. designer 칩 세트가 AI 태그 축의 절반을 커버하지 못함 — **오프라인 폴백 경로에서 하드필터가 무력화됨**
- **위치**: `03 §3.4` (칩 7종) ↔ `02 §1.3` (축 8종) ↔ `02 §1.2` (칩 전용 = LLM 미호출 경로)
- **문제**: 칩 7종은 companion 5값 + mood 1값 + spot_preference 2값만 커버한다. **`mobility`(5값), `accessibility`(boolean 4개), `congestion_preference`가 칩으로 전혀 입력되지 않는다.** 이게 중요한 이유:
  - AI §3.1-2 **하드필터는 전적으로 accessibility boolean 4개로만 작동**한다. 칩만 선택한 사용자는 전부 false가 되어 **하드필터가 아무것도 걸러내지 않는다** — 반려동물 동반 칩을 눌러도 `pet_friendly_required`가 false라 반려동물 불가 코스가 그대로 추천된다.
  - AI §1.2가 "칩 전용 입력은 LLM 미호출, 정확도 100%"라고 평가했는데, 이 경로는 실제로는 **정보량이 절반 이하**다.
  - AI §1.7이 시연 안전망으로 삼은 오프라인 경로가 바로 이 칩 경로이므로, 시연 중 LLM 장애 시 추천 품질이 눈에 띄게 떨어진다.
- **수정안**: (a) AI가 §1.7 칩→태그 직접 매핑 테이블을 실제로 작성하고, `#반려동물 동반` → `pet_present:true` + `accessibility.pet_friendly_required:true`처럼 **accessibility boolean까지 파급되도록** 규칙을 명시한다(현재 예시 1건뿐). (b) designer가 온보딩 2단계에 mobility 칩(도보/자전거/차량/대중교통)과 accessibility 칩(주차 필요/유모차/휠체어/반려동물 동반)을 추가한다 — 온보딩 헤더가 이미 "진행 1/2"로 2단계를 전제하므로 2단계에 배치하면 된다.
- **담당**: ai-optimization-engineer + designer

### Minor

#### m1. `select_route_with_balancing` read-then-decide 비원자성 (backend 자체신고 #1 — **격상 불필요, 현 등급 적정**)
- **위치**: `01 §8.3`
- **검증 결과**: 실재한다. `load_ratio()` 읽기 → 상태 분기 → 선택 사이에 락이 없고, `record_guidance()`는 선택 후 별도 호출이므로 동시 요청 N개가 같은 ratio를 읽고 모두 GREEN 판정을 받을 수 있다.
- **영향 평가**: 오차 상한은 "판정~카운트 반영 사이 동시 요청 수"이며, 윈도가 6시간·capacity가 일 단위라 **분모 대비 무시 가능한 크기**다. AMBER는 60% 확률 분산이 자연 완화 역할을 하고, RED 판정은 카운터가 이미 반영된 뒤 걸린다. 공모전 시연 및 초기 트래픽 규모에서 사용자 체감 영향은 사실상 0.
- **수정안**: 새 설계 불필요. 다만 문서에 "허용 오차임 + 그 근거(윈도 6h / 일 단위 capacity)"를 **명시적 설계 결정으로 기록**할 것. 정밀 제어가 필요해지면 Lua 스크립트로 read+incr를 원자화하는 경로만 각주로 남긴다.
- **담당**: backend-engineer (문서 보강만)

#### m2. 목업 "예시 데이터" 캡션이 6화면 중 2화면에만 존재 — 스펙 서술이 실제보다 넓음
- **위치**: `03 §9`("모든 수치 데이터에는 '예시 데이터' 캡션이 붙어 있다") ↔ `mockup/index.html` (실측 3건: 544 전광판 / 656 비교화면 / 894 전역 footer)
- **문제**: 2️⃣ 여행지 추천 카드의 거리 수치, 4️⃣ 저장한 코스의 저장일에는 개별 캡션이 없다. 전역 footer 문구가 있어 허위 데이터 오인 위험은 낮으나 **스펙 서술이 사실과 다르다.**
- **수정안**: 스펙 §9 문구를 "전광판·비교 화면에 개별 캡션 + 전역 footer 고지"로 정정하거나, 나머지 2화면에 캡션 추가.
- **담당**: designer

#### m3. verdict 델타 정의 불일치 (절대 포인트 vs 백분율)
- **위치**: `01 §6.2 verdict.congestion_delta: -64.6`(절대 p) ↔ `03 §5.2 "↓ 71% 낮음"`(상대 %)
- **문제**: 같은 값(87.4→22.8)을 backend는 -64.6p로, designer는 -71%로 표현한다(둘 다 산술적으로 맞음). 계약 확정 시 통일하지 않으면 화면 수치와 API 값이 달라 보인다.
- **수정안**: C2 재작업 시 `congestion_delta`(절대)와 `congestion_delta_pct`(상대)를 둘 다 내리고 designer가 어느 것을 쓸지 명시.
- **담당**: backend-engineer + designer

#### m4. 목업의 경로 점선 표현이 backend의 `path_source` 규약과 의미 충돌
- **위치**: `mockup/index.html:755-759` (핫플=실선 navy / 숨은길=`stroke-dasharray` 점선 green) ↔ `01 §7.6`("straight인 경로를 실선으로 그리면 실제 도로로 오인된다 — designer에게 점선 스타일 필요를 전달한다")
- **문제**: backend는 **점선 = 좌표열 미확보(품질 저하)** 신호로 규정했는데, 목업은 점선을 **숨은길 코스의 브랜드 표현**으로 쓰고 있다. 구현 시 숨은길 코스가 항상 저품질 경로로 오인된다.
- **수정안**: 숨은길/핫플 구분은 **색상 + 핀 형태**(§3.6에 이미 정의됨)로만 하고, 실선/점선은 `path_source` 전용 신호로 예약한다. designer §3.6에 이 규칙을 명문화.
- **담당**: designer

#### m5. `06-security-report.md` 미존재 — 3차 게이트가 QA 단독으로는 종결되지 않음
- **위치**: `projects/sumeungil/` (파일 목록 실측: 00, 01, 02, 03, 07, APPROVALS, _draft, mockup)
- **문제**: PRD §4는 3차 게이트를 "약식 + 개인정보 범위 한정 보안검토"로 지정하고 security-engineer의 `06-security-report.md`를 예외적으로 **필수 지정**했다. 현재 없다. 또한 4차(07 legal)가 3차보다 먼저 완료된 상태로 PRD §6.1 실행 순서와 어긋난다.
- **수정안**: planning-lead가 security-engineer에 "설계상 개인정보 수집 범위" 한정 검토를 위임하거나, 07 §1의 개인정보 판정으로 갈음한다는 결정을 APPROVALS.md에 명시 기록.
- **담당**: planning-lead

---

## 3. 스코프 준수 점검 (C항목)

### 3.1 논스코프(N1~N8) 침범 여부

| # | 항목 | 판정 | 근거 |
|---|---|---|---|
| N1 | EXIF/사진 인증 | **부분 침범** | backend 모범(스키마에 `verified_*`/`photo_*`/`exif_*` 컬럼 **0개**, 이유까지 명시). designer 허용범위(비활성 "준비 중" — PRD 6.4 명시 허용). **AI 침범**: `verified_review_count`를 스코어링 실입력으로 사용 → **J6** |
| N2 | 쿠폰 | 미침범 | 3개 문서·목업 전체에서 "쿠폰" 0건 |
| N3 | 오디오 가이드 | 허용범위 | designer 5️⃣ 화면 비활성 "준비 중" — PRD가 "화면 자리만 확보" 명시 허용. backend D13 수집 안 함 |
| N4 | Tmap 실주행 | 허용범위 | backend·designer 모두 "외부 지도앱 딥링크"로 일치 대체 |
| N5 | PWA | 미침범 | manifest/service worker 언급 0건 |
| N6 | BM/수익화 | 미침범 | backend §8.5가 `lb:fallback` 집계를 "B2G 리포트 근거"로 1줄 언급했으나 구현 설계 아님 |
| N7 | 인증 상세구현 | 허용범위 | backend §10이 토큰/rotation/argon2id까지 다루나 **설계 수준**이며 PRD가 "설계 수준만" 허용. 코드 구현 없음 |
| N8 | 배포/인프라 | 미침범 | backend §11.3이 "EC2+Nginx+Docker Compose 수준이며 후속 프로젝트 범위"로 1줄 언급만 |

**N1 관련 스키마/화면/필드 전수 확인 결과**: DB 스키마에 EXIF·사진 관련 컬럼 **0개**(backend가 의도적으로 배제하고 그 이유를 §11.3에 문서화 — 모범 사례로 기록). 화면은 비활성 자리표시로 PRD 허용범위. **유일한 실질 침범은 AI의 `verified_review_count`가 스코어링에 실제로 사용된다는 점**이며 J6로 분리 처리했다.

### 3.2 MVP(M1~M7) 커버리지 — 구멍 점검

| # | 기능 | backend | AI | designer | 판정 |
|---|---|---|---|---|---|
| M1 | 자연어 온보딩 + 태그 추출 | O | O | O | 계약 불일치(C1) / 칩 커버리지 부족(J9) |
| M2 | 실시간 혼잡도 전광판 | O (Tier A/B/C Plan B) | — (소비만) | O | tier 혼재(J5) |
| M3 | AI 1:1 대조 경로 리포트 | O | O | O | 계약 전면 불일치(C2), verdict 미설계(J2) |
| M4 | 지도 기반 경로 시각화 | O (Kakao 권고, path_geojson, MapProvider 격리) | — | O (마커/팝업/SVG) | SDK 저작권 표기 자리 없음(J8), 점선 의미 충돌(m4) |
| M5 | 로컬 스팟 매핑 | O (ST_DWithin 500m) | O (S_local) | O (로컬 상권 카드) | **구멍 없음** |
| M6 | 동적 로드밸런싱 규칙 | O | O | **X (UI 없음)** | 규칙 이중 정의(C3) + 화면 부재(J7) |
| M7 | 화면 5종 반응형 웹 UI | — | — | O (6종) | **구멍 없음** |

**어느 부서도 다루지 않아 구멍이 난 항목**: 없음. 다만 **M6가 designer 산출물에서 완전히 누락**되어 사용자에게 보이지 않는 상태다(J7). M6는 PRD 심사축 "사회적 가치"의 단일 증거이므로 실질적 구멍으로 취급했다.

---

## 4. 목업 실검증 결과 (D항목)

`projects/sumeungil/mockup/index.html` — **실행 검증 수행**

| 검증 항목 | 방법 | 결과 |
|---|---|---|
| 파일 존재/크기 | `ls -la`, `wc -l` | 통과 — 단일 파일 50,508 bytes / 926줄 |
| **외부 네트워크 요청 0건** | `grep -E "https?://ㅣ<script srcㅣ<link ㅣcdnㅣ@importㅣfetch(ㅣXMLHttpRequest"` | **통과 — 매칭 0건.** 오프라인 요건 충족 |
| `<script>` 태그 | `grep -c "<script"` | 통과 — 1개, 전부 인라인 (src 속성 없음) |
| 웹폰트 | `03 §1.2` 대조 | 통과 — Pretendard → OS 산세리프 로컬 폴백, CDN 로드 없음 |
| **6개 화면 존재** | `grep 'class="screen"'` | **통과** — `s-onboard`/`s-home`/`s-discover`/`s-compare`/`s-saved`/`s-tips` (464·511·569·640·787·844행) |
| 화면 전환 동작 | 인라인 스크립트 검토 | 통과 — `.viewer__tab` 클릭 → `is-active` 토글, `data-target`으로 섹션 매핑. 로직 정합 |
| **토큰 #1B4332** | `grep` | **통과** — 14행 `--color-green-600:#1B4332` |
| **토큰 #0B2545** | `grep` | **통과** — 18행 `--color-navy-600:#0B2545` |
| **토큰 #5C4033** | `grep` | **통과** — 22행 `--color-brown-600:#5C4033` |
| **"예시 데이터" 표기** | `grep -c` | **조건부** — 3건(544 전광판 / 656 비교화면 / 894 전역 footer). 스펙 §9의 "모든 수치 데이터" 서술보다 좁음 → **m2** |
| N1/N2 UI 비활성 | `grep "인증ㅣ쿠폰"` | 통과 — 605·617·629행 `badge--muted "인증 방문 준비 중"`, 810·824행 `<button disabled>`. 쿠폰 0건 |
| 데스크톱 2컬럼 비교표 | 732행 확인 | 통과 — `<td>` 기반 테이블 존재 (스펙 §5.2 데스크톱 변형과 일치) |
| legal 요구 UI | `grep "출처ㅣ동의ㅣ개인정보ㅣ저작권ㅣ국외"` | **미달 — 0건** → **J8** |
| M6 분산 안내 UI | `grep "분산ㅣ대안 코스ㅣ시간대"` | **미달 — 0건** → **J7** |

**목업 종합**: 오프라인 요건·화면 수·디자인 토큰·논스코프 비활성 처리는 **전부 검증 통과**. 결함은 누락 2건(J7·J8)과 캡션 범위(m2)·점선 의미(m4)뿐이며, 파일 자체의 무결성 문제는 없다.

---

## 5. 시크릿 하드코딩 점검 (E항목, 약식 검수 필수)

**스캔 범위**: `projects/sumeungil/` 하위 전 `*.md` + `*.html`
**패턴**: `sk-[A-Za-z0-9]{16,}`, `AKIA[0-9A-Z]{12,}`, `ghp_[A-Za-z0-9]{20,}`, `serviceKey=[A-Za-z0-9%]{20,}`, `api[_-]?key\s*[:=]\s*"[A-Za-z0-9]{16,}"`

### 결과: 매칭 0건 — **통과**

발견된 문자열은 전부 안전한 플레이스홀더로 확인:

| 위치 | 문자열 | 판정 |
|---|---|---|
| `01 §6.2 F2` | `"password": "••••••••"` | 마스킹 문자, 실값 아님 |
| `01 §6.2 F2` | `"access_token": "eyJhbGciOi..."` | 절단된 JWT 헤더 예시, 페이로드·서명 없음 |
| `01 §7.3` | `f"Bearer {settings.public_api_key}"` | ENV 참조 변수, 리터럴 아님 |
| `01 §10.4` | `"secret"` | **금지 사례로 인용**된 것 (기본값 금지 규칙) |
| `01 §6.2 A1` | `"region_code": "26350"` | 행정구역 코드 |

**추가 확인 — 시크릿 관리 설계 자체는 우수**: backend §10.4가 (a) 5종 시크릿의 저장 위치·금지사항 표, (b) `.env.example`만 커밋 + `.gitignore`, (c) pre-commit `gitleaks`/`detect-secrets`, (d) 필수 ENV 미설정 시 **부팅 즉시 종료(fail-fast)**, (e) 로깅 미들웨어에서 `Authorization`/`serviceKey`/`apiKey`/`password` 마스킹까지 규정했다. 지도 SDK 키의 클라이언트 노출 불가피성을 인정하고 **referrer 도메인 허용목록**으로 대응한 점도 정확하다. 이 절은 그대로 구현 단계로 넘겨도 좋다.

---

## 6. 검수 통과 여부

| 게이트 조건 | 결과 |
|---|---|
| Critical 이슈 0건 | **미달 — 3건** |
| 시크릿 하드코딩 0건 | 통과 |
| 논스코프 침범 없음 | 조건부 (N1 잔재 1건, Major로 처리) |
| MVP 커버리지 | 조건부 (M6 화면 누락) |
| 목업 오프라인 요건 | 통과 |

> ## **3차 게이트: 미통과 — 재작업 필요**

### 재작업 요청 대상

| 담당 부서 | 처리할 이슈 |
|---|---|
| **planning-lead** | C3(M6 규칙 택일), J3(게스트 도입 여부 확정 Q-I3), m5(보안 검토 위임 또는 갈음 결정) |
| **ai-optimization-engineer** | C1(주), C2(주), J1, J2, J6, J9 |
| **backend-engineer** | C1(종), C2(종), J1, J4, J5(주), m1, m3 |
| **designer** | C2(종), J3(주), J6, J7, J8, m2, m3, m4 |

**재작업 후 재검수 범위**: Critical 3건 + Major 9건의 해소 여부만 확인하는 **약식 재검수 1회**. 목업 오프라인 요건·시크릿·논스코프 나머지 항목은 이번에 통과했으므로 재검증하지 않는다.

**AI 최적화 정확도 회귀 확인**: 해당 없음. 02-ai-strategy.md는 신규 설계이며 기존 모델의 최적화·벤치마크 비교 대상이 존재하지 않는다. AI팀도 정확도 수치를 제시하지 않았고(PRD 6.3 제약 준수), 비용 추정치는 전부 "가정치"로 명시했다 — 근거 없는 수치 제시 없음을 확인했다.

---

## 7. 검수하며 확인된 강점 (기록용)

재작업 지시가 문서 전체의 품질을 오해하게 만들지 않도록 함께 기록한다.

1. **backend §7.5 Tier A/B/C Plan B** — R1(SPOF)에 대해 "D1이 어떤 형태든 서비스가 성립한다"는 목표를 실제 산출식·상태머신·화면 표기 정책까지 완결했다. 이 문서에서 가장 가치 높은 부분이며 심사 대응력도 실질적이다.
2. **backend의 N1 차단 방식** — 스키마에 컬럼을 만들지 않은 것 + "자리를 만들면 다음 단계에서 자동으로 구현 대상이 된다"는 이유 명시는 스코프 통제의 모범이다.
3. **AI §1.5 prompt injection 다층 방어** — 특히 "이 LLM 호출에는 도구 권한이 없으므로 blast radius가 0에 가깝다"는 위협 모델링이 정확하고, 향후 도구 권한 부여 시 재검토하라는 조건까지 남겼다.
4. **AI의 hallucination 억제 설계** — 페르소나1에서 초안이 부여한 "혼잡 회피"를 입력에 근거가 없다는 이유로 `unspecified`로 남긴 판단, `unmatched_note`로 스키마 밖 개념을 강제 태그화하지 않은 처리는 PRD의 정직성 원칙을 실제로 구현했다.
5. **designer §2 WCAG 대비비 실측** — 통과 조합뿐 아니라 **실패 조합 3건(1.18:1 등)을 계산해 기각 근거로 남긴 것**은 드문 수준의 성실성이다. Glassmorphism을 무장애 근거로 기각한 판단도 타당하다.
6. **designer §5 모바일 비교 UI** — "컬럼→행 전환"은 375px 제약에서 비교 목적을 지키는 정확한 해법이며, 대안(가로 스크롤/폰트 축소/아코디언)을 왜 기각했는지도 명시했다.
7. **3개 문서 모두 "확인 필요"를 정직하게 집계** — backend 26건(P0 8건), AI 7건, designer 4건. PRD 2.3 완료 조건을 실제로 충족했고, 추측으로 사실을 채운 곳을 검수 중 발견하지 못했다.

---

## 8. 핸드오프 노트

```
[다음 부서가 알아야 할 것]
1. Critical 3건(온보딩 태그 스키마 / 비교 리포트 필드 / M6 규칙 이중정의)은 전부 부서 간 계약 불일치이며,
   "누가 정본인지 정하고 나머지가 따라간다"로 해소된다 — 새 설계가 필요한 건 C3 택일 하나뿐이다.
2. content-marketer 주의: 아래 3개는 클라이언트/대외 보고서에 성과로 쓰면 안 된다 —
   (a) "실방문 인증 리뷰"·"방문 인증" 일체(N1 미구현, J6), (b) "AI 경로 비교 API 계약 확정"(C2 미확정),
   (c) "동적 로드밸런싱 동작"(규칙 미택일 + 화면 미구현, C3·J7).
3. 목업은 오프라인 실행·6화면·브랜드 토큰·시크릿 0건을 실검증 통과했다 —
   시연 자료로 그대로 써도 되나, 개인정보 동의·공공데이터 출처·지도 SDK 저작권 표기 자리가 없다(J8).
```
