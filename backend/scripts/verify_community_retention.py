"""부록 R 보존정책(M-2) + 숨김 글 자력 복구(M-3) 검증 — 임시 DB · 인메모리 ASGI.

`verify_community.py` 는 **기존 계약의 회귀 감시용**이라 손대지 않았다(67/67 유지).
이번 QA 수정으로 새로 생긴 동작만 이 스크립트가 검증한다.

lifespan 을 열지 않으므로(=`with TestClient` 미사용) 프리워밍·주기 정리 태스크가 돌지 않는다.
정리는 `share_service.run_cleanup` 을 직접 호출해 결정적으로 검증한다(네트워크 불필요).

실행:
    cd backend && py scripts/verify_community_retention.py
"""

from __future__ import annotations

# 2026-09-03 — 공유 코스 검증은 시드에 실제로 있는 스팟 id를 써야 한다. 2026-08-20부터
# rebuild_course_for_store(strict=True)가 없는 스팟을 400 INVALID_COURSE로 거부한다
# (이 스크립트는 CI가 2026-09-02에 생기기 전까지 안 돌아서 그때 깨진 걸 몰랐다).
def _real_spot_ids(n: int = 2) -> list[int]:
    from app.deps import get_spot_repository
    return [s.id for s in get_spot_repository().all_spots()[:n]]

import asyncio
import os
import sys
import threading
import uuid
from datetime import timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# !!! import 전에 !!! 임시 Postgres 스키마 + 검증용 작은 상한을 주입한다(설정은 import
# 시점에 고정된다 — 2026-08-17 PostgreSQL 전환으로 tempfile SQLite 파일 방식에서 바뀌었다).
from _pg_test_helpers import drop_schema, isolated_database_url  # noqa: E402

_ISOLATED_DSN, _BASE_DSN, _SCHEMA = isolated_database_url()
os.environ["DATABASE_URL"] = _ISOLATED_DSN

# 2026-09-20 — 후기 쓰기가 로그인 필수가 되면서 세션 서명키가 필요해졌다.
# UserAuth.enabled 가 이 값으로 판정되고, 비어 있으면 require_login 이 항상 401 이다.
os.environ.setdefault("USER_SESSION_SECRET", "verify-session-secret-not-for-prod")

os.environ["SHARE_MAX_PER_DEVICE"] = "3"
os.environ["SHARE_MAX_TOTAL"] = "10"
os.environ["SHARE_RETENTION_DAYS"] = "180"
os.environ["SHARE_RECENT_VIEW_GRACE_DAYS"] = "30"
os.environ["SHARE_CLEANUP_BATCH"] = "5"
# 쓰기 쿼터는 이 스크립트의 검증 대상이 아니다(verify_community.py §6 이 따로 본다).
os.environ["SHARE_WRITE_PER_MIN"] = "500"
os.environ["REVIEW_WRITE_PER_MIN"] = "500"

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.deps import get_database, get_user_auth  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories import user_repo  # noqa: E402
from app.services import share_service  # noqa: E402
from app.util.time import now_kst, to_iso_kst  # noqa: E402

client = TestClient(app)
db = get_database()


def login(sub: str, name: str) -> TestClient:
    """세션 쿠키가 박힌 TestClient. 2026-09-20 부터 후기 쓰기·신고는 로그인 필수다."""
    auth = get_user_auth()
    user = db.write(
        lambda conn: user_repo.upsert_login(
            conn, provider="google", provider_sub=sub, email=f"{sub}@example.com",
            email_verified=True, default_display_name=name,
            now_iso="2026-09-20T00:00:00+09:00",
        )
    )
    token, _ = auth.issue_token(
        user_id=user["id"], email=user["email"], epoch=user_repo.session_epoch_of(user)
    )
    c = TestClient(app)
    c.cookies.set(auth.cookie_name, token)
    return c

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    (PASS if cond else FAIL).append(f"{name}{(' — ' + extra) if extra else ''}")
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def dev(tag: str) -> dict[str, str]:
    return {"X-Device-Id": f"dev-{tag}-{uuid.uuid4().hex[:12]}"}


COURSE = {"region": {"code": "26350"}, "spots": [{"id": sid} for sid in _real_spot_ids(1)]}


def share(headers: dict[str, str], title: str) -> str:
    r = client.post(
        "/api/v1/courses/share",
        json={"nickname": "코스장인", "title": title, "course": COURSE},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["share_code"]


def backdate(code: str, days: int) -> None:
    """created_at 을 과거로 옮긴다(보존기간 검증용). 형식은 서비스가 쓰는 것과 동일하게 유지."""
    stamp = to_iso_kst(now_kst() - timedelta(days=days))
    db.write(
        lambda conn: conn.execute(
            "UPDATE shared_courses SET created_at = %s WHERE share_code = %s", (stamp, code)
        )
    )


def count_all() -> int:
    return db.read(lambda conn: conn.execute("SELECT COUNT(*) c FROM shared_courses").fetchone()["c"])


def exists(code: str) -> bool:
    return client.get(f"/api/v1/courses/shared/{code}").status_code == 200


# --------------------------------------------------------------------------
section("A. 기기당 보유 상한 3건 — 초과 시 오래된 것부터 자동 삭제(생성은 항상 성공)")

D = dev("cap")
codes = [share(D, f"코스 {i}") for i in range(5)]
check("5회 생성 모두 201(409 로 막지 않음)", len(codes) == 5)
device_rows = db.read(
    lambda conn: conn.execute(
        "SELECT share_code FROM shared_courses WHERE device_id = %s ORDER BY seq",
        (D["X-Device-Id"],),
    ).fetchall()
)
kept = [r["share_code"] for r in device_rows]
check("기기 보유 건수 = 상한 3", len(kept) == 3, str(len(kept)))
check("남은 것은 최신 3건", kept == codes[2:], f"kept={kept}")
check("가장 오래된 2건은 404", not exists(codes[0]) and not exists(codes[1]))
check("최신 건은 정상 조회", exists(codes[-1]))

# --------------------------------------------------------------------------
section("B. 전체 row 상한 10건 — 조회수 0·오래된 것부터 정리 / 최근 조회분은 유예")

# 지금까지 3건. 인기 코스 1건을 만들고 조회수를 올려 '최근 + 조회됨' 유예 대상으로 만든다.
POP = dev("pop")
popular = share(POP, "인기 코스")
client.get(f"/api/v1/courses/shared/{popular}")
client.get(f"/api/v1/courses/shared/{popular}")

for i in range(14):  # 서로 다른 기기 14대가 1건씩 → 전체 상한을 확실히 넘긴다
    share(dev(f"bulk{i}"), f"대량 {i}")

total = count_all()
check("쓰기 경로 트림으로 전체 상한 근처 유지(≤ 상한)", total <= settings.share_max_total, str(total))
check("최근 조회된 인기 코스는 유예되어 살아 있음", exists(popular))

# --------------------------------------------------------------------------
section("C. 보존 기간 180일 — 기동/주기 정리에서 삭제 (조회수 있어도 기간 지나면 대상)")

OLD = dev("old")
old_plain = share(OLD, "오래된 코스")
old_viewed = share(dev("oldv"), "오래됐지만 조회된 코스")
client.get(f"/api/v1/courses/shared/{old_viewed}")
fresh = share(dev("fresh"), "최근 코스")
backdate(old_plain, 200)
backdate(old_viewed, 200)

result = asyncio.run(share_service.run_cleanup(db))
check("run_cleanup 이 만료분을 지웠다", result["expired"] >= 2, str(result))
check("200일 지난 코스 삭제(조회수 0)", not exists(old_plain))
check("200일 지난 코스 삭제(조회수 있어도 기간 초과면 대상)", not exists(old_viewed))
check("최근 코스는 보존", exists(fresh))
check("정리 후 전체 행 ≤ 상한", count_all() <= settings.share_max_total, str(count_all()))

# 유예 규칙: 최근(30일 내) + 조회수>0 은 전체 상한 정리에서도 살아남는다.
check("유예 대상(최근+조회됨)은 정리 후에도 생존", exists(popular))

# --------------------------------------------------------------------------
section("D. 정리 중에도 조회 API 정상 (긴 잠금 없음)")

for i in range(30):
    share(dev(f"flood{i}"), f"홍수 {i}")
for r in db.read(lambda conn: conn.execute("SELECT share_code FROM shared_courses").fetchall())[:20]:
    backdate(r["share_code"], 300)

errors_seen: list[str] = []


def _cleanup_thread() -> None:
    try:
        asyncio.run(share_service.run_cleanup(db))
    except Exception as exc:  # noqa: BLE001
        errors_seen.append(f"cleanup: {exc}")


t = threading.Thread(target=_cleanup_thread)
t.start()
statuses = [client.get("/api/v1/courses/shared", params={"limit": 5}).status_code for _ in range(20)]
t.join(timeout=30)
check("정리 스레드 정상 종료", not t.is_alive() and not errors_seen, str(errors_seen))
check("정리 중 피드 조회 전부 200", set(statuses) == {200}, str(sorted(set(statuses))))
check("정리 후에도 전체 상한 이하", count_all() <= settings.share_max_total, str(count_all()))

# --------------------------------------------------------------------------
section("E. 숨김 리뷰 — 본인에게만 hidden:true 로 보인다 (M-3)")

TARGET = {"target_type": "spot", "target_id": "555001"}
OWNER, R1, R2, R3 = dev("owner"), dev("r1"), dev("r2"), dev("r3")
OTHER = dev("other")
# 2026-09-20 — 소유권이 계정 기준이므로 "본인/타인"도 계정으로 갈린다(기기 헤더는 쿼터용).
c_owner, c_other = login("ret-owner", "작성자"), login("ret-other", "타인")
c_r1, c_r2, c_r3 = login("ret-r1", "신고1"), login("ret-r2", "신고2"), login("ret-r3", "신고3")

r = c_owner.post("/api/v1/reviews", json={**TARGET, "nickname": "작성자", "rating": 5,
                                          "comment": "좋았어요"}, headers=OWNER)
own_id = r.json()["review"]["id"]
check("본인 리뷰 생성 201 + hidden:false", r.status_code == 201 and r.json()["review"]["hidden"] is False)

r = c_other.post("/api/v1/reviews", json={**TARGET, "nickname": "타인", "rating": 3},
                 headers=OTHER)
other_id = r.json()["review"]["id"]

before = client.get("/api/v1/reviews", params=TARGET).json()["summary"]

for c, h in ((c_r1, R1), (c_r2, R2), (c_r3, R3)):
    c.post(f"/api/v1/reviews/{own_id}/report", json={"reason": "신고"}, headers=h)
hidden_now = db.read(
    lambda conn: conn.execute("SELECT hidden FROM reviews WHERE id = %s", (own_id,)).fetchone()["hidden"]
)
check("신고 3건으로 자동 숨김 처리됨", int(hidden_now) == 1, str(hidden_now))

mine = c_owner.get("/api/v1/reviews", params=TARGET).json()
mine_ids = {i["id"]: i for i in mine["items"]}
check("본인 목록에는 숨김 글이 포함된다", own_id in mine_ids, str(list(mine_ids)))
check("본인 글 hidden:true + is_mine:true",
      own_id in mine_ids and mine_ids[own_id]["hidden"] is True
      and mine_ids[own_id]["is_mine"] is True, str(mine_ids.get(own_id)))
check("본인 목록의 타인 글은 hidden:false",
      mine_ids[other_id]["hidden"] is False and mine_ids[other_id]["is_mine"] is False)

theirs = c_other.get("/api/v1/reviews", params=TARGET).json()
check("타인 목록에는 숨김 글이 없다", own_id not in {i["id"] for i in theirs["items"]},
      str([i["id"] for i in theirs["items"]]))
anon = client.get("/api/v1/reviews", params=TARGET).json()
check("헤더 없는 조회에도 숨김 글 없음", own_id not in {i["id"] for i in anon["items"]})
check("어떤 응답에도 device_id 미노출",
      "device_id" not in c_owner.get("/api/v1/reviews", params=TARGET).text)

# --------------------------------------------------------------------------
section("F. 집계 무회귀 — 평균·분포·건수는 hidden 제외 (종전 계산과 동일)")

after_owner = client.get("/api/v1/reviews", params=TARGET, headers=OWNER).json()
after_anon = client.get("/api/v1/reviews", params=TARGET).json()
check("숨김 후 count 는 1(2건 중 숨김 1건 제외)", after_anon["summary"]["count"] == 1,
      str(after_anon["summary"]))
check("평균은 남은 1건(3점)만 반영", after_anon["summary"]["average"] == 3.0,
      str(after_anon["summary"]))
check("분포에서도 숨김 제외(5점 0건)", after_anon["summary"]["distribution"]["5"] == 0,
      str(after_anon["summary"]["distribution"]))
check("본인 조회여도 summary 는 동일(집계 무회귀)",
      after_owner["summary"] == after_anon["summary"], str(after_owner["summary"]))
check("total 은 공개 건수(=summary.count) 유지",
      after_owner["total"] == after_owner["summary"]["count"] == 1, str(after_owner["total"]))
check("숨김 전 2건 → 숨김 후 1건(숨김분만 빠짐)",
      before["count"] == 2 and after_anon["summary"]["count"] == 1,
      f"before={before} after={after_anon['summary']}")

# --------------------------------------------------------------------------
section("G. 409 REVIEW_EXISTS detail.hidden (M-3)")

r = client.post("/api/v1/reviews", json={**TARGET, "nickname": "작성자", "rating": 4}, headers=OWNER)
body = r.json()
check("숨김 상태 재작성 → 409 + detail.hidden=true",
      r.status_code == 409 and body["error"]["code"] == "REVIEW_EXISTS"
      and body["error"]["detail"]["hidden"] is True, r.text)

r = client.post("/api/v1/reviews", json={**TARGET, "nickname": "타인", "rating": 2}, headers=OTHER)
body = r.json()
check("정상 글 중복 → 409 + detail.hidden=false",
      r.status_code == 409 and body["error"]["detail"]["hidden"] is False, r.text)

# 자력 복구: 숨김 글이라도 본인은 수정·삭제할 수 있다.
r = client.patch(f"/api/v1/reviews/{own_id}", json={"comment": "고쳤어요"}, headers=OWNER)
check("숨김 글 본인 수정 200 + hidden:true 유지",
      r.status_code == 200 and r.json()["hidden"] is True and r.json()["comment"] == "고쳤어요",
      r.text[:120])
r = client.delete(f"/api/v1/reviews/{own_id}", headers=OWNER)
check("숨김 글 본인 삭제 200", r.status_code == 200, str(r.status_code))
r = client.post("/api/v1/reviews", json={**TARGET, "nickname": "작성자", "rating": 5}, headers=OWNER)
check("삭제 후 새로 작성 가능 201(dead-end 해소)", r.status_code == 201, str(r.status_code))

# --------------------------------------------------------------------------
print("\n" + "=" * 64)
print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
for f in FAIL:
    print("  FAIL:", f)
db.close()
drop_schema(_BASE_DSN, _SCHEMA)
print("임시 스키마 삭제 완료")

sys.exit(1 if FAIL else 0)
