# 숨은길 (Sumeungil)

혼잡한 명소 대신 **숨은 관광지를 추천**하는 AI 여행 웹서비스.
2026 관광데이터 활용 공모전 ②-2 웹·앱 구현 부문 지정과제 2번 출품작.

- 운영: https://sumeungil.co.kr
- 스택: FastAPI (backend) + Next.js 14 (frontend) + nginx + Ollama, Docker Compose 배포

## 처음 온 사람은 이 순서로

1. **[인수인계 8월 10일.md](인수인계%208월%2010일.md)** — 현재 상태, 대기 항목, 그리고 **다시 밟으면 시간을 잃는 함정들**
2. [01-interface-contract.md](01-interface-contract.md) — 백-프론트 인터페이스 계약 (부록 T~X 포함)
3. [deploy/DEPLOY.md](deploy/DEPLOY.md) — 배포·HTTPS·관리자 콘솔 절차
4. [APPROVALS.md](APPROVALS.md) — 결재 로그 (게이트 통과 이력)
5. [STATUS.md](STATUS.md) — 대표님 확인용 현재 구현 현황

지나간 단계별 PRD·설계·QA·보안·법률 리뷰는 [docs/](docs/)에 있다 — 지금 뭘 해야 하는지는 위 5개면 충분하고, docs/는 "그때 왜 그렇게 정했는지" 찾을 때만 연다.

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

API 확인은 Swagger UI(http://localhost:8000/docs) 또는 ReDoc(http://localhost:8000/redoc). `APP_ENV`가
`production`이 아닐 때만 열린다 — 운영에서는 의도적으로 꺼져 있다(관리자 콘솔 스키마 노출 +
Swagger UI의 외부 CDN 스크립트 로드가 세션 쿠키에 닿는 XSS 경로가 되는 걸 막기 위함, `backend/app/main.py` 주석 참고).

## 규칙

- **시크릿(.env, 키, 해시)은 절대 커밋하지 않는다** — .gitignore가 막고 있지만 눈으로도 확인할 것
- **운영 배포는 대표 승인 후에만** — 절차는 DEPLOY.md, 결과는 APPROVALS.md에 기록
- 10~12월(심사 기간)에는 서버를 정지시키는 작업 금지

## 브랜치 전략

영구 브랜치는 두 개, `main`과 `develop`이다.

- `main` — 운영 배포 기준(release). 태그와 배포는 여기서만 나간다.
- `develop` — 평소 작업이 모이는 통합 브랜치. PR은 기본적으로 여기로 올린다.

규칙은 이 다섯이다.

1. **작업 브랜치는 이슈 단위.** `develop`에서 따고, 머지되면 지운다.
2. **브랜치에 맞는 이슈를 만든다** — 뭘, 왜 하는지 한두 줄이면 충분.
3. **`main`·`develop`에는 PR로만.** 직접 푸시하지 않는다. PR엔 이슈를 `Closes #번호`로 연결.
4. **리뷰어는 기본으로 대표(@insik03)** — `.github/CODEOWNERS` 참고. 대표 본인이 올리는 PR은 GitHub 정책상 스스로를 리뷰어로 못 거니 팀원이 리뷰하거나 본인 확인 후 머지.
5. **커밋/PR 제목엔 타입 접두어를 붙인다** — `.github/release.yml` 카테고리·라벨이 여기 맞춰져 있어, 릴리스 만들 때(`gh release create vX.Y.Z --generate-notes`) 자동으로 분류된 changelog가 나온다.

  | 접두어 | 뜻 | 대응 라벨 |
  | --- | --- | --- |
  | `feat:` | 새 기능 | enhancement |
  | `fix:` | 버그 수정 | bug |
  | `security:` | 보안 관련 변경 | security |
  | `docs:` | 문서 | documentation |
  | `chore:` | 설정·잡무·리팩터링 | chore |
  | `release:` | `develop → main` 배포용 머지 | release |

브랜치 이름 예시: `feat/course-map`, `fix/naver-maps-load`, `docs/readme`

## 매일 작업 시작

최신 `develop`을 받은 뒤에만 고친다.

```bash
git checkout develop
git pull origin develop
git checkout -b feat/화면이름
```

## 저장소 접근 권한

| GitHub | 권한 |
| --- | --- |
| `insik03` | admin |
| `qweasd-22` | write |

팀원이 새로 필요하면 대표에게 초대를 요청한다.
