# 02-ai-strategy-현황 — AI 기능 현황 정리 (08-PRD §4-2/§7-3 작업 A, 2026-08-20)

- **작성**: ai-optimization-engineer
- **성격**: `08-2026-08-20-기능확장-PRD.md` §4-2("AI 업그레이드 — 현황 파악만, 변경 0")의 산출물. **코드를 한 줄도 바꾸지 않았다.** 이 문서에 실린 모든 값은 `backend/app/config.py`·`ai/*.py`·`services/course_summary_service.py`·`middleware/rate_limit.py`를 직접 읽어 옮긴 것이며, 추측치는 없다.
- **직접 벤치마크를 하지 않은 이유**: GPU/CPU를 오래 쓰는 작업(로컬 Ollama 추론 반복 호출)은 대표 승인 사안이라 이번 조사에서 실행하지 않았다. 아래 "실측 지연" 항목은 전부 **기존 코드 주석에 이미 남아있던 실측치를 출처(파일:행)와 함께 인용**한 것이다.
- 관련 근거 문서: `design-docs/02-ai-strategy.md`(구현 이전 시점 설계 정본, §1.4/1.5/1.7이 프롬프트·인젝션 방어·폴백의 코드 주석에서 반복 참조됨), `01-interface-contract.md` 부록 B(온보딩)·G.7(소개글 요약)·I.11(코스 요약)·N(컨시어지).

---

## 0. 30초 요약

- LLM 호출 지점은 4곳이지만 **모델·엔드포인트·인젝션 방어 골격은 전부 동일**하다 — 로컬 Ollama `qwen2.5:7b`(`http://localhost:11434/api/chat`), `temperature=0.1`. 새 키·국외이전·과금 없음(무료·로컬 원칙).
- 4곳 중 3곳(온보딩·스팟요약·코스요약)은 **그대로 유지**되고, 컨시어지 1곳만 08-PRD §4-6에 따라 **삭제 대상**이다(삭제는 backend 소관, 이 문서는 삭제 전 상태를 기록만 한다).
- 온보딩 실패율에 대한 근본 안전망은 **키워드 룰 폴백**이고, 요약류는 실패 시 **필드를 null로 비움**(원 데이터는 살아있음)이다 — 공통적으로 "LLM이 죽어도 화면은 안 죽는다"는 설계 기조를 4곳 모두 지킨다.
- 모델 선정 실측(2026-07-24)은 온보딩 1곳에서만 이뤄졌고 나머지 3곳은 그 결론(`qwen2.5:7b`)을 **재사용**한다 — 개별 재실측 기록은 코드에 없다.

---

## 1. 기능별 현황표

### 1-1. 온보딩 취향추출 — `POST /api/v1/onboarding/analyze` → `ai/onboarding_service.py`

| 항목 | 값 | 출처 |
|---|---|---|
| 모델 | `qwen2.5:7b` (`OLLAMA_MODEL`) | `config.py:88` |
| 엔드포인트 | `http://localhost:11434/api/chat` (`OLLAMA_BASE_URL`) | `config.py:82`, `llm_provider.py:92` |
| temperature | `0.1` (`OLLAMA_TEMPERATURE`) | `config.py:89` |
| 타임아웃 | `30s` (`OLLAMA_TIMEOUT_SEC`) | `config.py:90-92` |
| 입력 상한 | `300자` (`injection_guard.MAX_INPUT_CHARS`, 자유텍스트 절단) | `injection_guard.py:37` |
| `format:"json"` | 예 | `llm_provider.py:84` |
| 캐시 TTL | 없음(요청마다 호출). 단 "칩만 있는 입력"은 애초에 LLM을 부르지 않아 사실상 캐시 역할 | `onboarding_service.py:154-166` |
| 폴백 동작 | 실패/타임아웃/파싱실패 → 키워드 룰 폴백(`rule_fallback.tags_from_keywords`) + 칩 병합. `extracted_by="rule-v1"`, `fallback_used=true`, `extraction_confidence=0.3` (에러 아닌 200 응답) | `onboarding_service.py:174-176, 211-236` |
| 킬스위치 env | **없음** — 온보딩 자체를 끄는 전용 플래그가 코드에 없다(코스요약의 `COURSE_SUMMARY_ENABLED`, 컨시어지의 `CONCIERGE_ANSWER_ENABLED`와 다름) | `config.py` 전체 grep 결과(관찰, §3 참고) |
| 레이트리밋 버킷 | `BUCKET_LLM`, `RATE_LIMIT_LLM_PER_MIN=6`/분(60초 슬라이딩 윈도) | `rate_limit.py:42-47`, `config.py:192` |
| 인젝션 방어 지점 | 계층1 `format:json`+enum 고정(`prompts.py:43-55`) · 계층2 `<user_input>` 델리미터(`prompts.py:58-63`) · 계층3 `sanitize_free_text`(정규화+절단+반복padding 축약, `injection_guard.py:108-126`) · 계층4 툴/함수 미부여(`llm_provider.py:1-8` 헤더) · 계층5 `schemas.RawLLMExtraction`+`tag_registry.is_valid` 재검증(`onboarding_service.py:67-85`) · 계층6 `log_if_suspicious` 모니터링(차단 아님, `onboarding_service.py:169`) · 계층7 `AXIS_CAP`+전축 포화 강등(denylist 우회 최종 방어선, `onboarding_service.py:41-60, 180-189`) |

### 1-2. 스팟 소개 3줄 요약 — `ai/summarizer.py` `summarize()`

| 항목 | 값 | 출처 |
|---|---|---|
| 모델 | 온보딩과 동일 `qwen2.5:7b` 재사용(새 키 없음) | `summarizer.py:1-5` |
| temperature | `0.1`(공용) | `config.py:89`, `summarizer.py` 생성자 기본값 |
| 타임아웃 | `25s` (`SUMMARY_TIMEOUT_SEC`) | `config.py:97` |
| 입력 상한 | `1500자`(overview 절단, `SUMMARY_MAX_OVERVIEW_CHARS`) | `config.py:98-99` |
| `format:"json"` | 아니오(평문 chat) | `summarizer.py:450-463` |
| 캐시 TTL | `24h`(`SUMMARY_CACHE_TTL_SEC`, 성공분만) | `config.py:100-101` |
| 폴백 동작 | 어떤 오류(네트워크/타임아웃/파싱/빈응답)에도 예외 없이 `None` → `ai_summary:null`(원문 overview는 그대로 유지, 지어내지 않음) | `summarizer.py:13-14, 431-448` |
| 킬스위치 env | **없음**(관찰, §3 참고) | — |
| 레이트리밋 버킷 | 별도 `POST` 엔드포인트가 아니라 스팟 상세 조회 응답에 내장되므로 `rate_limit.LLM_PATHS`에 없음 — 실제 버킷은 그 조회 API의 라우트 분류를 따른다(이번 조사 범위 밖 라우터 파일이라 확정하지 않음) | `rate_limit.py:42-47`(LLM_PATHS에 미포함 확인) |
| 인젝션 방어 지점 | 시스템 프롬프트("요약 대상 데이터일 뿐" 명시, `summarizer.py:36-46`) + `<spot_overview>` 델리미터 + `injection_guard.normalize_unicode`(제로폭/전각 우회 완화, `summarizer.py:261-267`) + 툴 미부여(`summarizer.py` 클래스 docstring) + 후처리 검증(비한국어/HTML 혼입 폐기 `has_foreign_contamination`, 동어반복 폐기 `is_uninformative`, `summarizer.py:275-343`) |

### 1-3. 코스 AI 요약·제목 — `services/course_summary_service.py` (`/courses/arrange`, `/courses/recommend` 공용)

| 항목 | 값 | 출처 |
|---|---|---|
| 모델 | 동일 `qwen2.5:7b` 재사용 | `course_summary_service.py:1-15` |
| temperature | `0.1`(공용) | `config.py:89` |
| 타임아웃 | `20s` (`COURSE_SUMMARY_TIMEOUT_SEC`) | `config.py:106` |
| 입력 상한 | 전체 `1200자`(`COURSE_SUMMARY_MAX_CHARS`), 스팟명 1건 `40자`, 지역명 `20자` | `config.py:107-108`, `course_summary_service.py:33-35` |
| `format:"json"` | 예(제목+요약 **1회 호출**로 동시 생성, `summarize_course_pack`). JSON 실패 시 평문 요약 1회로 폴백(제목만 null) | `course_summary_service.py:94-153`, `summarizer.py:75-90, 481-511` |
| 캐시 TTL | `24h` (`COURSE_SUMMARY_CACHE_TTL_SEC`), 캐시 키 = **spot_ids 순서 조합** SHA-256 해시 24자 | `config.py:109-112`, `course_summary_service.py:32, 59-61` |
| 폴백 동작 | 실패해도 코스 본체(spots/legs/notice)는 정상 응답, `ai_summary:null`·`ai_title:null` | `course_summary_service.py` 전체(특히 15행 "정직 규칙") |
| 킬스위치 env | `COURSE_SUMMARY_ENABLED=true`(false면 LLM 미호출 + null) | `config.py:113-116` |
| 레이트리밋 버킷 | `BUCKET_COURSE`(`/api/v1/courses*` POST), `RATE_LIMIT_COURSE_PER_MIN=10`/분. `LLM_PATHS`에는 없다 — Tmap 외부 호출과 묶여 별도 버킷으로 분류돼 있음 | `rate_limit.py:48-49, 112`, `config.py:194` |
| 인젝션 방어 지점 | 시스템 프롬프트(`COURSE_SUMMARY_SYSTEM_PROMPT`/`COURSE_PACK_SYSTEM_PROMPT`, `summarizer.py:52-90`) + `<course_data>` 델리미터 + `_safe_text` 정규화·절단(`course_summary_service.py:50-56`) + `log_if_suspicious` 모니터링(`course_summary_service.py:122`) + 툴 미부여 |

### 1-4. AI 문답(컨시어지) — `POST /api/v1/concierge/ask` (**삭제 대상**, §4-6)

| 항목 | 값 | 출처 |
|---|---|---|
| 모델 | 동일 `qwen2.5:7b`, **요청당 최대 2회**(① 통합 이해 ② 답변 생성) | `config.py:118-121` |
| temperature | `0.1`(공용) | `config.py:89` |
| 타임아웃 | 이해 `30s`(`CONCIERGE_UNDERSTANDING_TIMEOUT_SEC`), 답변 `20s`(`CONCIERGE_TIMEOUT_SEC`) | `config.py:122, 141-143` |
| 입력 상한 | 답변용 데이터 블록 `900자`(`CONCIERGE_MAX_INPUT_CHARS`); 이해 단계는 온보딩과 동일한 `sanitize_free_text` 300자 상한 재사용 | `config.py:123-124`, `concierge_prompts.py:79-91`(`injection_guard.sanitize_free_text` 호출) |
| `format:"json"` | 이해 단계 예, 답변 단계 아니오(평문 2문장 하드 절단) | `concierge_understanding.py` → `llm_provider.py:131-137`(json), `summarizer.py:514-532`(평문) |
| 캐시 TTL | 없음(코드에서 LLM 응답 자체를 캐시하는 로직을 찾지 못함 — 축제 데이터 스윕 캐시는 별개) | `config.py:118-143` 범위 확인 |
| 폴백 동작 | 이해 실패 → 온보딩과 동일한 키워드 룰 폴백 + 중립값(intent="spots" 등, 무회귀 설계). 답변 실패 → 템플릿 답변(`answer`는 항상 존재) | `concierge_understanding.py:55-71`, `summarizer.py:369-376` |
| 킬스위치 env | `CONCIERGE_ANSWER_ENABLED=true`(false면 LLM 미호출 + 템플릿 답변만) | `config.py:125-128` |
| 레이트리밋 버킷 | `BUCKET_LLM`(`/api/v1/concierge/ask`, `RATE_LIMIT_LLM_PER_MIN=6`/분 — **온보딩과 같은 버킷 공유**) | `rate_limit.py:42-47`, `config.py:192` |
| 인젝션 방어 지점 | 이해 단계는 온보딩과 **동일한 7계층 전부** 재사용(`_sanitize_llm_additions`/`AXIS_CAP`/포화강등을 `onboarding_service`의 사설 함수로 재사용, `concierge_understanding.py:120-136`). 답변 단계는 `<travel_data>` 델리미터 + **사용자 질문 원문을 프롬프트에 넣지 않음**(서버가 enum으로 접은 결과만 전달, `summarizer.py:96-101`) + `normalize_unicode` 절단 + 데이터 라벨 유출 감지 시 답변 전체 폐기 후 템플릿 폴백(`summarizer.py:223-258`) |

---

## 2. 실측 지연 인용 (기존 코드 주석 원문, 직접 벤치마크 아님)

| 모델 후보 | 실측 지연 | 판정 | 출처 |
|---|---|---|---|
| `gemma4:12b` | CPU에서 **56~101초** | 60초 타임아웃을 자주 넘겨 폴백됨 — **사실상 미사용** | `config.py:84`, 2026-07-24 오케스트레이터 실측 비교 주석 |
| `qwen2.5:3b` | **3~5초** | 축 배치가 어긋나 태그 유실 → 미채택 | `config.py:85` |
| `qwen2.5:7b` | **3~7초** | 축 배치·정확도 우수 → **채택(현재 기본값)** | `config.py:86-88` |

이 실측은 **온보딩 1곳**에서 2026-07-24에 한 번 수행된 것으로 코드에 남아 있으며, 스팟요약·코스요약·컨시어지는 이 결론을 그대로 재사용한다는 것 외에 별도 재실측 기록은 코드에 없다(관찰, §3-3 참고).

---

## 3. 관찰 (제안만 — 실행하지 않음, N-1 준수)

> 08-PRD §5 Non-goal N-1: "AI 모델 교체·양자화·프롬프트 튜닝" — 대표가 "현황 파악만"으로 확정했으므로 아래는 전부 **백로그 제안**이며 이번 세션에서 실행하지 않았다.

### 3-1. 모델 교체
현재 3개 후보(`gemma4:12b`/`qwen2.5:3b`/`qwen2.5:7b`)만 실측 비교됐다. GPU가 없는 현재 배포 환경(CPU 추론)에서는 파라미터 수가 큰 모델일수록 `gemma4:12b`처럼 타임아웃을 넘길 위험이 크므로, 재평가하더라도 **CPU 추론 전제**로 실측해야 의미가 있다. 백로그로만 남긴다 — 이번 세션에서 재벤치마크하지 않았다.

### 3-2. 양자화
현재 `qwen2.5:7b`가 Ollama에 어떤 양자화 레벨(예: Q4_K_M 등)로 받아졌는지는 `ollama show qwen2.5:7b` 등으로 직접 확인해야 하는데, 이는 로컬 명령 실행이라 이번 조사 범위(코드 읽기)를 벗어난다. **확인되지 않은 값이므로 이 문서에 추측으로 채우지 않는다.** 필요하면 별도 작업으로 확인.

### 3-3. 프롬프트 튜닝
컨시어지 프롬프트(`summarizer.py:125-176`)의 반복 보정 이력을 보면, **7B 로컬 모델이 프롬프트 안의 구체적 예시 문구를 표면 그대로 복사하는 경향**이 2회 실측됐다("천안의 축제를 찾으시는군요" 오사례). 이는 신규 팁 개인화 프롬프트(§작업 B)를 설계할 때 반드시 반영해야 하는 교훈이며, 아래 §작업 B에서 "예시는 항상 플레이스홀더만 사용" 원칙으로 선반영했다.

### 3-4. 킬스위치 공백
온보딩·스팟요약 2곳은 전용 킬스위치 env가 없다(코스요약·컨시어지에는 있음). 기능을 완전히 끄려면 코드 배포가 필요하다는 뜻이다 — 이번 세션에서 코드를 바꾸지 않으므로 추가하지 않았고, 필요하다고 판단되면 별도 작업으로 backend에 제안할 사항이다(이 문서는 판단만 기록).

---

## 4. 핸드오프 노트

```
1. 이 문서는 조사 전용이다 — config.py/ai/*.py/course_summary_service.py/rate_limit.py를
   읽은 값만 옮겼고 코드는 한 줄도 바꾸지 않았다. 실측 지연은 2026-07-24 온보딩 실측
   주석(config.py:83-88)의 인용이며 이번 세션에서 새로 벤치마크하지 않았다.
2. 컨시어지(POST /concierge/ask)만 삭제 대상이고 나머지 3곳(온보딩/스팟요약/코스요약)은
   08-PRD 범위에서 무변경이다 — 삭제 실행은 backend-engineer 소관(§7-1).
3. 팁 개인화(작업 B, 아래 design-docs/02-ai-strategy.md 신설 §10)는 이 4곳과 같은 로컬
   Ollama·같은 인젝션 방어 골격을 재사용하는 5번째 LLM 호출 지점이다.
```
