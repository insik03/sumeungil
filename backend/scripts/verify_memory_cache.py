# -*- coding: utf-8 -*-
"""MemoryCache 항목 수 상한(보안감사 F-05) 회귀 — DB·원천 불필요.

실행: cd backend && python scripts/verify_memory_cache.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cache.memory import MemoryCache  # noqa: E402

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(label)


async def main() -> None:
    c = MemoryCache(max_entries=100)
    for i in range(100):
        await c.set(f"k{i}", i, 60)
    check("상한까지 채움", len(c) == 100, str(len(c)))
    await c.set("k100", 100, 60)
    check("상한 초과 시 항목 수가 상한을 넘지 않음", len(c) == 100, str(len(c)))
    check("가장 만료가 이른 항목(k0)이 밀려남", await c.get("k0") is None and await c.get("k100") == 100)

    c2 = MemoryCache(max_entries=10)
    for i in range(10):
        await c2.set(f"e{i}", i, 0)  # TTL 0 → 즉시 만료
    await c2.set("fresh", 1, 60)
    check("만료분이 먼저 걷혀 새 항목이 들어감", await c2.get("fresh") == 1 and len(c2) == 1, str(len(c2)))

    c3 = MemoryCache(max_entries=5)
    for i in range(5):
        await c3.set(f"s{i}", i, 60)
    await c3.set("s0", "updated", 60)  # 기존 키 갱신은 퇴거를 유발하지 않는다
    check("기존 키 갱신은 다른 항목을 밀어내지 않음", len(c3) == 5 and await c3.get("s1") == 1)


asyncio.run(main())
print()
if FAILURES:
    print(f"FAIL {len(FAILURES)}건: {FAILURES}")
    sys.exit(1)
print("PASS 전건")
