"""구글 로그인(/api/v1/auth/*) 회귀 검증 — 2026-08-17 QA 풀검수 M-5 대응.

qa-reviewer가 지적한 대로 다른 기능(admin/community/onboarding)엔 전부 verify_*.py가
있는데 인증만 없었다. 이 파일은 그 검수에서 실제로 실행 검증한 시나리오
(security-engineer C-1/C-2/M-1 + qa-reviewer C-1~C-4/M-1~M-3)를 회귀 스위트로 남긴다.

`fastapi.testclient.TestClient`로 프로세스 안에서 실행한다(포트 바인딩·구글 실호출 없음).
`exchange_code`/`fetch_userinfo`는 monkeypatch로 가짜 응답을 준다 — **실제 구글 동의화면
→ 토큰교환 경로는 이 스크립트로 검증되지 않는다**(실크레덴셜 확보 후 실브라우저로 별도 확인).

실행:
    cd backend && py scripts/verify_auth.py
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_TMP_DB = Path(tempfile.gettempdir()) / f"sumeungil_verify_auth_{uuid.uuid4().hex[:8]}.db"
os.environ["SQLITE_PATH"] = str(_TMP_DB)
os.environ.setdefault("PUBLIC_DATA_API_KEY", "verify-only")
os.environ["GOOGLE_CLIENT_ID"] = "verify-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "verify-client-secret"
os.environ["GOOGLE_REDIRECT_URI"] = "http://localhost:8000/api/v1/auth/google/callback"
os.environ["USER_SESSION_SECRET"] = "verify-session-secret-not-for-prod"
os.environ["FRONTEND_BASE_URL"] = "http://localhost:3000"
os.environ["COMMUNITY_ENABLED"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.deps import get_database, get_user_auth  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories import user_repo  # noqa: E402
from app.security.user_auth import UserAuth  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    (PASS if cond else FAIL).append(f"{name}{(' — ' + extra) if extra else ''}")
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def dev(tag: str) -> dict[str, str]:
    return {"X-Device-Id": f"dev-{tag}-{uuid.uuid4().hex[:12]}"}


db = get_database()
auth: UserAuth = get_user_auth()


def make_login(google_sub: str, email: str, name: str) -> tuple[TestClient, dict]:
    """DB에 계정을 만들고 그 계정으로 로그인된 TestClient를 돌려준다(콜백 왕복은 생략 —
    콜백 자체는 §2에서 별도 검증한다)."""
    user = db.write(
        lambda conn: user_repo.upsert_login(
            conn,
            google_sub=google_sub,
            email=email,
            default_display_name=name,
            now_iso="2026-08-17T00:00:00+09:00",
        )
    )
    token, _ = auth.issue_token(user_id=user["id"], email=email)
    client = TestClient(app)
    client.cookies.set(auth.cookie_name, token)
    return client, user


# === 1. 세션 토큰 위조 방지 (C-1) ===================================================
section("1. 세션 토큰 위조 방지 (C-1)")

anon = TestClient(app)
r = anon.get("/api/v1/auth/me")
check("비로그인 GET /me → 200 authenticated:false", r.status_code == 200 and r.json()["authenticated"] is False, str(r.json()))

# 서명키가 빈 문자열에서 파생된 상태를 흉내낸다 — enabled가 이를 막는지 별도 프로세스로 확인.
empty_secret_auth = UserAuth(
    client_id="x", client_secret="y", redirect_uri="http://x/cb",
    session_secret="", session_ttl_sec=3600, cookie_name="c", cookie_secure=False,
)
check("USER_SESSION_SECRET 미설정 → enabled=False(라우터 자체가 안 켜짐)", empty_secret_auth.enabled is False)

# 정상 설정에서도 서명 변조 토큰은 거부되는지.
valid_client, valid_user = make_login("sub-forge", "forge@example.com", "정상사용자")
good_token = valid_client.cookies.get(auth.cookie_name)
tampered = good_token[:-4] + ("AAAA" if good_token[-4:] != "AAAA" else "BBBB")
tclient = TestClient(app)
tclient.cookies.set(auth.cookie_name, tampered)
r = tclient.get("/api/v1/auth/me")
check("서명 변조 토큰 → authenticated:false", r.json()["authenticated"] is False)


# === 2. OAuth state — 서명·만료·브라우저 바인딩·1회용 (C-3) ==========================
section("2. OAuth state 서명/만료/브라우저 바인딩/1회용 (C-3)")

state, nonce = auth.issue_state(next_path="/reviews")
check("정상 state+올바른 쿠키 nonce → next_path 반환", auth.verify_state(state, cookie_nonce=nonce) == "/reviews")
check("state는 있는데 쿠키 nonce 없음 → 거부", auth.verify_state(state, cookie_nonce=None) is None)
check("다른 브라우저(다른 nonce)의 state 재사용 → 거부", auth.verify_state(state, cookie_nonce="attacker-nonce") is None)
check("서명 위조 state(v1.aaa.bbb) → 거부", auth.verify_state("v1.aaa.bbb", cookie_nonce=nonce) is None)
check("state 자체 없음 → 거부", auth.verify_state(None, cookie_nonce=nonce) is None)

expired_state, expired_nonce = auth.issue_state(next_path="/", now=int(time.time()) - 3600)
check("만료된 state → 거부", auth.verify_state(expired_state, cookie_nonce=expired_nonce) is None)


# === 3. 오픈 리다이렉트 화이트리스트 (M-1 舊, 정규식 회귀 포함) ========================
section("3. 오픈 리다이렉트 화이트리스트")

for bad in ("//evil.com", "https://evil.com", "http://evil.com/x", "/\\evil.com"):
    s, n = auth.issue_state(next_path=bad)
    result = auth.verify_state(s, cookie_nonce=n)
    check(f"next_path={bad!r} → '/'로 강제", result == "/", repr(result))

s, n = auth.issue_state(next_path="/a/b-c_d.e")
check("정상 내부 경로는 그대로 통과", auth.verify_state(s, cookie_nonce=n) == "/a/b-c_d.e")


# === 4. 콜백 팝업 HTML — script 컨텍스트 XSS 방지 (C-2) ===============================
section("4. 콜백 팝업 script 컨텍스트 XSS 방지 (C-2)")

from app.api.auth import _js_safe_json  # noqa: E402

evil = "</script><script>alert(document.cookie)</script>"
escaped = _js_safe_json({"name": evil})
check("</script> 탈출 문자열이 이스케이프됨", "</script>" not in escaped and "\\u003c" in escaped, escaped)

line_term = "a b c"
escaped2 = _js_safe_json(line_term)
check("JS 줄종결자(U+2028/2029) 이스케이프", " " not in escaped2 and " " not in escaped2)


# === 5. display-name 사칭/정제 (기존 리뷰 파이프라인 재사용 확인) =====================
section("5. display-name 사칭 차단 · 정제 재사용")

c5, _u5 = make_login("sub-name", "name@example.com", "이름확인전")
r = c5.patch("/api/v1/auth/display-name", json={"display_name": "숨은길 운영팀"})
check("사칭 이름(운영팀) → 400", r.status_code == 400, str(r.status_code))
r = c5.patch("/api/v1/auth/display-name", json={"display_name": "<b>길동</b>"})
check("HTML 태그 제거 후 200", r.status_code == 200 and r.json()["name"] == "길동", str(r.json()))
r = c5.patch("/api/v1/auth/display-name", json={"display_name": "a" * 21})
check("21자 → 422", r.status_code == 422, str(r.status_code))
anon5 = TestClient(app)
r = anon5.patch("/api/v1/auth/display-name", json={"display_name": "x"})
check("비로그인 PATCH → 401", r.status_code == 401, str(r.status_code))
r = c5.get("/api/v1/auth/me")
check("/me 응답에 email 미포함(m-4)", "email" not in r.json() or r.json().get("email") is None, str(r.json()))


# === 6. 계정 삭제(탈퇴) — C-4 실제 구현 ==============================================
section("6. 계정 삭제(탈퇴)")

c6, u6 = make_login("sub-del", "del@example.com", "탈퇴예정")
anon6 = TestClient(app)
r = anon6.delete("/api/v1/auth/me")
check("비로그인 DELETE /me → 401", r.status_code == 401, str(r.status_code))
r = c6.delete("/api/v1/auth/me")
check("로그인 상태 DELETE /me → 204", r.status_code == 204, str(r.status_code))
remaining = db.read(lambda conn: user_repo.get_by_id(conn, u6["id"]))
check("users 테이블에서 실제로 삭제됨", remaining is None, str(remaining))
set_cookie = r.headers.get("set-cookie", "")
check("세션 쿠키도 함께 삭제 지시", "max-age=0" in set_cookie.lower(), set_cookie)


# === 7. 로그인 세션이 리뷰/코스공유 nickname을 강제하는가 (M-1 신규) =================
section("7. 로그인 세션이 커뮤니티 글쓰기 nickname을 강제 (M-1)")

c7, _u7 = make_login("sub-review", "review@example.com", "확인된이름")
r = c7.post(
    "/api/v1/reviews",
    headers=dev("m1"),
    json={"target_type": "spot", "target_id": "m1-target", "nickname": "사칭시도", "rating": 5, "comment": "t"},
)
check(
    "로그인 중 POST /reviews → 클라이언트 nickname 무시하고 세션 표시이름 사용",
    r.status_code == 201 and r.json()["review"]["nickname"] == "확인된이름",
    str(r.json()),
)

anon7 = TestClient(app)
r = anon7.post(
    "/api/v1/reviews",
    headers=dev("m1-anon"),
    json={"target_type": "spot", "target_id": "m1-target-anon", "nickname": "익명닉네임", "rating": 4, "comment": "t"},
)
check(
    "비로그인 POST /reviews → 기존처럼 클라이언트 nickname 그대로 허용(익명 리뷰 유지)",
    r.status_code == 201 and r.json()["review"]["nickname"] == "익명닉네임",
    str(r.json()),
)

r = c7.post(
    "/api/v1/courses/share",
    headers=dev("m1-share"),
    json={"nickname": "공유사칭", "title": "T", "course": {"spots": []}},
)
share_code = r.json().get("share_code")
check("로그인 중 코스 공유 생성 성공", r.status_code == 201 and share_code, str(r.text))
detail = c7.get(f"/api/v1/courses/shared/{share_code}")
check(
    "코스 공유도 세션 표시이름으로 강제됨",
    detail.status_code == 200 and detail.json()["nickname"] == "확인된이름",
    str(detail.json()),
)


# === 8. 로그아웃 ====================================================================
section("8. 로그아웃")

c8, _u8 = make_login("sub-logout", "logout@example.com", "로그아웃테스트")
r = c8.post("/api/v1/auth/logout")
check("POST /logout → 204", r.status_code == 204, str(r.status_code))
check("Content-Type이 text/html이 아님(m-2 舊)", "text/html" not in (r.headers.get("content-type") or ""), r.headers.get("content-type"))


print("\n" + "=" * 64)
print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
if FAIL:
    print("실패 항목:")
    for f in FAIL:
        print(f"  - {f}")
print(f"임시 DB: {_TMP_DB}")
try:
    _TMP_DB.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(str(_TMP_DB) + suffix).unlink(missing_ok=True)
    print("임시 DB 삭제 완료")
except OSError:
    pass  # Windows 파일 잠금 — 무해(SQLite WAL 핸들이 아직 열려 있을 뿐)

sys.exit(1 if FAIL else 0)
