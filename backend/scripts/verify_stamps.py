# -*- coding: utf-8 -*-
"""방문 스탬프 계정 보관함(2026-09-20) 회귀 검증 — `/api/v1/stamps`.

verify_saved_spots.py 와 같은 격리 스키마 하네스(Postgres 필요 — CI 에서 실행).

    py scripts/verify_stamps.py

검증 항목
  (a) 비로그인 → 401 (조회·찍기 모두)
  (b) 현장(스팟 좌표) 위치 → 200, 이름·지역은 스토어에서 재구성
  (c) 멀리서(>500m) → 422 TOO_FAR + 거리, 계정에 아무것도 안 남음
  (d) 위치 정확도가 나쁘면(>1km) → 422 LOW_ACCURACY
  (e) 다시 찍어도 1건(멱등), 처음 찍은 시각 유지
  (f) 없는 스팟 → 404
  (g) 다른 계정의 스탬프는 보이지 않음
  (h) DELETE → 204(멱등), 목록에서 사라짐
  (i) 좌표는 DB 어디에도 저장되지 않는다(visit_stamps 컬럼 = user_id·spot_id·stamped_at)
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
os.environ["STAMPS_ENABLED"] = "true"  # 기본은 꺼져 있다(대표 지시로 접어 둠) — 검증은 켠 상태로
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
            now_iso="2026-09-20T00:00:00+09:00",
        )
    )
    token, _ = auth.issue_token(user_id=user["id"], email=user["email"], epoch=user_repo.session_epoch_of(user))
    c = TestClient(app)
    c.cookies.set(auth.cookie_name, token)
    return c


try:
    pool = spots.by_region("26350", None)
    assert pool, "해운대 시드 스팟 없음"
    s1 = pool[0]
    here = {"lat": s1.lat, "lng": s1.lng, "accuracy_m": 30}
    far = {"lat": s1.lat + 0.05, "lng": s1.lng, "accuracy_m": 30}  # 위도 0.05° ≈ 5.5km

    print("\n[a] 비로그인")
    anon = TestClient(app)
    check("GET 비로그인 → 401", anon.get("/api/v1/stamps").status_code == 401)
    check("POST 비로그인 → 401", anon.post(f"/api/v1/stamps/{s1.id}", json=here).status_code == 401)

    print("\n[b] 현장에서 찍기")
    me = login("sub-stamp-1", "stamp1@example.com", "스탬프러")
    r = me.post(f"/api/v1/stamps/{s1.id}", json=here)
    check("현장 → 200", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
    body = r.json()
    check("이름·카테고리는 스토어 값", body.get("name") == s1.name and body.get("category") == s1.category)
    check("stamped_at 있음", isinstance(body.get("stamped_at"), str) and len(body["stamped_at"]) > 10)
    first_at = body["stamped_at"]

    print("\n[c] 멀리서")
    other_spot = pool[1]
    r = me.post(f"/api/v1/stamps/{other_spot.id}", json={"lat": other_spot.lat + 0.05, "lng": other_spot.lng})
    check("멀리서 → 422", r.status_code == 422, str(r.status_code))
    err = r.json().get("error", {})
    check("TOO_FAR + 거리", err.get("code") == "TOO_FAR" and (err.get("detail") or {}).get("distance_m", 0) > 500, str(err))
    check("실패하면 계정에 안 남음", [i["spot_id"] for i in me.get("/api/v1/stamps").json()["items"]] == [s1.id])

    print("\n[d] 부정확한 위치")
    r = me.post(f"/api/v1/stamps/{other_spot.id}", json={**{"lat": other_spot.lat, "lng": other_spot.lng}, "accuracy_m": 5000})
    check("정확도 5km → 422 LOW_ACCURACY", r.status_code == 422 and r.json()["error"]["code"] == "LOW_ACCURACY", r.text[:120])

    print("\n[e] 멱등")
    time.sleep(1.1)
    r = me.post(f"/api/v1/stamps/{s1.id}", json=here)
    items = me.get("/api/v1/stamps").json()["items"]
    check("두 번 찍어도 1건", len(items) == 1)
    check("처음 찍은 시각 유지", r.json()["stamped_at"] == first_at == items[0]["stamped_at"])

    print("\n[f] 없는 스팟")
    r = me.post("/api/v1/stamps/999999999", json=here)
    check("없는 id → 404", r.status_code == 404, str(r.status_code))

    print("\n[g] 계정 분리")
    other = login("sub-stamp-2", "stamp2@example.com", "남")
    check("다른 계정 목록은 비어 있음", other.get("/api/v1/stamps").json()["items"] == [])

    print("\n[h] 삭제")
    check("DELETE → 204", me.delete(f"/api/v1/stamps/{s1.id}").status_code == 204)
    check("다시 DELETE → 204(멱등)", me.delete(f"/api/v1/stamps/{s1.id}").status_code == 204)
    check("삭제 후 목록 비어 있음", me.get("/api/v1/stamps").json()["items"] == [])

    print("\n[i] 좌표 비저장")
    cols = {
        r["column_name"]
        for r in db.read(
            lambda conn: conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'visit_stamps' AND table_schema = current_schema()"
            ).fetchall()
        )
    }
    check("visit_stamps 컬럼은 user_id·spot_id·stamped_at 뿐", cols == {"user_id", "spot_id", "stamped_at"}, str(cols))
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
