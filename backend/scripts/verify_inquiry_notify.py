# -*- coding: utf-8 -*-
"""고객문의 접수 → 알림 연결(2026-09-20) 회귀 검증 — POST /api/v1/inquiries.

verify_saved_spots.py 와 같은 격리 스키마 하네스(Postgres 필요 — CI 에서 실행). 알림 자체(메일·슬랙 전송)는
verify_email_notify.py 가 본다. 여기서는 "접수되면 알림이 호출되고, 내용·문의자 정보는 넘기지 않으며,
알림이 죽어도 접수는 성공한다"만 본다.

    py scripts/verify_inquiry_notify.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from _pg_test_helpers import drop_schema, isolated_database_url  # noqa: E402

_ISOLATED_DSN, _BASE_DSN, _SCHEMA = isolated_database_url()
os.environ["DATABASE_URL"] = _ISOLATED_DSN
os.environ.setdefault("PUBLIC_DATA_API_KEY", "verify-only")
os.environ["GOOGLE_CLIENT_ID"] = "verify-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "verify-client-secret"
os.environ["GOOGLE_REDIRECT_URI"] = "http://localhost:8000/api/v1/auth/google/callback"
os.environ["USER_SESSION_SECRET"] = "verify-session-secret-not-for-prod"
os.environ["FRONTEND_BASE_URL"] = "http://localhost:3000"

from fastapi.testclient import TestClient  # noqa: E402

from app.deps import get_database, get_user_auth  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories import user_repo  # noqa: E402
from app.services import inquiry_notify  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))


db = get_database()
auth = get_user_auth()
calls: list[tuple] = []


async def fake_notify(inquiry_id, created_at, *a, **kw):
    calls.append((inquiry_id, created_at, a, kw))


def login(sub: str, email: str, name: str) -> TestClient:
    user = db.write(
        lambda conn: user_repo.upsert_login(
            conn, provider="google", provider_sub=sub, email=email, email_verified=True,
            default_display_name=name, now_iso="2026-09-20T00:00:00+09:00",
        )
    )
    token, _ = auth.issue_token(user_id=user["id"], email=user["email"], epoch=user_repo.session_epoch_of(user))
    c = TestClient(app, raise_server_exceptions=False)
    c.cookies.set(auth.cookie_name, token)
    return c


try:
    inquiry_notify.notify_new_inquiry = fake_notify
    me = login("sub-inq-1", "inq1@example.com", "문의자")

    print("\n[a] 접수 → 알림 호출")
    secret_msg = "비밀문의내용-ZZZ 제 전화번호는 010-0000-0000"
    r = me.post("/api/v1/inquiries", json={"message": secret_msg, "contact_email": "reply-to@example.com"})
    check("접수 201", r.status_code == 201, f"{r.status_code} {r.text[:120]}")
    check("알림이 1번 호출됨", len(calls) == 1, str(calls))
    if calls:
        inq_id, created_at, extra_args, extra_kw = calls[0]
        check("번호(int)와 시각(str)만 넘김", isinstance(inq_id, int) and isinstance(created_at, str) and not extra_args and not extra_kw)
        check("호출 인자에 문의 내용·문의자 이메일이 없다", "ZZZ" not in repr(calls[0]) and "example.com" not in repr(calls[0]))
        check("넘긴 번호가 저장된 문의 번호", inq_id == r.json().get("id"))

    print("\n[b] 알림이 죽어도 접수는 성공")

    async def boom(inquiry_id, created_at, *a, **kw):
        raise RuntimeError("notify down")

    inquiry_notify.notify_new_inquiry = boom
    r = me.post("/api/v1/inquiries", json={"message": "두번째 문의"})
    check("알림 예외에도 접수 201", r.status_code == 201, str(r.status_code))
    check("문의는 실제로 저장됨", len(me.get("/api/v1/inquiries/mine").json().get("items", [])) == 2)

    print("\n[c] 실패한 접수는 알림 없음")
    calls.clear()
    inquiry_notify.notify_new_inquiry = fake_notify
    r = me.post("/api/v1/inquiries", json={"message": "   "})
    check("공백 문의는 422 이고 알림 없음", r.status_code == 422 and not calls, f"{r.status_code} {calls}")
    anon = TestClient(app, raise_server_exceptions=False)
    r = anon.post("/api/v1/inquiries", json={"message": "비로그인"})
    check("비로그인은 401 이고 알림 없음", r.status_code == 401 and not calls)
finally:
    try:
        db.close()
    except Exception:  # noqa: BLE001
        pass
    drop_schema(_BASE_DSN, _SCHEMA)

print(f"\n== {len(PASS)}/{len(PASS) + len(FAIL)} PASS ==")
if FAIL:
    print("FAIL:", FAIL)
    sys.exit(1)
