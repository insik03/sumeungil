"""검증 스크립트 — 스팟 요약 사전 생성 배치 + 서버측 우선순위 조립. 서버·원천 호출 0(전부 스텁).

검증 항목:
  (a) SummaryStore: 저장→재로드 라운드트립, has()/put() 이 재개(resume)의 근거가 되는지.
  (b) _fetch_overview_with_backoff: 429 2회 후 성공(재시도로 회복) / 429 계속(백오프 소진 →
      QuotaExhausted) / 429 아닌 실패(그 스팟만 스킵, 배치는 안 죽음) / overview 빈 문자열(스킵).
  (c) spot_detail_service._get_ai_summary: 사전 생성 파일 우선(LLM 미호출) → 런타임 캐시 →
      라이브 LLM 순서, 그리고 사전 생성 파일이 없거나 깨져도 앱이 죽지 않는지(graceful).

실행:
    cd projects/sumeungil-build/backend
    py scripts/verify_spot_summaries.py
"""

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
from app.services import spot_detail_service  # noqa: E402

import scripts.build_spot_summaries as bss  # noqa: E402

FAILS: list[str] = []


def check(label: str, cond: bool, got=None) -> None:
    print(f"[{'OK  ' if cond else 'FAIL'}] {label}" + ("" if cond else f"  <- got={got!r}"))
    if not cond:
        FAILS.append(label)


# ---------- (a) SummaryStore 라운드트립 ----------


def test_store_roundtrip(tmp_dir: Path) -> None:
    print("\n--- (a) SummaryStore: 저장→재로드→재개(resume) ---")
    path = tmp_dir / "spot_summaries.json"
    store = bss.SummaryStore.load(path, "qwen2.5:7b")
    check("빈 파일 시작 → summaries 비어있음", store.summaries == {}, store.summaries)

    store.put(111, "요약 하나\n요약 둘")
    store.put(222, "다른 요약")
    store.save()
    check("파일 생성됨", path.exists())

    reloaded = bss.SummaryStore.load(path, "qwen2.5:7b")
    check("재로드 후 2건 유지", len(reloaded.summaries) == 2, reloaded.summaries)
    check("has(111) True → 재개 시 스킵 대상", reloaded.has(111))
    check("has(999) False → 재개 시 처리 대상", not reloaded.has(999))

    # 깨진 파일도 죽지 않고 새로 시작
    path.write_text("{not json", encoding="utf-8")
    broken = bss.SummaryStore.load(path, "qwen2.5:7b")
    check("깨진 파일 → 빈 store 로 graceful", broken.summaries == {})


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


# ---------- (c) spot_detail_service 우선순위(사전생성 → 런타임캐시 → 라이브) ----------


class StubSummarizer:
    def __init__(self, answer: str | None) -> None:
        self.answer = answer
        self.calls = 0

    async def summarize(self, overview: str) -> str | None:
        self.calls += 1
        return self.answer


async def test_ai_summary_priority(tmp_dir: Path) -> None:
    print("\n--- (c) ai_summary: 사전생성 → 런타임캐시 → 라이브 LLM ---")
    spot_detail_service._pregenerated_summaries.cache_clear()

    # c-1: 사전 생성 파일이 없음(존재하지 않는 경로) → graceful 빈 dict, 죽지 않음
    missing_path = tmp_dir / "does_not_exist.json"
    orig_path = spot_detail_service.PREGENERATED_SUMMARIES_PATH
    spot_detail_service.PREGENERATED_SUMMARIES_PATH = missing_path
    try:
        cache = MemoryCache()
        summarizer = StubSummarizer("라이브 요약")
        result = await spot_detail_service._get_ai_summary(1001, "원문 소개글", summarizer, cache)
        check("사전생성 파일 없음 → 라이브 LLM 폴백 정상 동작", result == "라이브 요약", result)
        check("라이브 LLM 1회 호출됨", summarizer.calls == 1, summarizer.calls)

        # 런타임 캐시 히트 확인(같은 content_id 재조회 시 LLM 재호출 없음)
        result2 = await spot_detail_service._get_ai_summary(1001, "원문 소개글", summarizer, cache)
        check("런타임 캐시 히트 → LLM 재호출 없음", summarizer.calls == 1, summarizer.calls)
        check("캐시된 값 그대로 반환", result2 == "라이브 요약", result2)

        # c-2: 깨진 사전생성 파일 → graceful
        broken_path = tmp_dir / "broken.json"
        broken_path.write_text("{not json", encoding="utf-8")
        spot_detail_service.PREGENERATED_SUMMARIES_PATH = broken_path
        spot_detail_service._pregenerated_summaries.cache_clear()
        summarizer2 = StubSummarizer("또 라이브 요약")
        result3 = await spot_detail_service._get_ai_summary(2002, "다른 소개글", summarizer2, MemoryCache())
        check("깨진 사전생성 파일 → 죽지 않고 라이브로 폴백", result3 == "또 라이브 요약", result3)

        # c-3: 사전 생성 파일에 값이 있으면 overview 유무·LLM 과 무관하게 그 값 반환(LLM 호출 0)
        good_path = tmp_dir / "spot_summaries.json"
        good_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "generated_at": "2026-07-31T00:00:00+09:00",
                    "model": "qwen2.5:7b",
                    "summaries": {"3003": {"summary": "사전 생성된 요약입니다", "source": "llm", "at": "x"}},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        spot_detail_service.PREGENERATED_SUMMARIES_PATH = good_path
        spot_detail_service._pregenerated_summaries.cache_clear()
        summarizer3 = StubSummarizer("호출되면 안 됨")
        result4 = await spot_detail_service._get_ai_summary(3003, None, summarizer3, MemoryCache())
        check("사전생성 있음 → overview=None 이어도 그 값 반환", result4 == "사전 생성된 요약입니다", result4)
        check("사전생성 있음 → LLM 호출 0", summarizer3.calls == 0, summarizer3.calls)

        # 사전생성에 없는 id 는 기존 경로(overview 없으면 None)
        result5 = await spot_detail_service._get_ai_summary(9999, None, summarizer3, MemoryCache())
        check("사전생성에 없는 id + overview 없음 → None", result5 is None, result5)
    finally:
        spot_detail_service.PREGENERATED_SUMMARIES_PATH = orig_path
        spot_detail_service._pregenerated_summaries.cache_clear()


# ---------- 우선순위 후보 목록(테마 후보 함수 순수성) ----------


def test_collection_candidate_ids_pure() -> None:
    print("\n--- (d) _collection_candidate_ids: 원천 호출 없이 시드만으로 동작 ---")
    from app.repositories.spot_repo import JsonSpotRepository

    repo = JsonSpotRepository()
    if repo.total() == 0:
        print("  (스킵 — spots_seed.json 비어있음)")
        return
    ids = bss._collection_candidate_ids(repo)
    check("컬렉션 후보 id 목록이 리스트", isinstance(ids, list))
    check("중복 없음", len(ids) == len(set(ids)), len(ids) - len(set(ids)))


async def main() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        test_store_roundtrip(tmp_dir)
        await test_backoff()
        await test_ai_summary_priority(tmp_dir)
        test_collection_candidate_ids_pure()

    print("\n" + ("전부 통과" if not FAILS else f"실패 {len(FAILS)}건: {FAILS}"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
