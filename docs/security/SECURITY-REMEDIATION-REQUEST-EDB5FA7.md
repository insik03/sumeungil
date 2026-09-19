# 숨은 길 — 보안 보완 요청서 (6차 감사, 2026-09-14)

대상 커밋 `edb5fa7`(`develop`, 2026-09-12 · `main` `06a1075` 과 동일 코드). 5차(2026-09-03) 지적 #53·#54 는 반영 확인 완료. 이번 회차는 정적 검토 + 의존성 실측 + GitHub 설정 점검이며, 운영 사이트에는 요청을 보내지 않았습니다(DNS TXT 조회만). 전체 근거는 감사 보고서 `6차 보안 감사 취약점 분석 보고서.md`(AI가상회사/ai-security-company/audits/sumeungil) 에 있습니다.

## 우선 수정 (이슈 3건)

| 이슈 | 심각도 | 요청 | 완료 기준 |
|---|---|---|---|
| #127 | High | `frontend` Next.js `15.5.23 → 15.5.25`(sharp ≥0.35.4 동반). GHSA-2xp9-vwfh-vxw4 · GHSA-p293-qw3h-jr36 · GHSA-rgj7-g3m4-5g8c 해소 | `npm audit --omit=dev` 0건, Dependabot alerts 3건 close, `NPM_HIGH_BASELINE` 0 |
| #128 | Medium | 리뷰 신고 자동숨김의 신원 기준 변경 — (a) 로그인 필수 + `UNIQUE(review_id, user_id)` / (b) `ip_hash` 병행 저장 후 고유 `ip_hash` 수로 판정 / (c) 자동숨김 → 검토 대기 + 슬랙 알림 중 택 1 | 같은 IP 에서 `X-Device-Id` 3회 회전으로 `hidden=true` 가 나오지 않음(로컬 재현 스크립트 첨부) |
| #129 | Medium | `dependency-audit.yml` 기준선을 건수 → 허용 GHSA 목록으로 전환, 또는 `critical > 0` 이면 무조건 알림 | 알려진 이월분만 조용히 통과하고, 목록 밖 권고 1건이라도 있으면 슬랙 알림이 실제로 발송됨(workflow_dispatch 로 확인) |

## 여유 있을 때 (Low, 이슈 미등록)

- `backend/app/cache/memory.py` 항목 상한·주기 만료 정리 없음(PR #122 F-05 미반영).
- `share_service.py:212-218` 전체 상한(`delete_overflow`)은 기기 락 밖이라 기기 간 경합 잔존 — 고정 키 advisory lock 1줄. 주기 정리로 자기수렴하므로 Low.
- `deploy/docker-compose.yml` 에서 `.env` 전체를 postgres·postgres-backup 컨테이너가 공유 — `POSTGRES_*` 전용 env 파일로 분리.
- `GET /api/v1/health/llm` 공개 — n8n 전용이면 IP/헤더로 제한.
- `schemas/community.py:128,157` `course: dict[str, Any]`(3차 이월).

## 운영 확인 (코드 아님)

- 운영 `.env`: `RATE_LIMIT_ENABLED=true`, `CORS_ALLOW_CREDENTIALS` 미설정, `ADMIN_SESSION_SECRET`·`USER_SESSION_SECRET` 존재.
- 가비아 DNS SPF/DMARC — 2026-09-14 조회 기준 TXT 레코드 없음(2차부터 이월). `@ → v=spf1 -all`, `_dmarc → v=DMARC1; p=none;`
- HSTS 는 인증서 첫 자동갱신(≈2026-10-08) 성공 확인 후. CSP `script-src` 이월.
- `main`/`develop` 브랜치 보호 규칙 없음 — 최소 "PR 필수 + CI 통과" 권장.

## PR #122 (545ae9d 요청서) 대조 결과

F-01 ✅(단 #127) · F-02 ✅ · **F-03 ❌(#128)** · F-04 ✅ · **F-05 ❌(Low)** · F-06 ✅. PR #118 은 #122 와 같은 문서라 close 권장.

## 회신 형식

항목별로 수정 커밋 SHA, 변경 파일, 수정 전·후 재현 결과, 회귀 검사, 설정 변경(비밀값 제외), 배포 여부를 적어 주세요. 수정 완료와 배포 완료를 구분합니다.

[Unverified] 운영 환경에서의 공격 성공 여부는 확인하지 않았습니다. 결과는 커밋 `edb5fa7` 코드·로컬 의존성 실측·GitHub API 조회에 한정합니다.
