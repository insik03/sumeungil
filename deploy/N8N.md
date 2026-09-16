# n8n 자동화 (2026-09-07 신설)

인스턴스: https://n8n.aitestbed.kr (v2.13.4, 대표 계정). 워크플로 정의는 이 폴더의 JSON 이 정본이고,
n8n 화면에서 고쳤으면 **Export → 여기 JSON 갱신**까지가 한 세트다(인스턴스가 사라져도 복원 가능하게).

## 원칙

- **시크릿은 JSON 에 넣지 않는다.** 슬랙 웹훅 URL 같은 값은 n8n 화면에서 대표가 직접 붙여 넣고, JSON 엔 `PASTE_..._HERE` 자리만 둔다.
- 이미 GitHub Actions·백엔드 미들웨어가 하는 일(PR/이슈 알림, 헬스체크, 5xx 알림)은 n8n 으로 옮기지 않는다. n8n 은 "외부에서 주기적으로 우리 API 를 보고 판단하는 일"에만 쓴다.
- 서버 SSH 키·DB 접속 정보는 n8n 크레덴셜에 두지 않는다(외부 호스팅).

## 워크플로 목록

| 파일 | 하는 일 | 주기 | 상태 |
|---|---|---|---|
| `gemini-quota-watch.json` | `GET /api/v1/health/llm` 을 보고 최근 1시간 Gemini 429 가 있으면 `#서버-알림` 으로 1시간에 1회 알림, 복귀 시 복귀 알림 | 10분 | 가동 중(2026-09-12~) |

## gemini-quota-watch 설정 순서

1. n8n 에서 워크플로 "숨은길 · Gemini 한도 감시 → 슬랙" 을 연다 — https://n8n.aitestbed.kr/workflow/vHQfM7iRMyK8WbFY (2026-09-07 생성, 2026-09-12 v0.5.5 배포 후 활성화).
2. 마지막 노드 "슬랙 #서버-알림" 의 URL 에 `#서버-알림` 채널 웹훅 URL 을 붙여 넣는다(GitHub Secrets 의 `SLACK_WEBHOOK_URL` 과 같은 값).
3. 오른쪽 위 **Active** 토글을 켠다.
4. 확인: "Execute workflow" 를 한 번 눌러 "LLM 상태 조회" 노드 출력에 `fallback_suspected` 가 보이면 된다(429 가 없으면 슬랙엔 아무것도 안 감 — 정상).

백엔드 쪽 근거: `backend/app/ai/gemini_client.py` 가 429 시각을 메모리에 남기고 `backend/app/api/health.py` 의 `/api/v1/health/llm` 이 읽는다. 재시작하면 0 부터 센다.
