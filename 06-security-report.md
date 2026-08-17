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
