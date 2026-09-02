# 숨은길 (Sumeungil)

혼잡한 명소 대신 **숨은 관광지를 추천**하는 AI 여행 웹서비스.
2026 관광데이터 활용 공모전 ②-2 웹·앱 구현 부문 지정과제 2번 출품작.

- 운영: https://sumeungil.co.kr
- 스택: FastAPI (backend) + Next.js 15 (frontend) + nginx + PostgreSQL + Ollama, Docker Compose 배포

## 처음 온 사람은 이 순서로

1. **[인수인계 8월 10일.md](인수인계%208월%2010일.md)** — 현재 상태, 대기 항목, 그리고 **다시 밟으면 시간을 잃는 함정들**
2. [01-interface-contract.md](01-interface-contract.md) — 백-프론트 인터페이스 계약 (부록 T~X 포함)
3. [deploy/DEPLOY.md](deploy/DEPLOY.md) — 배포·HTTPS·관리자 콘솔 절차
4. [APPROVALS.md](APPROVALS.md) — 결재 로그 (게이트 통과 이력)

## 로컬 실행

```bash
# backend (포트 8000)
cd backend
pip install -r requirements.txt
cp .env.example .env   # 키 값은 대표에게 요청
py -m uvicorn app.main:app --port 8000

# frontend (포트 3000)
cd frontend
npm install
npm run dev
```

## 규칙

- **시크릿(.env, 키, 해시)은 절대 커밋하지 않는다** — .gitignore가 막고 있지만 눈으로도 확인할 것
- **운영 배포는 대표 승인 후에만** — 절차는 DEPLOY.md, 결과는 APPROVALS.md에 기록
- 10~12월(심사 기간)에는 서버를 정지시키는 작업 금지
