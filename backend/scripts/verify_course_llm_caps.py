# -*- coding: utf-8 -*-
"""AI 코스 비용 상한(2026-09-14) 회귀 — DB·LLM 불필요.

  1. 같은 문장+후보면 두 번째 호출은 캐시에서(LLM 미호출), 문장이 다르면 재호출
  2. 계정당 일일 상한 30 → 31번째부터 False, 전체 상한도 동일
  3. summarizer 없이도 캐시 히트는 결과를 돌려준다

실행: cd backend && python scripts/verify_course_llm_caps.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PUBLIC_DATA_API_KEY", "verify-only")

from app.cache.memory import MemoryCache  # noqa: E402
from app.config import settings  # noqa: E402
from app.services import course_service  # noqa: E402

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(label)


class Spot:
    def __init__(self, i: int):
        self.id = i; self.name = f"스팟{i}"; self.category = "cafe"; self.tags = []; self.themes = {}
        self.is_hidden_gem = False; self.lat = 35.1 + i * 0.001; self.lng = 129.0; self.pet_note = None


class Scored:
    def __init__(self, i: int):
        self.spot = Spot(i); self.congestion = None; self.match_score = None; self.reasons = None; self._sort_cong = 50.0


class StubSummarizer:
    def __init__(self) -> None:
        self.calls = 0

    async def _chat(self, system_prompt, user_content, timeout_sec, tag, format_schema=None):
        self.calls += 1
        return json.dumps({"picks": [{"id": i, "slot_label": "a", "reason": "r"} for i in (1, 2, 3, 4)]})


async def main() -> None:
    cache = MemoryCache()
    scored = [Scored(i) for i in range(1, 9)]
    stub = StubSummarizer()
    r1 = await course_service._pick_with_llm("비 오는 날 카페", scored, False, stub, cache)
    r2 = await course_service._pick_with_llm("비 오는  날 카페 ", scored, False, stub, cache)
    check("첫 호출은 LLM, 같은 문장(공백 차이) 두 번째는 캐시 → LLM 1회", stub.calls == 1 and r1 and r2 and [p.id for p in r2.picks] == [1, 2, 3, 4], str(stub.calls))
    r3 = await course_service._pick_with_llm("부모님과 천천히", scored, False, stub, cache)
    check("다른 문장은 재호출", stub.calls == 2 and r3 is not None)
    r4 = await course_service._pick_with_llm("비 오는 날 카페", scored, False, None, cache)
    check("summarizer 없어도(상한 초과 상황) 캐시 히트면 결과 반환", r4 is not None and stub.calls == 2)
    r5 = await course_service._pick_with_llm("전혀 새로운 문장", scored, False, None, cache)
    check("summarizer 없고 캐시 미스면 None(규칙 폴백)", r5 is None)

    cap_cache = MemoryCache()
    settings.course_llm_daily_cap_per_user = 3
    settings.course_llm_daily_cap_global = 5
    user_ok = [await course_service._llm_allowed(cap_cache, 7) for _ in range(4)]
    check("계정당 상한 3 → 4번째 False", user_ok == [True, True, True, False], str(user_ok))
    other = [await course_service._llm_allowed(cap_cache, 8) for _ in range(3)]
    check("다른 계정은 전체 상한(5) 안에서 2번 허용 후 False", other == [True, True, False], str(other))
    check("전체 상한 소진 뒤 새 계정도 False", (await course_service._llm_allowed(cap_cache, 9)) is False)


asyncio.run(main())
print()
if FAILURES:
    print(f"FAIL {len(FAILURES)}건: {FAILURES}")
    sys.exit(1)
print("PASS 전건")
