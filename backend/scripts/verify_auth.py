"""구글·카카오 로그인(/api/v1/auth/*) 회귀 검증 — 2026-08-17 QA 풀검수 M-5 대응,
카카오는 같은 날 추가(§9).

qa-reviewer가 지적한 대로 다른 기능(admin/community/onboarding)엔 전부 verify_*.py가
있는데 인증만 없었다. 이 파일은 그 검수에서 실제로 실행 검증한 시나리오
(security-engineer C-1/C-2/M-1 + qa-reviewer C-1~C-4/M-1~M-3)를 회귀 스위트로 남긴다.
§9는 카카오 추가 시 설계한 계정 통합 규칙(검증된 이메일만 자동 통합)을 검증한다.

`fastapi.testclient.TestClient`로 프로세스 안에서 실행한다(포트 바인딩·실호출 없음).
`exchange_code`/`fetch_userinfo`는 monkeypatch로 가짜 응답을 준다 — **실제 구글/카카오
동의화면 → 토큰교환 경로는 이 스크립트로 검증되지 않는다**(실크레덴셜 확보 후 실브라우저로
별도 확인).

실행:
    cd backend && py scripts/verify_auth.py
"""

from __future__ import annotations

import os

# 2026-09-03 — 공유 코스 검증은 시드에 실제로 있는 스팟 id를 써야 한다. 2026-08-20부터
# rebuild_course_for_store(strict=True)가 빈/없는 스팟을 400 INVALID_COURSE로 거부한다.
def _real_spot_ids(n: int = 1) -> list[int]:
    from app.deps import get_spot_repository
    return [s.id for s in get_spot_repository().all_spots()[:n]]
import sys
import time
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# !!! import 전에 !!! 임시 Postgres 스키마를 주입한다(2026-08-17 PostgreSQL 전환 —
# tempfile SQLite 파일 방식에서 바뀌었다).
from _pg_test_helpers import drop_schema, isolated_database_url  # noqa: E402

_ISOLATED_DSN, _BASE_DSN, _SCHEMA = isolated_database_url()
os.environ["DATABASE_URL"] = _ISOLATED_DSN
os.environ.setdefault("PUBLIC_DATA_API_KEY", "verify-only")
os.environ["GOOGLE_CLIENT_ID"] = "verify-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "verify-client-secret"
os.environ["GOOGLE_REDIRECT_URI"] = "http://localhost:8000/api/v1/auth/google/callback"
os.environ["KAKAO_CLIENT_ID"] = "verify-kakao-client-id"
os.environ["KAKAO_CLIENT_SECRET"] = "verify-kakao-client-secret"
os.environ["KAKAO_REDIRECT_URI"] = "http://localhost:8000/api/v1/auth/kakao/callback"
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
    콜백 자체는 §2에서 별도 검증한다). 기존 시그니처를 유지한 구글 전용 축약형 —
    카카오 케이스는 §9가 직접 provider_upsert()를 호출한다."""
    return provider_upsert(
        provider="google", provider_sub=google_sub, email=email, name=name, email_verified=True
    )


def provider_upsert(
    *,
    provider: str,
    provider_sub: str,
    email: str | None,
    name: str,
    email_verified: bool,
    now_iso: str = "2026-08-17T00:00:00+09:00",
) -> tuple[TestClient, dict]:
    """make_login의 일반화 버전(2026-08-17 카카오 추가) — provider/이메일 검증 여부를
    직접 지정할 수 있다. §9(계정 통합 규칙)가 쓴다. now_iso는 기본 고정값(다른 절과 동일한
    재현 가능한 타임스탬프) — §10(is_new 판정)만 신규/재로그인을 구분하려고 명시적으로
    다른 값을 넘긴다(실제 시계 경과를 기다리지 않기 위해)."""
    user = db.write(
        lambda conn: user_repo.upsert_login(
            conn,
            provider=provider,
            provider_sub=provider_sub,
            email=email,
            email_verified=email_verified,
            default_display_name=name,
            now_iso=now_iso,
        )
    )
    token, _ = auth.issue_token(user_id=user["id"], email=user["email"])
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
    google_client_id="x", google_client_secret="y", google_redirect_uri="http://x/cb",
    kakao_client_id="x", kakao_client_secret="y", kakao_redirect_uri="http://x/cb",
    session_secret="", session_ttl_sec=3600, cookie_name="c", cookie_secure=False,
)
check("USER_SESSION_SECRET 미설정 → enabled=False(라우터 자체가 안 켜짐)", empty_secret_auth.enabled is False)

# 2026-08-17 카카오 추가 — enabled(세션 인프라)와 google_enabled/kakao_enabled(provider별
# 설정 여부)가 서로 독립인지 확인. 한쪽 provider만 미설정이어도 다른 쪽은 영향받지 않는다.
partial_auth = UserAuth(
    google_client_id="g", google_client_secret="g", google_redirect_uri="http://x/g",
    kakao_client_id="", kakao_client_secret="", kakao_redirect_uri="",
    session_secret="s", session_ttl_sec=3600, cookie_name="c", cookie_secure=False,
)
check("세션 시크릿만 있으면 카카오 미설정이어도 enabled=True", partial_auth.enabled is True)
check("구글 3종 설정됨 → google_enabled=True", partial_auth.google_enabled is True)
check("카카오 3종 미설정 → kakao_enabled=False", partial_auth.kakao_enabled is False)

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
    json={"nickname": "공유사칭", "title": "T", "course": {"spots": [{"id": sid} for sid in _real_spot_ids(1)]}},
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


# === 9. 카카오 로그인 — 신규 가입 · 계정 통합 규칙 (2026-08-17 카카오 추가) ============
section("9. 카카오 로그인 — 신규 가입 · 계정 통합 규칙")

# (a) 카카오 신규 가입 — 이메일 동의를 안 해도(email=None) 정상적으로 새 계정이 만들어지는지.
_c9a, kakao_new = provider_upsert(
    provider="kakao", provider_sub="kakao-new-1", email=None, name="카카오유저", email_verified=False
)
check(
    "카카오 신규 가입(이메일 없음) → 새 계정 생성",
    kakao_new["email"] is None and kakao_new["display_name"] == "카카오유저",
    str(kakao_new),
)

# 재로그인(같은 provider_sub) 시 display_name을 덮어쓰지 않는지(카카오 버전, §5 원칙 재확인).
_c9a2, kakao_relogin = provider_upsert(
    provider="kakao", provider_sub="kakao-new-1", email=None, name="다른이름으로시도", email_verified=False
)
check(
    "카카오 재로그인 → display_name 유지(원본 이름으로 안 돌아감)",
    kakao_relogin["id"] == kakao_new["id"] and kakao_relogin["display_name"] == "카카오유저",
    str(kakao_relogin),
)

# (b) 구글로 먼저 가입한 계정과 "검증된" 이메일이 같은 카카오 로그인 → 같은 user_id로 통합.
_c9b1, google_first = provider_upsert(
    provider="google", provider_sub="merge-google-sub", email="merge@example.com",
    name="구글이름", email_verified=True,
)
_c9b2, kakao_merged = provider_upsert(
    provider="kakao", provider_sub="merge-kakao-sub", email="merge@example.com",
    name="카카오이름", email_verified=True,
)
check(
    "검증된 이메일 일치 → 구글 계정과 같은 user_id로 통합",
    kakao_merged["id"] == google_first["id"],
    f"google={google_first['id']} kakao={kakao_merged['id']}",
)
check(
    "통합 시 display_name은 기존(구글) 값 유지 — 카카오 이름으로 덮어쓰지 않음",
    kakao_merged["display_name"] == "구글이름",
    str(kakao_merged),
)

# (c) 이메일이 같아도 "검증 안 됨"이면 통합하지 않고 별개 계정 — 계정 탈취 방지의 핵심 방어선.
_c9c1, google_c = provider_upsert(
    provider="google", provider_sub="unverified-google-sub", email="shared@example.com",
    name="원래주인", email_verified=True,
)
_c9c2, kakao_unverified = provider_upsert(
    provider="kakao", provider_sub="unverified-kakao-sub", email="shared@example.com",
    name="사칭시도", email_verified=False,
)
check(
    "이메일 일치해도 미검증 → 별개 계정 생성(계정 탈취 방지)",
    kakao_unverified["id"] != google_c["id"],
    f"google={google_c['id']} kakao={kakao_unverified['id']}",
)

# 이메일 자체가 없는 카카오 로그인도 마찬가지로 통합 후보에서 제외되는지(방어적 재확인).
_c9d1, google_d = provider_upsert(
    provider="google", provider_sub="noemail-google-sub", email="noemail@example.com",
    name="원래주인2", email_verified=True,
)
_c9d2, kakao_noemail = provider_upsert(
    provider="kakao", provider_sub="noemail-kakao-sub", email=None, name="이메일없음", email_verified=False
)
check(
    "이메일 없는 카카오 로그인 → 항상 별개 계정",
    kakao_noemail["id"] != google_d["id"],
    f"google={google_d['id']} kakao={kakao_noemail['id']}",
)

# 라우트 gating — 이 프로세스는 구글·카카오 둘 다 설정돼 있으니(위 os.environ) 둘 다
# 자기 provider의 인가 URL로 302 되는지 확인한다(한쪽만 미설정인 프로세스 분리 테스트는
# 배포 후 실제 .env 조합으로 curl 확인 — deploy/DEPLOY.md (i-4) 참고).
anon9 = TestClient(app)
r = anon9.get("/api/v1/auth/google/login?next=/", follow_redirects=False)
check(
    "GET /google/login → 구글 인가 URL로 302",
    r.status_code == 302 and "accounts.google.com" in r.headers.get("location", ""),
    f"{r.status_code} {r.headers.get('location')}",
)
r = anon9.get("/api/v1/auth/kakao/login?next=/", follow_redirects=False)
check(
    "GET /kakao/login → 카카오 인가 URL로 302",
    r.status_code == 302 and "kauth.kakao.com" in r.headers.get("location", ""),
    f"{r.status_code} {r.headers.get('location')}",
)


# === 10. is_new 판정 — 신규가입만 닉네임 확인, 재로그인은 매번 안 물어봄 (2026-08-18) ===
section("10. is_new 판정(created_at==last_login_at) — 신규 vs 재로그인")

_c10a, first_login = provider_upsert(
    provider="google", provider_sub="is-new-check-sub", email="isnew@example.com",
    name="첫로그인", email_verified=True, now_iso="2026-08-18T09:00:00+09:00",
)
check(
    "최초 가입 → created_at == last_login_at(is_new=True로 판정됨)",
    first_login["created_at"] == first_login["last_login_at"],
    str(first_login),
)

_c10b, second_login = provider_upsert(
    provider="google", provider_sub="is-new-check-sub", email="isnew@example.com",
    name="첫로그인", email_verified=True, now_iso="2026-08-18T09:05:00+09:00",
)
check(
    "재로그인 → created_at != last_login_at(is_new=False로 판정됨)",
    second_login["created_at"] != second_login["last_login_at"],
    str(second_login),
)
check(
    "재로그인이어도 같은 계정(user_id 불변)",
    second_login["id"] == first_login["id"],
    f"first={first_login['id']} second={second_login['id']}",
)


# === 11. K-C1/K-M1 — 미검증 이메일로 계정 탈취 안 되는지 (2026-08-18 보안검토 재작업) ===
section("11. K-C1/K-M1 — 미검증 이메일 계정 탈취 방지(security-engineer 재작업)")

# (K-C1) 공격자가 카카오로 "victim2@example.com"을 미검증 상태로 먼저 선점 시도.
_c11a, attacker_row = provider_upsert(
    provider="kakao", provider_sub="attacker-kakao-sub", email="victim2@example.com",
    name="공격자", email_verified=False,
)
check(
    "미검증 이메일로 카카오 가입 → email 컬럼엔 저장되지 않음(None)",
    attacker_row["email"] is None,
    str(attacker_row),
)

# 나중에 진짜 피해자가 같은 이메일로 "검증된" 구글 로그인.
_c11b, victim_row = provider_upsert(
    provider="google", provider_sub="victim-google-sub", email="victim2@example.com",
    name="피해자", email_verified=True,
)
check(
    "K-C1 수정 확인 — 피해자의 검증된 구글 로그인이 공격자 행과 병합되지 않고 별개 계정",
    victim_row["id"] != attacker_row["id"],
    f"attacker={attacker_row['id']} victim={victim_row['id']}",
)

# (K-M1) 검증된 이메일이 저장된 계정이, 이후 미검증/이메일없는 재로그인 한 번으로
# 지워지거나 낮은 신뢰도 값으로 덮어써지지 않아야 한다.
_c11c, stable_first = provider_upsert(
    provider="google", provider_sub="km1-stable-sub", email="stable@example.com",
    name="안정계정", email_verified=True,
)
check("K-M1 사전조건 — 최초 로그인에 검증된 이메일 저장됨", stable_first["email"] == "stable@example.com", str(stable_first))

_c11d, stable_second = provider_upsert(
    provider="google", provider_sub="km1-stable-sub", email="attacker-claim@example.com",
    name="안정계정", email_verified=False,
)
check(
    "K-M1 수정 확인 — 미검증 이메일로 재로그인해도 기존 검증된 이메일 유지(덮어쓰기 안 됨)",
    stable_second["email"] == "stable@example.com",
    str(stable_second),
)


# === 12. M-2 — 삭제된 계정의 세션으로 쓰기 요청 시 500 대신 401 (2026-08-18) ===
section("12. M-2 — 삭제된 계정 세션 재사용 시 401(FK 위반 500 방지)")

c12, u12 = provider_upsert(
    provider="google", provider_sub="deleted-account-sub", email="deleted@example.com",
    name="탈퇴예정2", email_verified=True,
)
r = c12.delete("/api/v1/auth/me")
check("계정 삭제 요청 자체는 204", r.status_code == 204, str(r.status_code))
# 삭제 후에도 c12는 예전 쿠키(서명은 유효, DB엔 이제 없는 user_id)를 그대로 들고 있다 —
# 브라우저 탭을 안 닫았거나 쿠키가 남아있는 상황을 흉내낸다.
r = c12.post("/api/v1/inquiries", json={"message": "삭제된 계정으로 문의 시도"})
check(
    "삭제된 계정의 남은 쿠키로 쓰기 요청 → 500 아니고 401",
    r.status_code == 401,
    str(r.status_code) + " " + r.text,
)


# === 13. K-m1 — 공백만 있는 문의 거부 (2026-08-18) ===
section("13. K-m1 — 공백뿐인 고객문의 거부")

c13, _u13 = provider_upsert(
    provider="google", provider_sub="inquiry-blank-sub", email="blank@example.com",
    name="공백문의테스터", email_verified=True,
)
r = c13.post("/api/v1/inquiries", json={"message": "   "})
check(
    "공백만 있는 message → 422(min_length=1은 통과하지만 strip 후 재검증)",
    r.status_code == 422,
    str(r.status_code) + " " + r.text,
)
r = c13.post("/api/v1/inquiries", json={"message": "정상 문의 내용"})
check("정상 문의는 201", r.status_code == 201, str(r.status_code))


print("\n" + "=" * 64)
print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
if FAIL:
    print("실패 항목:")
    for f in FAIL:
        print(f"  - {f}")
db.close()
drop_schema(_BASE_DSN, _SCHEMA)
print("임시 스키마 삭제 완료")

sys.exit(1 if FAIL else 0)
