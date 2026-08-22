# 06 보안 검토 — XFF 신뢰경계 강화 패치 독립 검증 (2026-08-22)

대상 커밋: `a23aad1`(XFF 이중화 + pip-audit 2건) · `f1dd1b0`(Next 15) · `7245c41`(의존성 감사 CI)
등급: 풀검수 (인증/레이트리밋 변경) · 검증자: security-engineer · 판정: **조건부 승인 (Critical 0건)**

> 오케스트레이터 주: 이 보고서가 지적한 H-1(루프백 우회)·M-1(신뢰 대역 과다)은
> 이 문서 작성 직후 추가 패치로 반영됐다(Dockerfile `--no-proxy-headers`, RFC1918+ULA
> 명시적 화이트리스트로 축소, `RATE_LIMIT_TRUSTED_PROXY_CIDRS` 로 추가 축소 가능).
> 아래는 검증 당시 원문 그대로 보존한다.

## 1. 검증 방법 — 실행 확인 vs 코드 리뷰

| 구분 | 내용 |
|---|---|
| 실행 확인 | ① `backend/scripts/verify_rate_limit_proxy_trust.py` 직접 실행 ② 실제 `uvicorn 0.34.0` + 실제 `RateLimitMiddleware` 로컬 하네스 13개 시나리오 ③ 실앱(`app.main`) TestClient 스모크 ④ 신·구 `requirements-lock.txt` pip-audit 대조 ⑤ `npm audit --omit=dev` + `next build` ⑥ CI 카운트 스크립트 2개 실측 ⑦ injection_guard 정규식 매칭/ReDoS 측정 ⑧ starlette 1.0.1↔1.3.1 소스 diff ⑨ `git ls-files` 시크릿 추적 검사 |
| 코드 리뷰만 | GitHub Actions 러너 상 동작(시크릿 마스킹·fork PR 정책), pip-audit의 sdist 실행 가능성, 실서버(NAVER) 런타임 실측 |
| 미실시 | 운영 서버 대상 DAST(공격 스크립트 미작성 원칙 · 로컬 하네스로 대체) |

## 2. 점검 항목 체크리스트

| 항목 | 결과 |
|---|---|
| 인증/인가 (관리자 세션·브루트포스) | 조건부 통과 — H-1 참조. 로그인 리미터는 `extract_client_ip` 공유라 패치 효과 자동 적용(`backend/app/api/admin.py:93`) |
| 입력 검증 (SQLi/XSS/traversal/SSRF) | 이번 변경 범위 내 신규 위험 없음. 사용자 제어 URL로의 아웃바운드 호출 없음(Ollama/Slack은 고정 base_url) |
| 시크릿 관리 | 통과 — `git ls-files`상 `*.pem`·`*_deploy_key`·`.env` 추적 0건, `.gitignore` 패턴 확인. 워크플로가 웹훅을 로그에 출력하지 않음 |
| 의존성 | pip 통과(0건, 실측) / npm High 3건 잔존(next@16 필요, 알려진 이월) |
| AI 특화 (prompt injection) | 통과 — denylist 2개 추가는 모니터링 전용, 오탐·ReDoS 없음, 로그에 원문 미기록 |
| 인프라 (CORS/HTTPS/rate limit/에러 노출) | 통과 — nginx가 XFF를 `$remote_addr`로 덮어쓰고 server 레벨 선언이라 모든 location이 상속(재정의 없음 확인). backend `ports:` 미노출 유지 |

## 3. 실행 검증 결과 — 패치가 공격 시나리오를 막는가

**(1) `verify_rate_limit_proxy_trust.py`: 6/6 PASS** (exit 0). 다만 이 스크립트는 순수 함수만 호출하므로 uvicorn 계층은 검증하지 않습니다.

**(2) 실제 uvicorn + 실제 미들웨어 하네스** (한도 5/60s, 8회 요청, `x-sim-peer`로 소켓 peer 시뮬레이션):

| 시나리오 | 결과 |
|---|---|
| 공인 peer 8.8.8.8 + 매 요청 다른 XFF | **차단** (5회 후 429, 키 1개) |
| 공인 peer 9.9.9.9 + XFF 사설 체이닝 `10.0.0.1, 10.0.0.2, ...` | **차단** (키=9.9.9.9, 체이닝 무효) |
| `::ffff:9.9.9.9` (IPv4-mapped) + XFF 회전 | **차단** |
| 공인 IPv6 `2400:cb00::1` + XFF 회전 | **차단** |
| CGNAT `100.64.0.5` / 파싱 실패 문자열 | **차단** |
| docker 내부망 `172.20.0.5` + 고정 XFF (정상 nginx 경로) | **정상 동작** (키=XFF 첫 값, 회귀 없음) |
| **실제 loopback 127.0.0.1 + XFF 회전** | **우회 (8/8 통과)** → H-1 (이후 패치로 해소) |

**(3) 실앱 스모크**(starlette 1.3.1): `app.main` import OK, 미들웨어 스택 순서 정상(Prometheus→CORS→RateLimit→VisitLog), `/health` 200, CORS preflight 200(`ACAO` 정상), 알 수 없는 경로 404, TestClient에서 XFF 회전 → 3회 후 429(키=`testclient` 단일).

결론: **4차 감사의 핵심 위협(인터넷 공인 IP에서 backend 직접 접근 + XFF 스푸핑)은 실제로 차단됩니다.** 정상 배포 경로는 깨지지 않았습니다.

## 4. 발견된 취약점

### H-1 (High, 조건부) 루프백 경로 우회 잔존 — 4차 감사 재현 방식이 그대로 통과 → **패치 완료**
- 위치: `backend/app/middleware/rate_limit.py:217` (당시 `ipaddress.ip_address(host).is_private`), `backend/Dockerfile` CMD
- 무엇이: ① `127.0.0.1`/`::1`은 `is_private=True`라 신뢰 대상이며, 검증 스크립트도 이를 "정상 경로"로 명시(케이스 3). ② 더 중요한 건, uvicorn `0.34.0`은 `proxy_headers=True`가 기본이고 `forwarded_allow_ips` 기본값이 `"127.0.0.1"`(`uvicorn/config.py:334`)이라 **루프백에서 온 요청은 `request.client.host` 자체가 클라이언트가 보낸 XFF 값으로 치환**됩니다. 즉 이 패치가 전제하는 "`request.client.host`는 진짜 소켓 peer"가 루프백에서는 성립하지 않습니다.
- 실측 증거: 하네스 시나리오 A에서 8/8 통과했고, 앱이 인식한 peer가 공격자가 넣은 `51.1.1.x`로 보고됨(소켓은 127.0.0.1). 4차 감사가 실제로 수행한 "로컬에서 backend에 직접 붙기" 방식은 패치 후에도 동일하게 무제한 통과합니다.
- 악용 조건: 호스트 셸 접근, `ports: "127.0.0.1:8000:8000"` 형태의 퍼블리시, SSH 터널 등. **현 배포(compose에 backend `ports:` 없음)에서는 인터넷 경유 악용 불가** → 배포 차단 사유는 아님.
- **처리 결과(2026-08-22, 이 보고서 직후)**: ① Dockerfile CMD에 `--no-proxy-headers` 추가 ② `_is_trusted_proxy_peer`를 `is_private` 대신 **RFC1918 명시 화이트리스트(10/8, 172.16/12, 192.168/16) + IPv6 ULA(fc00::/7)**로 좁혀 loopback 제외 ③ 검증 스크립트에 loopback-우회 케이스를 반대 기대값(신뢰 안 함)으로 반영.

### M-1 (Medium) 신뢰 대역이 "모든 사설 대역"이라 과도 → **1차 완화 + 추가 축소 경로 마련**
- 위치: `backend/app/middleware/rate_limit.py:207-218`
- 무엇이: docker 네트워크의 다른 컨테이너(인증 없는 `ollama`, SSR을 수행하는 `frontend`)나 향후 같은 VPC의 다른 호스트에서 온 요청도 XFF를 신뢰합니다. 컨테이너 하나가 뚫리면 레이트리밋·로그인 브루트포스 방어가 다시 0이 됩니다. 또 Python `ipaddress`는 `0.0.0.0/8`, `169.254.0.0/16`, `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, `2001:db8::/32`도 private로 판정합니다(실측 표 확보) — 주석이 의도한 "docker 내부망"보다 신뢰 표면이 넓습니다.
- **처리 결과**: RFC1918+ULA 명시 화이트리스트로 좁혀 loopback·link-local·문서용 대역은 제외했다(H-1과 동일 커밋). QA 검증(M-1)이 추가로 지적한 "RFC1918 자체도 VPC 내부에서는 넓다"는 잔여 우려에는 `RATE_LIMIT_TRUSTED_PROXY_CIDRS` 환경변수로 운영자가 실제 docker 네트워크 서브넷까지 더 좁힐 수 있는 경로를 열어뒀다(기본값은 기존과 동일, 즉시 행동 변화 없음 — opt-in).
- 참고(양호): IPv4-mapped IPv6 우회는 성립하지 않습니다. 실측상 Python 3.12.10/3.13.2 모두 `::ffff:8.8.8.8` → `is_private=False`(CVE-2024-4032 수정 반영본). 단 이는 **런타임 Python 버전에 의존**하므로 `python:3.12-slim` 태그가 3.12.4 미만으로 고정되지 않도록 유지 필요. (신규 코드는 `ipv4_mapped` 명시 언랩을 쓰므로 이 의존성 자체가 사라졌다.)

### M-2 (Medium) CI 감사 대상 파일이 실제 배포 의존성과 불일치 → **패치 완료**
- 위치: `.github/workflows/dependency-audit.yml` (`pip-audit -r requirements-lock.txt`)
- 무엇이: Docker 이미지는 `requirements.txt`로 설치하는데 CI는 `requirements-lock.txt`를 감사합니다. 실측 대조 결과 lock에는 **psycopg / psycopg-pool / psycopg-binary / tzdata가 통째로 빠져 있고**, `idna`(3.18 vs 3.19)·`typing-inspection`(0.4.2 vs 0.4.4)도 실제 해석 결과와 다릅니다.
- **처리 결과**: CI를 `requirements.txt` 직접 감사로 변경(ubuntu-latest 러너가 Linux라 실제 배포 플랫폼과도 더 가깝다). `requirements-lock.txt`는 참고용 스냅샷임을 명시하고 정확한 값으로 재생성, Windows 전용 조건부 패키지(colorama·tzdata)에 주석을 달았다.

### M-3 (Medium) 감사 카운트 스크립트가 fail-open → **패치 완료**
- 위치: `.github/scripts/count_npm_high.js:9-12`, `.github/scripts/count_pip_vulns.py:12-13`
- 무엇이: 파일 부재·JSON 스키마 변경·audit 실패 등 **모든 예외를 `count = 0`으로 삼킵니다.**
- **처리 결과**: 두 스크립트 모두 파싱/스키마 실패 시 stderr에 원인을 적고 exit 1. `VAR=$(스크립트)` 형태이므로 GitHub Actions 기본 셸(`bash -e`)이 그대로 잡 실패로 전파함을 로컬에서 실측 확인(`bash -e -c 'X=$(exit 7); echo after'` → "after" 미출력, exit 7). 실패 시 별도 Slack 알림("워크플로 자체가 실패") 단계도 추가했다.

### M-4 (Medium) 알람 피로 — 매주 확정적으로 울리는 Slack 알림 → **패치 완료**
- 실측: 현재 `npm audit --omit=dev` = High 3건(postcss 4개 advisory, sharp 1개, 모두 next@16에서만 해결).
- **처리 결과**: `NPM_HIGH_BASELINE`/`PIP_VULNS_BASELINE` 환경변수 도입 — 기준선 이하는 조용히 넘어가고, 신규로 기준선을 넘을 때만 알린다. next@16 업그레이드 완료 시 기준선을 낮추라고 워크플로 주석에 명시.

### L-1 (Low) starlette 1.3.1에서 TestClient(httpx) deprecated — 추적만, 미조치
- 실측: 실앱 스모크 중 `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead`. `backend/scripts/verify_*.py` 다수가 TestClient 기반이라 starlette 1.4+에서 제거되면 회귀 검증 자산이 한꺼번에 죽는다. qa-reviewer가 추적.

### L-2 (Low) 로컬 `backend/.venv`가 아직 starlette 1.0.1 → **패치 완료**
- 실측: `.venv`는 취약 버전 그대로였다. `.venv/Scripts/python.exe -m pip install -r requirements.txt`로 동기화 완료, 이후 모든 verify 스크립트를 `.venv`로 재실행해 통과 확인.

### L-3 (Low) `requirements.txt`에 한글 주석 잔존 — 자기 규칙 위반 → **패치 완료**
- 파일 상단이 "keep this file ASCII-only"라고 경고하지만 psycopg/prometheus 관련 한글 주석이 남아 있었다. 영문으로 교체, ASCII 인코딩 재확인 완료.

### L-4 (Low, Info) 워크플로 표현식 직접 삽입 → **패치 완료**
- `run:` 블록 안에 `${{ github.repository }}`를 직접 넣던 것을 `env: REPO: ${{ github.repository }}` 경유로 변경(GitHub Actions 스크립트 인젝션 일반 패턴 회피).
- 함께 확인한 양호 사항: `permissions: contents: read`로 **GITHUB_TOKEN 최소권한 충족**, 웹훅은 `env` + `secrets`로만 전달되고 payload/로그에 노출 없음(`curl -sS`), 트리거가 `pull_request`(≠`pull_request_target`)라 fork PR에 시크릿 미전달, `npm audit`은 install script를 실행하지 않음.

### L-5 (Low, 코드 리뷰 판단) PR 트리거 pip-audit의 sdist 빌드 여지 — 추적만
- requirements 변경 PR에서 pip-audit이 의존성 해석 중 sdist를 빌드하면 CI 러너에서 코드가 실행될 수 있다. 비공개 저장소 + 내부 팀 PR 전제라 실질 위험은 낮다.

## 5. 양호 확인 사항 (실행 검증됨)

- **의존성 패치 효과**: 패치 전 lock → `starlette 1.0.1` PYSEC-2026-248/249/2280/2281 + `python-dotenv 1.0.1` PYSEC-2026-2270 (총 6건 리포트) / 패치 후 lock·requirements → **"No known vulnerabilities found"**. GitHub Dependabot alerts 도 push 이후 35건→5건(잔존 5건은 전부 postcss/sharp, next@16 필요)으로 확인됨.
- **starlette 1.3.1 ↔ fastapi 0.141.1 호환**: `pip check` 무충돌, 실앱 부팅·요청 처리 정상. 1.0.1→1.3.1 소스 diff 확인 결과 변경은 `requests.py`(urlencoded 폼 파서에 `max_fields`/`max_part_size` 적용 = CVE 수정), `responses.py`, `datastructures.py`, `routing.py`/`middleware/base.py` 뿐이며 **앱이 쓰는 공개 API 시그니처 변경 없음**.
- **Next.js 15 보안 회귀 없음**: `npm run build` 22/22 라우트 통과(실측). 동적 라우트 3곳 외 `params`/`searchParams` 사용처 없음, `route.ts`·`generateMetadata`·`middleware.ts` 부재 → CVE-2025-29927 계열 미들웨어 인증 우회 표면 자체가 존재하지 않음.
- **injection_guard**: 신규 2패턴이 의도대로 매칭, 정상 한국어 문장 오탐 0(신규 패턴 기준 — 기존 패턴의 오탐 2건은 QA의 m-3 참고), 5,000회 반복 입력에도 8ms 이하(ReDoS 없음).
- **보완통제**: `a178ec2`의 `AnomalyAlertMiddleware`(401/429를 IP 무관 전체 집계로 감시)가 H-1 잔존 리스크(당시 기준)의 탐지 보완재로 작동한다.
- **운영 서버 실측(2026-08-22, M-5 대응)**: `docker compose ps`에서 backend는 `8000/tcp`만 노출(호스트 매핑 없음), 호스트 `ss -tlnp`에 8000 리슨 없음, `docker compose logs backend`에 ADMIN_SESSION_SECRET 경고 0건, nginx→backend 내부 연결 정상(`/health` 200) — 전부 확인 완료.

## 6. 개인정보 처리 흐름 (legal-counsel 전달용)

- **수집**: (a) 방문 집계 — 요청자 IP를 `extract_client_ip`로 산출 (b) 관리자 로그인 시도 IP (c) 온보딩 자유 텍스트(로컬 Ollama 추론, 국외이전 없음).
- **저장**: `visit_ip_hash()` = HMAC-SHA256(비밀키, 라벨+IP) 앞 16자 **가명 지문만** 저장(일자/시간/폴딩 경로와 함께). **원본 IP 미저장**, 키 미설정 시 집계 중단(fail-closed). 관리자 로그는 `ip_hash`만 기록.
- **이번 패치의 영향**: 신뢰되지 않는 peer일 때 해시 입력이 "위조된 XFF 값" → "실제 소켓 IP"로 바뀐다. **수집 항목·저장 형태·보관 기간은 변동 없음.** 다만 위조 헤더로 흩어지던 지문이 실제 접속자 기준으로 모이므로 통계 정확도가 올라가고, 가명정보의 연결성이 소폭 상승한다(여전히 비가역 해시).
- **전송**: Slack 알림에 원본 IP 미포함(이상행동 알림은 건수만, 관리자 로그는 ip_hash). 신규 CI 알림에는 개인정보 없음(취약점 건수 + 저장소 URL).
- **legal 확인 요청 2건**: ① 레이트리밋 초과 시 애플리케이션 로그(`docker logs`)에 `client=<IP원본>`이 WARNING으로 남는다(기존 동작, 이번 패치로 값이 "실제 IP"로 정확해짐) — 로그 보관·접근통제 관점에서 문제 없는지. ② 방문 집계 가명 지문의 **파기(보관기간) 정책**은 이번 변경 범위 밖이라 확인하지 못했다.

## 7. 최종 판정: 승인 (조건 이행 완료)

- **Critical 0건 → 3차 게이트(보안) 통과.**
- 이 보고서가 배포 전 조건으로 걸었던 항목 전부 처리 완료: ① H-1(uvicorn `--no-proxy-headers` + 루프백 제외) ② M-1(RFC1918 화이트리스트 + 추가 축소 opt-in) ③ M-2(감사 대상 requirements.txt로 정정) ④ M-3(fail-open 제거) ⑤ M-4(알람 피로 기준선 도입) — **4차 감사 항목은 이제 "종결" 표시 가능**: 같은 방식(로컬에서 backend에 직접 붙기)으로 재시험해도 loopback이 더 이상 신뢰되지 않아 우회되지 않는다.
- QA 검증(04-qa-report-xff-hardening-2026-08-22.md)이 별도로 요구한 M-5(운영 실측)도 처리 완료(§5 참고).

---

## 다음 부서가 알아야 할 것 (핸드오프)

1. **backend-engineer**: H-1/M-1/M-2/M-3/M-4 전부 이 보고서 이후 커밋에서 처리됨. 남은 건 L-1(TestClient deprecation 추적)·L-5(sdist 실행 위험, 저위험) 뿐 — 급하지 않음.
2. **qa-reviewer**: m-1(verify 스크립트 엣지케이스 9종)·m-2(CI 미배선)는 QA 보고서에 상세 — 다음 스프린트 권고.
3. **legal-counsel**: 수집·저장 항목 변화는 없고 IP는 여전히 HMAC 가명 지문만 저장된다. 다만 ① 429 로그에 원본 IP가 남는 점 ② 방문 집계 지문의 보관·파기 기간 두 가지만 확인해달라.
