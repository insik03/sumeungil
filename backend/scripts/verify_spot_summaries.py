"""TourAPI source quota/backoff regression. Cache and batch tests are in verify_hybrid_ai.py."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cache.memory import MemoryCache  # noqa: E402
from app.clients.tourapi_detail_client import TourApiDetailError  # noqa: E402
from app.config import settings  # noqa: E402
from app.services import spot_detail_service  # noqa: E402

import scripts.build_spot_summaries as bss  # noqa: E402

FAILS: list[str] = []


def check(label: str, cond: bool, got=None) -> None:
    print(f"[{'OK  ' if cond else 'FAIL'}] {label}" + ("" if cond else f"  <- got={got!r}"))
    if not cond:
        FAILS.append(label)


# ---------- (a) SummaryStore 라운드트립 ----------


# ---------- (b) 429 백오프 / 스킵 ----------


async def test_backoff() -> None:
    print("\n--- (b) 429 백오프 재시도 / 소진 / 비-429 스킵 ---")
    limiter = bss.RateLimiter(per_min=0)  # 테스트에서는 페이싱 대기 없음

    # b-1: 429 두 번 후 성공(회복) — QUOTA_BACKOFF_SEC 를 짧게 오버라이드해 테스트 속도 확보
    orig_backoff = bss.QUOTA_BACKOFF_SEC
    bss.QUOTA_BACKOFF_SEC = (0.01, 0.01, 0.01)
    calls = {"n": 0}

    async def flaky(content_id: int):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise TourApiDetailError("upstream status 429")
        return {"overview": "정상 소개글"}

    orig_fetch = bss.detail_client.fetch_detail_common
    bss.detail_client.fetch_detail_common = flaky
    try:
        result = await bss._fetch_overview_with_backoff(1, limiter)
        check("429 2회 후 3번째 성공 → overview 반환", result == "정상 소개글", result)
        check("재시도 3회 호출됨", calls["n"] == 3, calls["n"])

        # b-2: 429 계속 → 백오프 3회 소진 후 QuotaExhausted
        calls["n"] = 0

        async def always_429(content_id: int):
            calls["n"] += 1
            raise TourApiDetailError("upstream status 429")

        bss.detail_client.fetch_detail_common = always_429
        raised = False
        try:
            await bss._fetch_overview_with_backoff(2, limiter)
        except bss.QuotaExhausted:
            raised = True
        check("429 계속 → QuotaExhausted(배치 중단 신호)", raised)

        # b-3: 429 아닌 실패(타임아웃 등) → 그 스팟만 None, 예외 전파 없음(배치는 안 죽음)
        calls["n"] = 0

        async def other_error(content_id: int):
            calls["n"] += 1
            raise TourApiDetailError("upstream request failed: timeout")

        bss.detail_client.fetch_detail_common = other_error
        result = await bss._fetch_overview_with_backoff(3, limiter)
        check("429 아닌 실패 → None(스킵), 배치 계속", result is None, result)
        check("재시도 없이 1회만 호출(비-429는 즉시 스킵)", calls["n"] == 1, calls["n"])

        # b-4: overview 필드 없음/빈 문자열 → None
        async def no_overview(content_id: int):
            return {"overview": "   "}

        bss.detail_client.fetch_detail_common = no_overview
        result = await bss._fetch_overview_with_backoff(4, limiter)
        check("overview 공백뿐 → None", result is None, result)
    finally:
        bss.detail_client.fetch_detail_common = orig_fetch
        bss.QUOTA_BACKOFF_SEC = orig_backoff


if __name__ == "__main__":
    asyncio.run(test_backoff())
    if FAILS:
        raise SystemExit(1)
    print("PASS: TourAPI quota/backoff regression. Hybrid cache tests: verify_hybrid_ai.py")
