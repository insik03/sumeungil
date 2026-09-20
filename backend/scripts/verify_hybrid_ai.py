"""Deterministic Hybrid AI regression: no external network, API keys or model required."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PUBLIC_DATA_API_KEY", "verify-only")

import httpx
from app.ai import gemini_client, local_client
from app.ai.course_picker import Candidate, pick_course_spots
from app.ai.llm_provider import OllamaProvider, create_provider_from_settings
from app.ai.summarizer import (OllamaSummarizer, GeminiSummarizer, create_summarizer_from_settings,
                               create_course_summarizer_from_settings)
from app.ai.tips_generator import OllamaTipsGenerator, create_tips_generator_from_settings
from app.cache.memory import MemoryCache
from app.config import settings
from app.repositories.summary_repo import SummaryRepository, source_hash
from app.services.summary_batch_service import process_one
from app.services import spot_detail_service, festival_detail_service
from scripts import build_spot_summaries, build_festival_summaries

SOURCE = "이 공원에는 숲을 따라 걷는 산책로와 지역의 전통 문화를 소개하는 전시 공간이 있습니다."
SUMMARY = "숲속 산책로를 걸으며 자연을 감상할 수 있는 공원입니다. 지역 전통 문화를 소개하는 전시 공간도 있습니다."


class HybridTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = SummaryRepository(self.temp.name, "test-4b")
        self.local = OllamaSummarizer("http://local.invalid", "test-4b")

    async def generate(self, source=SOURCE, content_id=1, kind="spot"):
        model = SimpleNamespace(summarize=AsyncMock(return_value=SUMMARY))
        with self.repo.batch_lock():
            outcome = await process_one(self.repo, model, kind, content_id, source, retries=0)
        return outcome, model

    async def test_factories_ignore_legacy_global_switch(self):
        with patch.object(settings, "llm_provider", "gemini"):
            self.assertIs(type(create_provider_from_settings(settings)), OllamaProvider)
            self.assertIs(type(create_tips_generator_from_settings(settings)), OllamaTipsGenerator)
            self.assertIs(type(create_summarizer_from_settings(settings)), OllamaSummarizer)
            self.assertIs(type(create_course_summarizer_from_settings(settings)), GeminiSummarizer)

    async def test_course_api_dependency(self):
        from app.api.courses import router
        from app.deps import get_course_summarizer, get_summarizer
        for route in router.routes:
            calls = [dep.call for dep in route.dependant.dependencies]
            if route.path.endswith(("recommend", "arrange")):
                self.assertIn(get_course_summarizer, calls)
                self.assertNotIn(get_summarizer, calls)

    async def test_structured_summary_success(self):
        with patch.object(self.local, "_chat", AsyncMock(return_value=json.dumps({"summary": SUMMARY}))) as chat:
            self.assertEqual(await self.local.summarize(SOURCE), SUMMARY)
            self.assertIn("format_schema", chat.call_args.kwargs)

    async def test_invalid_structured_results(self):
        for content in [None, "", "{broken", "null", "[]", "{}", '{"summary": ""}',
                        '{"summary": 7}', '{"summary": "짧음"}',
                        json.dumps({"summary": SUMMARY, "extra": "x"}),
                        json.dumps({"summary": "가" * 361}), json.dumps({"summary": "<script>" + SUMMARY})]:
            with self.subTest(content=str(content)[:30]), patch.object(self.local, "_chat", AsyncMock(return_value=content)):
                self.assertIsNone(await self.local.summarize(SOURCE))

    async def test_local_http_failures(self):
        for error in [httpx.ReadTimeout("private input"), httpx.ConnectError("private url")]:
            with self.subTest(error=type(error).__name__), patch("app.ai.summarizer.post_chat", AsyncMock(side_effect=error)):
                self.assertIsNone(await self.local.summarize(SOURCE))
        for response in [httpx.Response(500), httpx.Response(503), httpx.Response(404),
                         httpx.Response(200, text="bad envelope"), httpx.Response(200, json={}),
                         httpx.Response(200, json={"message": {"content": []}})]:
            with patch("app.ai.summarizer.post_chat", AsyncMock(return_value=response)):
                self.assertIsNone(await self.local.summarize(SOURCE))

    async def test_local_transport_serial_and_bounded(self):
        active = peak = 0
        async def post(*args, **kwargs):
            nonlocal active, peak
            self.assertEqual(kwargs["json"]["options"]["num_ctx"], 4096)
            self.assertEqual(kwargs["json"]["options"]["num_thread"], 2)
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(.015)
            active -= 1
            return httpx.Response(200)
        with patch.object(httpx.AsyncClient, "post", post):
            await asyncio.gather(*(local_client.post_chat("http://local.invalid", {}, 2) for _ in range(3)))
        self.assertEqual(peak, 1)

    async def test_deadline_includes_waiting(self):
        gate = local_client._gates.setdefault(asyncio.get_running_loop(), asyncio.Semaphore(1))
        async with gate:
            with patch.object(httpx.AsyncClient, "post", AsyncMock()) as post:
                with self.assertRaises(httpx.TimeoutException):
                    await local_client.post_chat("http://local.invalid", {}, .01)
                post.assert_not_called()

    async def test_queue_is_bounded(self):
        loop = asyncio.get_running_loop()
        local_client._pending[loop] = 5
        try:
            with patch.object(httpx.AsyncClient, "post", AsyncMock()) as post:
                with self.assertRaises(httpx.RequestError):
                    await local_client.post_chat("http://local.invalid", {}, 1)
                post.assert_not_called()
        finally:
            local_client._pending[loop] = 0

    async def test_admin_reports_course_provider_and_local_cache(self):
        from app.services.admin_service import ai_status
        with patch.object(spot_detail_service, "_pregenerated_summaries", return_value={"1": SUMMARY}):
            result = await ai_status(MemoryCache(), SimpleNamespace(all_spots=lambda: [1, 2]))
        self.assertEqual(result.provider, "gemini")
        self.assertEqual(result.summaries_pregenerated, 1)

    async def test_persist_before_inference(self):
        async def summarize(source):
            record = self.repo.load("spot", 1)
            self.assertEqual(record["status"], "pending")
            self.assertEqual(record["sourceHash"], source_hash(source))
            self.assertEqual(record["source"], SOURCE)
            return SUMMARY
        with self.repo.batch_lock():
            self.assertEqual(await process_one(self.repo, SimpleNamespace(summarize=summarize), "spot", 1, SOURCE), "success")

    async def test_duplicate_source_and_restart(self):
        _, model = await self.generate()
        other = SummaryRepository(self.temp.name, "test-4b")
        with other.batch_lock():
            self.assertEqual(await process_one(other, model, "spot", 1, SOURCE), "cached")
        self.assertEqual(model.summarize.await_count, 1)

    async def test_source_model_prompt_changes(self):
        await self.generate()
        self.assertIsNone(self.repo.current(self.repo.load("spot", 1), SOURCE + " 야간에는 문을 닫습니다."))
        outcome, _ = await self.generate(SOURCE + " 야간에는 문을 닫습니다.")
        self.assertEqual(outcome, "success")
        for repo in [SummaryRepository(self.temp.name, "new-model"), SummaryRepository(self.temp.name, "test-4b", "v2")]:
            self.assertIsNone(repo.current(repo.load("spot", 1)))

    async def test_failures_keep_source_and_limit_retry(self):
        model = SimpleNamespace(summarize=AsyncMock(return_value=None))
        with self.repo.batch_lock(), patch("app.services.summary_batch_service.asyncio.sleep", AsyncMock()):
            self.assertEqual(await process_one(self.repo, model, "spot", 1, SOURCE, retries=99), "failed")
        self.assertEqual(model.summarize.await_count, 2)
        record = self.repo.load("spot", 1)
        self.assertEqual(record["source"], SOURCE)
        self.assertEqual(self.repo.display("spot", 1, None), (SOURCE, None))

    async def test_changed_source_failure_does_not_serve_stale_summary(self):
        await self.generate()
        new = SOURCE + " 전시 공간은 현재 보수 중입니다."
        with self.repo.batch_lock():
            await process_one(self.repo, SimpleNamespace(summarize=AsyncMock(return_value=None)), "spot", 1, new, retries=0)
        self.assertEqual(self.repo.display("spot", 1, None), (new, None))

    async def test_corrupt_cache_and_atomic_visibility(self):
        path = self.repo._path("spot", 1)
        path.parent.mkdir()
        path.write_text("broken", encoding="utf-8")
        self.assertEqual(self.repo.display("spot", 1, SOURCE), (SOURCE, None))
        await self.generate()
        self.assertEqual(self.repo.display("spot", 1, SOURCE), (SUMMARY, "ollama"))

    async def test_batch_lock_contention_and_recovery(self):
        with self.repo.batch_lock():
            with self.assertRaises(RuntimeError):
                with SummaryRepository(self.temp.name, "other").batch_lock():
                    pass
        with self.repo.batch_lock():
            pass

    async def test_detail_never_calls_llm(self):
        model = SimpleNamespace(summarize=AsyncMock(side_effect=AssertionError("request must not infer")))
        with patch.object(spot_detail_service, "_summary_repository", return_value=self.repo):
            self.assertEqual(await spot_detail_service._get_ai_summary(1, SOURCE, model, MemoryCache()), (SOURCE, None))
            await self.generate()
            self.assertEqual(await spot_detail_service._get_ai_summary(1, SOURCE, model, MemoryCache()), (SUMMARY, "ollama"))
        model.summarize.assert_not_called()

    async def test_empty_source_and_html_fallback(self):
        outcome, model = await self.generate(" ")
        self.assertEqual(outcome, "no_source")
        model.summarize.assert_not_called()
        value, provider = self.repo.display("spot", 3, "<p>산책로</p>" * 200)
        self.assertNotIn("<", value)
        self.assertLessEqual(len(value), 360)
        self.assertIsNone(provider)

    async def test_spot_batch_resumes_and_handles_changes(self):
        spots = SimpleNamespace(all_spots=lambda: [SimpleNamespace(id=1), SimpleNamespace(id=2)])
        model = SimpleNamespace(summarize=AsyncMock(return_value=SUMMARY))
        with patch.object(build_spot_summaries, "_fetch_overview_with_backoff", AsyncMock(return_value=SOURCE)):
            first = await build_spot_summaries.run_batch([1, 2], spots, self.repo, model, None)
            second = await build_spot_summaries.run_batch([1, 2], spots, self.repo, model, None)
        self.assertEqual(first.success, 2)
        self.assertEqual(second.already_cached, 2)
        self.assertEqual(model.summarize.await_count, 2)

    async def test_festival_batch_handles_both_sources(self):
        entries = [SimpleNamespace(festival=SimpleNamespace(id=5), description=None),
                   SimpleNamespace(festival=SimpleNamespace(id=900000005), description=SOURCE)]
        model = SimpleNamespace(summarize=AsyncMock(return_value=SUMMARY))
        with patch.object(build_festival_summaries, "_fetch_overview_with_backoff", AsyncMock(return_value=SOURCE)) as fetch:
            stats = await build_festival_summaries.run_batch(entries, self.repo, model, None)
        self.assertEqual(stats["success"], 2)
        fetch.assert_awaited_once_with(5, None)
        self.assertEqual(self.repo.display("festival", 5, SOURCE), (SUMMARY, "ollama"))

    async def test_festival_detail_reads_summary(self):
        from app.schemas.places import Festival
        festival = Festival(id=5, title="축제", start_date="2026-09-01", end_date="2026-09-30",
                            address="서울", ongoing=True)
        entry = SimpleNamespace(festival=festival, region_code=None, description=SOURCE)
        await self.generate(content_id=5, kind="festival")
        with patch.object(festival_detail_service, "SummaryRepository", return_value=self.repo), \
             patch.object(festival_detail_service.festival_service, "find_entry", AsyncMock(return_value=entry)), \
             patch.object(festival_detail_service, "build_images", AsyncMock(return_value=[])), \
             patch.object(festival_detail_service, "build_description", AsyncMock(return_value=SOURCE)):
            response = await festival_detail_service.build_festival_detail(5, MemoryCache())
        self.assertEqual(response.description, SOURCE)
        self.assertEqual(response.ai_summary, SUMMARY)
        self.assertEqual(response.ai_provider, "ollama")

    async def test_gemini_reserved_for_courses(self):
        cloud = create_course_summarizer_from_settings(settings)
        with patch.object(gemini_client, "chat", AsyncMock()) as chat:
            self.assertIsNone(await cloud.summarize(SOURCE))
            self.assertIsNone(await cloud._chat("s", "u", 1, "ai_summary"))
            chat.assert_not_called()

    async def test_gemini_course_valid_and_invalid_results(self):
        cloud = GeminiSummarizer("stub", "stub", 1)
        candidates = [Candidate(id=i, name=f"장소{i}", category="nature") for i in range(1, 5)]
        good = json.dumps({"picks": [{"id": i, "slot_label": "관광", "reason": "산책"} for i in range(1, 5)]})
        with patch.object(gemini_client, "chat", AsyncMock(return_value=good)):
            result = await pick_course_spots(cloud, "산책", candidates, 1)
            self.assertEqual([p.id for p in result.picks], [1, 2, 3, 4])
        for text in ["bad", "[]", '{"picks": [{"id": 999}]}', ""]:
            with patch.object(gemini_client, "chat", AsyncMock(return_value=text)):
                self.assertIsNone(await pick_course_spots(cloud, "산책", candidates, 1))

    async def test_gemini_missing_key_timeout_and_api_error(self):
        with self.assertRaises(gemini_client.GeminiError):
            await gemini_client.chat([], api_key="", model="stub", timeout_sec=1)
        for side_effect in [httpx.ReadTimeout("private url"), httpx.ConnectError("private input")]:
            with patch.object(httpx.AsyncClient, "post", AsyncMock(side_effect=side_effect)):
                self.assertIsNone(await GeminiSummarizer("stub", "stub", 1).summarize_course(SOURCE))
        for status in [400, 429, 500, 503]:
            with patch.object(httpx.AsyncClient, "post", AsyncMock(return_value=httpx.Response(status))) as post, \
                 patch.object(gemini_client.asyncio, "sleep", AsyncMock()):
                self.assertIsNone(await GeminiSummarizer("stub", "stub", 1).summarize_course(SOURCE))
                self.assertLessEqual(post.await_count, 2)

    async def test_gemini_malformed_envelope(self):
        for body in [[], {}, {"candidates": [1]}, {"candidates": [{"content": {"parts": [{"text": 4}]}}]}]:
            with patch.object(httpx.AsyncClient, "post", AsyncMock(return_value=httpx.Response(200, json=body))):
                with self.assertRaises(gemini_client.GeminiError):
                    await gemini_client.chat([], api_key="stub", model="stub", timeout_sec=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
