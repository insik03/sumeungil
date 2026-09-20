"""부록 R 스텁 검증 — 리뷰/코스 공유 전 경로를 임시 DB 로 인메모리 실행.

`fastapi.testclient.TestClient` 는 ASGI 앱을 **프로세스 안에서** 호출한다(포트 바인딩 없음).
lifespan 을 일부러 열지 않는다(`with` 미사용) — 그래야 기동 프리워밍(공공 API 실호출)이
돌지 않아 네트워크 없이도 결정적으로 검증된다. DB 는 첫 요청에서 lazy 생성된다.

실행:
    cd backend && py scripts/verify_community.py
"""

from __future__ import annotations

# 2026-09-03 — 공유 코스 검증은 시드에 실제로 있는 스팟 id를 써야 한다. 2026-08-20부터
# rebuild_course_for_store(strict=True)가 없는 스팟을 400 INVALID_COURSE로 거부한다
# (이 스크립트는 CI가 2026-09-02에 생기기 전까지 안 돌아서 그때 깨진 걸 몰랐다).
def _real_spot_ids(n: int = 2) -> list[int]:
    from app.deps import get_spot_repository
    return [s.id for s in get_spot_repository().all_spots()[:n]]

import os
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# !!! import 전에 !!! 임시 Postgres 스키마를 만들어 주입한다(개발용 실데이터를 건드리지
# 않게 — 2026-08-17 PostgreSQL 전환으로 tempfile SQLite 파일 방식에서 바뀌었다).
from _pg_test_helpers import drop_schema, isolated_database_url  # noqa: E402

_ISOLATED_DSN, _BASE_DSN, _SCHEMA = isolated_database_url()
os.environ["DATABASE_URL"] = _ISOLATED_DSN

from fastapi.testclient import TestClient  # noqa: E402

from app.deps import get_community_write_limiter, get_database, get_user_auth  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories import user_repo  # noqa: E402

client = TestClient(app)


def login(sub: str, name: str) -> TestClient:
    """세션 쿠키가 박힌 TestClient. 2026-09-20 부터 후기 쓰기는 로그인 필수라 필요하다."""
    db = get_database()
    auth = get_user_auth()
    user = db.write(
        lambda conn: user_repo.upsert_login(
            conn,
            provider="google",
            provider_sub=sub,
            email=f"{sub}@example.com",
            email_verified=True,
            default_display_name=name,
            now_iso="2026-09-20T00:00:00+09:00",
        )
    )
    token, _ = auth.issue_token(
        user_id=user["id"], email=user["email"], epoch=user_repo.session_epoch_of(user)
    )
    c = TestClient(app)
    c.cookies.set(auth.cookie_name, token)
    return c


def reset_quota() -> None:
    """device 별 쓰기 카운터를 비운다(섹션 간 간섭 제거).

    쿼터는 **성공/실패와 무관하게 시도 1건을 소모**한다(409 중복 시도도 카운트된다).
    레이트 리밋으로서는 그것이 옳지만(실패 요청 반복도 자원을 쓴다), 검증 시나리오가
    서로를 밀어내므로 섹션 경계에서 초기화한다. 쿼터 자체는 §6 에서 따로 검증한다.
    """
    get_community_write_limiter.cache_clear()

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    (PASS if cond else FAIL).append(f"{name}{(' — ' + extra) if extra else ''}")
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


def dev(tag: str) -> dict[str, str]:
    """기기 식별자 헤더. 실제 프론트는 UUID v4 를 localStorage 에 보관한다."""
    return {"X-Device-Id": f"dev-{tag}-{uuid.uuid4().hex[:12]}"}


def section(title: str) -> None:
    reset_quota()
    print(f"\n=== {title} ===")


# --------------------------------------------------------------------------
section("1. 리뷰 생성 / 요약 / 중복 — 소유자는 계정이다(2026-09-20)")

A, B, C = dev("a"), dev("b"), dev("c")
# 기기 헤더는 여전히 필요하다(쓰기 쿼터가 기기 단위). 다만 **소유권은 계정**이다.
ca, cb, cc = login("rev-a", "여행자A"), login("rev-b", "여행자B"), login("rev-c", "여행자C")
TARGET = {"target_type": "spot", "target_id": "126508"}

r = ca.post("/api/v1/reviews", json={**TARGET, "nickname": "여행자A", "rating": 5,
                                     "comment": "조용하고 좋았어요"}, headers=A)
check("POST /reviews 201", r.status_code == 201, str(r.status_code))
body = r.json()
review_a_id = body["review"]["id"]
check("생성본 is_mine=true", body["review"]["is_mine"] is True)
check("응답에 device_id·user_id 미노출", "device_id" not in r.text and "user_id" not in r.text)
check("summary.count=1, average=5.0",
      body["summary"]["count"] == 1 and body["summary"]["average"] == 5.0, str(body["summary"]))

r = ca.post("/api/v1/reviews", json={**TARGET, "nickname": "여행자A2", "rating": 3}, headers=A)
check("같은 계정+대상 중복 → 409 REVIEW_EXISTS",
      r.status_code == 409 and r.json()["error"]["code"] == "REVIEW_EXISTS", str(r.status_code))

# 핵심 회귀: 종전엔 기기를 바꾸면 같은 사람이 같은 대상에 또 쓸 수 있었다.
r = ca.post("/api/v1/reviews", json={**TARGET, "nickname": "여행자A3", "rating": 1}, headers=dev("a2"))
check("같은 계정이 **다른 기기**로 써도 409(기기 바꿔 중복 작성 불가)",
      r.status_code == 409 and r.json()["error"]["code"] == "REVIEW_EXISTS", str(r.status_code))

r = cb.post("/api/v1/reviews", json={**TARGET, "nickname": "여행자B", "rating": 2,
                                     "comment": "사람이 많았어요"}, headers=B)
check("다른 계정은 같은 대상에 작성 가능 201", r.status_code == 201, str(r.status_code))
review_b_id = r.json()["review"]["id"]

r = cb.get("/api/v1/reviews", params={**TARGET, "limit": 10})
data = r.json()
check("GET /reviews 200 + 2건", r.status_code == 200 and data["total"] == 2, str(data.get("total")))
check("평균 3.5 / 분포 5:1,2:1",
      data["summary"]["average"] == 3.5 and data["summary"]["distribution"]["5"] == 1
      and data["summary"]["distribution"]["2"] == 1, str(data["summary"]))
mine = {i["id"]: i["is_mine"] for i in data["items"]}
check("is_mine 은 로그인 계정 것만 true",
      mine.get(review_b_id) is True and mine.get(review_a_id) is False, str(mine))
check("목록 응답에 device_id·user_id 미노출", "device_id" not in r.text and "user_id" not in r.text)

# 핵심 회귀: 기기가 달라도 로그인만 하면 내 글이 내 글로 보인다(종전엔 저장공간 지우면 남의 글이 됐다).
ca2 = login("rev-a", "여행자A")  # 같은 계정, 새 클라이언트(= 다른 기기)
r = ca2.get("/api/v1/reviews", params={**TARGET, "limit": 10})
mine2 = {i["id"]: i["is_mine"] for i in r.json()["items"]}
check("기기가 달라도 같은 계정이면 is_mine=true", mine2.get(review_a_id) is True, str(mine2))

r = client.get("/api/v1/reviews", params=TARGET)
check("비로그인 조회는 200 + is_mine 전부 false",
      r.status_code == 200 and all(not i["is_mine"] for i in r.json()["items"]), str(r.status_code))

# --------------------------------------------------------------------------
section("2. 로그인 필수 / 소유권 (수정 / 삭제)")

# 2026-09-20 — 종전엔 이 게이트가 프론트에만 있어서 X-Device-Id 만 있으면 비로그인으로 쓸 수 있었다.
r = client.post("/api/v1/reviews", json={**TARGET, "target_id": "9100", "nickname": "익명", "rating": 5},
                headers=dev("anon"))
check("비로그인 작성 → 401", r.status_code == 401, str(r.status_code))
r = client.patch(f"/api/v1/reviews/{review_a_id}", json={"rating": 1}, headers=dev("anon"))
check("비로그인 수정 → 401", r.status_code == 401, str(r.status_code))
r = client.delete(f"/api/v1/reviews/{review_a_id}", headers=dev("anon"))
check("비로그인 삭제 → 401", r.status_code == 401, str(r.status_code))
r = client.post(f"/api/v1/reviews/{review_a_id}/report", json={"reason": "스팸이에요"}, headers=dev("anon"))
check("비로그인 신고 → 401", r.status_code == 401, str(r.status_code))
check("비로그인 작성 시도가 글을 남기지 않는다",
      client.get("/api/v1/reviews", params={**TARGET, "target_id": "9100"}).json()["total"] == 0)

r = cb.patch(f"/api/v1/reviews/{review_a_id}", json={"rating": 1}, headers=B)
check("타인 수정 → 403 NOT_OWNER",
      r.status_code == 403 and r.json()["error"]["code"] == "NOT_OWNER", str(r.status_code))

r = cb.delete(f"/api/v1/reviews/{review_a_id}", headers=B)
check("타인 삭제 → 403 NOT_OWNER", r.status_code == 403, str(r.status_code))

# 기기를 바꿔도 내 글은 내가 고친다(계정 소유의 핵심 이득).
r = ca2.patch(f"/api/v1/reviews/{review_a_id}", json={"rating": 4, "comment": "다시 가고 싶어요"},
              headers=dev("a3"))
check("본인 수정 200 + 반영(다른 기기에서도)",
      r.status_code == 200 and r.json()["rating"] == 4, str(r.status_code))
check("수정 응답 device_id·user_id 미노출", "device_id" not in r.text and "user_id" not in r.text)

r = ca.patch(f"/api/v1/reviews/{review_a_id}", json={"comment": None}, headers=A)
check("comment:null → 한줄평 삭제", r.status_code == 200 and r.json()["comment"] is None)

r = ca.patch(f"/api/v1/reviews/{review_a_id}", json={}, headers=A)
check("빈 PATCH → 400 NOTHING_TO_UPDATE",
      r.status_code == 400 and r.json()["error"]["code"] == "NOTHING_TO_UPDATE", str(r.status_code))

r = ca.post("/api/v1/reviews", json={**TARGET, "target_id": "9101", "nickname": "익명", "rating": 5})
check("device_id 헤더 없음 → 400 DEVICE_ID_REQUIRED",
      r.status_code == 400 and r.json()["error"]["code"] == "DEVICE_ID_REQUIRED", str(r.status_code))

r = ca.post("/api/v1/reviews", json={**TARGET, "target_id": "9101", "nickname": "익명", "rating": 5},
            headers={"X-Device-Id": "short"})  # 8자 미만
check("형식 틀린 device_id → 400 INVALID_DEVICE_ID",
      r.status_code == 400 and r.json()["error"]["code"] == "INVALID_DEVICE_ID", str(r.status_code))

# --------------------------------------------------------------------------
section("3. 입력 검증 / 정제")

# 범위·형식 검증은 pydantic 이 본문에서 먼저 거르므로 계정과 무관하게 그대로다.
r = cc.post("/api/v1/reviews",
            json={**TARGET, "target_id": "9001", "nickname": "x" * 21, "rating": 5}, headers=C)
check("닉네임 21자 → 422", r.status_code == 422, str(r.status_code))

r = cc.post("/api/v1/reviews",
            json={**TARGET, "target_id": "9001", "nickname": "정상", "rating": 5,
                  "comment": "가" * 301}, headers=C)
check("한줄평 301자 → 422", r.status_code == 422, str(r.status_code))

r = cc.post("/api/v1/reviews",
            json={**TARGET, "target_id": "9001", "nickname": "정상", "rating": 6}, headers=C)
check("rating 6 → 422", r.status_code == 422, str(r.status_code))

r = cc.post("/api/v1/reviews",
            json={"target_type": "hotel", "target_id": "1", "nickname": "정상", "rating": 3},
            headers=C)
check("target_type 정의 밖 → 422", r.status_code == 422, str(r.status_code))

# 2026-09-20 — 로그인이 필수가 되면서 **닉네임은 항상 계정 표시 이름**이다. 본문의 nickname 은
# 계약(부록 R) 유지를 위해 계속 받지만 서버가 통째로 무시한다 → 닉네임으로 뭘 주입하든 안 통한다.
DIRTY = dev("dirty")
r = cc.post("/api/v1/reviews",
            json={**TARGET, "target_id": "9002",
                  "nickname": "<b>해​커</b>",
                  "rating": 4,
                  "comment": "<script>alert(1)</script>줄바꿈제어﻿문자 &lt;img src=x onerror=1&gt;"},
            headers=DIRTY)
item = r.json()["review"]
check("클라이언트 닉네임 무시 → 계정 표시 이름이 나간다",
      r.status_code == 201 and item["nickname"] == "여행자C", item["nickname"])
check("script 태그 제거(한줄평)", "<script>" not in item["comment"] and "alert(1)" in item["comment"],
      item["comment"])
check("엔티티 인코딩 태그도 제거", "<img" not in item["comment"], item["comment"])
check("제어문자/제로폭 제거",
      "" not in item["comment"] and "﻿" not in item["comment"])

# 표시 이름 자체의 정제는 가입 경로(clean_user_text)가 책임진다 — verify_auth.py 참고.
# 여기서는 "본문 닉네임이 빈 값이어도 계정 이름 덕에 성공한다"만 확인한다(종전 400 경로는 도달 불가).
r = cc.post("/api/v1/reviews",
            json={**TARGET, "target_id": "9003", "nickname": "  <b></b>  ", "rating": 4},
            headers=dev("empty"))
check("본문 닉네임이 비어도 201(계정 이름 사용)",
      r.status_code == 201 and r.json()["review"]["nickname"] == "여행자C", str(r.status_code))

r = cc.post("/api/v1/reviews",
            json={**TARGET, "target_id": "abc;DROP TABLE reviews", "nickname": "정상",
                  "rating": 4}, headers=dev("sqli"))
check("target_id 문자셋 위반 → 400/422", r.status_code in (400, 422), str(r.status_code))
r = client.get("/api/v1/reviews", params=TARGET)
check("테이블 정상(인젝션 미발생)", r.status_code == 200 and r.json()["total"] == 2)

r = cc.post("/api/v1/reviews",
            json={**TARGET, "target_id": 126509, "nickname": "숫자id", "rating": 5},
            headers=dev("numid"))
check("target_id 를 숫자로 보내도 수용(문자열 정규화)", r.status_code == 201, str(r.status_code))

# --------------------------------------------------------------------------
section("4. 신고 3건 → 자동 숨김")

# 2026-09-20 — 신고도 로그인 필수. 중복 방지 기준(기기 + IP 가명 지문)은 F-03 그대로다.
r = ca.post(f"/api/v1/reviews/{review_b_id}/report", json={"reason": "욕설"}, headers=A)
check("신고 1 → 202 accepted", r.status_code == 202 and r.json()["hidden"] is False, r.text)
r = ca.post(f"/api/v1/reviews/{review_b_id}/report", json={"reason": "욕설 또"}, headers=A)
check("같은 기기 중복 신고는 카운트 안 됨(202, hidden=false)",
      r.status_code == 202 and r.json()["hidden"] is False, r.text)

r = cc.post(f"/api/v1/reviews/{review_b_id}/report", json={"reason": "광고"}, headers=C)
check("신고 2(다른 기기) → 아직 노출", r.status_code == 202 and r.json()["hidden"] is False, r.text)

r = login("rev-d", "여행자D").post(f"/api/v1/reviews/{review_b_id}/report", json={"reason": "스팸"}, headers=dev("d"))
check("신고 3(고유 3명) → 자동 hidden=true", r.status_code == 202 and r.json()["hidden"] is True,
      r.text)

r = client.get("/api/v1/reviews", params=TARGET)
ids = [i["id"] for i in r.json()["items"]]
check("숨김 리뷰는 목록에서 제외", review_b_id not in ids, str(ids))
check("숨김 리뷰는 요약 집계에서도 제외", r.json()["summary"]["count"] == 1, str(r.json()["summary"]))

r = login("rev-e", "여행자E").post(f"/api/v1/reviews/{review_b_id}/report", json={"reason": "추가"}, headers=dev("e"))
check("이미 숨겨진 리뷰 신고 → 404", r.status_code == 404, str(r.status_code))

r = login("rev-f", "여행자F").post("/api/v1/reviews/99999999/report", json={"reason": "없음"}, headers=dev("f"))
check("없는 리뷰 신고 → 404", r.status_code == 404, str(r.status_code))

# --------------------------------------------------------------------------
section("5. 일괄 요약 (N+1 방지)")

# 대상이 서로 달라 한 계정으로도 3건을 쓸 수 있다(중복 제약은 계정+대상 조합이다).
cbulk = login("rev-bulk", "요약러")
for i, tid in enumerate(["7001", "7002", "7003"]):
    cbulk.post("/api/v1/reviews",
               json={"target_type": "spot", "target_id": tid, "nickname": f"u{i}", "rating": i + 3},
               headers=dev(f"bulk{i}"))

db = get_database()
# 2026-08-17 PostgreSQL 전환 — sqlite3.Connection.set_trace_callback(SQLite 전용)을
# 대체한다. review_repo.bulk_rating_histogram 은 그 자체가 "IN절 단일 쿼리 1회"만 실행
#하도록 고정돼 있으므로(코드 확인됨), 이 함수의 호출 횟수 = 실제 SQL 실행 횟수와 동치다.
import app.repositories.review_repo as _review_repo_module  # noqa: E402

_bulk_calls: list[int] = []
_original_bulk = _review_repo_module.bulk_rating_histogram


def _counting_bulk(*a, **kw):
    _bulk_calls.append(1)
    return _original_bulk(*a, **kw)


_review_repo_module.bulk_rating_histogram = _counting_bulk
r = client.get("/api/v1/reviews/summary",
               params={"target_type": "spot", "ids": "7001,7002,7003,9999,7001"})
_review_repo_module.bulk_rating_histogram = _original_bulk
selects = _bulk_calls

data = r.json()["summaries"]
check("일괄 요약 200", r.status_code == 200, str(r.status_code))
check("요청 id 전부 포함(리뷰 없는 9999 도 count:0)",
      set(data) == {"7001", "7002", "7003", "9999"} and data["9999"]["count"] == 0, str(list(data)))
check("리뷰 없는 대상 average=null", data["9999"]["average"] is None)
check("값 정확(7001=3.0, 7003=5.0)",
      data["7001"]["average"] == 3.0 and data["7003"]["average"] == 5.0, str(data))
check("N+1 없음 — SELECT 정확히 1회", len(selects) == 1, f"selects={len(selects)}")

# --------------------------------------------------------------------------
section("6. 쓰기 쿼터 (device_id 분당 3건)")

# 쿼터는 계정 전환 뒤에도 **기기 단위**다(로그인해도 한 기기에서 분당 3건).
SPAM = dev("spam")
cspam = login("rev-spam", "도배러")
codes = []
for i in range(4):
    rr = cspam.post("/api/v1/reviews",
                    json={"target_type": "spot", "target_id": f"81{i}", "nickname": "도배",
                          "rating": 5}, headers=SPAM)
    codes.append(rr.status_code)
check("4번째 쓰기부터 429 RATE_LIMITED", codes[:3] == [201, 201, 201] and codes[3] == 429,
      str(codes))

# --------------------------------------------------------------------------
section("7. 코스 공유")

S1, S2 = dev("s1"), dev("s2")
course = {"region": {"code": "26350", "name": "부산 해운대구"},
          "spots": [{"id": sid} for sid in _real_spot_ids(2)],
          "legs": [{"walk": {"minutes": 12, "meters": 900}}]}

r = client.post("/api/v1/courses/share",
                json={"nickname": "코스장인", "title": "해운대 반나절", "course": course}, headers=S1)
check("POST /courses/share 201", r.status_code == 201, str(r.status_code))
code = r.json()["share_code"]
check("share_code 8자 base32", len(code) == 8 and code.isalnum() and code.upper() == code, code)

r = client.get(f"/api/v1/courses/shared/{code}", headers=S2)
detail = r.json()
# 2026-08-20부터 저장 직전에 rebuild_course_for_store 가 스팟을 서버 원본으로 다시 채운다
# (클라이언트가 보낸 이름·사진은 버림) — 그래서 "원형 보존"은 스팟 id 순서·구간 정보로 본다.
check("공유 상세 200 + 스팟 순서·구간 보존",
      r.status_code == 200
      and [s["id"] for s in detail["course"]["spots"]] == [s["id"] for s in course["spots"]]
      and detail["course"]["legs"][0]["walk"]["minutes"] == 12,
      f'{r.status_code} {detail.get("course", {}).get("legs")}')
check("spot_count 파생", detail["spot_count"] == 2, str(detail.get("spot_count")))
check("조회수 증가(1)", detail["view_count"] == 1, str(detail.get("view_count")))
check("타인 조회 is_mine=false", detail["is_mine"] is False)
check("공유 상세에 device_id 미노출", "device_id" not in r.text)

r = client.get(f"/api/v1/courses/shared/{code.lower()}", headers=S1)
check("소문자 코드 관용 + 본인 is_mine=true",
      r.status_code == 200 and r.json()["is_mine"] is True, str(r.status_code))
check("조회수 2로 증가", r.json()["view_count"] == 2, str(r.json().get("view_count")))

r = client.get("/api/v1/courses/shared", params={"limit": 10})
lst = r.json()
check("피드 목록 200 + 1건", r.status_code == 200 and lst["total"] == 1, str(lst.get("total")))
check("목록 항목에 payload 미포함", "course" not in lst["items"][0], str(list(lst["items"][0])))
check("목록 항목 필드 계약",
      set(lst["items"][0]) == {"share_code", "nickname", "title", "spot_count", "created_at",
                               "view_count", "like_count", "liked_by_me"},  # R.14(2026-08-20) 좋아요 필드 추가
      str(list(lst["items"][0])))

r = client.get("/api/v1/courses/shared/AAAAAAAA")
check("없는 코드 → 404", r.status_code == 404, str(r.status_code))
r = client.get("/api/v1/courses/shared/!!")
check("형식 틀린 코드 → 404", r.status_code == 404, str(r.status_code))

big = {"spots": [{"id": i, "name": "가" * 200} for i in range(200)]}
r = client.post("/api/v1/courses/share",
                json={"nickname": "빅", "title": "너무 큰 코스", "course": big}, headers=dev("big"))
check("32KB 초과 → 413 COURSE_TOO_LARGE",
      r.status_code == 413 and r.json()["error"]["code"] == "COURSE_TOO_LARGE", str(r.status_code))

deep: dict = {"a": {}}
node = deep["a"]
for _ in range(40):
    node["a"] = {}
    node = node["a"]
r = client.post("/api/v1/courses/share",
                json={"nickname": "깊", "title": "깊은 중첩", "course": deep}, headers=dev("deep"))
check("과도한 중첩 → 400 INVALID_COURSE",
      r.status_code == 400 and r.json()["error"]["code"] == "INVALID_COURSE", str(r.status_code))

r = client.post("/api/v1/courses/share",
                json={"nickname": "빈", "title": "빈 코스", "course": {}}, headers=dev("empty2"))
check("빈 course → 400 INVALID_COURSE", r.status_code == 400, str(r.status_code))

r = client.delete(f"/api/v1/courses/shared/{code}", headers=S2)
check("타인 공유 삭제 → 403 NOT_OWNER",
      r.status_code == 403 and r.json()["error"]["code"] == "NOT_OWNER", str(r.status_code))

r = client.delete(f"/api/v1/courses/shared/{code}", headers=S1)
check("본인 공유 삭제 200", r.status_code == 200, str(r.status_code))
r = client.get(f"/api/v1/courses/shared/{code}")
check("삭제 후 조회 404", r.status_code == 404, str(r.status_code))

# --------------------------------------------------------------------------
section("8. 불변식 — 사용자 텍스트가 LLM 경로에 닿지 않는가 (정적 검사)")

llm_dirs = [BACKEND_DIR / "app" / "ai"]
llm_files = [
    BACKEND_DIR / "app" / "services" / "tips_service.py",
    BACKEND_DIR / "app" / "services" / "course_summary_service.py",
    BACKEND_DIR / "app" / "services" / "spot_detail_service.py",
]
targets = [p for d in llm_dirs for p in d.glob("*.py")] + [p for p in llm_files if p.exists()]
banned = ("review_service", "share_service", "review_repo", "shared_course_repo",
          "schemas.community", "db.sqlite")
hits = [f"{p.name}:{b}" for p in targets for b in banned if b in p.read_text(encoding="utf-8")]
check("LLM 관련 모듈이 리뷰/공유 모듈을 import 하지 않음", not hits, str(hits))

# --------------------------------------------------------------------------
section("9. 저장소 재기동 내구성")

db.close()
r = client.get("/api/v1/reviews", params=TARGET)
check("커넥션 재연결 후에도 데이터 유지", r.status_code == 200 and r.json()["total"] == 1,
      str(r.json().get("total")))

# --------------------------------------------------------------------------
print("\n" + "=" * 64)
print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print("  FAIL:", f)
print(f"임시 스키마: {_SCHEMA}")
get_database().close()
drop_schema(_BASE_DSN, _SCHEMA)
print("임시 스키마 삭제 완료")

sys.exit(1 if FAIL else 0)
