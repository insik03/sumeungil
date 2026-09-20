# Hybrid AI 구현 계획 및 운영

## Phase 1 — 저장소 분석

- Python/FastAPI 백엔드, Next.js/React/TypeScript 프론트엔드.
- 사용자·프로필·코스·커뮤니티는 PostgreSQL, 관광지는 TourAPI 수집 후 `spots_seed.json`과 `JsonSpotRepository` 사용.
- 축제는 TourAPI와 표준데이터를 `festival_service`에서 합쳐 메모리에 캐시. 날짜·주소는 구조화된 원천 필드.
- 기존 `LLM_PROVIDER`가 온보딩, 관광지 요약, 팁, 코스 전부를 전환.
- 관광지 상세는 사전 생성 JSON → 메모리 캐시 → 실시간 추론. 기존 배치는 ID만 확인해서 원문 변경을 감지하지 못함.
- 코스는 최대 후보 수 제한, ID 화이트리스트 검증, 원천 레코드 결합을 이미 구현. Haversine/2-opt 및 Tmap도 존재.
- Docker Compose 단일 서버, uvicorn worker 1, Ollama와 PostgreSQL은 내부망. 검증은 `backend/scripts/verify_*.py`.

## Phase 2 — 변경 계획

- 수정: AI factory·deps·courses API, 설정/환경변수, 관광지/축제 상세 및 코스 후보 요약 연결, 배치, Compose, README, 관련 회귀 검증.
- 신규: 공용 로컬 추론 전송 계층, 버전/해시 기반 영구 요약 캐시, 축제 배치, Hybrid 회귀 테스트.
- DB 스키마 변경 없음. 기존 JSON 저장 구조를 확장하고 `/app/data/ai-summaries` 볼륨에 원문·요약·메타데이터 저장.
- 일반 AI는 Ollama 전용. 코스 선택·설명은 Gemini 전용. 기존 전역 스위치가 남아 있어도 일반 AI가 Gemini로 전송되지 않도록 factory를 분리.
- 요약 실패는 제한된 배치 재시도 후 다음 항목으로 진행. 상세 요청에서는 추론하지 않고 원문 발췌로 폴백.
- 로컬 호출은 concurrency 1, 대기 포함 timeout, context/output 제한. 배치 간 OS 파일 잠금과 Ollama 서버의 직렬 처리도 적용.
- 검증: 외부 호출 없는 stub 기반 정상/실패/중복/변경/배치 테스트 및 기존 코스/팁/보안 회귀.

## 모델과 런타임 근거

기존 Ollama 컨테이너/HTTP 연결을 유지한다. 별도 런타임을 도입할 필요가 없고 모델을 프로세스에 상주시킬 수 있다.
기본 모델은 `qwen3:4b-instruct-2507-q4_K_M` (4.02B, Q4_K_M). 모델 파일 크기는 실행 시 RAM 사용량과 다르다.

- [Ollama 모델 정보](https://ollama.com/library/qwen3:4b-instruct-2507-q4_K_M)
- [Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama FAQ: context, keep_alive, concurrency 및 queue](https://docs.ollama.com/faq)

2 vCPU에서의 실제 처리량, 메모리 피크, 한국어 요약 품질은 대상 서버에서 측정해야 한다. JSON 스키마와 프롬프트는 사실 정확성의 보증이 아니므로 공모전 시연 데이터는 원문 대조 검수가 필요하다.

## 운영 실행

로컬 개발은 `backend/.env.example`, Docker는 `backend/.env.production.example`을 참고한다.
기존 Gemini 모델 설정은 유지했다. 계정에서 사용 가능한 모델인지 운영 환경에서 확인해야 한다.

```bash
# deploy/에서, 배포 승인 후 수행하는 운영 절차
docker compose up -d --build backend ollama frontend
docker compose exec ollama ollama pull qwen3:4b-instruct-2507-q4_K_M
docker compose exec backend python scripts/build_spot_summaries.py --limit 50
docker compose exec backend python scripts/build_festival_summaries.py --limit 50
docker compose exec backend python scripts/build_spot_summaries.py --all --report-only
docker compose stats --no-stream
```

관광지 수집 명령으로 `spots_seed.json`을 갱신한 다음 관광지 요약 배치를 실행한다.
축제 배치는 기존 전국 수집 함수를 호출해 TourAPI·표준데이터 원문을 확보한다.
배치는 기본적으로 한 번 실행하고 종료한다. 자동 스케줄러/추가 큐 서버는 설치하지 않았다.
기존 수집 스케줄이 있으면 수집 완료 후 이 명령을 연결하고, 시연 전에는 소규모 배치부터 확인한다.
축제 데이터의 수집 범위는 기존 `festival_service`의 기간 제한을 따른다.

두 배치는 같은 OS 파일 잠금을 사용한다. 중복 실행은 즉시 실패하며 프로세스 종료 시 잠금이 해제된다.
원문과 처리 상태는 추론 전에 저장하고, 성공·실패마다 파일을 원자적으로 교체한다.
실패한 항목은 다음 배치에서 재처리한다. TourAPI 429가 제한 재시도 후에도 계속되면 배치를 중단한다.
LLM 실패는 항목마다 최대 한 번만 재시도한다. 원천이 바뀌지 않아도 변경 감지를 위해 원천 API 조회는 수행한다.

영구 캐시: `SUMMARY_STORE_DIR/{spot|festival}/{id}.json`.
주요 필드: `source`, `sourceHash`, `status`, `updatedAt`,
`result.summary`, `result.sourceHash`, `result.modelName`, `result.promptVersion`, `result.generatedAt`.
원문은 HTML 제거·유니코드/공백 정규화 후 보존한다. 프롬프트나 출력 검증 규칙 변경 시 `SUMMARY_PROMPT_VERSION`을 올린다.
새 모델 가중치로 같은 태그를 덮어쓰는 운영은 피하고 모델 태그/프롬프트 버전도 함께 변경한다.
과거 `spot_summaries.json`은 이 메타데이터가 없어 자동 이관하지 않는다. 새 배치가 끝날 때까지 원문 발췌가 표시된다.

`/app/data` 볼륨을 유지해야 재배포 후에도 캐시가 남는다. 사용자 DB 마이그레이션은 없다.
캐시는 재생성할 수 있지만 느린 CPU 추론 비용을 고려하면 볼륨 백업에 함께 포함하는 편이 좋다.

## API/UI 변경

- 관광지 `ai_summary`: 유효한 로컬 배치 요약, 없으면 원문 발췌. `ai_provider="ollama"`이면 AI, `null`이면 발췌로 표시.
- 축제 상세: 기존 `description`을 보존하고 선택 필드 `ai_summary`, `ai_provider` 추가. AI 요약과 원문을 함께 볼 수 있다.
- 온보딩·팁: 기존 API 계약 유지, 로컬 제공자와 기존 규칙/정적 폴백 사용. Gemini 표시를 일반 AI 표시로 변경.
- 코스: 기존 하루 코스 모델과 최대 30개 관광지 후보 검색 유지. ID 검증 뒤 원천 데이터로 조립한다.
- 관리자 AI 한도 화면과 `/health/llm`: Gemini 코스 제공자를 표시하고 새 로컬 캐시의 유효 요약 수를 집계한다.

현재 코스 API에는 다일 일정과 축제 정차 지점을 표현하는 계약이 없다. 이번 변경은 기존 하루 관광지 코스를 유지하며,
축제를 코스 정차 지점으로 통합하거나 숙박 일정을 추가하지 않는다. 이는 별도 API/화면 설계가 필요한 확장이다.
거리 계산은 기존 Haversine/2-opt(선택 장소 정렬)와 Tmap(구간 거리/시간)을 유지한다.

## 장애와 자원 한도

- 사용자 상세 조회는 LLM 장애와 무관하게 캐시/원문 발췌를 반환한다. 원문도 없으면 null.
- 로컬 요청은 프로세스당 실행 1개 + 대기 최대 4개이며, 대기 포함 전체 timeout 후 기존 기능별 폴백으로 처리한다.
- Ollama 컨테이너는 parallel 1, loaded model 1, queue 4, context 4096, memory 6GB, CPU 1.5로 제한한다.
- 생성 요청은 num_thread 2, num_ctx 4096, num_predict 512. 모델 keep_alive=-1로 반복 로딩을 줄인다.
- 메모리 한도 초과로 Ollama 프로세스가 종료될 수 있다. 요약 배치는 실패 상태를 기록하고 조회는 원문을 사용한다.
- 배치 실행 중 온보딩/팁의 로컬 요청은 대기하다 폴백될 수 있으므로 수집/요약은 사용량이 낮은 시간에 실행한다.
- Gemini 키 누락, JSON 오류, API 오류/timeout은 기존 코스 생성의 규칙 기반 결과/설명 생략으로 처리한다.
- 로그에는 요청 결과, 지연, 재시도, 배치 생성/실패 수, fallback 여부를 기록한다. 새 배치의 httpx URL 로그는 끈다.

## 검증 명령

```bash
cd backend
python -m compileall -q app scripts
python scripts/verify_hybrid_ai.py
python scripts/verify_gemini_provider.py
python scripts/verify_spot_summaries.py
python scripts/verify_course_picker.py
python scripts/verify_course_llm_caps.py
python scripts/verify_detail_images.py
python scripts/verify_course_payload.py
python scripts/verify_security_boundaries.py
# DATABASE_URL이 테스트 PostgreSQL을 가리키는 환경에서:
python scripts/verify_tips.py
cd ../frontend
npm ci
npm run lint
npm run build
```

Hybrid 테스트는 실제 API 호출 없이 JSON 오류·누락·빈값·연결 실패·timeout·5xx·모델 404,
해시/모델/프롬프트 변경, 캐시 손상, 재시도 상한, batch 잠금, 재개,
축제 두 소스, 상세 조회의 추론 미호출, Gemini ID 검증·키 누락·quota/API 오류를 확인한다.
실제 서버의 OOM 복구와 모델 다운로드, TourAPI 및 Gemini 실호출, 브라우저 시연은 배포 전 별도 확인 항목이다.
