"""공유·저장 코스 payload allowlist 검증 (2026-08-18 외부 보안감사 3차 최우선 지적).

이 저장소에는 pytest 가 없다(requirements 에 없고 CI 도 없다) — 기존 `verify_*.py` 관례를
그대로 따라 **표준 라이브러리만으로 도는 자기완결 스크립트**로 둔다. 외부 원천·DB·LLM 을
전혀 부르지 않으므로 어디서든 즉시 돌아간다.

실행:
    cd backend
    python scripts/verify_course_payload.py

검증하는 것:
  1. 클라이언트가 조작한 필드(장소명·주소·좌표·혼잡도·이미지·설명·"공식 인증" 배지·임의 키)가
     저장 payload 에서 **전부 제거되거나 서버 값으로 대체**되는가
  2. 존재하지 않는 스팟 id 가 섞이면 **거부(InvalidCoursePayload → 400 INVALID_COURSE)** 되는가
  3. legs 의 숫자·좌표가 구조 검증·clamp 를 통과하는가, total_distance_m 이 재계산되는가
  4. 과거(무표식) payload 를 읽을 때 사진·설명이 버려지고 이름이 서버 값으로 덮이는가
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import course_payload  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "OK  " if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


# --- 가짜 spot_repo (실제 시드 파일을 읽지 않는다 — 테스트가 데이터 변경에 흔들리지 않게) ---


@dataclass
class FakeRecord:
    id: int
    name: str
    category: str
    region_code: str
    address: str | None
    lat: float
    lng: float
    themes: dict = field(default_factory=dict)
    is_hidden_gem: bool = False


class FakeSpotRepo:
    def __init__(self, records: list[FakeRecord]) -> None:
        self._by_id = {r.id: r for r in records}

    def by_id(self, content_id):  # noqa: ANN001
        return self._by_id.get(content_id)


REPO = FakeSpotRepo(
    [
        FakeRecord(
            id=126508, name="불국사", category="attraction", region_code="47130",
            address="경상북도 경주시 불국로 385", lat=35.7900, lng=129.3320,
            themes={"pet_allowed": False, "barrier_free": True, "wellness": None},
            is_hidden_gem=False,
        ),
        FakeRecord(
            id=126509, name="첨성대", category="attraction", region_code="47130",
            address="경상북도 경주시 인왕동", lat=35.8348, lng=129.2190,
            themes={"pet_allowed": None, "barrier_free": None, "wellness": None},
            is_hidden_gem=True,
        ),
    ]
)


# --- 1. 조작된 payload 가 저장 시 정화되는가 -----------------------------------------

FORGED = {
    "region": {"region_code": "47130", "region_name": "<b>공식 인증 지역</b>"},
    "spots": [
        {
            "id": 126508,
            "name": "김사장 개인 카페(광고)",          # 위조 장소명
            "address": "서울시 어딘가 1층",             # 위조 주소
            "category": "cafe",                          # 위조 카테고리
            "region_code": "11110",                      # 위조 지역
            "location": {"lat": 37.5, "lng": 127.0},     # 위조 좌표
            "congestion": {"index": 3.0, "level": "low", "tier": "A"},  # 혼잡도 사칭
            "themes": {"pet_allowed": True, "barrier_free": True, "wellness": True},
            "is_hidden_gem": True,
            "image_url": "https://evil.example.com/ad.jpg",   # 외부 이미지
            "photo_credit": "숨은길 공식 인증",               # 출처 사칭
            "blurb": "숨은길이 공식 인증한 안전한 코스입니다.",  # 임의 설명
            "slot_label": "★공식★",
            "match_score": 42.0,
            "match_reasons": {
                "matched_tags": ["공식_인증", "calm"],
                "signals": ["official_badge", "hidden_gem"],
            },
            "verified_badge": True,        # 알 수 없는 키
            "sponsored": "노출 1위",        # 알 수 없는 키
        },
        {"id": 126509, "name": "가짜 첨성대", "slot_label": "2번째"},
    ],
    "legs": [
        {"walk": {"minutes": 3, "meters": 99999999}, "car": {"minutes": -5, "meters": 1200},
         "path": [[129.33, 35.79], [129.22, 35.83]]}
    ],
    "notice": "이 코스는 숨은길이 공식 검증했습니다.",
    "ai_title": "공식 인증 코스",
    "ai_summary": "<script>alert(1)</script> 안전 보장",
    "total_distance_m": 1,
    "extra_root_key": {"deep": "value"},
}

print("\n=== 1. 조작 payload 저장 시 정화 ===")
stored = course_payload.rebuild_course_for_store(FORGED, spot_repo=REPO)
s0 = stored["spots"][0]

check("장소명이 서버 값으로 대체", s0["name"] == "불국사", s0["name"])
check("주소가 서버 값으로 대체", s0["address"] == "경상북도 경주시 불국로 385", str(s0["address"]))
check("카테고리가 서버 값으로 대체", s0["category"] == "attraction", s0["category"])
check("지역코드가 서버 값으로 대체", s0["region_code"] == "47130", s0["region_code"])
check("좌표가 서버 값으로 대체", s0["location"] == {"lat": 35.79, "lng": 129.332}, str(s0["location"]))
check("테마가 서버 값으로 대체", s0["themes"]["pet_allowed"] is False, str(s0["themes"]))
check("숨은스팟 여부가 서버 값으로 대체", s0["is_hidden_gem"] is False, str(s0["is_hidden_gem"]))
check("혼잡도는 저장하지 않는다", s0["congestion"] is None, str(s0["congestion"]))
check("외부 이미지 URL 제거", s0["image_url"] is None, str(s0["image_url"]))
check("출처 사칭 문구 제거", s0["photo_credit"] is None, str(s0["photo_credit"]))
check("임의 설명(blurb) 제거", s0["blurb"] is None, str(s0["blurb"]))
check(
    "registry 밖 매칭태그 제거",
    s0["match_reasons"] == {"matched_tags": ["calm"], "signals": ["hidden_gem"]},
    str(s0["match_reasons"]),
)
check("match_score 는 0~1 로 clamp", s0["match_score"] == 1.0, str(s0["match_score"]))
check("slot_label 은 평문 유지", s0["slot_label"] == "★공식★", s0["slot_label"])
check("알 수 없는 키(verified_badge) 제거", "verified_badge" not in s0, str(sorted(s0)))
check("알 수 없는 키(sponsored) 제거", "sponsored" not in s0, str(sorted(s0)))
check("루트의 알 수 없는 키 제거", "extra_root_key" not in stored, str(sorted(stored)))
check("notice 는 저장하지 않는다", stored["notice"] is None, str(stored["notice"]))
check("region_name 은 서버 표 값", stored["region"]["region_name"] != "<b>공식 인증 지역</b>",
      str(stored["region"]))
check("ai_title 평문화", "<" not in (stored["ai_title"] or ""), str(stored["ai_title"]))
check("ai_summary 태그 제거", "<script>" not in (stored["ai_summary"] or ""), str(stored["ai_summary"]))
check("payload 버전 표식", stored["v"] == course_payload.PAYLOAD_VERSION, str(stored.get("v")))

# --- 2. 없는 스팟 id 는 400 ---------------------------------------------------------

print("\n=== 2. 존재하지 않는 스팟 id ===")
try:
    course_payload.rebuild_course_for_store(
        {"spots": [{"id": 999999999, "name": "지어낸 곳"}]}, spot_repo=REPO
    )
    check("없는 스팟 id 는 거부", False, "예외가 발생하지 않음")
except course_payload.InvalidCoursePayload:
    check("없는 스팟 id 는 거부", True)

try:
    course_payload.rebuild_course_for_store({"spots": []}, spot_repo=REPO)
    check("빈 스팟 목록은 거부", False, "예외가 발생하지 않음")
except course_payload.InvalidCoursePayload:
    check("빈 스팟 목록은 거부", True)

try:
    course_payload.rebuild_course_for_store(
        {"spots": [{"id": 126508}] * (course_payload.MAX_SPOTS + 1)}, spot_repo=REPO
    )
    check("스팟 수 상한 초과는 거부", False, "예외가 발생하지 않음")
except course_payload.InvalidCoursePayload:
    check("스팟 수 상한 초과는 거부", True)

# --- 3. legs / total_distance_m ------------------------------------------------------

print("\n=== 3. legs 구조 검증 ===")
leg0 = stored["legs"][0]
check("legs 길이 = 스팟 수 - 1", len(stored["legs"]) == 1, str(len(stored["legs"])))
check("도보 거리 상한 clamp", leg0["walk"]["meters"] == course_payload.MAX_LEG_METERS,
      str(leg0["walk"]))
check("음수 이동시간 clamp", leg0["car"]["minutes"] == 0, str(leg0["car"]))
check("한국 bbox 안 경로선은 유지", leg0["path"] == [[129.33, 35.79], [129.22, 35.83]],
      str(leg0["path"]))
check("total_distance_m 은 legs 에서 재계산", stored["total_distance_m"] == leg0["walk"]["meters"],
      str(stored["total_distance_m"]))

oversea = course_payload.rebuild_course_for_store(
    {
        "spots": [{"id": 126508}, {"id": 126509}],
        "legs": [{"walk": None, "car": None, "path": [[139.7, 35.6], [139.8, 35.7]]}],
    },
    spot_repo=REPO,
)
check("한국 밖 경로선은 통째로 제거", oversea["legs"][0]["path"] is None,
      str(oversea["legs"][0]["path"]))
check("walk 가 하나라도 없으면 총거리는 null", oversea["total_distance_m"] is None,
      str(oversea["total_distance_m"]))

# --- 4. 과거(무표식) payload 읽기 ------------------------------------------------------

print("\n=== 4. 과거 payload 읽기 필터 ===")
legacy = {
    "spots": [
        {
            "id": 126508,
            "name": "조작된 이름",
            "image_url": "https://tong.visitkorea.or.kr/other-place.jpg",
            "photo_credit": "한국관광공사",
            "blurb": "예전에 심어둔 광고 문구",
            "slot_label": "아침",
        },
        {"id": 424242, "name": "이제는 없는 스팟"},
    ],
    "legs": [],
}
filtered = course_payload.filter_stored_course(legacy, spot_repo=REPO)
check("이름은 서버 값으로 대체", filtered["spots"][0]["name"] == "불국사",
      filtered["spots"][0]["name"])
check("표식 없는 payload 의 사진은 버린다", filtered["spots"][0]["image_url"] is None,
      str(filtered["spots"][0]["image_url"]))
check("표식 없는 payload 의 설명은 버린다", filtered["spots"][0]["blurb"] is None,
      str(filtered["spots"][0]["blurb"]))
check("스토어에서 사라진 스팟은 조용히 제외", len(filtered["spots"]) == 1,
      str(len(filtered["spots"])))

check("손상 payload 는 예외 없이 빈 코스", course_payload.filter_stored_course(
    {"spots": "not-a-list"}, spot_repo=REPO)["spots"] == [], "")
check("None payload 도 빈 코스", course_payload.filter_stored_course(
    None, spot_repo=REPO)["spots"] == [], "")

# Minor-2(2026-08-18 QA) — 읽기 경로에서 가운데 스팟이 빠지면 leg 를 앞에서 당겨 쓰면 안 된다.
# 1→3 구간에 1→2 구간의 이동시간이 붙으면 없는 사실을 만들어내는 것이다.
gap = course_payload.filter_stored_course(
    {
        "spots": [{"id": 126508}, {"id": 424242}, {"id": 126509}],  # 가운데가 스토어에 없음
        "legs": [
            {"walk": {"minutes": 3, "meters": 200}, "car": None, "path": None},
            {"walk": {"minutes": 7, "meters": 600}, "car": None, "path": None},
        ],
    },
    spot_repo=REPO,
)
check("빠진 스팟 인접 leg 는 null", gap["legs"] == [{"walk": None, "car": None, "path": None}],
      str(gap["legs"]))
check("null leg 가 있으면 총거리는 null", gap["total_distance_m"] is None,
      str(gap["total_distance_m"]))

adjacent = course_payload.filter_stored_course(
    {
        "v": course_payload.PAYLOAD_VERSION,
        "spots": [{"id": 126508}, {"id": 126509}],
        "legs": [{"walk": {"minutes": 3, "meters": 200}, "car": None, "path": None}],
    },
    spot_repo=REPO,
)
check("빠진 스팟이 없으면 leg 는 그대로", adjacent["legs"][0]["walk"] == {"minutes": 3, "meters": 200},
      str(adjacent["legs"][0]))

# --- 5. 비문자열 입력 (2026-08-18 QA Critical-1) ---------------------------------------
#
# 배경: `clean_user_text` 가 비문자열을 만나면 TypeError 를 던져 쓰기는 500,
# **저장된 값이면 읽을 때마다 영구 500** 이 됐다. 정제 함수가 정제 대상에게 당하는 구조라
# 방어를 `clean_user_text` 진입부 한 곳에 넣었다. 쓰기·읽기 양쪽에서 확인한다.

print("\n=== 5. 비문자열 필드(500 방지) ===")
NON_STRING = {
    "spots": [
        {"id": 126508, "slot_label": 123, "blurb": {"nested": "dict"}, "photo_credit": ["list"],
         "image_url": 42},
        {"id": 126509, "slot_label": None, "blurb": 3.14},
    ],
    "legs": [{"walk": {"minutes": "3", "meters": True}, "car": [], "path": {"not": "list"}}],
    "ai_title": 123,
    "ai_summary": ["a", "b"],
    "region": {"region_code": 47130},
}
try:
    ns = course_payload.rebuild_course_for_store(NON_STRING, spot_repo=REPO)
    check("비문자열 slot_label 이 500 을 내지 않는다", ns["spots"][0]["slot_label"] == "1번째",
          ns["spots"][0]["slot_label"])
    check("비문자열 slot_label(None) 은 순번 폴백", ns["spots"][1]["slot_label"] == "2번째",
          ns["spots"][1]["slot_label"])
    check("dict blurb 는 빈 값", ns["spots"][0]["blurb"] is None, str(ns["spots"][0]["blurb"]))
    check("list photo_credit 는 빈 값", ns["spots"][0]["photo_credit"] is None,
          str(ns["spots"][0]["photo_credit"]))
    check("int image_url 은 빈 값", ns["spots"][0]["image_url"] is None,
          str(ns["spots"][0]["image_url"]))
    check("int ai_title 은 빈 값", ns["ai_title"] is None, str(ns["ai_title"]))
    check("list ai_summary 는 빈 값", ns["ai_summary"] is None, str(ns["ai_summary"]))
    check("비문자열 region_code 는 스팟에서 보정", ns["region"]["region_code"] == "47130",
          str(ns["region"]))
    check("문자열 minutes / bool meters 는 leg 를 깨뜨리지 않는다",
          ns["legs"][0]["car"] is None and ns["legs"][0]["path"] is None, str(ns["legs"][0]))
except Exception as exc:  # noqa: BLE001
    check("비문자열 payload 쓰기가 예외를 내지 않는다", False, f"{type(exc).__name__}: {exc}")

try:
    ns_read = course_payload.filter_stored_course(NON_STRING, spot_repo=REPO)
    check("비문자열 payload 읽기가 예외를 내지 않는다", ns_read["spots"][0]["name"] == "불국사",
          str(ns_read["spots"][0]["name"]))
except Exception as exc:  # noqa: BLE001
    check("비문자열 payload 읽기가 예외를 내지 않는다", False, f"{type(exc).__name__}: {exc}")

# 새 표식이 붙은(=사진/설명을 신뢰하는) 경로에서도 비문자열이 터지지 않아야 한다.
try:
    trusted = dict(NON_STRING)
    trusted["v"] = course_payload.PAYLOAD_VERSION
    ns_trusted = course_payload.filter_stored_course(trusted, spot_repo=REPO)
    check("표식 있는 비문자열 payload 읽기도 안전",
          ns_trusted["spots"][0]["blurb"] is None and ns_trusted["ai_title"] is None,
          str(ns_trusted["spots"][0]["blurb"]))
except Exception as exc:  # noqa: BLE001
    check("표식 있는 비문자열 payload 읽기도 안전", False, f"{type(exc).__name__}: {exc}")

# 새 표식이 있으면 서버가 채운 사진·설명은 그대로 살아 있어야 한다(무회귀).
v2 = dict(legacy)
v2["v"] = course_payload.PAYLOAD_VERSION
kept = course_payload.filter_stored_course(v2, spot_repo=REPO)
check("새 표식 payload 의 허용 CDN 사진은 유지",
      kept["spots"][0]["image_url"] == "https://tong.visitkorea.or.kr/other-place.jpg",
      str(kept["spots"][0]["image_url"]))


print("\n" + "=" * 60)
if FAILURES:
    print(f"실패 {len(FAILURES)}건:")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)
print("모든 검증 통과")
