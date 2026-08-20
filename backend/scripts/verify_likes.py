"""공유 코스 좋아요·정렬 검증 (부록 R.14, 2026-08-20) — 임시 Postgres 스키마 · 인메모리 ASGI.

`verify_community.py`(기존 계약 회귀 감시)는 손대지 않는다. 이번에 새로 생긴 동작만 여기서 본다:
  1. 멱등 토글(중복 POST/DELETE 가 카운트를 흔들지 않는다)
  2. 계정당 1회(PK 제약) · 다른 계정은 각각 1표
  3. 비로그인 401 · 없는 코드/hidden 404
  4. 카운트 정합성(like_count == COUNT(course_likes)) — 부록 R.14 §2-6 점검 쿼리
  5. `sort` 무회귀(미지정 = latest) · popular 정렬 · 화이트리스트 밖 값 422
  6. `liked_by_me`(비로그인 전부 false, 로그인 본인만 true) · 목록 N+1 없음
  7. CASCADE(공유 삭제 시 좋아요 행도 사라진다) · **계정 탈퇴 시 카운터 감산**(보안 M-1)
  8. `delete_overflow` 우선순위(좋아요 받은 코스가 먼저 지워지지 않는다) · `_GRACE` 확장
  9. payload 불가침(좋아요가 저장 payload 를 건드리지 않는다)

실행:
    cd backend && python scripts/verify_likes.py
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# !!! app.* import 전에 !!! 임시 스키마 + 검증용 설정을 주입한다(설정은 import 시점에 고정된다).
from _pg_test_helpers import drop_schema, isolated_database_url  # noqa: E402

_ISOLATED_DSN, _BASE_DSN, _SCHEMA = isolated_database_url()
os.environ["DATABASE_URL"] = _ISOLATED_DSN
os.environ.setdefault("PUBLIC_DATA_API_KEY", "verify-only")
os.environ["USER_SESSION_SECRET"] = "verify-session-secret-not-for-prod"
os.environ["COMMUNITY_ENABLED"] = "true"
# 쿼터는 이 스크립트의 검증 대상이 아니다(전용 절에서만 낮춰서 본다).
os.environ["SHARE_WRITE_PER_MIN"] = "500"
os.environ["REVIEW_WRITE_PER_MIN"] = "500"
os.environ["LIKE_WRITE_PER_MIN"] = "500"
os.environ["SHARE_MAX_PER_DEVICE"] = "50"
os.environ["SHARE_MAX_TOTAL"] = "1000"

from fastapi.testclient import TestClient  # noqa: E402

from app.deps import get_database, get_spot_repository, get_user_auth  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories import shared_course_repo, user_repo  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


db = get_database()
auth = get_user_auth()
anon = TestClient(app)

# 저장 시 payload 재구성(2026-08-18 보안감사 A-6)이 **실재하는 스팟 id 만** 받아들이므로,
# 시드에 실제로 있는 id 를 쓴다(가짜 id 를 쓰면 400 INVALID_COURSE 로 떨어진다).
_SPOTS = get_spot_repository().by_region("26350", None)[:2]
assert len(_SPOTS) >= 2, "검증에 쓸 스팟 시드가 부족합니다(26350)"
COURSE = {
    "region": {"code": "26350"},
    "spots": [{"id": s.id, "name": s.name} for s in _SPOTS],
}


def dev(tag: str) -> dict[str, str]:
    return {"X-Device-Id": f"dev-{tag}-{uuid.uuid4().hex[:12]}"}


def login(tag: str) -> tuple[TestClient, int]:
    user = db.write(
        lambda conn: user_repo.upsert_login(
            conn,
            provider="google",
            provider_sub=f"sub-{tag}-{uuid.uuid4().hex[:8]}",
            email=f"{tag}-{uuid.uuid4().hex[:8]}@example.com",
            email_verified=True,
            default_display_name=f"사용자{tag}",
            now_iso="2026-08-20T00:00:00+09:00",
        )
    )
    token, _ = auth.issue_token(user_id=user["id"], email=user["email"])
    client = TestClient(app)
    client.cookies.set(auth.cookie_name, token)
    return client, int(user["id"])


def share(headers: dict[str, str], title: str) -> str:
    r = anon.post(
        "/api/v1/courses/share",
        json={"nickname": "코스장인", "title": title, "course": COURSE},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["share_code"]


def count_rows(code: str) -> int:
    return db.read(
        lambda conn: conn.execute(
            "SELECT COUNT(*) AS c FROM course_likes WHERE share_code = %s", (code,)
        ).fetchone()["c"]
    )


def stored_payload(code: str) -> str:
    return db.read(lambda conn: shared_course_repo.get_share(conn, share_code=code))["payload"]


def like_count(code: str) -> int:
    return int(db.read(lambda conn: shared_course_repo.get_share(conn, share_code=code))["like_count"])


def count_mismatch() -> list[dict[str, object]]:
    """부록 R.14 §2-6 정합성 점검 쿼리 — `like_count` 와 실제 행 수가 어긋난 코스를 전부 반환.

    §2 뿐 아니라 **행이 사라질 수 있는 절(§7 계정 삭제)에서도 다시 돌린다**. 2026-08-20
    보안검수 M-1 이 정확히 그 틈(CASCADE 로 행만 사라지고 카운터는 남음)이었고, 당시
    §7 이 "course_likes 행 수 == 0" 만 봐서 드리프트를 놓쳤다.
    """
    return db.read(
        lambda conn: conn.execute(
            """
            SELECT s.share_code, s.like_count, COALESCE(l.c, 0) AS actual
              FROM shared_courses s
              LEFT JOIN (SELECT share_code, COUNT(*) c FROM course_likes GROUP BY share_code) l
                ON l.share_code = s.share_code
             WHERE s.like_count <> COALESCE(l.c, 0)
            """
        ).fetchall()
    )


# --------------------------------------------------------------------------
section("1. 좋아요 등록·취소 멱등성")

A, uid_a = login("a")
B, _uid_b = login("b")
D1 = dev("s1")
code = share(D1, "해운대 반나절")
before_payload = stored_payload(code)

r = A.post(f"/api/v1/courses/shared/{code}/like")
check("POST like 200 {liked:true, like_count:1}",
      r.status_code == 200 and r.json() == {"liked": True, "like_count": 1}, r.text)

r = A.post(f"/api/v1/courses/shared/{code}/like")
check("같은 계정 재요청도 200 + 카운트 불변(멱등, 409 아님)",
      r.status_code == 200 and r.json() == {"liked": True, "like_count": 1}, r.text)

r = B.post(f"/api/v1/courses/shared/{code}/like")
check("다른 계정은 별도 1표(2)", r.status_code == 200 and r.json()["like_count"] == 2, r.text)
check("계정당 1행(course_likes 2행)", count_rows(code) == 2, str(count_rows(code)))

r = B.delete(f"/api/v1/courses/shared/{code}/like")
check("DELETE like 200 {liked:false, like_count:1}",
      r.status_code == 200 and r.json() == {"liked": False, "like_count": 1}, r.text)

r = B.delete(f"/api/v1/courses/shared/{code}/like")
check("누른 적 없는 계정의 취소도 200 + 카운트 불변(멱등, 404 아님)",
      r.status_code == 200 and r.json() == {"liked": False, "like_count": 1}, r.text)

check("응답에 user_id 미노출", "user_id" not in r.text)

# --------------------------------------------------------------------------
section("2. 카운트 정합성 (부록 R.14 §2-6 점검 쿼리)")

mismatch = count_mismatch()
check("like_count == COUNT(course_likes) (전 행)", not mismatch, str(mismatch))

# 같은 계정이 연달아 눌러도 카운트가 두 번 오르지 않는다(PK 제약이 보장).
for _ in range(5):
    A.post(f"/api/v1/courses/shared/{code}/like")
check("연속 5회 재요청 후에도 like_count=1", count_rows(code) == 1 and
      db.read(lambda conn: shared_course_repo.get_share(conn, share_code=code))["like_count"] == 1)

# --------------------------------------------------------------------------
section("3. 인증·404 경계")

r = anon.post(f"/api/v1/courses/shared/{code}/like")
check("비로그인 POST like → 401", r.status_code == 401, str(r.status_code))
r = anon.delete(f"/api/v1/courses/shared/{code}/like")
check("비로그인 DELETE like → 401", r.status_code == 401, str(r.status_code))

r = A.post("/api/v1/courses/shared/ZZZZZZZZ/like")
check("없는 코드 → 404 NOT_FOUND",
      r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND", r.text)
r = A.post("/api/v1/courses/shared/badcode!/like")
check("형식 위반 코드 → 404", r.status_code == 404, str(r.status_code))

hidden_code = share(dev("hidden"), "가려진 코스")
db.write(
    lambda conn: conn.execute(
        "UPDATE shared_courses SET hidden = 1 WHERE share_code = %s", (hidden_code,)
    )
)
r = A.post(f"/api/v1/courses/shared/{hidden_code}/like")
check("hidden=1 코스 → 404(가려진 글에 좋아요가 붙지 않는다)", r.status_code == 404, str(r.status_code))

# --------------------------------------------------------------------------
section("4. 피드 정렬 · liked_by_me")

old_code = share(dev("old"), "오래된 인기 코스")
new_code = share(dev("new"), "최신 무반응 코스")
A.post(f"/api/v1/courses/shared/{old_code}/like")
B.post(f"/api/v1/courses/shared/{old_code}/like")

r = anon.get("/api/v1/courses/shared", params={"limit": 50})
items = r.json()["items"]
codes_default = [i["share_code"] for i in items]
r2 = anon.get("/api/v1/courses/shared", params={"limit": 50, "sort": "latest"})
check("sort 미지정 == sort=latest (무회귀)",
      codes_default == [i["share_code"] for i in r2.json()["items"]])
check("latest 는 최신이 앞", codes_default.index(new_code) < codes_default.index(old_code))
check("목록 항목에 like_count·liked_by_me 항상 존재",
      all("like_count" in i and "liked_by_me" in i for i in items))
check("비로그인 목록의 liked_by_me 는 전부 false",
      all(i["liked_by_me"] is False for i in items))
check("목록 응답에 payload 미포함", all("course" not in i for i in items))

r = anon.get("/api/v1/courses/shared", params={"limit": 50, "sort": "popular"})
pop = [i["share_code"] for i in r.json()["items"]]
check("popular 는 좋아요 많은 코스가 앞", pop[0] == old_code, str(pop[:3]))

r = anon.get("/api/v1/courses/shared", params={"limit": 50, "sort": "hot"})
check("화이트리스트 밖 sort → 422", r.status_code == 422, str(r.status_code))

r = A.get("/api/v1/courses/shared", params={"limit": 50})
mine = {i["share_code"]: i["liked_by_me"] for i in r.json()["items"]}
check("로그인 목록: 내가 누른 코스만 liked_by_me=true",
      mine[old_code] is True and mine[new_code] is False and mine[code] is True, str(mine))
r = B.get("/api/v1/courses/shared", params={"limit": 50})
mine_b = {i["share_code"]: i["liked_by_me"] for i in r.json()["items"]}
check("다른 계정에는 그 계정의 상태가 보인다", mine_b[old_code] is True and mine_b[code] is False)

# N+1 없음: **항목 수를 바꿔도 SELECT 횟수가 그대로**여야 한다(카드마다 별도 조회 금지).
# 절대값(3회 = 세션 계정 확인 + JOIN 목록 + total)이 아니라 "증가하지 않는다"를 본다 —
# 부수적인 고정 쿼리가 하나 늘어도 이 검사는 흔들리지 않아야 한다.
_orig_read = type(db).read


def _count_selects(client: TestClient, limit: int) -> int:
    hits: list[str] = []

    def _counting_read(self, fn):  # noqa: ANN001
        def wrapped(conn):
            real = conn.execute

            def spy(sql, *a, **k):
                if "select" in str(sql).lower():
                    hits.append(str(sql))
                return real(sql, *a, **k)

            conn.execute = spy  # type: ignore[method-assign]
            try:
                return fn(conn)
            finally:
                conn.execute = real  # type: ignore[method-assign]

        return _orig_read(self, wrapped)

    type(db).read = _counting_read  # type: ignore[method-assign]
    try:
        client.get("/api/v1/courses/shared", params={"limit": limit})
    finally:
        type(db).read = _orig_read  # type: ignore[method-assign]
    return len(hits)


few, many = _count_selects(A, 1), _count_selects(A, 50)
check("N+1 없음 — 항목 수가 늘어도 SELECT 횟수 불변", few == many, f"limit1={few} limit50={many}")

# --------------------------------------------------------------------------
section("5. 상세 응답 (U-6: 서버는 항상 값을 준다)")

r = anon.get(f"/api/v1/courses/shared/{old_code}")
detail = r.json()
check("비로그인 상세: like_count 제공 + liked_by_me=false",
      detail["like_count"] == 2 and detail["liked_by_me"] is False, str(detail.get("like_count")))
r = A.get(f"/api/v1/courses/shared/{old_code}")
check("로그인 상세: liked_by_me=true", r.json()["liked_by_me"] is True)
check("상세 응답에 device_id·user_id 미노출",
      "device_id" not in r.text and "user_id" not in r.text)

# --------------------------------------------------------------------------
section("6. payload 불가침 (A-6 회귀)")

check("좋아요 전후 저장 payload 가 바이트 단위로 동일", stored_payload(code) == before_payload)
check("payload 에 like 관련 키가 없다",
      "like_count" not in before_payload and "liked" not in before_payload)

# --------------------------------------------------------------------------
section("7. CASCADE (공유 삭제 → 좋아요 행 삭제) · 계정 탈퇴 카운터 감산")

del_code = share(D1, "곧 지워질 코스")
A.post(f"/api/v1/courses/shared/{del_code}/like")
check("삭제 전 좋아요 1행", count_rows(del_code) == 1)
r = anon.delete(f"/api/v1/courses/shared/{del_code}", headers=D1)
check("본인 기기 삭제 200", r.status_code == 200, str(r.status_code))
check("공유 삭제 시 course_likes 행도 함께 사라짐(CASCADE)", count_rows(del_code) == 0)

# 계정 삭제 — 탈퇴해도 좋아요 행만 사라지고 공유 코스는 남는다.
# **반드시 user_repo.delete_account 를 통해** 지운다. 예전엔 여기서 raw `DELETE FROM users`
# 를 쏘고 행 수만 봤는데, 그러면 실제 탈퇴 경로(API → delete_account)가 카운터를 어떻게
# 다루는지는 아무도 검증하지 않게 된다 — 2026-08-20 보안검수 M-1 이 그 사각지대였다.
C, uid_c = login("c")
cascade_code = share(dev("cascade"), "탈퇴 테스트")
C.post(f"/api/v1/courses/shared/{cascade_code}/like")
check("탈퇴 전 like_count=1", like_count(cascade_code) == 1 and count_rows(cascade_code) == 1)
db.write(lambda conn: user_repo.delete_account(conn, user_id=uid_c))
check("계정 삭제 시 그 계정의 좋아요 행 삭제(CASCADE)", count_rows(cascade_code) == 0)
check("계정이 사라져도 공유 코스 자체는 남는다",
      db.read(lambda conn: shared_course_repo.get_share(conn, share_code=cascade_code)) is not None)
check("탈퇴로 사라진 좋아요만큼 like_count 가 감산된다(M-1)",
      like_count(cascade_code) == 0, str(like_count(cascade_code)))

# M-1 재현 시나리오 그대로: 3계정이 누른 코스에서 2계정이 탈퇴하면 1 이 남아야 한다
# (수정 전에는 3 이 그대로 남아 popular 랭킹이 부풀고 delete_overflow 유예가 영구화됐다).
drift_code = share(dev("drift"), "드리프트 재현")
likers = [login(f"drift{i}") for i in range(3)]
for client, _uid in likers:
    client.post(f"/api/v1/courses/shared/{drift_code}/like")
check("3계정 좋아요 → like_count=3", like_count(drift_code) == 3, str(like_count(drift_code)))
for _client, uid in likers[:2]:
    db.write(lambda conn, u=uid: user_repo.delete_account(conn, user_id=u))
check("2계정 탈퇴 후 like_count=1 (실제 행 수와 일치)",
      like_count(drift_code) == 1 and count_rows(drift_code) == 1,
      f"like_count={like_count(drift_code)} rows={count_rows(drift_code)}")

# 여러 코스에 누른 계정이 탈퇴해도 **누른 코스만** 각각 1씩 감산된다(누르지 않은 코스 불변).
multi_a, multi_b = share(dev("m1"), "다중 A"), share(dev("m2"), "다중 B")
untouched = share(dev("m3"), "누르지 않은 코스")
M, uid_m = login("multi")
N, _uid_n = login("multi2")
for c in (multi_a, multi_b):
    M.post(f"/api/v1/courses/shared/{c}/like")
    N.post(f"/api/v1/courses/shared/{c}/like")
N.post(f"/api/v1/courses/shared/{untouched}/like")
db.write(lambda conn: user_repo.delete_account(conn, user_id=uid_m))
check("여러 코스를 누른 계정의 탈퇴는 코스마다 1씩만 감산",
      like_count(multi_a) == 1 and like_count(multi_b) == 1,
      f"A={like_count(multi_a)} B={like_count(multi_b)}")
check("그 계정이 누르지 않은 코스는 영향 없음", like_count(untouched) == 1, str(like_count(untouched)))

# 탈퇴 계정이 좋아요를 하나도 안 눌렀거나 이미 취소한 경우에도 카운터가 흔들리지 않는다.
zero_code = share(dev("zero"), "취소 후 탈퇴")
Z, uid_z = login("zero")
Z.post(f"/api/v1/courses/shared/{zero_code}/like")
Z.delete(f"/api/v1/courses/shared/{zero_code}/like")
db.write(lambda conn: user_repo.delete_account(conn, user_id=uid_z))
check("좋아요를 취소한 뒤 탈퇴해도 like_count 가 음수로 내려가지 않는다",
      like_count(zero_code) == 0, str(like_count(zero_code)))

mismatch = count_mismatch()
check("계정 삭제 후에도 like_count == COUNT(course_likes) (전 행, M-1 회귀)",
      not mismatch, str(mismatch))

# --------------------------------------------------------------------------
section("8. 보존정책 우선순위 (U-5 결론)")


def _mk(conn, code_: str, *, created: str, views: int, likes: int) -> None:
    conn.execute(
        """
        INSERT INTO shared_courses
            (share_code, device_id, nickname, title, payload, spot_count,
             created_at, view_count, hidden, like_count)
        VALUES (%s, 'dev-x', 'n', 't', '{}', 0, %s, %s, 0, %s)
        """,
        (code_, created, views, likes),
    )


OLD = "2020-01-01T00:00:00+09:00"   # 유예(_GRACE) 밖 — 반응이 있어도 삭제 후보가 된다
FRESH = "2099-01-01T00:00:00+09:00"  # 유예 안 — 반응이 있으면 제외된다

db.write(lambda conn: conn.execute("DELETE FROM shared_courses"))
db.write(lambda conn: (
    _mk(conn, "OLDLIKED", created=OLD, views=0, likes=5),
    _mk(conn, "OLDVIEWD", created=OLD, views=9, likes=0),
    _mk(conn, "OLDEMPTY", created=OLD, views=0, likes=0),
))
removed = db.write(
    lambda conn: shared_course_repo.delete_overflow(
        conn, max_total=2, batch=1, grace_since_iso="2026-08-01T00:00:00+09:00"
    )
)
alive = db.read(
    lambda conn: {r["share_code"] for r in conn.execute("SELECT share_code FROM shared_courses").fetchall()}
)
check("overflow 1건 삭제", removed == 1, str(removed))
check("반응 0인 코스가 먼저 지워진다(좋아요 받은 코스 생존)",
      "OLDEMPTY" not in alive and {"OLDLIKED", "OLDVIEWD"} <= alive, str(alive))

db.write(lambda conn: conn.execute("DELETE FROM shared_courses"))
db.write(lambda conn: (
    _mk(conn, "NEWLIKED", created=FRESH, views=0, likes=3),   # 최근 + 좋아요 → 유예
    _mk(conn, "OLDPLAIN", created=OLD, views=0, likes=0),
))
removed = db.write(
    lambda conn: shared_course_repo.delete_overflow(
        conn, max_total=1, batch=5, grace_since_iso="2026-08-01T00:00:00+09:00"
    )
)
alive = db.read(
    lambda conn: {r["share_code"] for r in conn.execute("SELECT share_code FROM shared_courses").fetchall()}
)
check("_GRACE 확장: 최근+좋아요 코스는 용량 정리에서 제외",
      "NEWLIKED" in alive and "OLDPLAIN" not in alive, str(alive))

# delete_expired 는 유예 확장의 영향을 받지 않는다(두 조건이 동시에 참일 수 없다).
db.write(lambda conn: conn.execute("DELETE FROM shared_courses"))
db.write(lambda conn: _mk(conn, "EXPIRED1", created=OLD, views=3, likes=7))
removed = db.write(
    lambda conn: shared_course_repo.delete_expired(
        conn,
        cutoff_iso="2026-01-01T00:00:00+09:00",
        batch=5,
        grace_since_iso="2026-08-01T00:00:00+09:00",
    )
)
check("기간 정리는 좋아요가 많아도 그대로 동작(무한 보존 아님)", removed == 1, str(removed))

# --------------------------------------------------------------------------
section("9. 킬스위치 · 계정 쿼터")

from app.config import settings  # noqa: E402
from app.deps import get_community_write_limiter  # noqa: E402

live_code = share(dev("switch"), "킬스위치 테스트")
settings.like_enabled = False
try:
    r = A.post(f"/api/v1/courses/shared/{live_code}/like")
    check("LIKE_ENABLED=false → 503 FEATURE_DISABLED",
          r.status_code == 503 and r.json()["error"]["code"] == "FEATURE_DISABLED", r.text)
    r = anon.get("/api/v1/courses/shared", params={"limit": 5})
    check("킬스위치 중에도 피드는 like_count 를 계속 내려준다",
          r.status_code == 200 and all("like_count" in i for i in r.json()["items"]))
finally:
    settings.like_enabled = True

limiter = get_community_write_limiter()
limiter._limits["like"] = 2  # type: ignore[attr-defined]
# 쿼터 키는 `user:{id}` 라 **앞 절에서 이미 여러 번 누른 A** 를 쓰면 안 된다(카운터가 남아 있다).
# 갓 만든 계정으로 봐야 "2건까지 허용 → 3건째 429"를 정확히 관측한다.
Q, _uid_q = login("quota")
codes = [share(dev(f"q{i}"), f"쿼터 {i}") for i in range(3)]
statuses = [Q.post(f"/api/v1/courses/shared/{c}/like").status_code for c in codes]
check("계정 쿼터 초과 시 429", statuses[:2] == [200, 200] and statuses[2] == 429, str(statuses))
# 쿼터는 계정별로 분리된다 — 다른 계정은 같은 순간에도 정상 통과해야 한다.
R, _uid_r = login("quota2")
check("쿼터는 계정별로 분리(다른 계정은 영향 없음)",
      R.post(f"/api/v1/courses/shared/{codes[0]}/like").status_code == 200)
limiter._limits["like"] = settings.like_write_per_min  # type: ignore[attr-defined]

# --------------------------------------------------------------------------
print(f"\nPASS {len(PASS)} / FAIL {len(FAIL)}")
if FAIL:
    print("실패 항목:")
    for f in FAIL:
        print(f"  - {f}")

drop_schema(_BASE_DSN, _SCHEMA)
print("임시 스키마 삭제 완료")
sys.exit(1 if FAIL else 0)
