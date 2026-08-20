# DEPLOY — 숨은길 Oracle Cloud Always Free (ARM) 배포 절차

> 작성: backend-engineer, 2026-07-31. **이 문서는 절차서일 뿐 아직 배포하지 않았다.**
> 대표가 Oracle VM 을 만든 뒤 오케스트레이터가 (a)~(g) 를 순서대로 수행한다.
>
> **원칙: 첫 이미지 빌드는 반드시 VM(ARM64) 위에서 한다.** Windows 개발 PC 는 x86_64 라
> 여기서 만든 이미지는 ARM VM 에서 실행되지 않는다(교차빌드 buildx 를 쓸 수도 있으나
> 느리고 검증 경로가 늘어난다). 개발 PC 에서는 파일만 만들고 전송한다.

구성 요약 — VM 한 대에 컨테이너 4개:

```
인터넷 :80
   │
   ▼
[nginx]  ─ /      ──▶ [frontend:3000]  Next.js 14
         └ /api/  ──▶ [backend:8000]   FastAPI (uvicorn, worker 1)
                            │
                            └────────▶ [ollama:11434]  qwen2.5:7b (CPU 추론)
```

호스트에 열리는 포트는 **80 하나뿐**이다. backend/frontend/ollama 는 도커 내부 네트워크에만
존재한다(ollama 는 인증이 없어 노출 시 즉시 남용된다).

---

## (a) VM 생성 — 선택할 값

Oracle Cloud 콘솔 → Compute → Instances → **Create instance**

| 항목 | 값 | 이유 |
|---|---|---|
| Shape | **VM.Standard.A1.Flex** (Ampere ARM) | Always Free 대상. x86 (E2.1.Micro)는 1GB RAM 이라 7B LLM 불가 |
| OCPU / Memory | **4 OCPU / 24 GB** | Always Free 한도 전량. 4개를 한 VM 에 몰아야 LLM 추론이 견딘다 |
| Image | **Canonical Ubuntu 22.04** (aarch64 빌드) | 지시서 확정값. 24.04 도 동작하나 아래 명령은 22.04 기준 |
| Boot volume | **100 GB** | Always Free 블록스토리지 200GB 내. 모델 5GB + 이미지 2GB + 시드 데이터 여유 |
| VCN / Subnet | Public subnet, **public IPv4 주소 할당** | 외부 접속용 |
| SSH key | 로컬 공개키 등록 | 비밀번호 로그인 없음 |

> **용량 부족(Out of host capacity) 에러**는 Always Free ARM 에서 흔하다. 다른 가용성 도메인
> (AD-1/2/3)으로 바꿔 재시도하거나 시간을 두고 다시 시도한다. 유료 전환 없이 해결 가능하다.

접속: `ssh -i ~/.ssh/<키> ubuntu@<VM_PUBLIC_IP>`

---

## (b) 80 포트 열기 — **두 군데 모두** 열어야 한다 (가장 흔한 함정)

### b-1. Oracle 쪽 (VCN Security List 또는 NSG)

콘솔 → Networking → VCN → 해당 Subnet → **Security List** → *Add Ingress Rules*

| 항목 | 값 |
|---|---|
| Stateless | No |
| Source CIDR | `0.0.0.0/0` |
| IP Protocol | TCP |
| Destination Port Range | `80` (나중에 HTTPS 적용 시 `443` 추가) |

### b-2. VM 내부 iptables — **여기가 진짜 함정**

Oracle 의 Ubuntu 이미지는 **기본 iptables 규칙에 `REJECT all`** 이 들어있고 22번만 열려 있다.
`ufw` 는 이 이미지에서 비활성이거나 별개 체인이라, **ufw 만 열어서는 80 이 통하지 않는다.**
반드시 iptables 규칙을 REJECT 줄 **앞에** 삽입해야 한다.

```bash
# 1) 현재 규칙과 REJECT 줄 번호 확인
sudo iptables -L INPUT --line-numbers -n
#  ... 예시 출력 ...
#  num  target     prot opt source     destination
#  1    ACCEPT     all  --  0.0.0.0/0  0.0.0.0/0   state RELATED,ESTABLISHED
#  ...
#  6    REJECT     all  --  0.0.0.0/0  0.0.0.0/0   reject-with icmp-host-prohibited
#                                                   ^^^ 이 줄 번호를 확인 (보통 6)

# 2) REJECT 줄 "앞" 번호에 80 허용 규칙 삽입 (아래 6 은 위에서 확인한 REJECT 줄 번호)
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT

# 3) 재부팅에도 유지되도록 저장
sudo netfilter-persistent save        # 없으면: sudo apt-get install -y iptables-persistent
# (저장 위치: /etc/iptables/rules.v4)

# 4) 확인 — 삽입한 ACCEPT 가 REJECT 보다 위에 있어야 한다
sudo iptables -L INPUT --line-numbers -n
```

> ufw 가 활성(`sudo ufw status` 가 active)이라면 `sudo ufw allow 80/tcp` 도 함께 실행한다.
> 두 방화벽이 공존할 수 있어 **둘 다** 확인하는 것이 안전하다.
>
> 도커는 자체적으로 `DOCKER` 체인을 INPUT 이 아닌 FORWARD/nat 에 넣기 때문에 위 INPUT 규칙과
> 충돌하지 않는다. 그래도 컨테이너를 띄운 뒤 `curl http://<VM_PUBLIC_IP>/` 로 **외부에서**
> 반드시 실검증할 것 (VM 안에서의 `curl localhost` 성공은 방화벽 통과를 증명하지 못한다).

---

## (c) Docker / Compose 설치 (Ubuntu 22.04 ARM64)

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg rsync

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
                        docker-buildx-plugin docker-compose-plugin

# sudo 없이 docker 쓰기 (로그아웃 후 재접속해야 반영)
sudo usermod -aG docker $USER
newgrp docker

docker version && docker compose version && dpkg --print-architecture   # arm64 확인
```

---

## (d) 소스 전송

개발 PC(Windows, Git Bash)에서 실행. `node_modules`/`.venv`/`.next`/시드 백업본은 제외한다
(각각 수백 MB~수 GB이고 VM 에서 새로 만든다).

```bash
cd "/c/Users/dbdls/OneDrive/바탕 화면/ai-company/projects/sumeungil-build"

rsync -avz --progress \
  -e "ssh -i ~/.ssh/<키파일>" \
  --exclude 'node_modules' \
  --exclude '.next' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'tsconfig.tsbuildinfo' \
  --exclude '.env' \
  --exclude '.env.local' \
  --exclude 'app/spots/data/*.backup-*.json' \
  backend frontend deploy \
  ubuntu@<VM_PUBLIC_IP>:/home/ubuntu/sumeungil/
```

> `.env`/`.env.local` 은 **일부러 제외**했다. 시크릿은 VM 에서 직접 입력한다((e) 참고).
> rsync 가 없으면 `scp -r` 로도 되지만 제외 목록을 못 써서 매우 느리다 — rsync 권장.
> 전송량은 대략 **15~20MB**(spots_seed.json 12.7MB 포함).

---

## (e) `.env` 작성 (VM 에서)

```bash
cd /home/ubuntu/sumeungil
cp backend/.env.production.example deploy/.env
chmod 600 deploy/.env
nano deploy/.env
```

`deploy/.env` **하나**가 (1) backend 런타임 환경변수와 (2) frontend 빌드 인자 치환에 함께 쓰인다.

반드시 채워야 하는 키 (**값은 이 문서에 적지 않는다** — 대표/기존 로컬 `.env` 에서 가져온다):

| 키 | 비고 |
|---|---|
| `PUBLIC_DATA_API_KEY` | 필수. 없으면 backend 가 부팅 즉시 종료(fail-fast) |
| `POSTGRES_DB`/`POSTGRES_USER`/`POSTGRES_PASSWORD` | 필수(2026-08-17 SQLite에서 전환). postgres 컨테이너 초기화값 |
| `DATABASE_URL` | 필수. `postgresql://<POSTGRES_USER>:<POSTGRES_PASSWORD>@postgres:5432/<POSTGRES_DB>` — 위 세 값과 **비밀번호가 일치**해야 한다(자동 치환 안 됨). 비면 리뷰·공유·로그인·온보딩·AI코스저장 전부 비활성(조회 기능은 정상) |
| `TMAP_APP_KEY` | 선택. 비우면 코스 legs 만 null 로 graceful |
| `NEXT_PUBLIC_API_BASE` | **`http://<VM_PUBLIC_IP>`** (끝에 `/api` 붙이지 않는다 — 프론트가 `/api/v1/...` 를 붙인다) |
| `NEXT_PUBLIC_TMAP_APP_KEY` | 지도 SDK 브라우저 공개키. Tmap 콘솔에서 도메인/IP 제한 필수 |
| `CORS_ORIGINS` | `http://<VM_PUBLIC_IP>` (와일드카드 `*` 금지) |
| `OLLAMA_BASE_URL` | **`http://ollama:11434`** (localhost 아님 — 컨테이너 서비스명) |
| `APP_ENV` | `production` |
| `RATE_LIMIT_ENABLED` | **`true`** (공개 배포에서는 필수. 로컬 기본값은 false) |
| `ADMIN_PASSWORD_HASH` | 선택. 관리자 콘솔을 쓸 때만. **평문이 아니라 scrypt 해시** — 아래 (h) 참고. 비우면 `/api/v1/admin/*` 자체가 없다(404) |
| `ADMIN_SESSION_SECRET` | **필수, 새로 생성**: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. 비워도 **에러 없이 폴백**한다(`JWT_SECRET_KEY` → 비밀번호 해시 파생) — 그래서 빠뜨리기 쉽다. 비우면 세션 서명키·방문 해시키가 같은 파생값을 공유해 그 값 유출이 곧 세션 위조가 된다. 기동 로그 경고로만 확인 가능 — 아래 (h-1) ②-b 참고 |
| `ADMIN_COOKIE_SECURE` | **설정하지 않는다**(기본 true). HTTPS 운영이므로 false 금지 — (h-2) 이력 참고 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | 구글 로그인. **로컬 개발용과 별도의 OAuth 클라이언트**로 발급받는다 — 아래 (h-3) 참고. 셋 중 하나라도 비면 `/api/v1/auth/google/*` 만 없다(404, 카카오와 독립) |
| `GOOGLE_REDIRECT_URI` | `https://sumeungil.co.kr/api/v1/auth/google/callback` — 구글 클라이언트의 "승인된 리디렉션 URI"와 문자 그대로 일치해야 한다 |
| `KAKAO_CLIENT_ID` / `KAKAO_CLIENT_SECRET` | 카카오 로그인(2026-08-17, 대표 지시). 아래 (i-4) 참고. 셋 중 하나라도 비면 `/api/v1/auth/kakao/*` 만 없다(404, 구글은 정상 동작) |
| `KAKAO_REDIRECT_URI` | `https://sumeungil.co.kr/api/v1/auth/kakao/callback` — 카카오 콘솔의 "Redirect URI"와 문자 그대로 일치해야 한다 |
| `FRONTEND_BASE_URL` | `https://sumeungil.co.kr`. 로그인 팝업의 postMessage 대상 오리진(구글·카카오 공용) — 와일드카드 금지 |
| `USER_SESSION_SECRET` | **필수, 로컬 값을 재사용하지 말고 새로 생성**: `py -c "import secrets; print(secrets.token_hex(32))"`. 비우면 `JWT_SECRET_KEY` 로 대체되지만, 그마저 없으면 세션 위조가 가능해진다(2026-08-17 보안검토 C-1) |
| `USER_COOKIE_SECURE` | **설정하지 않는다**(기본 true). HTTPS 운영이므로 false 금지 — `ADMIN_COOKIE_SECURE`와 동일 이유 |

> `NEXT_PUBLIC_*` 는 빌드타임에 JS 번들로 **인라인**된다. 값을 바꾸면
> `docker compose build frontend` 재빌드가 필요하다(컨테이너 재시작만으로는 안 바뀐다).

---

## (f) 기동 + 모델 pull

```bash
cd /home/ubuntu/sumeungil/deploy

# 첫 빌드는 ARM VM 에서 10~20분 걸릴 수 있다(Next 빌드가 대부분). 로그를 지켜본다.
docker compose build

docker compose up -d
docker compose ps        # 5개 다 Up 인지(postgres는 Up (healthy))
```

**모델 pull 은 최초 1회만 수동으로** (compose 에 넣지 않았다 — 기동마다 돌면 느리고,
네트워크 실패 시 부팅 자체가 막힌다):

```bash
docker compose exec ollama ollama pull qwen2.5:7b   # 약 4.7GB, 수 분 소요
docker compose exec ollama ollama list              # 목록에 보이면 성공
```

> 모델은 named volume `ollama-models` 에 남으므로 `docker compose down/up` 을 반복해도
> 다시 받지 않는다. `docker compose down -v` 는 볼륨까지 지우니 주의.

첫 추론 워밍업(선택, 응답 지연 체감 제거):

```bash
docker compose exec ollama ollama run qwen2.5:7b "안녕" --verbose
```

---

## (g) 검증 curl

### g-1. VM 안에서 (컨테이너 간 배선 확인)

```bash
cd /home/ubuntu/sumeungil/deploy

# nginx 자체
curl -i http://localhost/nginx-health

# nginx -> backend
curl -s http://localhost/health | head -c 300; echo
curl -s "http://localhost/api/v1/congestion/board" | head -c 300; echo
curl -s "http://localhost/api/v1/festivals?limit=2" | head -c 300; echo

# nginx -> frontend (HTML 200)
curl -sI http://localhost/ | head -3

# backend -> ollama (LLM 경로. 첫 호출은 모델 로딩으로 느릴 수 있다)
curl -s -X POST http://localhost/api/v1/tips/personalized \
  -H 'Content-Type: application/json' \
  -d '{"region_code":"26350"}' | head -c 400; echo
```

### g-2. 레이트 리밋 동작 확인 (RATE_LIMIT_ENABLED=true 일 때)

```bash
# 기본 버킷 120/분 — 130회 때리면 뒤쪽에 429 가 섞여야 한다
for i in $(seq 1 130); do curl -s -o /dev/null -w "%{http_code} " http://localhost/api/v1/congestion/board; done; echo

# 429 응답 봉투 형태 확인 (code=RATE_LIMITED, Retry-After 헤더)
curl -si http://localhost/api/v1/congestion/board | head -20
```

> `/health` 는 의도적으로 레이트 리밋 **면제**다(컨테이너 헬스체크/모니터링용).

### g-3. 밖에서 (방화벽 통과 확인 — 이게 진짜 검증)

개발 PC 또는 휴대폰에서:

```bash
curl -sI http://<VM_PUBLIC_IP>/ | head -3
curl -s  http://<VM_PUBLIC_IP>/api/v1/health; echo
```

브라우저로 `http://<VM_PUBLIC_IP>` 접속 후 개발자도구 Network 에서
API 요청이 `http://<VM_PUBLIC_IP>/api/v1/...` 로 나가는지 확인한다.
`localhost:8000` 으로 나간다면 `NEXT_PUBLIC_API_BASE` 를 안 넣고 빌드한 것이므로 재빌드한다.

---

## (h) 관리자(운영) 콘솔 설정 — 부록 T (2026-08-01)

> 후기·공유 코스에 광고/욕설이 올라왔을 때 **대표가 직접 숨기거나 지울 수 있는** 화면이다.
> 사용자 쪽 "로그인"(닉네임 + localStorage)과는 **완전히 분리**돼 있다 — 닉네임을 무엇으로
> 정하든 관리자가 될 수 없다.

### h-0. 설정하지 않으면 아예 없는 기능이다

`ADMIN_PASSWORD_HASH` 가 비어 있으면 백엔드는 관리자 라우터를 **등록조차 하지 않는다.**
`/api/v1/admin/*` 은 404 이고 `/docs` 에도 나타나지 않는다. 기본 비밀번호·백도어는 없다.

### h-1. 대표가 할 일 3단계

**① 개발 PC(또는 VM)에서 해시 생성 — 비밀번호는 대표만 안다**

```bash
cd backend
py scripts/make_admin_hash.py      # 비밀번호를 두 번 입력(화면에 표시되지 않음)
```

출력된 `ADMIN_PASSWORD_HASH=scrypt$...` **한 줄**을 복사한다.
- 평문 비밀번호는 파일·로그·터미널 히스토리 어디에도 남지 않는다.
- 최소 12자. 이 서비스 전용 비밀번호를 쓴다(다른 사이트와 재사용 금지).
- 출력된 해시 줄도 채팅·공개 저장소에 올리지 않는다(검증자값이다).

**② 서버 `.env` 에 붙여넣기**

```bash
cd /home/ubuntu/sumeungil/deploy
nano .env
```
```dotenv
ADMIN_PASSWORD_HASH=scrypt$16384$8$1$....$....
# ADMIN_COOKIE_SECURE 는 넣지 않는다(기본 true). HTTPS 운영이므로 false 로 내리면
# 세션 쿠키가 평문으로 흐른다 — 예전의 "HTTP 운영 중 false" 안내는 폐기됨(M-3, 2026-08-10).
```

**②-b `ADMIN_SESSION_SECRET` 생성 — 빠뜨리기 쉬운 필수 키 (2026-08-18 보안감사)**

해시만 넣어도 로그인은 **된다.** 심지어 이 키를 비워도 **에러가 나지 않고 조용히 폴백한다**
(`JWT_SECRET_KEY` → `ADMIN_PASSWORD_HASH` 파생). 그래서 "동작하니까 괜찮다"고 넘기기
가장 쉬운 키다. 비워두면 이렇게 나빠진다:

1. 관리자 세션 서명키가 `JWT_SECRET_KEY` 또는 `ADMIN_PASSWORD_HASH` 파생값이 된다 →
   그 값 한 줄이 새면 비밀번호를 몰라도 **세션 토큰을 위조**할 수 있다(키 하나가 두 역할을 겸함).
2. 방문 통계의 IP 가명화 키도 같은 파생값을 쓴다.

> **정확히 짚어둔다**: 방문 집계가 *꺼지는* 것은 `ADMIN_SESSION_SECRET`·`JWT_SECRET_KEY`·
> `ADMIN_PASSWORD_HASH` 가 **모두** 비었을 때뿐이다(그때만 fail-closed). 셋 중 하나라도
> 있으면 집계는 계속 돈다 — 즉 "안 넣으면 통계가 0 이 되니까 금방 안다"고 믿으면 안 되고,
> 아래 ③ 의 기동 경고로 확인해야 한다. 예전에 쓰던 저장소 하드코딩 폴백 키는 제거됐다
> (공개 상수를 키로 쓰면 후보 IP 대입으로 되맞출 수 있어 가명화가 성립하지 않는다).

```bash
# 대표 PC 또는 VM 어디서든 1회 생성 (값은 채팅·문서에 남기지 않는다)
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

```dotenv
ADMIN_SESSION_SECRET=<위 명령 출력 그대로>
```

> 이 값을 **나중에 바꾸면 로그인된 관리자 세션이 전부 끊긴다**(재로그인하면 끝).
> 방문 통계는 키가 바뀐 시점 이후의 ip_hash 가 달라져 그날 하루 고유 방문자 수가
> 부풀어 보일 수 있다 — 값 교체는 트래픽이 적은 시간에 한다.

**③ 반영**

```bash
docker compose up -d backend
docker compose logs --tail=20 backend | grep -i 관리자
#  "관리자 콘솔 활성화 — /api/v1/admin/* (세션 4시간, 쿠키 secure=True)" 가 보이면 성공

# ②-b 검증 — 이 경고가 **0회여야 정상**이다(출력이 비어 있으면 성공).
docker compose logs backend | grep ADMIN_SESSION_SECRET
#  "ADMIN_SESSION_SECRET 미설정 — 세션 서명키/방문 해시키가 파생값으로 동작 중.
#   운영에서는 반드시 설정할 것 (deploy/DEPLOY.md (h-1) ②-b)"
#  이 줄이 보이면 ②-b 를 빠뜨린 것이다. .env 를 고치고 `docker compose up -d backend`.
#
#  이 경고는 **기동 시 1회**만 뜬다(app/main.py `_warn_if_session_secret_derived`).
#  경고가 떠도 서비스는 정상 동작하므로 화면만 봐서는 알 수 없다 — 반드시 이 명령으로 확인할 것.
```

브라우저에서 `https://sumeungil.co.kr/ops-37878f1b71` 접속 → 비밀번호 입력.
(경로가 `/admin`이 아니라 무작위 문자열인 이유는 2026-08-18 대표 지시 — "너무 찾기 쉬운거
같아서". `frontend/app/ops-37878f1b71/page.tsx` 상단 주석 참고.)

### h-2. 쿠키 Secure 속성 이력 (참고)

2026-08-09 HTTPS(https://sumeungil.co.kr) 적용 완료. 그 전 평문 HTTP 시기에는
`ADMIN_COOKIE_SECURE=false` 가 필요했으나 **이제는 절대 넣지 않는다** — false 면
세션 쿠키가 암호화 없이 전송된다. `.env` 에 이 키가 남아 있으면 지우고
`docker compose restart backend`.

세션은 4시간 후 자동 만료된다(Mn-1, 8h→4h). 공용 PC 를 썼다면 사용 후 **로그아웃**을 누른다.

### h-3. IP 허용목록 켜기 (선택, 고정 IP 가 있을 때만)

`deploy/nginx.conf` 의 `location /api/v1/admin/` 과 `location /ops-37878f1b71` 블록에 주석 처리된
`allow`/`deny` 3줄이 있다. 내 공인 IP 를 넣고 `#` 를 지운 뒤:

```bash
curl -s https://ifconfig.me        # 내 현재 공인 IP 확인
nano deploy/nginx.conf             # 두 블록 모두 같은 IP 로 수정
docker compose restart nginx
```

> **주의**: 가정용 인터넷·LTE 는 IP 가 수시로 바뀐다. 바뀐 IP 로 접속하면 **대표 본인도 403**
> 이 되며, SSH 로 VM 에 들어가 nginx.conf 를 되돌려야 한다. 고정 IP 가 없다면 켜지 않는 편이
> 낫다 — 비밀번호(scrypt) + 로그인 5회/분 제한만으로도 1차 방어는 성립한다.

### h-4. 비밀번호 분실·유출 시 재설정

계정 복구 메일 같은 것은 없다(계정 테이블 자체가 없다). 절차는 **해시 교체 하나**다:

```bash
# 1) 개발 PC 에서 새 해시 생성
cd backend && py scripts/make_admin_hash.py

# 2) 서버 .env 의 ADMIN_PASSWORD_HASH 를 새 값으로 교체
nano /home/ubuntu/sumeungil/deploy/.env

# 3) 반영 — restart 가 아니라 up -d 다(아래 주의 참고)
cd /home/ubuntu/sumeungil/deploy && docker compose up -d backend
```

> ⚠️ **`.env` 를 고친 뒤에는 `docker compose restart` 를 쓰지 말 것.** restart 는 같은
> 컨테이너를 멈추고 다시 켜기만 해서 `env_file` 을 다시 읽지 않는다 — 새 해시가 반영되지
> 않은 채 "바꿨는데 옛 비밀번호로 계속 로그인된다"로 보인다. `up -d` 는 설정 변경을
> 감지해 컨테이너를 새로 만들므로 이때만 반영된다. (2026-08-18 정정)

- 해시를 바꾸면 **기존 세션 쿠키가 전부 즉시 무효**가 된다(토큰에 해시 지문이 들어 있다).
  세션 탈취가 의심될 때의 강제 로그아웃 절차도 이것과 동일하다.
- 관리자 기능을 통째로 잠그려면 `.env` 에서 `ADMIN_PASSWORD_HASH` 줄을 지우고 재시작한다
  (엔드포인트가 사라진다 = 404).

### h-5. 관리자 동작 기록 확인 (감사 로그)

숨김·복구·삭제는 전부 `admin_actions` 테이블에 남는다(원본 IP 는 저장하지 않고 해시만).

```bash
docker compose exec postgres psql -U sumeungil -d sumeungil -c \
  "SELECT * FROM admin_actions ORDER BY id DESC LIMIT 20;"
```

### h-6. 검증 curl (VM 안에서)

```bash
# 비활성 상태(해시 미설정)라면 404 여야 한다
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost/api/v1/admin/login \
  -H 'Content-Type: application/json' -d '{"password":"x"}'

# 활성 상태: 틀린 비밀번호는 401, 6회 연속 시도하면 429
for i in $(seq 1 6); do
  curl -s -o /dev/null -w "%{http_code} " -X POST http://localhost/api/v1/admin/login \
    -H 'Content-Type: application/json' -d '{"password":"wrong"}'
done; echo      # 401 401 401 401 401 429

# 인증 없이 운영 API 호출 → 401
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/api/v1/admin/stats
```

> 로그인 시도 한도는 IP 기준 분당 5회다(`ADMIN_LOGIN_PER_MIN`). 대표가 오타로 막혔다면
> **1분만 기다리면** 풀린다(서버 재시작도 카운터를 지운다).

---

## (i) 구글·카카오 로그인 설정 (2026-08-17, 데모 닉네임 로그인 완전 대체 — 카카오는 같은 날 추가)

> 사용자 쪽 로그인 전체를 구글·카카오 계정으로 대체한 기능이다. (h)의 관리자 콘솔과는
> 완전히 별개 — 구글·카카오로 로그인해도 관리자가 되지 않는다(둘은 다른 세션 쿠키·다른
> 서명 키를 쓴다, `security/user_auth.py` 참고). 아래 i-0~i-3은 구글, **카카오는 i-4**.

### i-0. 설정하지 않으면 아예 없는 기능이다

`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` / `USER_SESSION_SECRET`
(또는 그 대체값 `JWT_SECRET_KEY`) 중 하나라도 비면 백엔드는 `/api/v1/auth/*` 라우터를
**등록조차 하지 않는다.** 404 이고 `/docs` 에도 나타나지 않는다 — (h-0)의 관리자 콘솔과
동일한 원칙이다.

**특히 주의**: `GOOGLE_CLIENT_ID`/`SECRET` 만 채우고 `USER_SESSION_SECRET` 을 빠뜨리면
`JWT_SECRET_KEY` 로 조용히 대체되어 기능은 켜진 것처럼 보인다. 이 자체는 안전하지만
(둘 다 이미 무작위 값이라는 전제 하에), 로컬 개발용 `.env` 를 그대로 복사해 온 경우
`USER_SESSION_SECRET` 값이 **로컬과 운영이 같아지는** 문제가 생긴다 — 로컬 서버가
털리면 운영 세션도 위조 가능해진다. 운영용은 반드시 새로 생성한다(아래 i-1 ①).

### i-1. 대표가 할 일 3단계

**① 구글 OAuth 클라이언트 발급 (로컬 개발용과 별도로)**

console.cloud.google.com → API 및 서비스 → 사용자 인증 정보 → OAuth 클라이언트 ID
만들기(웹 애플리케이션):
- 승인된 자바스크립트 원본: `https://sumeungil.co.kr`
- 승인된 리디렉션 URI: `https://sumeungil.co.kr/api/v1/auth/google/callback`
  (문자 그대로 일치해야 한다 — `/auth/google` 처럼 줄여 쓰면 구글이 거부한다)

세션 서명 키도 새로 생성한다:

```bash
py -c "import secrets; print(secrets.token_hex(32))"
```

**② 서버 `.env` 에 붙여넣기**

```bash
cd /home/ubuntu/sumeungil/deploy
nano .env
```
```dotenv
GOOGLE_CLIENT_ID=...-....apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
GOOGLE_REDIRECT_URI=https://sumeungil.co.kr/api/v1/auth/google/callback
FRONTEND_BASE_URL=https://sumeungil.co.kr
USER_SESSION_SECRET=<위에서 새로 생성한 값>
# USER_COOKIE_SECURE 는 넣지 않는다(기본 true) — ADMIN_COOKIE_SECURE 와 동일 이유.
```

**③ 반영**

```bash
docker compose up -d backend
docker compose logs --tail=20 backend | grep -i 로그인
#  "구글 로그인 활성화 — /api/v1/auth/* (세션 7일, 쿠키 secure=True)" 가 보이면 성공
```

### i-2. 검증 curl (VM 안에서)

```bash
# 비활성 상태(키 미설정)라면 404 여야 한다
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/api/v1/auth/me

# 활성 상태: 로그인 없이 호출하면 200 + authenticated:false (401 아님 — 비로그인도 정상 응답)
curl -s http://localhost/api/v1/auth/me

# 로그인 시작 → 구글로 302 리다이렉트 되는지
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost/api/v1/auth/google/login?next=/"
```

실제 로그인 성공 여부(팝업 → 구글 인증 → 콜백 → 닉네임 확인)는 curl 로 확인할 수 없다 —
브라우저에서 `https://sumeungil.co.kr` 접속 후 직접 "Google로 로그인"을 눌러 확인한다.

### i-3. 계정 데이터 위치·보존

구글 로그인 계정은 `users` 테이블(2026-08-17부터 PostgreSQL, `postgres-data` named
volume — 후기·공유 코스와 같은 데이터베이스 안에 있다)에 저장된다. 저장 항목은 이메일과
사용자가 직접 정한 표시 이름뿐 — 구글 액세스 토큰은 저장하지 않는다(로그인 시
1회 조회 후 즉시 버림, `security/user_auth.py` 모듈 docstring 참고).

**계정 삭제(탈퇴)**: 로그인한 상태에서 화면 상단 "계정 삭제" 버튼(2단계 확인)을 누르면
`DELETE /api/v1/auth/me`가 호출돼 이메일·표시 이름·구글 계정 고유 식별자가 즉시
삭제되고 세션 쿠키도 함께 지워진다(2026-08-17 QA C-4 대응, `api/auth.py`). 사용자가
버튼을 못 찾거나 대신 요청하는 경우, 대표가 위 h-5 방식으로 직접 `users` 테이블에서
해당 행을 수동 삭제할 수도 있다.

### i-4. 카카오 로그인 설정 (2026-08-17, 대표 지시 — 구글 옆 간편로그인)

> 구글과 완전히 독립된 두 번째 로그인 수단이다. 같은 사람이 구글·카카오를 둘 다 쓰면
> **카카오 쪽 이메일이 검증된 상태일 때만** 자동으로 같은 계정에 통합된다 — 검증 안 된
> (또는 아예 없는) 이메일은 안전한 기본값인 별개 계정으로 떨어진다(계정 탈취 방지,
> `repositories/user_repo.py` 모듈 docstring 참고). 카카오 3개 값 중 하나라도 비어도
> **구글 로그인은 영향받지 않는다** — `/api/v1/auth/kakao/*` 만 개별적으로 404.

**① 카카오 애플리케이션 생성 + 동의항목 켜기**

developers.kakao.com → 내 애플리케이션 → 애플리케이션 추가하기:
- 앱 설정 > 요약 정보에서 **REST API 키**(=`KAKAO_CLIENT_ID`) 확인
- 앱 설정 > 플랫폼 > Web 플랫폼 등록: 사이트 도메인 `https://sumeungil.co.kr`
- 제품 설정 > 카카오 로그인 > 활성화 ON, Redirect URI에
  `https://sumeungil.co.kr/api/v1/auth/kakao/callback` 등록
  (문자 그대로 일치해야 한다)
- 제품 설정 > 카카오 로그인 > 보안 > Client Secret 발급 → 코드 상태 **"사용함"**으로 전환
  (선택 기능이지만 켜지 않으면 서버가 Client Secret 없이도 요청을 받아버려 방어가 약해진다
  — 반드시 켤 것)
- **제품 설정 > 카카오 로그인 > 동의항목** — "닉네임"은 **선택 동의**, "카카오계정
  (이메일)"은 **필수 동의**로 켠다(2026-08-17 대표 확인 — 이메일을 선택으로 두면
  대부분 사용자가 체크 해제하고 로그인해버려서 계정 통합 로직이 사실상 작동을 안
  하게 된다. 닉네임은 실명을 쓰는 사용자도 많아 선택으로 남긴다 — 코드가 닉네임
  없을 때 이메일 앞부분/"여행자"로 폴백하므로 선택이어도 기능상 문제없다). **여기서
  켜지 않으면 scope로 요청해도 사용자 정보 응답에 그 필드가 아예 안 온다** — 가장
  놓치기 쉬운 단계다.

개인 개발자는 이 단계까지만으로 실서비스(production) 전환이 가능하다 — 네이버처럼
별도 사업자등록·검수 절차가 없다(그래서 대표가 카카오를 선택했다).

**② 서버 `.env` 에 붙여넣기**

```bash
cd /home/ubuntu/sumeungil/deploy
nano .env
```
```dotenv
KAKAO_CLIENT_ID=<REST API 키>
KAKAO_CLIENT_SECRET=<Client Secret>
KAKAO_REDIRECT_URI=https://sumeungil.co.kr/api/v1/auth/kakao/callback
# FRONTEND_BASE_URL / USER_SESSION_SECRET 는 구글과 공유 — 이미 i-1 ②에서 채웠다면 그대로 둔다.
```

**③ 반영**

```bash
docker compose up -d backend
docker compose logs --tail=20 backend | grep -i 로그인
#  "로그인 활성화(구글+카카오) — /api/v1/auth/* (세션 7일, 쿠키 secure=True)" 가 보이면 성공
```

**검증 curl**

```bash
# 로그인 시작 → 카카오로 302 리다이렉트 되는지
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost/api/v1/auth/kakao/login?next=/"
```

실제 로그인 성공 여부(팝업 → 카카오 인증 → 콜백 → 닉네임 확인)는 curl 로 확인할 수 없다 —
브라우저에서 "카카오로 로그인"을 눌러 직접 확인한다. 계정 데이터 위치·삭제 절차는
i-3과 동일(같은 `users` 테이블, 같은 탈퇴 버튼).

---

## 운영 커맨드 모음

```bash
cd /home/ubuntu/sumeungil/deploy

docker compose logs -f backend          # 로그 팔로우
docker compose logs --tail=100 nginx
docker compose restart backend          # 코드 변경 없이 .env 만 반영
docker compose up -d --build backend    # 백엔드 코드 변경 반영
docker compose up -d --build frontend   # NEXT_PUBLIC_* 변경 시 반드시 build
docker compose down                     # 중지 (모델 볼륨은 보존)
docker stats                            # CPU/메모리 실시간
```

코드 업데이트 절차: 개발 PC 에서 (d) rsync 재실행 → VM 에서 `docker compose up -d --build`.

---

## 트러블슈팅

| 증상 | 원인 / 조치 |
|---|---|
| 외부에서 접속 불가, VM 안 curl 은 성공 | (b) 방화벽. **Security List 와 iptables 둘 다** 확인. iptables ACCEPT 가 REJECT 줄보다 위에 있어야 함 |
| 502 Bad Gateway | 해당 컨테이너가 죽었거나 부팅 중. `docker compose ps` / `logs backend`. backend 는 `PUBLIC_DATA_API_KEY` 없으면 즉시 종료(fail-fast)한다 |
| backend 가 계속 재시작 | `docker compose logs backend` 에 `[FATAL] 필수 환경변수` 가 있으면 `deploy/.env` 의 `PUBLIC_DATA_API_KEY` 확인 |
| 프론트가 `localhost:8000` 을 호출 | `NEXT_PUBLIC_API_BASE` 없이 빌드됨 → `.env` 수정 후 `docker compose build frontend --no-cache` |
| LLM 응답이 항상 폴백/느림 | ARM CPU 추론이 개발 PC 보다 느릴 수 있다. `docker compose logs backend` 에서 타임아웃 확인 후 `.env` 의 `TIPS_TIMEOUT_SEC` / `OLLAMA_TIMEOUT_SEC` 상향, `OLLAMA_KEEP_ALIVE=-1` 유지(모델 언로드 방지) |
| Next 빌드 중 OOM | 24GB VM 에서는 드물다. 발생 시 스왑 2GB 추가: `sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile` |
| pip 설치 중 컴파일러 오류 | aarch64 휠이 없는 패키지가 생긴 것. backend/Dockerfile 의 pip 앞에 `RUN apt-get update && apt-get install -y --no-install-recommends build-essential` 추가 |
| `/docs` 를 공개하고 싶지 않음 | `deploy/nginx.conf` 의 `location /docs`, `location = /openapi.json` 블록을 지우거나 `allow <내IP>; deny all;` 추가 후 `docker compose restart nginx` |

---

## 아직 하지 않은 것 (의도적 스코프 밖)

- **HTTPS / 도메인**: 현재는 `http://<IP>` 다. 도메인 확보 후 nginx 에 certbot(letsencrypt)을
  붙이고 443 을 (b) 양쪽에 열면 된다. 그때 `NEXT_PUBLIC_API_BASE`·`CORS_ORIGINS` 를
  `https://<도메인>` 으로 바꾸고 frontend 를 **재빌드**해야 한다.
- **자동 배포(CI/CD)**: 현재는 rsync + `up -d --build` 수동 절차다.
- **자동 백업(스케줄)**: 아래 백업 대상이 생겼지만 cron/스냅샷 자동화는 아직 없다 — 수동 절차다.

---

## 백업 (2026-08-17 갱신 — PostgreSQL 전환)

부록 R(후기·코스 공유) 도입 전까지 이 서비스는 **무상태**였다(모든 응답이 공공데이터 +
인메모리 캐시). 지금은 다르다 — 2026-08-17부터 저장소가 SQLite에서 PostgreSQL로
바뀌었다(로그인 계정·온보딩 취향 프로필·AI 코스 저장이 추가되면서).

| 볼륨 | 내용 | 유실 시 |
|---|---|---|
| `ollama-models` | qwen2.5:7b 가중치 | 다시 `ollama pull` 하면 복구됨 (백업 불필요) |
| **`postgres-data`** | **후기·공유코스·로그인 계정·온보딩 프로필·AI 코스 전부** | **복구 불가** |
| `sumeungil-data` | 과거 SQLite 파일(이관 완료 후 사실상 미사용) | 이관이 끝났다면 무해, 백업 우선순위 낮음 |

```bash
# 백업 (VM 에서) — pg_dump로 논리 백업(SQL 텍스트) 1개 파일을 만든다.
docker compose exec -T postgres pg_dump -U sumeungil -d sumeungil \
  > sumeungil-postgres-$(date +%Y%m%d).sql

# 복구
docker compose stop backend
cat sumeungil-postgres-YYYYMMDD.sql | docker compose exec -T postgres \
  psql -U sumeungil -d sumeungil
docker compose start backend
```

- `docker compose down -v` 는 `postgres-data` 볼륨까지 삭제한다. 배포 스크립트에 `-v` 를 넣지 말 것.
- 후기 기능을 급히 닫아야 하면 `.env` 에 `COMMUNITY_ENABLED=false` 후 `docker compose restart backend`
  (데이터는 남고 API 만 503 을 반환한다).
- 관리자 콘솔로 개별 글만 숨기고 싶다면 (h) 절 참고 — 기능 전체를 닫는 것보다 이쪽이 먼저다.
  `admin_actions`(감사 로그)도 같은 Postgres 안에 있으므로 위 백업에 함께 포함된다.
- 정기 자동 백업(cron)은 아직 없다 — 수동 절차다. 배포 규모가 커지면 `pg_dump`를 cron에
  등록하고 오프사이트(예: 오브젝트 스토리지)로 보내는 것을 검토할 것.

---

## 디스크 사용량 점검 (2026-08-17 갱신 — PostgreSQL 전환)

사용자가 쓴 데이터가 남는 순간부터 **디스크가 서비스 가용성의 일부**가 된다.
Postgres 도 디스크가 차면 쓰기가 실패하고, 그러면 후기·공유·로그인 관련 API 가
`503`/`500` 을 반환한다(조회 API 는 영향 없음).

서버는 스스로 상한을 지킨다(부록 R.13 보존정책: 기기당 20건 · 전체 5,000건 · 180일).
아래 점검은 "그 상한이 실제로 지켜지고 있는지"를 눈으로 확인하는 절차다 —
**한 달에 한 번이면 충분하다.**

```bash
# 1) VM 전체 여유 공간 (여기가 90% 를 넘으면 다른 것부터 정리할 것)
df -h /

# 2) Postgres 데이터 디렉터리 크기
docker compose exec postgres du -sh /var/lib/postgresql/data

# 3) 테이블별 행 수·용량 — 상한(SHARE_MAX_TOTAL) 이하인지 확인
docker compose exec postgres psql -U sumeungil -d sumeungil -c "
  SELECT relname, n_live_tup,
         pg_size_pretty(pg_total_relation_size(relid)) AS size
    FROM pg_stat_user_tables ORDER BY n_live_tup DESC;"

# 4) 정리 로그 확인 (기동 직후 + 하루 1회 실행된다)
docker compose logs backend | grep "share retention"
```

**판단 기준**

| 상황 | 조치 |
|---|---|
| Postgres 데이터 디렉터리 < 500MB | 정상 — 아무것도 하지 않는다 |
| 500MB~1GB | `.env` 의 `SHARE_MAX_TOTAL` / `SHARE_RETENTION_DAYS` 를 낮추고 `docker compose restart backend` |
| 1GB 초과 또는 `df` 90% 초과 | 위 조정 + 아래 정리. 그래도 늘면 `COMMUNITY_ENABLED=false` 로 쓰기 차단 |

> **SQLite 시절의 수동 `VACUUM` 절차는 더 이상 필요 없다.** PostgreSQL은 `autovacuum`이
> 기본 활성화돼 있어 삭제된 행의 공간을 백그라운드에서 자동 회수한다(공식 문서 기준
> 기본 설정으로 대부분의 워크로드에 충분 — 이 배포 규모에서 수동 튜닝은 불필요).

---

## 부록: 프론트를 나중에 Vercel 로 분리하는 경우

트래픽이 늘어 Next.js 렌더링이 VM CPU 를 잡아먹거나(= LLM 추론과 경합), 전 세계 CDN 이
필요해지면 프론트만 Vercel 로 떼어낼 수 있다. **백엔드 코드 변경은 필요 없다.**

1. Vercel 프로젝트 생성 → Root Directory 를 `frontend/` 로 지정 (Next.js 자동 인식).
2. Vercel 환경변수에 `NEXT_PUBLIC_API_BASE` = `https://api.<도메인>` (또는 `http://<VM_IP>`),
   `NEXT_PUBLIC_TMAP_APP_KEY` 를 넣고 배포.
3. VM 쪽 `deploy/.env` 의 `CORS_ORIGINS` 에 Vercel 도메인을 추가 → `docker compose restart backend`.
   (이때부터는 **크로스 오리진**이 되므로 CORS 설정이 실제로 동작해야 한다.)
4. `deploy/docker-compose.yml` 에서 `frontend` 서비스와 nginx 의 `location /` 블록을 제거하거나
   그대로 두어 폴백으로 유지한다.

주의 2가지:
- **브라우저 Mixed Content**: Vercel 은 HTTPS 인데 백엔드가 HTTP(`http://<VM_IP>`)면
  브라우저가 API 요청을 차단한다. 이 조합을 쓰려면 백엔드에 **먼저 HTTPS 를 붙여야 한다.**
- 레이트 리밋은 여전히 nginx→backend 경로에서 IP 기준으로 동작한다(Vercel 이 프록시가 아니라
  브라우저가 백엔드를 직접 호출하는 구조이므로 클라이언트 IP 가 그대로 보인다).

---

## HTTPS (2026-08-09 적용 완료)

도메인 `sumeungil.co.kr`(가비아) + Let's Encrypt. 인증서는 무료이고 결제 정보가 걸려 있지 않다.

| 항목 | 값 |
|---|---|
| 인증서 대상 | `sumeungil.co.kr`, `www.sumeungil.co.kr` |
| 발급 | 2026-08-09 / 만료 2026-11-07 (90일) |
| 갱신 | `certbot` 컨테이너가 12시간마다 `renew` 시도 (만료 30일 전부터 실제 갱신) |
| 갱신 반영 | `/etc/cron.d/sumeungil-nginx-reload` 가 매일 04:17 `nginx -s reload` |
| TLS | TLSv1.2 / TLSv1.3 만 허용 |
| 안내 메일 | dbdlstlr25@naver.com (폐기·만료 통지 수신) |

### 건드리면 안 되는 것

1. **80 포트를 닫지 말 것.** ACME HTTP-01 검증이 80 으로 들어온다. 닫으면 90일 뒤 갱신이 *조용히* 실패한다.
2. **`location ^~ /.well-known/acme-challenge/` 를 지우지 말 것.** 같은 이유다. 이 블록은 https 리다이렉트보다 먼저 매칭돼야 한다.
3. **`nginx.conf` 를 바꾼 뒤에는 반드시 컨테이너를 재생성**해야 한다(`docker compose up -d --force-recreate nginx`).
   단일 파일 bind mount 는 **inode 에 묶이기 때문에**, `tar`/`scp` 로 파일을 교체하면 새 inode 가 생겨
   컨테이너는 계속 옛 파일을 본다. `nginx -s reload` 만으로는 반영되지 않고, `nginx -t` 도 옛 파일을
   검사해 통과해버린다 — 2026-08-09 실제로 이 함정에 걸렸다.
4. **`NEXT_PUBLIC_API_BASE` 는 빌드타임 인라인 값**이다. 도메인이 바뀌면 `.env` 수정 후 반드시
   `docker compose build frontend` 재빌드해야 한다. 안 하면 자물쇠는 뜨는데 브라우저가
   mixed content 로 API 를 전부 차단해 화면이 빈다.

### 아직 적용하지 않은 것

- **HSTS**: 첫 자동갱신이 실제로 성공하는 것을 확인한 뒤 적용한다. 지금 켜면 갱신 실패 시
  브라우저가 http 폴백조차 거부해 사이트가 완전히 닫힌다 — 공모전 심사 기간에는 가용성이 우선이다.
- ~~탄력적 IP 연결~~ → **2026-08-09 완료**. 서버 공인 IP 는 `54.116.76.172`(탄력적)이며,
  A 레코드(`@`, `www`)도 여기를 가리킨다. 이제 인스턴스를 정지·재시작해도 IP 가 바뀌지 않는다.
  SSH 접속 주소도 `ubuntu@54.116.76.172` 다. 옛 IP `3.35.77.85` 는 반납되어 영구히 사라졌다.

### 수동 점검 명령

```bash
cd ~/sumeungil/deploy
docker compose run --rm --entrypoint certbot certbot certificates      # 만료일 확인
docker compose run --rm --entrypoint certbot certbot renew --dry-run   # 갱신 예행연습
```

---

## 관리자 콘솔 (2026-08-09 활성화)

| 항목 | 값 |
|---|---|
| 경로 | `https://sumeungil.co.kr/ops-37878f1b71` (서브도메인 아님 — CT 로그 노출 회피. 2026-08-18부터 `/admin`이 아닌 무작위 경로 — 대표 지시) |
| 인증 | `.env` 의 `ADMIN_PASSWORD_HASH` 하나 (scrypt). 관리자 3명이 공유 |
| 표시 이름 | `.env` 의 `ADMIN_OPERATORS=지훈,인식,태준` (부록 V). **2026-08-18부터 로그인 화면이 이 목록을 드롭다운으로 보여주지 않는다** — 운영자가 자기 이름을 직접 입력한다(인증 없이 열리는 API 가 운영진 명단을 광고하지 않도록. 외부 보안감사 3차). 틀린 이름은 비밀번호 오류와 같은 401 |
| 세션 서명 | `.env` 의 `ADMIN_SESSION_SECRET` (미설정 시 비밀번호 해시에서 파생 — (h-1) ②-b 참고, **반드시 채울 것**) |
| 세션 | 8시간, HttpOnly + Secure + SameSite=Lax |
| 로그인 제한 | IP 기준 분당 5회 → 초과 시 429 |

### ⚠️ `.env` 에 `$` 가 들어가는 값은 반드시 `$$` 로 쓴다

**docker compose 는 `.env` 값 안의 `$` 를 변수 치환 기호로 해석한다.**
scrypt 해시는 `scrypt$N$r$p$솔트$해시` 형식이라 `$` 가 5개 들어간다. 그대로 두면:

```
파일에 있는 값   scrypt$16384$8$1$SF5pg...$Us3QD...
컨테이너가 받는 값 scrypt$16384$8$1            ← 솔트·해시가 빈 문자열로 치환됨
```

백엔드는 `ADMIN_PASSWORD_HASH 형식이 올바르지 않습니다` 로그만 남기고 관리자 기능을
조용히 끈다. **`.env` 를 눈으로 보면 값이 멀쩡해 보여서 원인을 찾기 어렵다.**
2026-08-09 실제로 여기 걸렸다.

진단 방법 — 컨테이너가 실제로 받는 값을 확인한다(값 노출 주의):
```bash
docker compose run --rm --no-deps -T --entrypoint sh backend -c 'printenv ADMIN_PASSWORD_HASH'
```

`docker compose up` 실행 시 **`variable is not set` 경고가 뜨면 이 문제다.**
경고 메시지에 해시 조각이 그대로 찍히므로, 그 출력은 공유하지 말 것.

### 비밀번호 설정·교체

`backend/scripts/set_admin_password.py` 가 이 이스케이프를 **자동으로 처리한다**
(대상이 compose 가 읽는 `.env` 인지 판별해서 적용). 손으로 편집하지 말 것.

```bash
cd ~/sumeungil/backend && python3 scripts/set_admin_password.py
cd ~/sumeungil/deploy  && docker compose up -d backend
```

해시를 화면에 출력하지 않고 `.env` 에 직접 쓴다(백업 자동 생성). 비밀번호를 교체하면
세션 서명키가 바뀌어 **로그인해 있던 전원이 즉시 로그아웃**된다 — 팀원이 빠질 때 쓰면 된다.

### 활성화 확인

```bash
docker compose logs backend --tail 60 | grep 관리자
#  정상: 관리자 콘솔 활성화 — /api/v1/admin/* (세션 8시간, 쿠키 secure=True)
#  실패: ADMIN_PASSWORD_HASH 형식이 올바르지 않습니다 → 위 $$ 문제
#  미설정: 관리자 기능 비활성 → 라우터 미등록(404)
```
