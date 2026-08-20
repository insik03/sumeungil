# 06-security-report — 구글 로그인(Google OAuth 2.0) 보안 풀검수

- **검수자**: security-engineer
- **검수일**: 2026-08-17
- **대상 커밋**: `bdebedd`(BE 최초)·`a473dc6`(FE 최초)·`114727d`(닉네임 확인단계+처리방침)·`6075e5a`(users 테이블 DB 연동)
- **검수 등급**: 풀검수 (CLAUDE.md 규칙 — 인증·개인정보를 다루는 변경)
- **검증 방식**: 코드 리뷰 + 단위 실행 검증(세션 토큰/`state` 위·변조·만료·오픈리다이렉트)

## 최초 판정: **재작업 필요 (배포 승인 불가)**

| 심각도 | 건수 |
|---|---|
| Critical | 2 |
| Major | 2 |
| Minor | 7 |

## 발견된 이슈

### Critical

**C-1. 세션 서명키가 빈 문자열에서 파생될 수 있어 임의 계정 탈취 가능**

`UserAuth.enabled`가 `GOOGLE_CLIENT_ID`/`SECRET`/`REDIRECT_URI` 3개만 확인하고 세션 서명키
(`USER_SESSION_SECRET` → `JWT_SECRET_KEY` 폴백)가 실제로 채워졌는지는 보지 않았다. 두
환경변수가 모두 비어 있으면 서명 키가 `HMAC(_KEY_LABEL, b"")`로 고정되는데, `_KEY_LABEL`은
소스코드에 공개된 상수라 **누구나 동일한 키를 계산할 수 있다** — 임의 `user_id`로 세션을
위조해 타인 계정의 이메일을 열람하거나 표시 이름을 바꿀 수 있었다.

담당: backend-engineer. 조치 권고: `enabled`가 세션 시크릿 존재 여부도 함께 확인해,
미설정이면 admin_auth.py와 동일하게 기능 자체를 끌 것.

**C-2. 콜백 팝업 HTML의 script 블록에 구글 이름이 원문 삽입 — XSS**

`api/auth.py`가 만드는 `json.dumps({..., "name": name})`를 `<script>` 블록 안에 문자열
그대로 보간했다. `json.dumps`는 `<`와 `/`를 이스케이프하지 않으므로 `</script>` 시퀀스로
스크립트 블록을 조기 종료시키고 뒤에 임의 마크업/스크립트를 주입할 수 있다. 신규 계정은
구글 이름을 정제 없이 그대로 DB에 저장하고(`clean_user_text`를 타지 않음) 그 값이 다시
팝업 HTML에 삽입돼 공격 표면이 됐다.

담당: backend-engineer. 조치 권고: `<`·U+2028·U+2029를 유니코드 이스케이프하거나
`<script type="application/json">`+`textContent` 파싱으로 전환. 구글 이름에도
`clean_user_text`/`is_impersonating_staff`를 적용할 것.

### Major

**M-1. OAuth state가 브라우저에 바인딩되지 않음 — 로그인 CSRF 여지**

`issue_state`가 담는 값은 만료시각과 `next_path`뿐이라, 서명만 유효하면 어느 브라우저에서
발급받은 state든 다른 브라우저의 콜백에서도 통과한다. 브라우저별 nonce를 별도 쿠키로 심어
대조하는 절차가 없었다.

담당: backend-engineer. 조치 권고: 발급 시 랜덤 nonce를 만들어 서명 페이로드와 단명
HttpOnly 쿠키 양쪽에 넣고, 콜백에서 대조 후 즉시 삭제(1회용)할 것.

**M-2. 세션 TTL이 30일로 김 — 무상태 토큰이라 서버 강제 폐기 수단이 없음**

로그아웃은 쿠키 삭제일 뿐 토큰 자체를 무효화하지 않는다. 탈취 시 노출 기간이 곧 TTL이며,
admin 세션(8h→4h로 단축 이력)에 비해 지나치게 길다.

담당: backend-engineer. 조치 권고(최소): TTL을 7일로 단축. 완전한 해법(로그아웃 즉시 전
세션 무효화)은 `users` 테이블에 `session_epoch` 컬럼을 추가해야 하며 별도 스코프.

### Minor

- **m-1** `POST /logout`이 `HTMLResponse(content="", status_code=204)`라 204 응답에
  `content-type: text/html`이 붙는다. `Response(status_code=204)`가 맞다.
- **m-2** `/api/v1/auth/*` 전용 rate limit 버킷이 없다(default 버킷만 적용).
- **m-3** `next` 쿼리 파라미터가 오픈 리다이렉트 표면이 될 수 있어 발급 시점부터 화이트리스트로
  좁혀두는 편이 안전(현재는 HTML 앵커 href로만 쓰여 당장 악용 경로는 없음).
- **m-4** 팝업 콜백 HTML의 `fallback_link`는 `html.escape`로 처리돼 있으나, 인접한
  `<script>` 블록과 컨텍스트가 다르다는 점을 주석으로 명확히 남길 것(혼동 방지).
- **m-5** `email_verified` 필드가 아예 없는 구글 계정 유형이 있어 존재 여부만으로 판단하지
  않는 현재 로직(명시적 `false`만 거부)은 맞으나, 실크레덴셜로 이 분기를 실제 검증한 적은
  없다 — 별도 확인 필요.
- **m-6** 배포 문서(`deploy/DEPLOY.md`)·`backend/.env.production.example`에 신규
  `GOOGLE_*`/`USER_SESSION_SECRET`/`FRONTEND_BASE_URL` 안내가 전무하다. 이대로 배포하면
  최선의 경우 기능이 조용히 404가 되고, 최악의 경우 C-1이 재현된다.
- **m-7** 세션 토큰에 이메일이 담기므로, 로그를 남길 때 절대 이메일·토큰 원문을 기록하지
  않도록 하는 규율이 코드 전반에 지켜지는지 지속 점검 필요.

## 최종 판정: **재작업 필요 (배포 승인 불가)**

Critical 2건이 해소돼야 3차 게이트를 통과시킬 수 있다. C-1·C-2는 backend-engineer 단독으로
조치 가능. 재검수 시 세션 위조 재현 스크립트와 XSS 재현 스크립트를 회귀 자산으로 남길 것을
권고한다.

## 오케스트레이터 조치 결과 (같은 세션, 2026-08-17)

C-1·C-2·M-1(state 바인딩)·M-2(TTL 단축)를 즉시 반영했고, 이어서 진행된 qa-reviewer의
독립 병렬 풀검수(`02-qa-report.md` §G)가 같은 취약점들을 실행 검증으로 재확인함과 동시에
신규 이슈(C-4 개인정보처리방침 불일치, M-1/M-2 로그인 미강제 등, qa-reviewer 번호체계)를
추가로 발견했다. 두 리포트를 합쳐 전량 조치한 상세 내역은 `02-qa-report.md` §H와
`APPROVALS.md`(2026-08-17T14:10:00 행)를 참고할 것 — 이 문서의 이슈 번호(C-1/C-2/M-1/M-2)와
`02-qa-report.md`의 이슈 번호는 **별도 체계**이므로 대조 시 주의.

## 핸드오프 노트
```
1. Critical 2건(C-1 세션위조, C-2 콜백XSS) 전부 조치·재검증 완료(오케스트레이터).
2. qa-reviewer가 병렬로 독립 재검증 — 같은 결론(해소 확인) + 신규 이슈 발견, 02-qa-report.md 참고.
3. 배포 전 여전히 필요: 실제 Google Cloud Console 크레덴셜로 실브라우저 로그인 1회 완주.
```

---

# 2026-08-18 카카오 로그인 + 마이페이지 + 고객문의 풀검수

> 검수 범위: 2026-08-17 구글 로그인 풀검수(위 섹션, C-1/C-2 조치 완료) **이후 새로 생긴 변경분만**.
> 대상 파일 — backend: `clients/kakao_oauth_client.py`(신설), `config.py`, `security/user_auth.py`,
> `deps.py`, `db/postgres.py`(schema 6/7), `repositories/user_repo.py`, `api/auth.py`,
> `api/inquiries.py`+`repositories/inquiry_repo.py`+`schemas/inquiry.py`(신설), `main.py`,
> `scripts/verify_auth.py`. frontend: `LoginModal.tsx`, `Header.tsx`, `MyPageContent.tsx`(신설),
> `lib/api.ts`, `app/privacy/page.tsx`.
> 실행 검증: `backend/scripts/verify_auth.py` 45/45 PASS + 별도 방어 검증 스크립트(계정 통합
> 순서 · 고객문의 인가 · 스키마 제약)를 로컬 Postgres 격리 스키마에서 직접 실행. 익스플로잇
> 코드는 작성하지 않았고, 재현 절차는 방어 검증에 필요한 최소한만 기술한다.

## 판정

# **재작업 필요 (배포 승인 불가) — Critical 1건**

| 심각도 | 건수 | 항목 |
|---|---|---|
| **Critical** | **1** | K-C1 (계정 통합을 통한 계정 선점·탈취) |
| Major | 4 | K-M1 ~ K-M4 |
| Minor | 8 | K-m1 ~ K-m8 |

Critical 1건은 **신규 사용자 계정을 이메일 주소만 알면 가로챌 수 있는 실제 인증 우회 경로**다.
조치 전 운영 배포 불가로 판정한다. Major 중 K-M3(개인정보처리방침 미갱신)은 법적 고지 의무와
직결되므로 legal-counsel 판정을 함께 받아야 한다.

## 1. 점검 항목 체크리스트

| 항목 | 결과 | 근거 |
|---|---|---|
| 인증/인가 — 세션·토큰 처리 | 통과 | `security/user_auth.py` HMAC 서명 + 만료 검증, admin과 다른 키 라벨. verify_auth 1절 6/6 PASS |
| 인증/인가 — **계정 통합(provider 연결)** | **불통과** | **K-C1** — `user_repo.upsert_login` L80-87 |
| 인증/인가 — 권한 우회 / 관리자 API 노출 | 통과 | admin 라우터는 `ADMIN_PASSWORD_HASH` 없으면 미등록. inquiries에 admin 조회 경로 없음 |
| 인증/인가 — 신규 엔드포인트 로그인 강제 | 통과 | 비로그인 POST/GET `/api/v1/inquiries*` 모두 401 실측 |
| 입력 검증 — SQL injection | 통과 | `_PROVIDER_COLUMNS` f-string은 고정 화이트리스트 식별자만, 값은 전부 `%s` 바인딩 (아래 3절) |
| 입력 검증 — XSS (저장형/DOM) | 통과(조건부) | 문의 `message` 원문 저장되나 현재 렌더/LLM 소비 경로 0건(grep 확인). 관리자 화면 신설 시 재검토 — K-m6 |
| 입력 검증 — path traversal / SSRF | 해당 없음 | 신규 코드에 파일 경로·사용자 지정 URL 요청 없음. 카카오 엔드포인트는 상수 |
| 입력 검증 — 오픈 리다이렉트 | 통과 | verify_auth 3절 5/5 PASS (`//evil.com` 포함) |
| 시크릿 — 하드코딩 | 통과 | `KAKAO_CLIENT_ID/SECRET/REDIRECT_URI` 전부 `os.getenv`, 기본값 없음 |
| 시크릿 — .env 커밋 | 통과 | `git check-ignore` 결과 `backend/.env`·`frontend/.env.local` 모두 무시됨. 추적 대상은 `.example` 뿐 |
| 시크릿 — 로그 노출 | 통과 | 카카오 클라이언트가 token/access_token/응답본문을 로그하지 않음. 문의 로그는 id·user_id만 |
| 의존성 | **주의** | K-M4 — `next@14.2.35` high 2건, `starlette@0.41.3` 8건 (기존 이슈, 이번 변경 무관) |
| AI 특화 — prompt injection | 통과 | 문의 `message`가 어떤 LLM 프롬프트에도 유입되지 않음(소비 경로 grep 7파일 전수 확인) |
| AI 특화 — LLM 출력 무검증 실행 | 해당 없음 | 신규 코드에 LLM 연동 없음 |
| AI 특화 — 학습/로그 데이터의 개인정보 | 통과 | `contact_email`·`message`는 로그에 남지 않음 |
| 인프라 — CORS | 통과 | 신규 변경 없음. `allow_credentials`는 와일드카드 오리진이면 config가 강제 False |
| 인프라 — HTTPS 강제 | 통과 | `USER_COOKIE_SECURE` 기본 true, 운영 예시에서 미설정 유지 |
| 인프라 — rate limiting | **주의** | K-m3 — `/api/v1/inquiries`가 default 버킷(120/min)만 적용, 계정별 쓰기 한도 없음 |
| 인프라 — 에러 메시지 내부정보 노출 | 통과 | 콜백 실패 사유를 구분해 알려주지 않음, DB 예외는 팝업 실패로 수렴 |
| 회귀 — C-1(세션 서명키 위조) | 통과 | `_secret_present` 유지, verify_auth 1절 PASS |
| 회귀 — C-2(콜백 script XSS) | 통과 | `_js_safe_json` 유지, verify_auth 4절 PASS |
| 회귀 — M-1(state nonce 브라우저 바인딩) | 통과 | 카카오 콜백도 동일 `verify_state(cookie_nonce=...)` 경유 |

## 2. 발견된 취약점

### K-C1. 미검증 이메일 선점을 통한 계정 통합 탈취 (Account pre-hijacking)

- **심각도**: **Critical**
- **위치**: `backend/app/repositories/user_repo.py` L80-87(2단계 통합) · L89-96(3단계 신규 생성)
  · `backend/app/api/auth.py` L336-344(카카오 email/email_verified 산출)
- **담당 부서**: backend-engineer

**무엇이 문제인가.** 모듈 docstring(L8-15)은 통합 규칙이 계정 탈취를 막는다고 주장한다.
실제로 `upsert_login` 2단계는 **이번 로그인의 이메일이 검증됐는지**만 확인한다(L80
`if email and email_verified:`). 그런데 3단계 INSERT(L89-96)는 `email_verified`를 보지 않고
**미검증 이메일을 그대로 `users.email`에 저장한다.** 즉 매칭 대상이 되는 기존 행의 이메일이
검증된 값인지는 아무도 확인하지 않는다. 방어선이 절반만 걸려 있다.

카카오는 이메일 동의가 선택이고 `is_email_verified=false`인 계정이 정상적으로 존재한다
(`api/auth.py` L334-342 주석이 이를 인정한다). 따라서 공격자는 카카오 계정에 피해자의
이메일을 미검증 상태로 넣고 한 번 로그인하기만 하면, 피해자의 이메일이 박힌 행을 **선점**할
수 있다. 이후 피해자가 그 이메일의 구글 계정으로 **처음** 로그인하면 2단계가 발동해
피해자의 `google_sub`가 공격자 행에 붙는다 — 두 사람이 같은 `user_id`를 공유하게 된다.

**영향.** 공격자는 자신의 카카오 계정으로 계속 로그인해 같은 `user_id` 세션을 받는다.
그 세션으로 접근 가능한 것: 피해자의 온보딩 취향 프로필(`onboarding_profiles`), 저장한 AI
코스(`ai_courses`), 고객문의 내역(`inquiries` — 연락처 이메일 포함), 표시 이름 변경
(`PATCH /auth/display-name` — 피해자 명의 리뷰 작성자명 조작), 계정 삭제(`DELETE /auth/me`).
반대로 피해자가 남긴 활동이 공격자에게 그대로 노출된다. 필요한 사전 정보는 **피해자의 이메일 주소 하나뿐**이다.

**재현(방어 검증용, 리포지토리 함수 직접 호출 — 격리 스키마에서 실측).**

```
up(kakao, atk-kakao, victim@example.com, email_verified=False)  # 1) 선점
  -- kakao row: {id: 1, email: victim@example.com, google_sub: None, kakao_sub: atk-kakao}
up(google, victim-google-sub, victim@example.com, email_verified=True)  # 2) 피해자 최초 로그인
  -- google result: {id: 1, email: victim@example.com, google_sub: victim-google-sub, kakao_sub: atk-kakao}
MERGED same id? True | attacker kakao_sub kept? True
```

즉 피해자의 구글 로그인이 **공격자 행에 흡수**됐고, 공격자의 `kakao_sub`는 그대로 남아
있어 이후에도 같은 계정으로 로그인된다.

**기존 검증이 이 경로를 놓친 이유.** `scripts/verify_auth.py` 9절의 케이스
`이메일 일치해도 미검증 -- 별개 계정 생성(계정 탈취 방지)`는 **구글(검증) 먼저 -- 카카오(미검증)
나중** 순서만 확인한다. 실제 위험한 순서는 그 반대(**미검증 먼저 -- 검증 나중**)이며 이
순서에 대한 케이스가 없다. 45/45 PASS는 이 경로를 커버하지 않는다.

**수정 권고 (택1 이상, (a)+(b) 동시 적용 권장).**

- **(a) 미검증 이메일을 `users.email`에 저장하지 않는다** — `upsert_login` 3단계 INSERT에서
  `email if email_verified else None`을 넣는다. 그러면 `get_by_email`이 애초에 검증된
  이메일 행만 매칭하게 되어 통합 규칙이 docstring이 주장하는 대로 동작한다. 연락처 목적의
  미검증 이메일이 필요하면 통합 판정에 쓰이지 않는 별도 컬럼(예: `contact_email_unverified`)에
  분리 저장한다.
- **(b) 검증 상태를 스키마에 남긴다** — `users.email_verified BOOLEAN NOT NULL DEFAULT false`를
  추가하고, 2단계 통합 조건을 `이번 로그인 email_verified = true` **AND** `기존 행의
  email_verified = true`로 강화한다.
- **(c) 1단계 이메일 갱신에도 같은 조건을 건다** — 아래 K-M1 참고.
- **(d) 기존 데이터 점검** — 조치 배포 시 이미 저장된 미검증 이메일 행이 있는지 확인하고
  (`SELECT ... WHERE kakao_sub IS NOT NULL AND email IS NOT NULL`) 검증 플래그를 채우거나
  이메일을 비운다. 조치 전 프로덕션 데이터가 없다면 불필요.

### K-M1. 재로그인 시 미검증 이메일이 기존 계정의 `email`을 덮어쓴다

- **심각도**: Major (K-C1과 같은 뿌리 — K-C1의 두 번째 주입 경로)
- **위치**: `backend/app/repositories/user_repo.py` L74-77
- **담당 부서**: backend-engineer

1단계(provider_sub 일치)는 `UPDATE users SET email = %s, last_login_at = %s`를 무조건
실행한다. `email_verified`를 보지 않는다. 따라서 이미 만들어진 카카오 계정이라도, 카카오
계정의 이메일을 임의 값으로 바꾼 뒤 다시 로그인하면 우리 DB의 `email`이 그 값으로 갱신된다.

실측:

```
up(kakao, k2, own@example.com,   email_verified=True)   -- email = own@example.com
up(kakao, k2, other@example.com, email_verified=False)  -- email = other@example.com
```

K-C1을 (a)안으로 고쳐도 이 경로가 남으면 선점 primitive가 그대로 살아있다. **수정 권고**:
`email_verified`가 참일 때만 `email`을 갱신하고, 거짓이면 `last_login_at`만 갱신한다.

### K-M2. `users.email`에 UNIQUE 제약이 없다

- **심각도**: Major
- **위치**: `backend/app/db/postgres.py` L168-179 (`ix_users_email`는 일반 인덱스)
- **담당 부서**: backend-engineer

실측한 인덱스: `users_pkey`(id), `users_google_sub_key`(UNIQUE), `users_kakao_sub_key`(UNIQUE),
`ix_users_email`(**비유니크**). 즉 같은 이메일을 가진 계정 행이 여러 개 존재할 수 있고,
`get_by_email`의 `fetchone()`은 **어느 행이 반환될지 보장하지 않는다**(ORDER BY 없음).
K-C1 조치 후에도 통합 판정이 비결정적이면 같은 계정 혼선이 재발할 수 있다.

**수정 권고**: `CREATE UNIQUE INDEX ... ON users (email) WHERE email IS NOT NULL`(부분 유니크
인덱스 — NULL 다수 허용). 적용 전 중복 이메일 행이 있는지 먼저 확인한다. 유니크 위반이
로그인 500으로 새지 않도록 `upsert_login`에 충돌 처리(기존 행으로 수렴 또는 통합 거부)를 넣는다.
보조로 `get_by_email`에 `ORDER BY id LIMIT 1`을 붙여 결정성을 확보한다.

### K-M3. 개인정보처리방침이 신규 수집 항목을 전혀 반영하지 않았다

- **심각도**: Major (법적 고지 의무 — legal-counsel 판정 필요)
- **위치**: `frontend/app/privacy/page.tsx` — 문서 전체가 구글 로그인 전용(L33-49 1~2항,
  L82-89 5~6항, L114-118 10항)
- **담당 부서**: legal-counsel(문구 판정) + designer/backend-engineer(반영)

현재 방침에 **없는** 실제 수집·처리 항목:

| 누락 항목 | 실제 코드 위치 | 방침에 필요한 내용 |
|---|---|---|
| **카카오 로그인** 자체 | `api/auth.py` L300-352 | 수집 항목(카카오 회원번호 `id`, 이메일, 닉네임), 수집 방법, 처리 위탁/제3자 관계 |
| **계정 통합** | `user_repo.upsert_login` | 구글·카카오 계정이 같은 이메일로 하나의 계정으로 합쳐질 수 있다는 사실 |
| **고객문의 내용(`message`)** | `schemas/inquiry.py` L15, `inquiries` 테이블 | 자유서술 텍스트 수집, 목적, 보유기간, 파기 |
| **답변받을 이메일(`contact_email`)** | `schemas/inquiry.py` L16 | 계정 이메일과 별개로 이용자가 직접 입력하는 연락처 |
| **온보딩 취향 프로필** | `onboarding_profiles` 테이블 | 취향 태그/벡터의 계정 연동 영구 저장 |
| **저장한 AI 코스** | `ai_courses` 테이블 | 여행 계획 payload의 계정 연동 저장 |

방침 3항은 아직도 처리 목적이 로그인·표시 이름 두 가지뿐이고, 1항은 수집 항목을 구글
3종으로 한정한다. 8항의 이용자 권리 안내도 `화면 상단의 계정 삭제 버튼`이라고 쓰여 있으나
실제로는 마이페이지 안으로 이동했다(`MyPageContent.tsx` L271-280, `Header.tsx`에서 제거).

**수정 권고**: 배포 전 방침을 실제 코드 동작에 맞춰 개정하고 시행일자를 갱신한다.
문구 확정은 legal-counsel에 위임한다(아래 4절 전달표 참조).

### K-M4. 알려진 취약 버전 의존성 (기존 이슈, 이번 변경과 무관)

- **심각도**: Major
- **위치**: `frontend/package.json` L33 `next@14.2.35` · `backend/requirements.txt`(fastapi
  0.115.6 경유 `starlette@0.41.3`)
- **담당 부서**: backend-engineer

- `npm audit --omit=dev` 실측: **high 2건** — next(DoS/SSRF/캐시 포이즈닝/서버 함수 엔드포인트
  노출 등 다수 advisory)와 그 하위 postcss(GHSA-qx2v-qp2m-jg93 외 3건). 수정은 next 16 계열
  업그레이드가 필요한 breaking change다.
- `pip-audit` 실측: `starlette 0.41.3`에 8건(PYSEC-2026-161/248/249/1941/1942/2280/2281),
  `python-dotenv 1.0.1` 1건(PYSEC-2026-2270). 이번에 새로 추가된 `psycopg[binary,pool]==3.2.3`
  **자체는 알려진 취약점 0건**이다.
- 이번 변경으로 생긴 문제가 아니므로 K-C1과 달리 배포 차단 사유로 두지 않지만, 공개 서비스
  운영 중이므로 별도 티켓으로 업그레이드 계획을 잡을 것을 권고한다.

### Minor

- **K-m1** 공백만 입력한 문의가 빈 문자열로 저장된다. `CreateInquiryRequest.message`의
  `min_length=1`은 Pydantic 검증 시점(`schemas/inquiry.py` L15)에 걸리는데, 실제 저장값은
  `api/inquiries.py` L44 `req.message.strip()`이라 검증을 통과한 뒤 비워진다. 실측: 공백 3칸
  -- 201, DB `message = 빈 문자열`. **권고**: `field_validator`로 strip 후 길이를 검증하거나
  `constr(strip_whitespace=True, min_length=1)`을 쓴다. (담당: backend-engineer)
- **K-m2** `contact_email`에 형식 검증이 없다. `str`에 `max_length`만 걸려 있어
  `not-an-email`도 201로 저장된다(실측). 저장 자체는 무해하나 답변 불가·데이터 품질 문제.
  **권고**: `EmailStr` 또는 최소한의 정규식. (담당: backend-engineer)
- **K-m3** `/api/v1/inquiries`가 rate limit **default 버킷(120/min)**에만 걸린다.
  `middleware/rate_limit.py` L53-55의 UGC 판정 대상(`/api/v1/reviews`, `/courses/share`,
  `/courses/shared`)에 포함되지 않는다. 로그인 계정 하나로 2000자 문의를 분당 120건 쌓을 수
  있다. **권고**: `resolve_bucket`의 UGC 분기에 `/api/v1/inquiries`를 추가하거나
  `get_community_write_limiter`에 계정 기준 버킷을 추가한다. (담당: backend-engineer)
- **K-m4** `is_new` 판정이 `created_at == last_login_at` **문자열 초 단위 비교**다
  (`api/auth.py` L232). 같은 초 안에 재로그인하면 신규로 오판해 표시 이름 단계를 다시
  보여준다. 보안 영향은 없다(세션은 서버가 발급). **권고**: `upsert_login`이 신규 여부를
  명시 플래그로 반환하게 한다(`INSERT ... RETURNING`에서 판정). (담당: backend-engineer)
- **K-m5** `LoginModal.tsx` L86-111의 message 리스너 `useEffect` 의존성 배열이 `[open]`뿐인데
  콜백 안에서 `onLoggedIn`/`onClose`를 참조한다. 부모가 매 렌더 새 함수를 넘기면 stale
  closure가 된다. 기능 이슈이며 보안 영향은 없다. (담당: designer/frontend)
- **K-m6** 문의 `message`는 정제 없이 원문 저장된다(`api/inquiries.py` 모듈 docstring이
  의도적 결정임을 명시). 현재 소비 경로가 없어 실제 위험은 없다 — `contact_email|inquiry|
  inquiries` grep 결과 참조 파일은 7개뿐이고 그중 렌더링은 `MyPageContent.tsx`의 **입력 폼**,
  응답 모델은 `InquirySummary`(id/status/created_at)로 `message`를 아예 반환하지 않는다.
  **다만 admin 조회 화면을 신설하는 시점에 저장형 XSS 표면이 즉시 생긴다** — 그때 반드시
  텍스트 노드 렌더(React 기본 이스케이프 유지, `dangerouslySetInnerHTML` 금지)를 확인할 것.
  LLM 프롬프트로 유입시키지 않는다는 불변식도 함께 유지. (담당: backend-engineer, qa-reviewer)
- **K-m7** 신규 계정 생성 시 provider 원본 닉네임이 **이용자 확인 전에** `display_name`으로
  DB에 저장된다(`api/auth.py` L203 -- `user_repo.upsert_login` L89-96). 이용자가 표시 이름
  확인 단계에서 확인/취소하지 않고 창을 닫으면 미확인 이름이 남고, 그 상태로 리뷰를 쓰면
  공개 표시명으로 쓰인다. 정제·사칭차단은 통과하지만 **동의 관점**의 잔여 표면이다
  (구글 단독 시절부터 있던 구조 — 이번 변경으로 카카오까지 확대). (담당: legal-counsel 판정)
- **K-m8** `_popup_close_html`의 postMessage targetOrigin이 `settings.frontend_base_url`을
  그대로 쓴다(`api/auth.py` L154). 이 값이 빈 문자열/와일드카드로 잘못 설정되면 표시 이름이
  임의 오프너에 전달될 수 있다. **권고**: config 로드 시 `http(s)://호스트` 형식만 허용하도록
  검증하고 아니면 부팅 실패시킨다. (담당: backend-engineer)

## 3. 우선 검토 요청 항목에 대한 답변

### 3.1 `_PROVIDER_COLUMNS` f-string SQL 삽입 — **안전 (인젝션 경로 없음)**

`user_repo.py` L26 `_PROVIDER_COLUMNS = {google: google_sub, kakao: kakao_sub}`.
f-string에 들어가는 것은 이 딕셔너리의 **값**뿐이고(L40, L70), 값은 소스에 박힌 두 개의
고정 식별자다. 키(`provider`)는 `api/auth.py` L291/L346에서 리터럴 `google`/`kakao`로만
전달된다. 사용자 입력이 키로 흘러들 경로가 없고, 설령 흘러들어도 딕셔너리 조회가
`KeyError`로 즉시 끊는다(문자열이 SQL에 도달하지 못한다). 나머지 모든 값은 `%s`
파라미터 바인딩이다. **주장한 대로 안전하다.** 다만 방어적으로 `Provider` Literal 타입을
런타임에서도 강제하도록 `if provider not in _PROVIDER_COLUMNS: raise ValueError`를 두면
향후 호출부가 늘어나도 안전이 유지된다(권고 수준, 취약점 아님).

### 3.2 고객문의 엔드포인트 인가 — **통과**

실측 결과:

| 검증 | 결과 |
|---|---|
| 비로그인 `POST /api/v1/inquiries` | **401** |
| 비로그인 `GET /api/v1/inquiries/mine` | **401** |
| 로그인 사용자 A의 문의 생성 | 201 (`id`/`status`/`created_at`만 반환 — 본문 미반환) |
| 사용자 B가 `GET /mine` | `{items: []}` — A의 문의 미노출 |
| 요청 본문에 `user_id` 주입 시도 | 201이지만 **주입값 무시**, 세션의 `user_id`로 저장됨 |
| 계정 삭제 후 문의 잔존 여부 | 0건 (`ON DELETE CASCADE` 동작 확인) |

`user_id`는 오직 `Depends(require_login)`이 반환한 `UserIdentity.user_id`에서 온다
(`api/inquiries.py` L36, L43, L56). 그 값은 HMAC 서명된 세션 토큰에서 파싱되며
(`security/user_auth.py` L234-258) 서명 불일치/만료 시 `None`이 되어 401로 끊긴다.
**세션 토큰의 `user_id`를 신뢰하는 구조는 타당하다** — 다만 그 신뢰는 K-C1이 세션에
엉뚱한 `user_id`를 실어주지 않는다는 전제 위에 서 있고, 지금은 그 전제가 깨져 있다.
단건 조회(`GET /inquiries/{id}`) 엔드포인트가 없어 IDOR 표면 자체가 없다
(`inquiry_repo.get`은 정의만 되어 있고 라우터에서 호출되지 않는다).

### 3.3 `is_new` 위조 가능성 — **실질 위험 낮음 (origin 검증 유효)**

`is_new`는 서버가 팝업 HTML의 postMessage payload에 실어 보낸다(`api/auth.py` L153).
부모 창은 `LoginModal.tsx` L90에서 `e.origin !== new URL(API_BASE).origin`으로 **백엔드
오리진에서 온 메시지만** 받아들인다. 서버 측 targetOrigin도 `FRONTEND_BASE_URL`로 고정돼
있다(L164). 따라서 임의 웹페이지가 부모 창에 위조 메시지를 넣으려면 백엔드 오리진에서
스크립트를 실행할 수 있어야 하는데, 그 능력이 있으면 이미 세션 쿠키가 문제지 `is_new`가
문제가 아니다. **기존 origin 검증은 여전히 유효한 방어다.**

설령 위조되더라도 피해가 제한적이다 — `is_new`는 UI 분기(표시 이름 확인 단계 노출 여부)에만
쓰이고, **인증 판정에는 전혀 쓰이지 않는다.** 세션 쿠키는 이미 서버가 `Set-Cookie`로
발급했고, 표시 이름 저장은 별도의 `PATCH /auth/display-name`(세션 필수, 서버 정제·사칭차단
통과)을 거친다. `is_new=false` 위조 -- 확인 단계 스킵(이름은 DB 값 그대로),
`is_new=true` 위조 -- 불필요한 확인 단계 노출. 어느 쪽도 권한 상승이 아니다.
보조 권고: origin 검증 실패 메시지를 세지 않으므로 진단이 어렵다 — 개발 빌드에서만
console.debug를 남기면 회귀 발견이 쉬워진다(선택).

### 3.4 `is_new` 스킵이 legal-counsel 원칙과 충돌하는가 — **충돌하지 않음 (코드 주석의 논리 타당)**

legal-counsel의 원래 지적은 `로그인 목적으로 받은 provider 제공 이름을 동의 없이 다른
목적(공개 게시물 작성자 표시)으로 자동 전용하지 말 것`이었다. 재로그인 시 팝업이 돌려주는
`name`은 provider 원본이 아니라 **DB의 현재 `display_name`**이다(`api/auth.py` L224-234).
그 값은 이용자가 최초 가입 때 확인/수정해 `PATCH /display-name`으로 직접 저장한 값이고,
`upsert_login` 1단계는 `display_name`을 절대 건드리지 않는다(L74-77 — UPDATE 컬럼이
`email`/`last_login_at`뿐). 즉 재로그인 시 새로 전용되는 provider 데이터가 없다.
**`최초 1회 동의로 충분하다`는 주석의 논리는 타당하다.**

계정 통합(2단계) 경로도 같은 결론이다 — 통합 시 `display_name`을 기존 값으로 유지하고
카카오 닉네임으로 덮어쓰지 않는다(verify_auth 9절에서 확인).

단, 두 가지를 조건으로 붙인다:
1. **K-m7** — 신규 계정은 확인 전에 provider 이름이 이미 DB에 들어간다. 이 잔여 표면은
   `is_new`와 무관하게 원래 있던 것이며 legal-counsel의 판정 대상이다.
2. **카카오 닉네임에 대한 별도 고지** — 방침 1항이 여전히 구글 3종만 열거한다(K-M3).
   동의 논리가 성립하려면 무엇을 받는지가 방침에 적혀 있어야 한다.

### 3.5 저장형 XSS / 프롬프트 인젝션 실제 위험 — **현재 없음 (소비 경로 0건)**

`message`에 스크립트 태그와 지시문을 함께 넣어 저장한 뒤 소비 경로를 추적했다.

- 저장은 원문 그대로다(DB 확인). `api/inquiries.py` 모듈 docstring이 `clean_user_text`를
  쓰지 않는 이유를 명시하고 있으며, 그 근거(관리자만 읽고 LLM에 넣지 않음)는 현재 코드와
  일치한다.
- `contact_email|inquiry|inquiries` 전체 grep 결과 참조 파일 7개
  (`MyPageContent.tsx`, `lib/api.ts`, `main.py`, `api/inquiries.py`, `repositories/inquiry_repo.py`,
  `schemas/inquiry.py`, `db/postgres.py`) — **LLM 프롬프트 조립 코드도, HTML 렌더 코드도 없다.**
- 목록 API는 `message`를 SELECT조차 하지 않는다(`inquiry_repo.list_by_user` L40-49).
- 따라서 지금 상태에서 저장형 XSS·프롬프트 인젝션은 **실현 경로가 없다**. K-m6에 적은 대로
  admin 조회 화면 신설 시점이 재검토 지점이다.

### 3.6 C-1 / C-2 회귀 여부 — **회귀 없음**

- **C-1(세션 서명키 위조)**: `UserAuth.__init__` L140 `self._secret_present = bool(secret)`,
  `enabled` L145-147이 이 플래그만 본다. 카카오 추가로 분리된 것은 `google_enabled`/
  `kakao_enabled`이며, `main.py` L318이 `enabled and (google_enabled or kakao_enabled)`로
  라우터를 게이팅한다 — 시크릿이 없으면 provider 설정과 무관하게 라우터가 등록되지 않는다.
  verify_auth 1절 6/6 PASS(시크릿 미설정 시 `enabled=False` 포함).
- **C-2(콜백 script 컨텍스트 XSS)**: `_js_safe_json`(L129-139)이 그대로 남아 있고
  `payload`·`frontend_origin_js` 양쪽에 적용된다. verify_auth 4절 2/2 PASS
  (`</script>` 탈출, U+2028/2029).
- **M-1(state nonce 브라우저 바인딩)**: 카카오 콜백도 `auth.verify_state(state,
  cookie_nonce=...)`를 동일하게 통과한다(`api/auth.py` L303-304). verify_auth 2절 6/6 PASS.
- 새로 추가된 `is_new` 필드는 `_js_safe_json` 직렬화 대상 안에 포함돼 있어 C-2 방어를
  우회하지 않는다.

## 4. 개인정보 처리 흐름 요약 (legal-counsel 전달용)

### 4.1 신규/변경 수집 항목 인벤토리

| # | 항목 | 수집 경로 | 저장 위치 | 방침 반영 | 비고 |
|---|---|---|---|---|---|
| **G1** | 카카오 회원번호(`id`) | 카카오 OAuth userinfo | `users.kakao_sub` | **미반영** | 화면 미노출, 재로그인 식별 전용 |
| **G2** | 카카오 계정 이메일 | 카카오 userinfo `kakao_account.email` (동의 선택) | `users.email` | **미반영** | **검증 여부와 무관하게 저장됨 -- K-C1** |
| **G3** | 카카오 닉네임 | 카카오 userinfo `profile.nickname` | `users.display_name`(최초 1회) | **미반영** | 정제·사칭차단 통과 후 저장 |
| **G4** | 고객문의 내용 | 이용자 직접 입력(마이페이지 폼) | `inquiries.message` (최대 2000자, 원문) | **미반영** | 자유서술 -- 이용자가 임의 개인정보를 적을 수 있음 |
| **G5** | 답변받을 이메일 | 이용자 직접 입력(선택) | `inquiries.contact_email` | **미반영** | 계정 이메일과 다를 수 있음, 형식 미검증 |
| **G6** | 온보딩 취향 프로필 | AI 온보딩 문답 | `onboarding_profiles` (계정당 1건) | **미반영** | 이번 검수 범위 밖이나 방침 누락이라 함께 보고 |
| **G7** | 저장한 AI 코스 | 이용자 저장 버튼 | `ai_courses.payload` | **미반영** | 상동 |

### 4.2 흐름 (수집 -- 저장 -- 전송 -- 파기)

- **수집**: (a) OAuth 위임 — 구글/카카오 동의화면에서 이용자가 제공 범위를 승인.
  (b) 직접 입력 — 표시 이름, 고객문의 내용·연락처.
- **저장**: 전부 자체 운영 PostgreSQL(`users`, `inquiries`, `onboarding_profiles`,
  `ai_courses`). provider의 access/refresh token은 **저장하지 않는다**(userinfo 1회 조회 후 폐기).
  세션 쿠키에는 `user_id`와 이메일만 담기고 표시 이름은 담기지 않는다.
- **전송**: 제3자 제공 없음. 국외 이전은 로그인 시 이용자 본인이 구글/카카오에 인증하는
  경로뿐(서버가 개인정보를 국외로 내보내지 않는다). 프론트-백엔드 통신은 동일 오리진 +
  `credentials: include` 세션 쿠키.
- **파기**: `DELETE /api/v1/auth/me`(마이페이지 -- 계정관리 -- 계정 삭제) 실행 시 `users` 행
  즉시 삭제. FK `ON DELETE CASCADE`로 `inquiries`·`onboarding_profiles`·`ai_courses`가 함께
  삭제되는 것을 실측 확인(문의 4건 -- 0건). 세션 쿠키는 만료(7일) 또는 로그아웃 시 무효화.
  리뷰·공유 코스의 `nickname`은 작성 시점 텍스트 복사본이라 계정 삭제 후에도 남는다(기존 동작).

### 4.3 legal-counsel이 판정해야 할 것

| # | 질의 | 근거 |
|---|---|---|
| **SEC-L-1** | 개인정보처리방침을 **배포 전에** 개정해야 하는가, 개정 범위는(카카오 3항목 + 문의 2항목 + 프로필/코스 2항목 + 계정 통합 사실 + 계정 삭제 위치 변경) | K-M3 |
| **SEC-L-2** | 고객문의 `message`·`contact_email`의 **보유기간과 파기 기준**을 방침에 명시해야 하는가(현재 무기한 보관 + admin 조회 화면 없음 -- 사실상 수동 DB 조회로만 처리) | K-M3, 4.2 |
| **SEC-L-3** | 카카오 이메일 동의가 **선택**이라 이메일 없이 가입 가능한 구조에서, 문의 답변용 연락처를 별도로 받는 것이 최소수집 원칙에 부합하는가 | G5 |
| **SEC-L-4** | 신규 가입 시 provider 원본 닉네임이 **이용자 확인 전에** DB에 저장되고, 확인 없이 이탈하면 그 이름이 공개 표시명으로 쓰일 수 있는 구조가 기존 권고(동의 없는 자동 전용 금지)에 저촉되는가 | K-m7 |
| **SEC-L-5** | 재로그인 시 표시 이름 확인 단계를 생략하는 것(`is_new=false`)은 보안팀 판단상 원 권고와 충돌하지 않는다(3.4절). 이 해석을 legal이 승인하는가 | 3.4 |
| **SEC-L-6** | K-C1로 인해 **타인의 계정 정보에 접근 가능한 상태**가 배포 전 반드시 해소되어야 함(개인정보 안전성 확보조치 관점)을 확인 | K-C1 |

## 5. 잘 되어 있는 부분 (재작업 시 훼손 금지)

1. **provider별 게이팅 분리** — `enabled`(세션 인프라) / `google_enabled` / `kakao_enabled`를
   나눠 한쪽 provider 미설정이 전체 로그인을 죽이지 않으면서도, 시크릿 없으면 라우터 자체를
   등록하지 않는 C-1 방어는 그대로 유지했다.
2. **카카오 토큰 미저장** — 구글과 동일하게 access/refresh token을 저장하지 않고 userinfo
   1회 조회 후 폐기. 탈취 시 노출 범위를 우리 서명 세션으로 국한한다.
3. **로그 위생** — 카카오 클라이언트가 응답 본문·토큰·client_secret을 로그에 남기지 않고
   status code만 기록한다. 문의 로그도 `id`/`user_id`만 남긴다.
4. **문의 응답 최소화** — `InquirySummary`가 `message`/`contact_email`을 반환하지 않고,
   목록 쿼리에서 `message`를 SELECT조차 하지 않는다.
5. **CASCADE 파기** — 계정 삭제 시 문의·프로필·코스가 함께 지워지는 것을 실측 확인.
6. **표시 이름 파이프라인 재사용** — 마이페이지 닉네임 변경이 기존 `PATCH /display-name`을
   그대로 타서 정제·사칭차단·길이 제한이 동일하게 적용된다(verify_auth 5절 5/5 PASS).
7. **회귀 스위트 확장** — verify_auth.py에 카카오 통합·is_new 절을 추가한 것은 옳은 방향이다
   (다만 K-C1 순서 케이스가 빠져 있다 — 아래 6절).

## 6. 담당 부서별 조치 요약

### backend-engineer (Critical 1 / Major 3 / Minor 6)
- **K-C1** 미검증 이메일을 `users.email`에 저장하지 않거나(권장) `users.email_verified`
  컬럼을 두고 양쪽 검증을 요구하도록 `upsert_login` 수정 — **배포 차단 사유**
- **K-M1** 1단계 `UPDATE`의 `email` 갱신을 `email_verified` 참일 때로 제한
- **K-M2** `users.email` 부분 UNIQUE 인덱스 + 충돌 처리 + `get_by_email` 결정성 확보
- **K-M4** next/starlette 업그레이드 계획 수립(별도 티켓, 배포 차단 아님)
- **K-m1/m2/m3/m4/m6/m8** message strip 후 검증, contact_email 형식 검증, inquiries UGC
  버킷 편입, is_new 명시 플래그화, admin 조회 화면 신설 시 렌더 안전 확인,
  FRONTEND_BASE_URL 형식 검증

### qa-reviewer (회귀 테스트 추가 필수)
- `verify_auth.py`에 **역순 케이스** 추가: 카카오 미검증 이메일로 먼저 가입 -- 같은 이메일의
  구글 검증 로그인 -- **반드시 별개 계정(user_id 불일치)** 이어야 한다. 현재 9절은 정방향만
  검증해 K-C1을 통과시킨다.
- 1단계 재로그인 시 미검증 이메일이 기존 `email`을 덮지 않는지(K-M1)
- `users.email` 중복 INSERT가 거부되는지(K-M2)
- 문의: 비로그인 401 / 타 사용자 목록 비노출 / body `user_id` 무시 / 공백 message 거부(K-m1)
- 계정 삭제 시 inquiries CASCADE 0건

### legal-counsel
- SEC-L-1 ~ SEC-L-6 (4.3절) — 특히 **SEC-L-1(방침 개정 범위)**과 **SEC-L-6(K-C1 해소 확인)**

### designer / frontend
- **K-m5** LoginModal message 리스너 의존성 배열 정리
- 방침 개정 확정 후 마이페이지 계정 삭제 안내 문구와 `/privacy` 8항 정합

## 7. 최종 판정

### **재작업 필요 — 3차 게이트(보안) 불통과, 운영 배포 승인 불가**

| 구분 | 내용 |
|---|---|
| 판정 | **Critical 1 / Major 4 / Minor 8** |
| 게이트 | **불통과** (Critical 0건 조건 미충족) |
| 차단 사유 | **K-C1** — 피해자의 이메일 주소만으로 신규 계정을 선점·탈취할 수 있는 인증 우회. `user_repo.py` L80-96 |
| 재검수 범위 | K-C1 조치 후 `user_repo.upsert_login` + `verify_auth.py` 역순 케이스만 약식 재검수. 나머지 영역은 재검증 불필요 |
| 조건부 승인 가능 조건 | K-C1 + K-M1 + K-M2 조치 완료 및 회귀 테스트 통과 시 **조건부 승인**으로 전환 가능. 단 K-M3(방침 개정)는 legal-counsel 판정을 받아 배포 전 반영해야 한다 |
| 배포 차단 아님 | K-M4(의존성)는 기존 이슈로 별도 티켓 처리 — 이번 배포를 막지 않는다 |

**한 줄 총평**: 카카오 확장 자체는 구글 로그인의 방어 구조(시크릿 게이팅·state nonce·script
컨텍스트 이스케이프·표시 이름 정제)를 훼손하지 않고 잘 이식했고 고객문의 인가도 정확하다.
결함은 단 한 곳 — **계정 통합에서 "이번 로그인의 이메일"만 검증하고 "기존 행의 이메일"은
검증하지 않은 비대칭**이며, 이것이 문서가 막았다고 주장하는 바로 그 계정 탈취를 실제로 허용한다.

## 8. 핸드오프 노트

```
1. [legal-counsel] 개인정보처리방침이 카카오(회원번호·이메일·닉네임)·고객문의(문의내용·
   연락처이메일)·온보딩 프로필·저장 코스를 전혀 담고 있지 않다(K-M3). 배포 전 개정 필요 여부와 문의
   데이터 보유기간 명시 여부를 판정해달라 — 상세 질의 SEC-L-1~L-6은 4.3절.
2. [qa-reviewer] 회귀 테스트 필수 추가 — 카카오 미검증 이메일 선가입 후 같은 이메일 구글
   로그인이 **별개 계정**이 되는지(K-C1 역순 케이스, 현재 verify_auth 9절이 놓친 방향),
   미검증 이메일의 기존 email 덮어쓰기 차단(K-M1), 공백만 문의 거부(K-m1).
3. [backend-engineer] K-C1 조치 전 배포 금지. 조치는 upsert_login 한 함수 수정으로 끝난다
   (미검증 이메일 비저장 + 1단계 email 갱신 조건화 + users.email 부분 UNIQUE).
```

## 9. 조치 완료 보고 (오케스트레이터, 2026-08-18)

security-engineer·qa-reviewer 병렬 풀검수(§본문, `design-docs/04-qa-report.md` 말미)에서
나온 지적을 전량 조치했다.

| 항목 | 조치 |
|---|---|
| K-C1(Critical, 계정 탈취) | `user_repo.py upsert_login` — 이메일은 **검증된 값만** `email` 컬럼에 저장하도록 변경. 미검증 이메일로 선점한 행은 `email=NULL`이라 나중에 검증된 로그인의 `get_by_email` 매칭 대상이 될 수 없다 |
| K-M1(재로그인 시 이메일 덮어쓰기) | 같은 함수 — 이번 로그인이 검증된 이메일을 안 주면 기존 저장값을 건드리지 않음(무조건 UPDATE → 조건부 UPDATE) |
| K-M2(email UNIQUE 없음) | schema_version 8 — `ux_users_email` UNIQUE 인덱스 신설(기존 비-UNIQUE `ix_users_email` 대체). 배포 전 로컬 DB에 중복 이메일 없음을 직접 확인 후 마이그레이션 실행 |
| K-M3(개인정보처리방침 미반영) | `frontend/app/privacy/page.tsx` 전면 갱신 — 카카오 로그인, 온보딩 취향, AI 코스 저장, 고객문의(메시지+연락처 이메일) 4개 항목을 수집/목적/보유기간/파기 전 섹션에 반영. 계정 삭제 버튼 위치 안내도 헤더→마이페이지로 갱신 |
| M-2(qa, 삭제 계정 세션 재사용 시 500) | `api/auth_deps.py require_login` — 토큰 서명 검증 후 DB에 해당 user_id가 실제로 있는지까지 확인, 없으면 401(기존엔 서명만 보고 통과시켜 하위 INSERT가 FK 위반 500을 냄) |
| M-3(qa, Esc로 닉네임 확인 우회) | `LoginModal.tsx` — 전역 Esc 핸들러가 클로저에 갇힌 stale `step`("provider")만 보고 있어 닉네임 확인 단계에서 Esc를 눌러도 계정 삭제 없이 그냥 닫히던 버그. `stepRef`로 최신 단계를 추적하도록 수정 |
| M-4(qa, 처리방침 항목 누락) | K-M3와 동일 조치로 함께 해소 |
| M-5(qa, 문의 API 레이트리밋 버킷 오분류) | `middleware/rate_limit.py` — `/api/v1/inquiries` POST를 `default`(120/분)에서 리뷰·코스공유와 동일한 `ugc` 버킷으로 재분류 |
| K-m1(qa, 공백만 있는 문의 통과) | `api/inquiries.py` — Pydantic `min_length=1`은 공백 1글자도 통과시키므로, strip 후 재검증해 422 반환하도록 추가 |
| M-6(qa, 배포 마이그레이션 문서 부재) | 미착수 — 문서 보강 항목이라 배포 차단 사유는 아님, 별도로 처리 예정 |

**검증**: `verify_auth.py` 53/53(신규 K-C1/K-M1/M-2/K-m1 재현 테스트 4건 포함, §11~13), `verify_community.py` 67/67, `verify_community_retention.py` 35/35, `verify_admin.py` phase B 77/77(phase A 1건은 로컬 `.env`의 `CORS_ALLOW_CREDENTIALS=true` 리크로 인한 기존 무관 결함, 재확인), 프론트 `tsc --noEmit` 0에러, 백엔드 임포트 정상, 로컬 dev Postgres에 schema_version 8 마이그레이션 실적용 확인.

**판정**: K-C1/K-M1/K-M2/K-M3 전부 조치 완료로 두 부서의 "조건부 승인 조건"을 충족했다고 판단한다. M-6만 미해결 상태로 남기고, 문서 보강 성격이라 배포를 막지 않는다고 판단했다 — 최종 배포 승인은 대표 몫이다.

---

## 2026-08-18 외부 보안감사(2차 개발자용 · 3차 비전공자용) 반영 검수

- 검수자: security-engineer / 대상: 워킹트리 미커밋 변경분 (슬랙 연동 변경은 범위 밖 — 별도 세션)
- 근거 문서: `security-reports/2026-08-18-감사반영-작업기록.md`
- **판정: 조건부 승인** — Critical 0 / High 0 / Medium 2 / Low 5. M-1·M-2는 커밋 전 조치 권고(배포 차단 사유 아님).

### 1. 점검 항목 체크리스트

| 항목 | 결과 |
|---|---|
| 인증/인가 | ○ 관리자 세션 서명·401 무구분 유지, `/mine` 소유권 확인 유지, 인증 없는 운영자 명단 노출 제거 |
| 입력 검증 | ○ 코스 payload allowlist 재구성(적대적 입력 직접 검증), 온보딩 text 2000자 상한. SQL은 전량 파라미터 바인딩, `prune`의 f-string은 고정 튜플 |
| XSS | ○ 프론트 `dangerouslySetInnerHTML` 0건, 서버 `clean_user_text` 정제 |
| 시크릿 관리 | △ 하드코딩 0건·`.env` 커밋 0건이나 **로그 마스킹 2곳 누락(M-1)** |
| 의존성 | ○ `starlette==1.0.1`(BadHost 패치 반영본) 핀, 신규 의존성 0. 이미지 태그 고정 |
| AI 특화 | ○ 사용자 텍스트는 LLM 프롬프트 미투입 불변식 유지, LLM 출력의 코드/SQL 실행 경로 없음 |
| 인프라 | △ CORS·rate limit·보안 헤더 유지. **HSTS 여전히 미적용(이월)** |
| 개인정보 | ○ 방문 IP 가명화 fail-closed + 90일 파기 실배선(이번이 최초) |

### 2. 발견된 취약점

| ID | 심각도 | 위치 | 내용 | 수정 권고 | 담당 |
|---|---|---|---|---|---|
| M-1 | Medium | `backend/app/clients/kto_client.py:133-134`, `backend/app/clients/stddata_festival_client.py:110` | A-2 미완. 두 클라이언트 모두 `serviceKey=public_data_api_key`를 보내는데 파싱 실패 시 `resp.text[:200]`을 마스킹 없이 로그에 남긴다. 원천이 쿼리스트링을 되비추면 API 키가 운영 로그에 평문 잔류 | `redact_secrets(resp.text)[:200]` 로 감싼다 | backend-engineer |
| M-2 | Medium | `backend/app/config.py:277-278`, `backend/app/middleware/visit_log.py:107-119`, `deploy/DEPLOY.md`(③ 검증), `backend/.env.production.example:151-157` | 폴백 체인(`ADMIN_SESSION_SECRET`→`JWT_SECRET_KEY`→`ADMIN_PASSWORD_HASH` 파생) 때문에 운영 구성에서는 키를 비워도 집계가 꺼지지 않고 경고도 안 나온다. DEPLOY.md의 `grep ADMIN_SESSION_SECRET` 검증이 **항상 통과 = no-op**이며, 문서의 "fail-closed" 서술이 사실과 다르다 | 기동 시 `os.getenv("ADMIN_SESSION_SECRET")`가 비었고 `admin_password_hash`가 있으면 "파생 키 사용 중" 경고 1회 출력, 그 문구를 검증 대상으로 문서 정정 | backend-engineer |
| L-1 | Low | `backend/app/services/course_payload.py:406` | `filter_stored_course`가 payload 내부의 `"v": 2`를 신뢰 근거로 쓴다. 클라이언트 형태 payload에 `v:2`를 넣으면 `blurb`가 살아남는다. 현재 쓰기 경로 2곳이 모두 `v`를 서버 값으로 덮으므로 **API로는 도달 불가** | 신뢰 판정을 DB 컬럼(`payload_version`)이나 서명으로 이전 | backend-engineer |
| L-2 | Low | `backend/app/middleware/visit_log.py:113-117` ↔ `backend/app/security/admin_auth.py:184-193` | 폴백 ③에서 방문 해시 키가 관리자 세션 서명키와 동일한 파생값(라벨 상이). 절단 HMAC이라 키 역산은 비현실적 | `ADMIN_SESSION_SECRET` 실제 설정(M-2와 함께 해소) | 배포 담당 |
| L-3 | Low | `backend/app/util/redact.py:44-48` | 소문자 퍼센트인코딩(`%2b`/`%2f`) 형태는 치환되지 않음. httpx는 대문자 hex를 쓰므로 실환경 가능성 낮음 | 대소문자 무시 매칭 추가 | backend-engineer |
| L-4 | Low | `backend/app/middleware/rate_limit.py:88-99`, `backend/app/api/course_share.py:173` | `POST /api/v1/courses/mine`은 영구 기록 쓰기인데 `ugc`가 아니라 `course` 버킷이고 `_encode_payload` 크기·깊이 사전 검사도 없음. 로그인 필수 + nginx 1m 바디 제한이 완충 | `UGC_METHODS`에 `/api/v1/courses/mine` 추가, `_encode_payload` 사전 검사 통일 | backend-engineer |
| L-5 | Low(이월) | `deploy/nginx.conf` | HSTS 헤더 미적용(2026-08-09 "첫 실갱신 성공 후"로 유예) | 갱신 이력 확인 후 적용 | 배포 담당 |
| I-1 | Info | `backend/app/middleware/error_alert.py:148` | `request.url.path` 잔존 — 알림 문구용, 영향 없음 | 통일 시 `scope_path()` | — |
| I-2 | Info | `backend/app/api/admin.py:190` | `required` 불리언은 여전히 콘솔 활성 여부를 알려주나 잔여 정보량 무시 가능 | 조치 불요 | — |

### 3. 검증 방법

- `python scripts/verify_course_payload.py` → 38/38
- `rebuild_course_for_store`에 위조 필드(가짜 장소명·`congestion.level`·외부 이미지·`verified_badge`·`match_score:99`·`<script>` slot_label·클라이언트 `v:2`) 직접 투입 → 전량 서버 값 대체·폐기·clamp 확인. `filter_stored_course` 읽기 경로도 동일
- `redact_secrets`에 서비스키 6개 인코딩 형태 투입 → 5개 마스킹, 소문자 hex 미치환(L-3)
- starlette 1.0.1 `URL.__init__` `_HOST_RE` 가드 확인 · tracked 465파일 시크릿 패턴 grep 0건

### 4. 개인정보 처리 흐름 요약 (legal-counsel 전달용)

| 단계 | 내용 | 이번 변경 |
|---|---|---|
| 수집 | 방문 IP → HMAC 앞 16자 가명화(원본 미저장) | 키 부재 시 수집 중단(fail-closed) 신설, 고정 폴백 키 제거 |
| 전송 | 공공 API 원천 호출 5종 | 전량 https 승격, 응답 로그 마스킹(2곳 누락 = M-1) |
| 파기 | 90일 | **`prune` 자동 실행이 이번에 최초 배선** — 그 이전 기간은 미이행(처리방침·관리자 화면 문구와 과거 불일치 구간) |
| UGC | 공유/저장 코스 payload | 서버 재구성으로 사용자 자유입력 잔류가 `slot_label`(24자)·`ai_title`(40자)·`ai_summary`(400자)로 축소 |
| 공개 | `security.txt` 연락처 | 처리방침 §9 기공개 값과 동일 — 신규 노출 없음 |

### 5. 최종 판정

**조건부 승인.** Critical/High 0건 → 3차 게이트(보안) 통과. 조건: (a) M-1 로그 마스킹 2곳 보완, (b) M-2 기동 경고 추가 + 문서 정정. 미처리 시에도 배포는 막지 않되 `.env`의 `ADMIN_SESSION_SECRET` 실재 여부를 대표가 파일로 직접 확인해야 한다.

---

## 검증 방식 (전부 실제 실행)

읽기만으로 판단하지 않고 라이브 Postgres + `TestClient`로 직접 두드렸다. 워킹트리의 Prometheus 변경 때문에 venv에서 `app.main` import가 깨져(`ModuleNotFoundError: prometheus_fastapi_instrumentator`, 범위 밖) 스크래치패드에 스텁 모듈을 놓고 `PYTHONPATH`로만 주입해 실행했다 — 저장소 파일은 한 글자도 건드리지 않았다.

실행한 것: `verify_likes.py` 42/42 PASS, `verify_tips.py` 42/42 PASS, 그리고 자체 probe 3종(탈퇴 계정 개인화 경로 / like_count 드리프트 / 단정표현 필터 커버리지).

# 2026-08-20 기능확장 6건 구현 검수 (security-engineer)

## 0. 판정

**조건부 승인** — Critical 0건 · High 0건. 3차 게이트(QA+보안) 통과 조건은 충족한다.
배포 전 조건 2건: ① 개인정보 처리방침 갱신(법률팀 4차와 연동, §4) ② M-1(좋아요 카운트 드리프트) 수정 또는 대표의 리스크 수용 기록.

## 1. 필수 점검 항목 체크리스트

| 항목 | 결과 | 근거 |
|---|---|---|
| 인증/인가 — 좋아요 신원 | ✅ | `api/course_share.py:188,210` 둘 다 `Depends(require_login)`. 비로그인·위조 쿠키 모두 401 실측 |
| 인증/인가 — `optional_identity` 우회 | ✅ | `api/auth_deps.py:47-67`. 서명 검증 + 탈퇴 계정 DB 재확인까지 `require_login`과 동일. 저장소 장애 시 `None`(비로그인)으로 fail-closed |
| 입력 검증 — SQL Injection (`sort`) | ✅ | 라우터 `Literal["latest","popular"]`(422) + 리포지토리 dict 화이트리스트. 문자열 보간 0 |
| 입력 검증 — XSS | ✅ | `dangerouslySetInnerHTML` 저장소 전체 0건. LLM 팁은 텍스트 노드 렌더 |
| 시크릿 하드코딩 | ✅ | 신규 5파일 + diff 전체 grep 0건 |
| 의존성 | ✅ | 이번 6건이 추가한 의존성 0 |
| AI — prompt injection | ✅ | 요청 스키마에 자유 텍스트 필드 0, 삽입값은 registry/서버 상수만 |
| AI — LLM 출력 무검증 실행 | ✅ | 코드·SQL 실행 경로 없음, 출력은 카테고리 allowlist + 길이 절단 |
| 인프라 — 삭제 잔재로 정보 노출 | ✅ | `/concierge/ask` → 404, 스택트레이스 없음, nginx/env 죽은 참조 0 |
| A-6 재구성 로직 불가침 | ✅ | `git diff course_payload.py` 변경 0 |

## 2. 검증 상세 (요지)

- **탈퇴 계정 + 유효 서명 쿠키** 재현: feed/상세는 liked_by_me=False로 fail-closed, like는 401, tips는 정적 폴백(generated_by=static-v2) — 인증 우회 없음.
- **스키마10**: `course_likes` FK `ON DELETE CASCADE` 양방향, PK `(share_code,user_id)`로 1인1표 DB 강제, `ON CONFLICT DO NOTHING`+rowcount라 경쟁 없음. `sort` 인젝션 시도(`?sort=latest; DROP TABLE...`) → 422.
- **A-6**: `course_payload.py` diff 빈 값. `verify_likes.py` §6 "좋아요 전후 payload 바이트 단위 동일" PASS.
- **팁 프롬프트**: `TipsRequest`엔 `region_code`(정규식 검증) 단 하나뿐. 스팟명·닉네임·자유텍스트 필드 자체가 없음. 잉여 필드(`text` 주입) 실측 시 LLM 미도달.
- **단정표현 필터**(`_TIP_UNSAFE_PATTERNS`): "반드시 우산을" 등 일부 차단, "안전이 보장됩니다"/"치료 효과가 있어요" 등 다수 통과(L-1) — 입력이 공격자 제어가 아니라 실위험은 낮음.
- **레이트리밋**: 좋아요=ugc버킷+계정별 30/분 이중, 팁=llm버킷. 컨시어지 제거 후 BUCKET_LLM(6/분)을 온보딩·팁이 공유하나 팁은 비로그인/무프로필이면 LLM 미호출이라 실사용 압력 낮음(관찰, 조치 불요).
- **삭제 잔재**: `grep -rni concierge backend/` 코드참조 0(주석 3건만), nginx `/concierge/` → `/tips/`로 교체, `.env*`의 `CONCIERGE_*` 6종 제거.

## 3. 발견된 취약점

| ID | 심각도 | 위치 | 내용 | 담당 |
|---|---|---|---|---|
| M-1 | Medium | `repositories/user_repo.py:126-133`(delete_account), `db/postgres.py`(스키마10), `shared_course_repo.py:233,312` | 계정 탈퇴 시 `course_likes`는 CASCADE 삭제되지만 `shared_courses.like_count` 감산 경로가 없어 실측 드리프트 확인(3명 좋아요→2명 탈퇴 후 like_count=3, 실제 행=1). `sort=popular` 랭킹 왜곡(가입→좋아요→탈퇴 반복 악용 가능) + `delete_overflow`가 실제 좋아요 0인 코스를 영구 유예할 수 있음. 수정: `delete_account` 트랜잭션에서 `users` DELETE 전에 `UPDATE shared_courses SET like_count = GREATEST(like_count-1,0) WHERE share_code IN (SELECT share_code FROM course_likes WHERE user_id=%s)` | backend-engineer |
| L-1 | Low | `services/tips_service.py:53-57` | 단정표현 필터가 동등 표현 다수 통과("안전이 보장됩니다" 등). 입력이 비공격자 제어라 실위험 낮음. 패턴 6~8개 추가 권고 | ai-optimization-engineer |
| L-2 | Low | `frontend/lib/api.ts:1999-2007`(fetchSharedCoursesFeed) | `credentials:"include"` 누락 — 동일 오리진 배포는 무해하나 로컬개발/분리배포 환경에서 liked_by_me가 항상 false로 보임(fail-closed, 정보노출 아님) | backend-engineer |
| L-3 | Low | `.env.example`·`.env.production.example` | 좋아요 킬스위치(`LIKE_ENABLED`·`LIKE_WRITE_PER_MIN`)가 코드엔 있으나(503 FEATURE_DISABLED 실측) 템플릿에 미기재 | backend-engineer |
| L-4 | Low | `schemas/tips.py:24-27` | `TipsRequest`가 잉여 필드를 조용히 무시 — 현재 무해하나 향후 자유텍스트 필드 실수 추가를 스키마가 막지 못함. `extra="forbid"` 권고 | backend-engineer |

관찰(조치 불필요): `_cache_key`에 `user_id` 없음(현재 안전, `TipFeatures` 필드 추가 시 `_cache_key` 동시 갱신 안 하면 팁 교차노출 위험 — verify_tips.py에 단언 추가 권고).

## 4. 개인정보 처리 흐름 (legal-counsel 전달용)

**신규 수집 — 좋아요**: user_id+share_code+created_at, 자체 Postgres 저장, 제3자 제공·국외이전 0, 공유코스 삭제/계정탈퇴/보존기간만료 시 CASCADE 삭제. **법률팀 확인 필요 ①**: `/privacy` §1·§3·§7·§8에 좋아요 항목 누락(실동작은 방침 취지와 부합, 문구만 없음).

**목적 확장 — 팁 개인화**: 온보딩 취향 태그+최근 코스 카테고리 분포(스팟명 미사용)+지역 혼잡도+강수확률 → 로컬 Ollama(국외이전 없음, 신규 외부API/SDK 0). **법률팀 확인 필요 ②(U-8)**: 방침 §3 문구가 "취향 유지·코스 재사용"으로 좁아 팁 개인화를 포섭 못함 — 문구 확장 권고(원 수집 맥락과 합리적 관련성은 인정될 소지 큼, 최종판단은 법률팀).

**컨시어지 삭제**: 자연어 질문 원문이 LLM에 전달되던 경로가 사라짐(개인정보 관점 순감소).

## 5. 핸드오프 노트

```
[legal-counsel] 처리방침 갱신 2건 — ①좋아요 반응기록 항목 누락 보완 ②§3 목적 문구에 팁 개인화 포함(U-8).
[qa-reviewer] 회귀 3건 추가 — ①탈퇴 후 like_count 정합성(M-1) ②fetchSharedCoursesFeed credentials 누락(L-2) ③TipFeatures 필드추가시 _cache_key 동시갱신 단언.
[backend-engineer] M-1(delete_account 감산) · L-3(env 템플릿) · L-4(extra=forbid) — 전부 소규모. A-6·인증경계·SQL바인딩은 이상 없음.
```
