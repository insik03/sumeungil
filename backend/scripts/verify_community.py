"""부록 R 스텁 검증 — 리뷰/코스 공유 전 경로를 임시 DB 로 인메모리 실행.

`fastapi.testclient.TestClient` 는 ASGI 앱을 **프로세스 안에서** 호출한다(포트 바인딩 없음).
lifespan 을 일부러 열지 않는다(`with` 미사용) — 그래야 기동 프리워밍(공공 API 실호출)이
돌지 않아 네트워크 없이도 결정적으로 검증된다. DB 는 첫 요청에서 lazy 생성된다.

실행:
    cd backend && py scripts/verify_community.py
"""

from __future__ import annotations

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

from app.deps import get_community_write_limiter, get_database  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


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
section("1. 리뷰 생성 / 요약 / 중복")

A, B, C = dev("a"), dev("b"), dev("c")
TARGET = {"target_type": "spot", "target_id": "126508"}

r = client.post("/api/v1/reviews", json={**TARGET, "nickname": "여행자A", "rating": 5,
                                         "comment": "조용하고 좋았어요"}, headers=A)
check("POST /reviews 201", r.status_code == 201, str(r.status_code))
body = r.json()
review_a_id = body["review"]["id"]
check("생성본 is_mine=true", body["review"]["is_mine"] is True)
check("응답에 device_id 미노출", "device_id" not in r.text)
check("summary.count=1, average=5.0",
      body["summary"]["count"] == 1 and body["summary"]["average"] == 5.0, str(body["summary"]))

r = client.post("/api/v1/reviews", json={**TARGET, "nickname": "여행자A2", "rating": 3},
                headers=A)
check("같은 기기+대상 중복 → 409 REVIEW_EXISTS",
      r.status_code == 409 and r.json()["error"]["code"] == "REVIEW_EXISTS", str(r.status_code))

r = client.post("/api/v1/reviews", json={**TARGET, "nickname": "여행자B", "rating": 2,
                                         "comment": "사람이 많았어요"}, headers=B)
check("다른 기기는 같은 대상에 작성 가능 201", r.status_code == 201, str(r.status_code))
review_b_id = r.json()["review"]["id"]

r = client.get("/api/v1/reviews", params={**TARGET, "limit": 10}, headers=B)
data = r.json()
check("GET /reviews 200 + 2건", r.status_code == 200 and data["total"] == 2, str(data.get("total")))
check("평균 3.5 / 분포 5:1,2:1",
      data["summary"]["average"] == 3.5 and data["summary"]["distribution"]["5"] == 1
      and data["summary"]["distribution"]["2"] == 1, str(data["summary"]))
mine = {i["id"]: i["is_mine"] for i in data["items"]}
check("is_mine 은 헤더 기기 것만 true",
      mine.get(review_b_id) is True and mine.get(review_a_id) is False, str(mine))
check("목록 응답에 device_id 미노출", "device_id" not in r.text)

r = client.get("/api/v1/reviews", params=TARGET)
check("헤더 없이 조회 시 is_mine 전부 false",
      all(not i["is_mine"] for i in r.json()["items"]))

# --------------------------------------------------------------------------
section("2. 소유권 (수정 / 삭제)")

r = client.patch(f"/api/v1/reviews/{review_a_id}", json={"rating": 1}, headers=B)
check("타인 수정 → 403 NOT_OWNER",
      r.status_code == 403 and r.json()["error"]["code"] == "NOT_OWNER", str(r.status_code))

r = client.delete(f"/api/v1/reviews/{review_a_id}", headers=B)
check("타인 삭제 → 403 NOT_OWNER", r.status_code == 403, str(r.status_code))

r = client.patch(f"/api/v1/reviews/{review_a_id}", json={"rating": 4, "comment": "다시 가고 싶어요"},
                 headers=A)
check("본인 수정 200 + 반영", r.status_code == 200 and r.json()["rating"] == 4, str(r.status_code))
check("수정 응답 device_id 미노출", "device_id" not in r.text)

r = client.patch(f"/api/v1/reviews/{review_a_id}", json={"comment": None}, headers=A)
check("comment:null → 한줄평 삭제", r.status_code == 200 and r.json()["comment"] is None)

r = client.patch(f"/api/v1/reviews/{review_a_id}", json={}, headers=A)
check("빈 PATCH → 400 NOTHING_TO_UPDATE",
      r.status_code == 400 and r.json()["error"]["code"] == "NOTHING_TO_UPDATE", str(r.status_code))

r = client.post("/api/v1/reviews", json={**TARGET, "nickname": "익명", "rating": 5})
check("device_id 헤더 없음 → 400 DEVICE_ID_REQUIRED",
      r.status_code == 400 and r.json()["error"]["code"] == "DEVICE_ID_REQUIRED", str(r.status_code))

r = client.post("/api/v1/reviews", json={**TARGET, "nickname": "익명", "rating": 5},
                headers={"X-Device-Id": "short"})  # 8자 미만
check("형식 틀린 device_id → 400 INVALID_DEVICE_ID",
      r.status_code == 400 and r.json()["error"]["code"] == "INVALID_DEVICE_ID", str(r.status_code))

# --------------------------------------------------------------------------
section("3. 입력 검증 / 정제")

r = client.post("/api/v1/reviews",
                json={**TARGET, "target_id": "9001", "nickname": "x" * 21, "rating": 5}, headers=C)
check("닉네임 21자 → 422", r.status_code == 422, str(r.status_code))

r = client.post("/api/v1/reviews",
                json={**TARGET, "target_id": "9001", "nickname": "정상", "rating": 5,
                      "comment": "가" * 301}, headers=C)
check("한줄평 301자 → 422", r.status_code == 422, str(r.status_code))

r = client.post("/api/v1/reviews",
                json={**TARGET, "target_id": "9001", "nickname": "정상", "rating": 6}, headers=C)
check("rating 6 → 422", r.status_code == 422, str(r.status_code))

r = client.post("/api/v1/reviews",
                json={"target_type": "hotel", "target_id": "1", "nickname": "정상", "rating": 3},
                headers=C)
check("target_type 정의 밖 → 422", r.status_code == 422, str(r.status_code))

DIRTY = dev("dirty")
r = client.post("/api/v1/reviews",
                json={**TARGET, "target_id": "9002",
                      "nickname": "<b>해​커</b>",
                      "rating": 4,
                      "comment": "<script>alert(1)</script>줄바꿈제어﻿문자 &lt;img src=x onerror=1&gt;"},
                headers=DIRTY)
item = r.json()["review"]
check("HTML 태그 제거(닉네임)", r.status_code == 201 and "<" not in item["nickname"], item["nickname"])
check("script 태그 제거(한줄평)", "<script>" not in item["comment"] and "alert(1)" in item["comment"],
      item["comment"])
check("엔티티 인코딩 태그도 제거", "<img" not in item["comment"], item["comment"])
check("제어문자/제로폭 제거",
      "" not in item["comment"] and "﻿" not in item["comment"]
      and "​" not in item["nickname"])

r = client.post("/api/v1/reviews",
                json={**TARGET, "target_id": "9003", "nickname": "  <b></b>  ", "rating": 4},
                headers=dev("empty"))
check("정제 후 빈 닉네임 → 400 INVALID_NICKNAME",
      r.status_code == 400 and r.json()["error"]["code"] == "INVALID_NICKNAME", str(r.status_code))

r = client.post("/api/v1/reviews",
                json={**TARGET, "target_id": "abc;DROP TABLE reviews", "nickname": "정상",
                      "rating": 4}, headers=dev("sqli"))
check("target_id 문자셋 위반 → 400/422", r.status_code in (400, 422), str(r.status_code))
r = client.get("/api/v1/reviews", params=TARGET)
check("테이블 정상(인젝션 미발생)", r.status_code == 200 and r.json()["total"] == 2)

r = client.post("/api/v1/reviews",
                json={**TARGET, "target_id": 126509, "nickname": "숫자id", "rating": 5},
                headers=dev("numid"))
check("target_id 를 숫자로 보내도 수용(문자열 정규화)", r.status_code == 201, str(r.status_code))

# --------------------------------------------------------------------------
section("4. 신고 3건 → 자동 숨김")

r = client.post(f"/api/v1/reviews/{review_b_id}/report", json={"reason": "욕설"}, headers=A)
check("신고 1 → 202 accepted", r.status_code == 202 and r.json()["hidden"] is False, r.text)
r = client.post(f"/api/v1/reviews/{review_b_id}/report", json={"reason": "욕설 또"}, headers=A)
check("같은 기기 중복 신고는 카운트 안 됨(202, hidden=false)",
      r.status_code == 202 and r.json()["hidden"] is False, r.text)

r = client.post(f"/api/v1/reviews/{review_b_id}/report", json={"reason": "광고"}, headers=C)
check("신고 2(다른 기기) → 아직 노출", r.status_code == 202 and r.json()["hidden"] is False, r.text)

r = client.post(f"/api/v1/reviews/{review_b_id}/report", json={"reason": "스팸"}, headers=dev("d"))
check("신고 3(고유 3명) → 자동 hidden=true", r.status_code == 202 and r.json()["hidden"] is True,
      r.text)

r = client.get("/api/v1/reviews", params=TARGET)
ids = [i["id"] for i in r.json()["items"]]
check("숨김 리뷰는 목록에서 제외", review_b_id not in ids, str(ids))
check("숨김 리뷰는 요약 집계에서도 제외", r.json()["summary"]["count"] == 1, str(r.json()["summary"]))

r = client.post(f"/api/v1/reviews/{review_b_id}/report", json={"reason": "추가"}, headers=dev("e"))
check("이미 숨겨진 리뷰 신고 → 404", r.status_code == 404, str(r.status_code))

r = client.post("/api/v1/reviews/99999999/report", json={"reason": "없음"}, headers=dev("f"))
check("없는 리뷰 신고 → 404", r.status_code == 404, str(r.status_code))

# --------------------------------------------------------------------------
section("5. 일괄 요약 (N+1 방지)")

for i, tid in enumerate(["7001", "7002", "7003"]):
    client.post("/api/v1/reviews",
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

SPAM = dev("spam")
codes = []
for i in range(4):
    rr = client.post("/api/v1/reviews",
                     json={"target_type": "spot", "target_id": f"81{i}", "nickname": "도배",
                           "rating": 5}, headers=SPAM)
    codes.append(rr.status_code)
check("4번째 쓰기부터 429 RATE_LIMITED", codes[:3] == [201, 201, 201] and codes[3] == 429,
      str(codes))

# --------------------------------------------------------------------------
section("7. 코스 공유")

S1, S2 = dev("s1"), dev("s2")
course = {"region": {"code": "26350", "name": "부산 해운대구"},
          "spots": [{"id": 1, "name": "해운대해수욕장"}, {"id": 2, "name": "동백섬"}],
          "legs": [{"walk": {"minutes": 12, "meters": 900}}]}

r = client.post("/api/v1/courses/share",
                json={"nickname": "코스장인", "title": "해운대 반나절", "course": course}, headers=S1)
check("POST /courses/share 201", r.status_code == 201, str(r.status_code))
code = r.json()["share_code"]
check("share_code 8자 base32", len(code) == 8 and code.isalnum() and code.upper() == code, code)

r = client.get(f"/api/v1/courses/shared/{code}", headers=S2)
detail = r.json()
check("공유 상세 200 + payload 원형 보존",
      r.status_code == 200 and detail["course"] == course, str(r.status_code))
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
                               "view_count"}, str(list(lst["items"][0])))

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
    BACKEND_DIR / "app" / "services" / "concierge_service.py",
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
