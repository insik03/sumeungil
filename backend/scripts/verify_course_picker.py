# -*- coding: utf-8 -*-
"""AI 코스 스팟 선택기(app/ai/course_picker.py) 회귀 검증 (2026-09-05).

LLM·DB·원천을 부르지 않는다 — 대역 Summarizer 가 정해진 JSON 을 돌려준다. 검증하는 것:
  1. 후보 밖 id·중복 id 는 버려지고 순서는 유지되는가
  2. 유효 선택이 2곳 미만이면 None(슬롯 휴리스틱 폴백)인가
  3. slot_label/reason 길이 절단·빈 라벨 대체
  4. 사용자 문장이 델리미터 안에 sanitize 되어 들어가는가 (PII 마스킹 포함)
  5. `_chat` 이 없는 대역이면 조용히 None

실행: cd backend && python scripts/verify_course_picker.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai import course_picker  # noqa: E402
from app.ai.injection_guard import PII_MASK  # noqa: E402

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(label)


class StubChat:
    def __init__(self, answer: str | None) -> None:
        self.answer = answer
        self.last_user: str | None = None
        self.last_schema: dict | None = None

    async def _chat(self, system_prompt, user_content, timeout_sec, tag, format_schema=None):
        self.last_user = user_content
        self.last_schema = format_schema
        return self.answer


CANDS = [
    course_picker.Candidate(id=1, name="비 오는 날 카페", category="cafe", tag_labels=("로맨틱",), congestion_level="low",
                            summary="창가에서 비 구경하기 좋은 카페"),
    course_picker.Candidate(id=2, name="실내 공방", category="craft", is_hidden_gem=True),
    course_picker.Candidate(id=3, name="시장 국밥", category="restaurant", congestion_level="mid"),
    course_picker.Candidate(id=4, name="해안 산책로", category="trail", pet_allowed=True),
]
ALLOWED = {c.id for c in CANDS}

print("=== 1. 화이트리스트 재검증 · 순서 유지 ===")
raw = {"picks": [
    {"id": 2, "slot_label": "아침 공방", "reason": "실내라 비 와도 괜찮아요"},
    {"id": 999, "slot_label": "지어낸 곳", "reason": "후보에 없음"},
    {"id": 2, "slot_label": "중복", "reason": "중복"},
    {"id": "1", "slot_label": "오후 카페", "reason": "창가에서 비 구경"},
    {"id": 3, "slot_label": "", "reason": "x" * 200},
], "note": "  야경은 후보에 없었어요  "}
res = course_picker.parse_result(json.dumps(raw, ensure_ascii=False), ALLOWED)
check("결과 있음", res is not None)
check("후보 밖 id(999)·중복(2) 제거, 순서 유지", res is not None and [p.id for p in res.picks] == [2, 1, 3], str(res))
check("문자열 id('1') 도 정수로 수용", res is not None and res.picks[1].id == 1)
check("빈 slot_label → 'N번째' 대체", res is not None and res.picks[2].slot_label == "3번째", str(res and res.picks[2]))
check("reason 60자 절단", res is not None and len(res.picks[2].reason) == course_picker.REASON_MAX)
check("note 공백 정리", res is not None and res.note == "야경은 후보에 없었어요")

print("=== 2. 부족·깨짐 → None ===")
check("유효 1곳 → None", course_picker.parse_result(json.dumps({"picks": [{"id": 1, "slot_label": "a", "reason": "b"}]}), ALLOWED) is None)
check("전부 후보 밖 → None", course_picker.parse_result(json.dumps({"picks": [{"id": 8, "slot_label": "a", "reason": "b"}, {"id": 9, "slot_label": "a", "reason": "b"}]}), ALLOWED) is None)
check("JSON 아님 → None", course_picker.parse_result("not json", ALLOWED) is None)
check("picks 가 배열 아님 → None", course_picker.parse_result(json.dumps({"picks": "x"}), ALLOWED) is None)
check("빈 문자열 → None", course_picker.parse_result("", ALLOWED) is None)
big = {"picks": [{"id": i, "slot_label": "a", "reason": "b"} for i in (1, 2, 3, 4)] * 2}
res_big = course_picker.parse_result(json.dumps(big), ALLOWED)
check("최대 PICK_MAX 곳", res_big is not None and len(res_big.picks) == min(4, course_picker.PICK_MAX))

print("=== 2b. 후보 4곳 이상이면 최소 4곳 (리뷰 P2) ===")
check("required_picks: 후보 4 → 4", course_picker.required_picks(4) == 4)
check("required_picks: 후보 3 → 2", course_picker.required_picks(3) == 2)
three = json.dumps({"picks": [{"id": i, "slot_label": "a", "reason": "b"} for i in (1, 2, 3)]})
stub3 = StubChat(three)
check("후보 4곳인데 3곳만 선택 → None(폴백)", asyncio.run(course_picker.pick_course_spots(stub3, "비", CANDS, timeout_sec=5)) is None)
r3 = asyncio.run(course_picker.pick_course_spots(stub3, "비", CANDS[:3], timeout_sec=5))
check("후보 3곳에 3곳 선택 → 성공", r3 is not None and len(r3.picks) == 3)
four = json.dumps({"picks": [{"id": i, "slot_label": "a", "reason": "b"} for i in (1, 2, 3, 4)]})
r4 = asyncio.run(course_picker.pick_course_spots(StubChat(four), "비", CANDS, timeout_sec=5))
check("후보 4곳에 4곳 선택 → 성공", r4 is not None and len(r4.picks) == 4)

print("=== 3. 프롬프트 조립 (델리미터 + sanitize + PII 마스킹) ===")
stub = StubChat(json.dumps({"picks": [{"id": 1, "slot_label": "오후 카페", "reason": "r"}, {"id": 2, "slot_label": "아침 공방", "reason": "r"}]}, ensure_ascii=False))
out = asyncio.run(course_picker.pick_course_spots(stub, "비 오는 날 연인이랑, 연락처 010-1234-5678", CANDS[:3], timeout_sec=5))
check("대역 호출(후보 3곳) → 2곳 선택", out is not None and [p.id for p in out.picks] == [1, 2], str(out))
check("<user_wish> 델리미터", stub.last_user is not None and "<user_wish>" in stub.last_user and "</user_wish>" in stub.last_user)
check("전화번호 마스킹", stub.last_user is not None and "010-1234-5678" not in stub.last_user and PII_MASK in stub.last_user)
check("후보 목록에 id·소개 포함", stub.last_user is not None and "id=1" in stub.last_user and "창가에서 비 구경" in stub.last_user)
check("JSON 스키마 전달", stub.last_schema is not None and "picks" in stub.last_schema["properties"])

print("=== 4. 비활성·빈 입력 ===")
class NoChat:  # _chat 없는 대역(기존 verify 들의 StubSummarizer 와 동일 형태)
    pass
check("_chat 없는 대역 → None", asyncio.run(course_picker.pick_course_spots(NoChat(), "비 오는 날", CANDS, timeout_sec=5)) is None)
check("summarizer None → None", asyncio.run(course_picker.pick_course_spots(None, "비 오는 날", CANDS, timeout_sec=5)) is None)
check("빈 문장 → None(LLM 미호출)", asyncio.run(course_picker.pick_course_spots(stub, "   ", CANDS, timeout_sec=5)) is None)
check("후보 1곳 → None(LLM 미호출)", asyncio.run(course_picker.pick_course_spots(stub, "비", CANDS[:1], timeout_sec=5)) is None)

print()
if FAILURES:
    print(f"FAIL {len(FAILURES)}건: {FAILURES}")
    sys.exit(1)
print("PASS 전건")
