# -*- coding: utf-8 -*-
"""저장한 스팟 계정 보관함(2026-09-16) 회귀 검증 — `/api/v1/saved-spots`.

verify_auth.py 와 같은 격리 스키마 하네스(Postgres 필요 — CI 에서 실행).

    py scripts/verify_saved_spots.py

검증 항목
  (a) 비로그인 → 401
  (b) PUT 저장 → 201/200 + 스팟 본문은 스토어에서 재구성(이름·좌표), 스냅샷 보존
  (c) 같은 스팟 재저장 → 중복 없이 1건(upsert), saved_at 갱신
  (d) 목록은 최근 저장 순
  (e) DELETE → 204, 다시 DELETE 도 204(멱등), 목록에서 사라짐
  (f) 없는 스팟 id → 404
  (g) 다른 계정의 저장은 보이지 않음
"""
from __future__ import annotations

import os
import sys
import time
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

from app.deps import get_database, get_spot_repository, get_user_auth  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories import user_repo  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))


db = get_database()
auth = get_user_auth()
spots = get_spot_repository()


def login(sub: str, email: str, name: str) -> TestClient:
    user = db.write(
        lambda conn: user_repo.upsert_login(
            conn,
            provider="google",
            provider_sub=sub,
            email=email,
            email_verified=True,
            default_display_name=name,
            now_iso="2026-09-16T00:00:00+09:00",
        )
    )
    token, _ = auth.issue_token(user_id=user["id"], email=user["email"], epoch=user_repo.session_epoch_of(user))
    c = TestClient(app)
    c.cookies.set(auth.cookie_name, token)
    return c


try:
    # 실제 시드에서 스팟 2곳을 고른다(지어내지 않음)
    pool = spots.by_region("26350", None)
    assert len(pool) >= 2, "해운대 시드 스팟 부족"
    s1, s2 = pool[0], pool[1]

    print("\n[a] 비로그인")
    anon = TestClient(app)
    check("GET 비로그인 → 401", anon.get("/api/v1/saved-spots").status_code == 401)
    check("PUT 비로그인 → 401", anon.put(f"/api/v1/saved-spots/{s1.id}", json={}).status_code == 401)

    print("\n[b] 저장 + 재구성")
    me = login("sub-saved-1", "saved1@example.com", "저장이")
    r = me.put(
        f"/api/v1/saved-spots/{s1.id}",
        json={"congestion": {"index": 63.4, "level": "mid", "tier": "B"}},
    )
    check("PUT 저장 → 200", r.status_code == 200, str(r.status_code) + r.text[:120])
    body = r.json()
    check("이름·좌표는 스토어 값", body.get("name") == s1.name and body.get("location", {}).get("lat") == s1.lat)
    check("스냅샷 보존", (body.get("congestion") or {}).get("index") == 63.4 and body["congestion"]["level"] == "mid")
    check("saved_at 있음", isinstance(body.get("saved_at"), str) and len(body["saved_at"]) > 10)

    print("\n[c] 재저장 upsert")
    first_saved_at = body["saved_at"]
    r = me.put(f"/api/v1/saved-spots/{s1.id}", json={"congestion": None})
    items = me.get("/api/v1/saved-spots").json()["items"]
    check("같은 스팟 2번 저장해도 1건", sum(1 for i in items if i["id"] == s1.id) == 1)
    check("재저장 시 스냅샷 갱신(None)", next(i for i in items if i["id"] == s1.id)["congestion"] is None)
    check("saved_at 갱신(같거나 이후)", r.json()["saved_at"] >= first_saved_at)

    from app.repositories import saved_spot_repo
    previous_limit = saved_spot_repo.MAX_PER_USER
    saved_spot_repo.MAX_PER_USER = 1
    try:
        check("상한 도달 후 기존 스팟 갱신 허용", me.put(f"/api/v1/saved-spots/{s1.id}", json={}).status_code == 200)
        check("상한 도달 후 신규 스팟 거부", me.put(f"/api/v1/saved-spots/{s2.id}", json={}).status_code == 409)
    finally:
        saved_spot_repo.MAX_PER_USER = previous_limit

    print("\n[d] 순서")
    time.sleep(1.1)  # saved_at 이 초 단위라 순서 판정이 흔들리지 않게
    me.put(f"/api/v1/saved-spots/{s2.id}", json={})
    items = me.get("/api/v1/saved-spots").json()["items"]
    check("목록 2건", len(items) == 2, str(len(items)))
    check("최근 저장이 앞", items[0]["id"] == s2.id)

    print("\n[e] 삭제")
    check("DELETE → 204", me.delete(f"/api/v1/saved-spots/{s2.id}").status_code == 204)
    check("다시 DELETE → 204(멱등)", me.delete(f"/api/v1/saved-spots/{s2.id}").status_code == 204)
    items = me.get("/api/v1/saved-spots").json()["items"]
    check("삭제 후 목록 1건", [i["id"] for i in items] == [s1.id])

    print("\n[f] 없는 스팟")
    r = me.put("/api/v1/saved-spots/999999999", json={})
    check("없는 id → 404", r.status_code == 404, str(r.status_code))

    print("\n[g] 계정 분리")
    other = login("sub-saved-2", "saved2@example.com", "남")
    check("다른 계정 목록은 비어 있음", other.get("/api/v1/saved-spots").json()["items"] == [])
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
