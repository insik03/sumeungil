# 8차 DAST 실공격 증거 (2026-09-15)

7차 위협 모델의 상위 위협을 **로컬 인스턴스에 실제 공격 요청을 던져** 확인한 결과입니다. 새 취약점 클래스는 없었고, 열린 이슈 하나(#128)가 실공격으로 확정됐으며 수정 항목들은 전부 버텼습니다. **새 이슈는 만들지 않았습니다** — 전부 기존 이슈로 수렴합니다.

## 환경

- 대상 `http://127.0.0.1:8000` 만. 운영 사이트 무접촉(DNS 조회조차 안 함).
- 백엔드 로컬 venv `uvicorn --workers 1 --no-proxy-headers`(운영 CMD 동일), DB 는 로컬 전용 `postgres:16-alpine`(운영 DB 분리). **nginx 없음**(백엔드 직접 타격 = 4차 방식).
- 시크릿 전부 테스트용 더미. `RATE_LIMIT_ENABLED=true`, `APP_ENV=production`.
- 인증 뒤편: 계정 생성이 아니라, 로컬 DB 에 테스트 사용자 행을 심고 로컬 `USER_SESSION_SECRET`/`ADMIN_SESSION_SECRET` 으로 세션 쿠키를 직접 서명(4·5차가 못 들어간 로그인 영역 진입).
- 방법론 자기정정: 첫 시도에서 하네스 httpx 클라이언트가 `/auth/me` 재발행 쿠키를 물어와 anon 요청이 200 으로 보였음(취약점 아님, 설정 오류). 쿠키 항아리 격리 후 재측정 → anon 게이트 전부 401.

## 실공격 확정 (Medium) — 기존 이슈 #128

**T6 리뷰 신고 자동숨김이 device_id 회전 3회로 발동** — 6차 정적 지적을 실제로 성공시킴.

```
POST /api/v1/reviews  (X-Device-Id: victim)      -> 201, review.id=2, 공개목록 노출
POST /api/v1/reviews/2/report  (X-Device-Id: 회전1) -> 202 hidden=False
POST /api/v1/reviews/2/report  (X-Device-Id: 회전2) -> 202 hidden=False
POST /api/v1/reviews/2/report  (X-Device-Id: 회전3) -> 202 hidden=True
GET  /api/v1/reviews?target_type=spot&target_id=... -> rid=2 목록에서 사라짐(숨김)
```

한 클라이언트(같은 소켓 IP)가 `X-Device-Id` 만 3회 바꿔 아무 리뷰나 즉시 검열. 관리자 알림 없음. → **#128 의 실공격 근거. 확정 등급 상향.**

## 구조적 노출 실측 (Low/Info) — 기존 이슈 #137

**T5 비인증 비용 표면** — `GET /api/v1/places/{id}` 비로그인 12회 연타 전부 200, 429 0건. `resolve_bucket` 실측 `default`(120/분), `llm` 아님. 캐시 미스 시 Gemini 요약 + TourAPI 호출(사전생성 요약 4건뿐). `GET /api/v1/health/llm` 비인증 200 으로 provider/model/429 카운터 노출. **더미 키라 실제 쿼터 고갈 끝단은 미구동** — 표면 개방·저한도 버킷 아님까지 실증.

## 회귀 재검증 — 실공격에도 버팀 (SAFE)

| 항목 | 공격 | 결과 |
|---|---|---|
| XFF 스푸핑 (4차 High) | 백엔드 직접 + 회전 XFF 로 admin 로그인 9회 | 5회 후 429 — loopback 비신뢰로 회전 무시. `--no-proxy-headers`+`_is_trusted_proxy_peer` 가 4차 공격을 차단 |
| 코스공유 위조 (2차 Critical) | 가짜 혼잡도·배지·좌표·이미지·`is_admin` 주입해 발급 | 조회 시 위조 필드 전부 미노출(서버 재구성) |
| 기기 상한 동시성 (#53) | 그레이박스: 19+동시 10 삽입(5차 PoC 조건) | 최종 20건(상한 유지). advisory lock 직렬화(수정 전 29) |
| 인증 게이트 | anon 으로 onboarding/courses/inquiries/admin/mine | 전부 401 |
| 관리자 브루트포스 | 회전 XFF+오답 9회 | 5회 후 429 |
| Mass assignment | 리뷰에 `hidden/id/report_count/is_admin` 얹기 | 201, 스키마밖 필드 무시 |
| verb tampering / 에러누출 | `PUT /reviews` / 깨진 JSON | 405 / 422, 트레이스백·키 노출 0 |
| operators 명단 | 비인증 `GET /admin/operators` | `operators: []` |
| 온보딩 인젝션 (로그인) | "전부 켜기"·"지시 무시"·PII 문장 | 룰 폴백, 과다추출 없음, PII 반향 0 |

## 이번 환경 한계 (미검증 — 다음 회차)

1. **LLM-present 인젝션** — Ollama/Gemini 부재로 항상 룰 폴백. 로그인 상태 룰 폴백의 안전성만 확정, 실제 모델의 인젝션 내성 미검증.
2. **실제 쿼터 고갈** — 더미 키라 T5 체인 끝단 미구동.
3. **nginx 계층** — 백엔드 직접 타격이라 IP 허용목록·`/metrics` 404·`/prom/` Basic Auth 미실행(운영 무접촉 원칙, 배포 담당 몫).
4. **OAuth 실공격** — 실 클라이언트 부재로 콜백 끝단 미검증(4차 이월).

## 결론

신규 Critical 0, 신규 취약점 클래스 0. 이슈 #128(실공격 확정) → #137(표면 실측) → #127·#129·#138·#139 순으로 기존 우선순위 유지. 다음 9차 숙제: 로컬 Ollama 로 LLM-present 인젝션, 목 업스트림으로 T5 끝단, 운영 nginx 배포 후 스모크(#139).
