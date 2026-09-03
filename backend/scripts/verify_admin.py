"""부록 T 스텁 검증 — 관리자 인증·운영 API 전 경로를 임시 DB 로 인메모리 실행.

    cd backend && py scripts/verify_admin.py

## 왜 2단계(phase)로 나뉘어 있나
"ADMIN_PASSWORD_HASH 미설정이면 관리자 기능이 **존재하지 않는다**"는 것은 `app.main` 을
import 하는 **순간**에 결정된다(라우터 등록 여부). 한 프로세스에서 두 상태를 모두 볼 수 없으므로:

  phase A (기본 실행): 해시 없이 import → /api/v1/admin/* 404 · OpenAPI 미노출 확인
                        → 그 다음 자기 자신을 phase B 로 재실행
  phase B (자식 프로세스): 임시 해시를 env 에 주입해 import → 인증·운영 API 전체 검증

## 비밀번호에 대하여
이 스크립트는 실행할 때마다 `secrets.token_urlsafe` 로 **일회용 임시 비밀번호**를 만들어
자식 프로세스 환경에만 넣는다. 파일·저장소·로그 어디에도 남지 않으며, 대표의 실제
비밀번호와는 아무 관계가 없다(실제 비밀번호는 `scripts/make_admin_hash.py` 로 대표만 만든다).
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import uuid

# 2026-09-03 — 공유 코스 검증은 시드에 실제로 있는 스팟 id를 써야 한다. 2026-08-20부터
# rebuild_course_for_store(strict=True)가 없는 스팟을 400 INVALID_COURSE로 거부한다
# (이 스크립트는 CI가 2026-09-02에 생기기 전까지 안 돌아서 그때 깨진 걸 몰랐다).
def _real_spot_ids(n: int = 2) -> list[int]:
    from app.deps import get_spot_repository
    return [s.id for s in get_spot_repository().all_spots()[:n]]
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Windows 기본 콘솔 코덱(cp949)은 em dash 등을 인코딩하지 못해 검증이 UnicodeEncodeError 로
# 죽는다. 검증 스크립트가 검증 대상이 아닌 이유로 실패하지 않게 출력 인코딩을 고정한다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover - 리다이렉트된 스트림
        pass

PHASE = os.environ.get("_VERIFY_ADMIN_PHASE", "A")
# B5.5(고객문의)는 로그인 세션이 필요하다. UserAuth.enabled 가 세션 서명키(USER_SESSION_SECRET)
# 유무로 켜지므로, CI처럼 시크릿이 없는 환경에서는 401만 나온다 — verify_auth.py와 같은 임시값을 준다.
os.environ.setdefault("USER_SESSION_SECRET", "verify-session-secret-not-for-prod")

# !!! import 전에 !!! 임시 Postgres 스키마 주입(개발용 실데이터를 건드리지 않게 —
# 2026-08-17 PostgreSQL 전환으로 tempfile SQLite 파일 방식에서 바뀌었다). phase B는
# 자식 프로세스라 env로 이미 격리된 DATABASE_URL을 물려받는다(아래 phase A 분기 참고) —
# 여기서는 phase A(부모, 최초 실행)일 때만 새로 만든다.
from _pg_test_helpers import drop_schema, isolated_database_url  # noqa: E402

_BASE_DSN = ""
_SCHEMA = ""
if PHASE == "A":
    # 부모(phase A) — 새 스키마를 만들고, phase B(자식)에게는 아래에서 별도 스키마를 만들어 넘긴다.
    _ISOLATED_DSN, _BASE_DSN, _SCHEMA = isolated_database_url()
    os.environ["DATABASE_URL"] = _ISOLATED_DSN
# phase B(자식)는 부모가 env["DATABASE_URL"]에 이미 격리된 값을 넣어 넘겨준다(아래 참고) —
# 여기서 새로 만들지 않는다(같은 스키마를 두 프로세스가 공유하면 서로의 상태가 섞인다).

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def summary(label: str) -> int:
    print(f"\n{'-' * 66}")
    print(f"{label}: {len(PASS)}/{len(PASS) + len(FAIL)} PASS")
    if FAIL:
        print("실패 항목:")
        for f in FAIL:
            print(f"  - {f}")
    return 1 if FAIL else 0


# ==========================================================================
# phase A — 관리자 미설정 상태
# ==========================================================================
def phase_a() -> int:
    os.environ.pop("ADMIN_PASSWORD_HASH", None)

    from fastapi.testclient import TestClient

    from app.config import settings
    from app.deps import get_database
    from app.main import app

    client = TestClient(app)

    section("A. ADMIN_PASSWORD_HASH 미설정 → 관리자 기능 전면 비활성")

    check("설정 기본값: admin_password_hash 비어 있음", settings.admin_password_hash == "")
    check("설정 기본값: ADMIN_COOKIE_SECURE 기본 true", settings.admin_cookie_secure is True)
    check("설정 기본값: CORS allow_credentials 기본 false", settings.cors_allow_credentials is False)

    r = client.post("/api/v1/admin/login", json={"password": "anything"})
    check("POST /admin/login → 404(존재하지 않는 경로)", r.status_code == 404, str(r.status_code))
    check("404 본문이 FastAPI 기본형(관리자 기능 존재 미노출)",
          r.json() == {"detail": "Not Found"}, r.text[:80])

    for path in ("/api/v1/admin/me", "/api/v1/admin/stats", "/api/v1/admin/reviews"):
        r = client.get(path)
        check(f"GET {path} → 404", r.status_code == 404, str(r.status_code))

    spec = client.get("/openapi.json").json()
    admin_paths = [p for p in spec.get("paths", {}) if "/admin" in p]
    check("OpenAPI 에 admin 경로 미노출", admin_paths == [], str(admin_paths))

    r = client.get("/api/v1/health")
    check("기존 공개 API 무회귀(/api/v1/health 200)", r.status_code == 200, str(r.status_code))

    # 인증 프리미티브 단위 검증(서버 기동 불필요).
    from app.security.admin_auth import (
        AdminAuth,
        make_password_hash,
        parse_password_hash,
        verify_password,
    )

    pw = secrets.token_urlsafe(16)
    h = make_password_hash(pw)
    params = parse_password_hash(h)
    check("make/parse/verify 왕복 성공", params is not None and verify_password(pw, params))
    check("틀린 비밀번호 거부", params is not None and not verify_password(pw + "x", params))
    check("해시 문자열에 평문 미포함", pw not in h)
    for bad in ("", "plain-text", "scrypt$0$8$1$AAAA$BBBB", "scrypt$16384$8$1$short$x",
                "bcrypt$16384$8$1$AAAAAAAAAAAA$AAAAAAAAAAAAAAAAAAAAAA", h.replace("$", ":")):
        check(f"잘못된 해시 형식 거부: {bad[:24]!r}", parse_password_hash(bad) is None)

    disabled = AdminAuth(password_hash=None)
    check("해시 없으면 AdminAuth.enabled=False", disabled.enabled is False)
    check("해시 없으면 어떤 토큰도 거부", disabled.verify_token("v1.aaa.bbb") is None)
    broken = AdminAuth(password_hash="scrypt$broken")
    check("형식 오류는 misconfigured 로 표시(비활성 유지)",
          broken.enabled is False and broken.misconfigured is True)

    auth = AdminAuth(password_hash=h, session_secret=None)
    token, exp = auth.issue_token()
    check("토큰 발급/검증 왕복", auth.verify_token(token) == exp)
    check("변조 토큰 거부", auth.verify_token(token[:-2] + ("aa" if not token.endswith("aa") else "bb")) is None)
    check("서명 없는 토큰 거부", auth.verify_token("v1.YWJj") is None)
    expired, _ = auth.issue_token(ttl_sec=-10)
    check("만료 토큰 거부", auth.verify_token(expired) is None)
    other = AdminAuth(password_hash=make_password_hash(secrets.token_urlsafe(16)))
    check("다른 비밀번호(해시)로 발급된 토큰 거부", other.verify_token(token) is None)
    check("ip_hash 는 원본 IP 를 담지 않는다",
          "1.2.3.4" not in auth.ip_hash("1.2.3.4") and len(auth.ip_hash("1.2.3.4")) == 16)
    check("ip_hash 는 키에 종속(다른 서버는 다른 값)",
          auth.ip_hash("1.2.3.4") != other.ip_hash("1.2.3.4"))
    check("actor_hash 8자 + 원본 미포함",
          len(auth.actor_hash("device-abcdef123456")) == 8
          and "device-abcdef123456" not in auth.actor_hash("device-abcdef123456"))

    from app.middleware.rate_limit import BUCKET_ADMIN, BUCKET_DEFAULT, resolve_bucket

    check("레이트리밋: POST /admin/login → admin 버킷",
          resolve_bucket("POST", "/api/v1/admin/login") == BUCKET_ADMIN)
    check("레이트리밋: 관리자 목록 조회는 default 버킷(운영 불가 방지)",
          resolve_bucket("GET", "/api/v1/admin/reviews") == BUCKET_DEFAULT)
    check("레이트리밋: 기존 버킷 판정 무회귀",
          resolve_bucket("POST", "/api/v1/reviews") == "ugc"
          and resolve_bucket("POST", "/api/v1/tips/personalized") == "llm"
          and resolve_bucket("GET", "/health") is None)

    rc = summary("phase A")

    # --- phase B 를 자식 프로세스로 실행 -------------------------------------
    section("B. ADMIN_PASSWORD_HASH 설정 상태 (자식 프로세스)")
    temp_password = secrets.token_urlsafe(18)  # 일회용. 대표의 실제 비밀번호와 무관.
    env = dict(os.environ)
    env["_VERIFY_ADMIN_PHASE"] = "B"
    env["ADMIN_PASSWORD_HASH"] = make_password_hash(temp_password)
    env["_VERIFY_ADMIN_PW"] = temp_password
    env["ADMIN_COOKIE_SECURE"] = "false"  # 테스트 클라이언트는 http:// 라 Secure 쿠키를 보관하지 않는다
    # phase B 전용 별도 스키마 — phase A와 같은 걸 공유하면 두 프로세스의 상태가 섞인다.
    _b_isolated_dsn, _b_base_dsn, _b_schema = isolated_database_url()
    env["DATABASE_URL"] = _b_isolated_dsn
    sys.stdout.flush()  # 자식 출력과 섞이지 않게(파이프 버퍼링)
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve())], env=env)
    drop_schema(_b_base_dsn, _b_schema)
    get_database().close()
    drop_schema(_BASE_DSN, _SCHEMA)
    print(f"\n총계: phase A {'PASS' if rc == 0 else 'FAIL'} · phase B "
          f"{'PASS' if proc.returncode == 0 else 'FAIL'}")
    return rc or proc.returncode


# ==========================================================================
# phase B — 관리자 설정 상태
# ==========================================================================
# 부록 V(2026-08-09): 관리자 표시 이름. 셋이 같은 비밀번호를 공유하므로 "누가 했는지"를
# 남기기 위해 로그인 시 이름을 고르고, 그 값을 **세션 토큰 안에 서명해** 넣는다.
OPERATOR = "지훈"


def phase_b() -> int:
    password = os.environ["_VERIFY_ADMIN_PW"]

    import logging

    from fastapi.testclient import TestClient

    from app.deps import get_admin_auth, get_admin_login_limiter, get_database
    from app.main import app

    # 모든 로그를 가로채 비밀번호·토큰 문자열이 새는지 확인한다.
    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                captured.append(record.getMessage() % () if False else record.getMessage())
            except Exception:  # noqa: BLE001
                captured.append(str(record.msg))

    root = logging.getLogger()
    handler = _Capture()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    client = TestClient(app)
    auth = get_admin_auth()

    def reset_login_quota() -> None:
        get_admin_login_limiter.cache_clear()

    section("B1. 로그인 실패 · 브루트포스")

    check("관리자 기능 활성화됨", auth.enabled is True)

    spec = client.get("/openapi.json").json()
    admin_paths = sorted(p for p in spec.get("paths", {}) if "/admin" in p)
    # login/logout/me + reviews(목록)·reviews/{id}(삭제)·hide·unhide + courses 4종 + stats = 12
    # 14 = 12(부록 T) + /admin/operators(부록 V) + /admin/traffic(부록 X 트래픽 집계).
    # 16 = 14 + /admin/inquiries(목록)·/admin/inquiries/{id}/reply(답변, 2026-08-18 추가).
    # 18 = 16 + /admin/users(회원 탭)·/admin/server-status(서버 상태 탭, 둘 다 2026-08-24 추가).
    check("OpenAPI 에 admin 경로 18개 노출", len(admin_paths) == 18, str(admin_paths))

    r1 = client.post("/api/v1/admin/login", json={"password": "wrong-password"})
    check("틀린 비밀번호 → 401", r1.status_code == 401, str(r1.status_code))
    check("401 봉투 code=UNAUTHORIZED", r1.json()["error"]["code"] == "UNAUTHORIZED", r1.text[:120])
    check("실패 응답에 Set-Cookie 없음", "set-cookie" not in {k.lower() for k in r1.headers})

    r2 = client.post("/api/v1/admin/login", json={"password": ""})
    check("빈 비밀번호도 동일한 401(형식 힌트 미노출)",
          r2.status_code == 401 and r2.json() == r1.json(), str(r2.status_code))

    r3 = client.post("/api/v1/admin/login", json={"password": password[:-1]})
    check("한 글자 다른 비밀번호도 동일한 401 본문", r3.json() == r1.json())

    # 위 3회 + 2회 = 5회 소진 → 6회째 429
    r4 = client.post("/api/v1/admin/login", json={"password": "x1"})
    r5 = client.post("/api/v1/admin/login", json={"password": "x2"})
    r6 = client.post("/api/v1/admin/login", json={"password": "x3"})
    check("4·5회째는 아직 401", r4.status_code == 401 and r5.status_code == 401,
          f"{r4.status_code}/{r5.status_code}")
    check("6회째 → 429 RATE_LIMITED",
          r6.status_code == 429 and r6.json()["error"]["code"] == "RATE_LIMITED", str(r6.status_code))
    check("429 에 Retry-After 헤더", "retry-after" in {k.lower() for k in r6.headers})

    r7 = client.post("/api/v1/admin/login", json={"password": password, "operator": OPERATOR})
    check("한도 소진 상태에서는 정답 비밀번호도 429(추측 속도 차단)", r7.status_code == 429,
          str(r7.status_code))

    section("B2. 로그인 성공 · 세션 쿠키")

    reset_login_quota()
    r = client.post("/api/v1/admin/login", json={"password": password, "operator": OPERATOR})
    check("정답 비밀번호 → 200", r.status_code == 200, str(r.status_code))
    body = r.json()
    check("응답 authenticated=true + expires_at", body.get("authenticated") is True and body.get("expires_at"))
    raw_cookie = r.headers.get("set-cookie", "")
    check("Set-Cookie 발급", auth.cookie_name in raw_cookie, raw_cookie[:60])
    check("HttpOnly 속성", "httponly" in raw_cookie.lower())
    check("SameSite=Lax 속성", "samesite=lax" in raw_cookie.lower())
    check("Path=/ 속성", "path=/" in raw_cookie.lower())
    check("Max-Age 4시간(Mn-1)", "max-age=14400" in raw_cookie.lower(), raw_cookie[:120])
    check("응답 바디에 토큰 미포함(HttpOnly 의미 유지)", auth.cookie_name not in r.text and "token" not in r.text)
    check("쿠키 값에 비밀번호 미포함", password not in raw_cookie)

    cookie_value = client.cookies.get(auth.cookie_name)
    check("클라이언트가 쿠키 보관", bool(cookie_value))

    r = client.get("/api/v1/admin/me")
    check("GET /admin/me 200(세션 유효)", r.status_code == 200, str(r.status_code))

    section("B2-V. 표시 이름(부록 V) — 책임 추적")

    from app.config import settings as _settings
    if _settings.admin_operators:
        check("세션 토큰 안에 이름이 서명돼 있다",
              auth.token_operator(cookie_value) == OPERATOR,
              repr(auth.token_operator(cookie_value)))
        # 쿠키를 뜯어 이름만 바꾸려 하면 서명이 깨져 세션 자체가 무효가 된다.
        bad_sig = cookie_value[:-3] + ("aaa" if not cookie_value.endswith("aaa") else "bbb")
        check("서명 변조 → 이름 추출 불가", auth.token_operator(bad_sig) == "")
        check("서명 변조 → 세션 무효", auth.verify_token(bad_sig) is None)
        # 목록에 없는 이름은 비밀번호가 맞아도 401 (요청을 손으로 조작했다는 뜻)
        probe = TestClient(app)
        reset_login_quota()
        rx = probe.post("/api/v1/admin/login",
                        json={"password": password, "operator": "없는사람"})
        check("목록에 없는 이름 → 401", rx.status_code == 401, str(rx.status_code))
        check("실패 시 쿠키 미발급", not probe.cookies.get(auth.cookie_name))
        # 이름을 아예 빼고 보내는 것도 막는다 — 생략으로 책임 추적을 피할 수 없어야 한다.
        reset_login_quota()
        ry = probe.post("/api/v1/admin/login", json={"password": password})
        check("이름 생략 → 401", ry.status_code == 401, str(ry.status_code))
        reset_login_quota()
    else:
        check("ADMIN_OPERATORS 미설정 → 이름 검사 생략(무회귀)", True)

    section("B3. 무인증 · 변조 · 만료 접근 차단")

    protected = [
        ("GET", "/api/v1/admin/me"),
        ("GET", "/api/v1/admin/stats"),
        ("GET", "/api/v1/admin/reviews"),
        ("GET", "/api/v1/admin/courses"),
        ("POST", "/api/v1/admin/reviews/1/hide"),
        ("POST", "/api/v1/admin/reviews/1/unhide"),
        ("DELETE", "/api/v1/admin/reviews/1"),
        ("POST", "/api/v1/admin/courses/ABCDEFGH/hide"),
        ("POST", "/api/v1/admin/courses/ABCDEFGH/unhide"),
        ("DELETE", "/api/v1/admin/courses/ABCDEFGH"),
        ("GET", "/api/v1/admin/inquiries"),
        ("POST", "/api/v1/admin/inquiries/1/reply"),
    ]
    anon = TestClient(app)
    ok = True
    for method, path in protected:
        rr = anon.request(method, path)
        if rr.status_code != 401 or rr.json()["error"]["code"] != "UNAUTHORIZED":
            ok = False
            print(f"      · {method} {path} → {rr.status_code}")
    check(f"쿠키 없이 보호 엔드포인트 {len(protected)}개 전부 401", ok)

    tampered = TestClient(app)
    bad = cookie_value[:-3] + ("aaa" if not cookie_value.endswith("aaa") else "bbb")
    tampered.cookies.set(auth.cookie_name, bad)
    r = tampered.get("/api/v1/admin/stats")
    check("서명 변조 쿠키 → 401", r.status_code == 401, str(r.status_code))

    expired_client = TestClient(app)
    expired_token, _ = auth.issue_token(ttl_sec=-60)
    expired_client.cookies.set(auth.cookie_name, expired_token)
    r = expired_client.get("/api/v1/admin/stats")
    check("만료 쿠키 → 401", r.status_code == 401, str(r.status_code))

    fake_client = TestClient(app)
    fake_client.cookies.set(auth.cookie_name, "v1.YWRtaW4.YWRtaW4")
    r = fake_client.get("/api/v1/admin/stats")
    check("임의 문자열 쿠키 → 401", r.status_code == 401, str(r.status_code))

    device_client = TestClient(app)
    r = device_client.get("/api/v1/admin/stats", headers={"X-Device-Id": "abcdefgh12345678"})
    check("X-Device-Id 로는 관리자가 될 수 없다 → 401", r.status_code == 401, str(r.status_code))

    section("B4. 리뷰 운영 (숨김/복구/삭제 + 공개 API 반영)")

    dev_a = {"X-Device-Id": f"dev-a-{uuid.uuid4().hex[:12]}"}
    dev_b = {"X-Device-Id": f"dev-b-{uuid.uuid4().hex[:12]}"}
    target = {"target_type": "spot", "target_id": "126508"}
    rid_a = client.post("/api/v1/reviews", json={**target, "nickname": "여행자A", "rating": 5,
                                                 "comment": "조용하고 좋았어요"},
                        headers=dev_a).json()["review"]["id"]
    rid_b = client.post("/api/v1/reviews", json={**target, "nickname": "여행자B", "rating": 1,
                                                 "comment": "광고글입니다"},
                        headers=dev_b).json()["review"]["id"]
    client.post(f"/api/v1/reviews/{rid_b}/report", json={"reason": "광고"}, headers=dev_a)

    r = client.get("/api/v1/admin/reviews", params={"status": "all", "sort": "recent"})
    check("GET /admin/reviews 200", r.status_code == 200, str(r.status_code))
    items = r.json()["items"]
    check("관리자 목록에 2건", r.json()["total"] == 2, str(r.json()["total"]))
    check("응답에 device_id 미노출", "device_id" not in r.text)
    check("author_hash 8자 제공", all(len(i["author_hash"]) == 8 for i in items), str(items[:1]))
    check("작성자가 다르면 author_hash 도 다름",
          items[0]["author_hash"] != items[1]["author_hash"])
    check("report_count 반영",
          {i["id"]: i["report_count"] for i in items}.get(rid_b) == 1, str(items))

    r = client.get("/api/v1/admin/reviews", params={"status": "reported"})
    check("status=reported 는 신고된 1건만", r.json()["total"] == 1 and r.json()["items"][0]["id"] == rid_b)

    r = client.post(f"/api/v1/admin/reviews/{rid_b}/hide")
    check("POST /admin/reviews/{id}/hide 200", r.status_code == 200, str(r.status_code))
    check("응답 hidden=true", r.json()["hidden"] is True, r.text[:120])

    pub = client.get("/api/v1/reviews", params=target)
    ids = [i["id"] for i in pub.json()["items"]]
    check("공개 목록에서 숨김 리뷰 제외", rid_b not in ids and rid_a in ids, str(ids))
    check("공개 요약 평균도 숨김 반영", pub.json()["summary"]["count"] == 1, str(pub.json()["summary"]))

    r = client.get("/api/v1/admin/reviews", params={"status": "hidden"})
    check("status=hidden 으로 숨김 리뷰 조회 가능", r.json()["total"] == 1 and r.json()["items"][0]["hidden"] is True)

    r = client.post(f"/api/v1/admin/reviews/{rid_b}/unhide")
    check("unhide 200 + hidden=false", r.status_code == 200 and r.json()["hidden"] is False)
    pub = client.get("/api/v1/reviews", params=target)
    check("복구 후 공개 목록에 다시 노출", rid_b in [i["id"] for i in pub.json()["items"]])

    r = client.delete(f"/api/v1/admin/reviews/{rid_b}")
    check("DELETE /admin/reviews/{id} 200 + deleted", r.status_code == 200 and r.json()["deleted"] is True)
    pub = client.get("/api/v1/reviews", params=target)
    check("삭제 후 공개 목록 1건", pub.json()["total"] == 1, str(pub.json()["total"]))
    r = client.delete(f"/api/v1/admin/reviews/{rid_b}")
    check("없는 리뷰 삭제 → 404 NOT_FOUND",
          r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND", str(r.status_code))
    r = client.post("/api/v1/admin/reviews/999999/hide")
    check("없는 리뷰 숨김 → 404", r.status_code == 404, str(r.status_code))

    section("B5. 공유 코스 운영")

    code = client.post("/api/v1/courses/share",
                       json={"nickname": "코스장인", "title": "해운대 반나절",
                             "course": {"spots": [{"id": sid} for sid in _real_spot_ids(2)]}},
                       headers=dev_a).json()["share_code"]

    r = client.get("/api/v1/admin/courses", params={"status": "all"})
    check("GET /admin/courses 200 + 1건", r.status_code == 200 and r.json()["total"] == 1, str(r.status_code))
    check("코스 응답에 device_id 미노출", "device_id" not in r.text)
    check("코스 응답에 payload 미포함(목록 경량)", "course" not in r.text)

    r = client.post(f"/api/v1/admin/courses/{code}/hide")
    check("코스 hide 200", r.status_code == 200 and r.json()["hidden"] is True, str(r.status_code))
    check("숨긴 코스는 공개 피드에서 제외",
          client.get("/api/v1/courses/shared").json()["total"] == 0)
    check("숨긴 코스 상세 → 404", client.get(f"/api/v1/courses/shared/{code}").status_code == 404)
    check("소문자 코드로도 관리자 조작 가능(정규화)",
          client.post(f"/api/v1/admin/courses/{code.lower()}/unhide").status_code == 200)
    check("복구 후 공개 피드 노출", client.get("/api/v1/courses/shared").json()["total"] == 1)
    r = client.delete(f"/api/v1/admin/courses/{code}")
    check("코스 삭제 200", r.status_code == 200 and r.json()["deleted"] is True)
    check("삭제 후 공개 피드 0건", client.get("/api/v1/courses/shared").json()["total"] == 0)
    r = client.post("/api/v1/admin/courses/ZZZZZZZZ/hide")
    check("없는 코스 → 404", r.status_code == 404, str(r.status_code))
    r = client.post("/api/v1/admin/courses/@@@/hide")
    check("형식 위반 코드 → 404(존재 여부 미노출)", r.status_code == 404, str(r.status_code))

    section("B5.5. 고객문의 운영 (2026-08-18 — 대표 지시 '답변 작성 칸')")

    from app.repositories import user_repo as _user_repo
    from app.deps import get_user_auth as _get_user_auth

    user_auth = _get_user_auth()
    inquiry_user = get_database().write(
        lambda conn: _user_repo.upsert_login(
            conn,
            provider="google",
            provider_sub=f"verify-admin-{uuid.uuid4().hex[:12]}",
            email="inquiry-tester@example.com",
            email_verified=True,
            default_display_name="문의테스터",
            now_iso="2026-08-18T00:00:00+09:00",
        )
    )
    user_token, _ = user_auth.issue_token(user_id=inquiry_user["id"], email=inquiry_user["email"])
    user_client = TestClient(app)
    user_client.cookies.set(user_auth.cookie_name, user_token)

    r = user_client.post("/api/v1/inquiries", json={"message": "카카오 로그인이 안 돼요"})
    check("사용자 문의 접수 201", r.status_code == 201, str(r.status_code))
    inquiry_id = r.json()["id"]
    check("접수 직후 reply는 null", r.json()["reply"] is None, str(r.json()))

    r = client.get("/api/v1/admin/inquiries", params={"status": "new"})
    check("GET /admin/inquiries(status=new) 200 + 1건 이상",
          r.status_code == 200 and r.json()["total"] >= 1, str(r.status_code))
    found = next((i for i in r.json()["items"] if i["id"] == inquiry_id), None)
    check("목록에 방금 접수한 문의 포함 + 닉네임 표시", found is not None and found["nickname"] == "문의테스터",
          str(found))
    check("문의 응답에 message 전문 포함", found is not None and found["message"] == "카카오 로그인이 안 돼요")

    r = client.post(f"/api/v1/admin/inquiries/{inquiry_id}/reply", json={"reply": "   "})
    check("공백만 있는 답변 → 422", r.status_code == 422, str(r.status_code))

    r = client.post(f"/api/v1/admin/inquiries/{inquiry_id}/reply",
                    json={"reply": "설정 > 카카오 재연동을 시도해주세요."})
    check("POST /admin/inquiries/{id}/reply 200", r.status_code == 200, str(r.status_code))
    replied = r.json()
    check("응답 status=resolved", replied["status"] == "resolved", str(replied))
    check("응답에 replied_by(로그인 시 이름 미설정이면 빈 문자열)", "replied_by" in replied, str(replied))

    r = client.get("/api/v1/admin/inquiries", params={"status": "new"})
    check("답변 후 status=new 목록에서 제외", inquiry_id not in [i["id"] for i in r.json()["items"]])
    r = client.get("/api/v1/admin/inquiries", params={"status": "resolved"})
    check("답변 후 status=resolved 목록에 포함", inquiry_id in [i["id"] for i in r.json()["items"]])

    r = client.post("/api/v1/admin/inquiries/999999/reply", json={"reply": "안녕하세요"})
    check("없는 문의 답변 → 404", r.status_code == 404, str(r.status_code))

    r = user_client.get("/api/v1/inquiries/mine")
    check("사용자 본인 목록에서도 답변 확인 가능",
          any(i["id"] == inquiry_id and i["reply"] == "설정 > 카카오 재연동을 시도해주세요." for i in r.json()["items"]),
          str(r.json()))

    other_dev_user = get_database().write(
        lambda conn: _user_repo.upsert_login(
            conn,
            provider="google",
            provider_sub=f"verify-admin-other-{uuid.uuid4().hex[:12]}",
            email="other-tester@example.com",
            email_verified=True,
            default_display_name="다른사람",
            now_iso="2026-08-18T00:00:00+09:00",
        )
    )
    other_token, _ = user_auth.issue_token(user_id=other_dev_user["id"], email=other_dev_user["email"])
    other_client = TestClient(app)
    other_client.cookies.set(user_auth.cookie_name, other_token)
    r = other_client.get("/api/v1/inquiries/mine")
    check("남의 문의는 본인 목록에 안 보임", inquiry_id not in [i["id"] for i in r.json()["items"]])

    r = anon.post(f"/api/v1/admin/inquiries/{inquiry_id}/reply", json={"reply": "무인증"})
    check("무인증 답변 시도 → 401", r.status_code == 401, str(r.status_code))

    section("B6. 감사 로그 · 통계")

    from app.repositories import admin_repo

    db = get_database()
    actions = db.read(lambda conn: admin_repo.list_actions(conn, limit=50))
    kinds = [a["action"] for a in actions]
    expected = {"review_hide", "review_unhide", "review_delete",
                "course_hide", "course_unhide", "course_delete", "inquiry_reply"}
    check("감사 로그에 7종 동작 전부 기록", expected.issubset(set(kinds)), str(sorted(set(kinds))))
    check("감사 로그 ip_hash 기록(원본 IP 아님)",
          all(a["ip_hash"] and len(a["ip_hash"]) == 16 for a in actions))
    check("감사 로그에 원본 IP(testclient) 미포함",
          all("testclient" not in (a["ip_hash"] or "") for a in actions))
    check("실패한 조작은 기록되지 않음(트랜잭션 롤백)",
          len([a for a in actions if a["target_id"] == "999999"]) == 0)

    r = client.get("/api/v1/admin/stats")
    check("GET /admin/stats 200", r.status_code == 200, str(r.status_code))
    st = r.json()
    check("stats: reviews_total=1, courses_total=0",
          st["reviews_total"] == 1 and st["courses_total"] == 0, str(st))
    check("stats: reviews_today 카운트 동작", st["reviews_today"] == 1, str(st))
    check("stats: inquiries_total=1, inquiries_new=0(답변 완료)",
          st["inquiries_total"] == 1 and st["inquiries_new"] == 0, str(st))
    check("stats: generated_at KST", st["generated_at"].endswith("+09:00"), st["generated_at"])

    section("B7. 로그아웃 · 로그 위생")

    r = client.post("/api/v1/admin/logout")
    check("POST /admin/logout 200", r.status_code == 200, str(r.status_code))
    check("logout 시 쿠키 만료 지시",
          "max-age=0" in r.headers.get("set-cookie", "").lower(), r.headers.get("set-cookie", ""))
    r = client.get("/api/v1/admin/me")
    check("로그아웃 후 /admin/me → 401", r.status_code == 401, str(r.status_code))

    joined = "\n".join(captured)
    check("로그에 비밀번호 문자열 미출현", password not in joined)
    check("로그에 세션 토큰 미출현", cookie_value not in joined)
    check("로그에 비밀번호 해시 미출현", os.environ["ADMIN_PASSWORD_HASH"] not in joined)
    check("로그에 device_id 원본 미출현", dev_a["X-Device-Id"] not in joined)
    check("로그에 관리자 실패/성공 기록은 남음(ip_hash 형태)", "ip_hash=" in joined)

    section("B8. 무회귀 — 기존 공개 API")

    check("/api/v1/health 200", client.get("/api/v1/health").status_code == 200)
    r = client.get("/api/v1/reviews", params=target)
    check("공개 리뷰 목록 정상 + device_id 미노출",
          r.status_code == 200 and "device_id" not in r.text)
    r = client.post("/api/v1/reviews", json={**target, "nickname": "여행자C", "rating": 4},
                    headers={"X-Device-Id": f"dev-c-{uuid.uuid4().hex[:12]}"})
    check("공개 리뷰 작성 여전히 201", r.status_code == 201, str(r.status_code))

    root.removeHandler(handler)
    return summary("phase B")


if __name__ == "__main__":
    if PHASE == "B":
        raise SystemExit(phase_b())
    raise SystemExit(phase_a())
