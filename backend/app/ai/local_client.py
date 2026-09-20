"""Bounded CPU-only Ollama transport shared by all local AI tasks."""
from __future__ import annotations

import asyncio
import logging
import time
from weakref import WeakKeyDictionary

import httpx

logger = logging.getLogger("sumeungil.ai.local_client")
_gates: WeakKeyDictionary = WeakKeyDictionary()
_pending: WeakKeyDictionary = WeakKeyDictionary()


async def post_chat(base_url: str, payload: dict, timeout_sec: float) -> httpx.Response:
    # One gate per event loop (also supports independent asyncio.run test cases).
    loop = asyncio.get_running_loop()
    gate = _gates.setdefault(loop, asyncio.Semaphore(1))
    if _pending.get(loop, 0) >= 5:  # one active + at most four waiting requests
        logger.info("local_llm outcome=queue_full")
        raise httpx.RequestError("local inference queue full")
    _pending[loop] = _pending.get(loop, 0) + 1
    body = dict(payload)
    body["options"] = {
        **body.get("options", {}), "num_thread": 2, "num_ctx": 4096,
        "num_predict": 512,
    }
    started = time.monotonic()
    outcome = "failed"
    try:
        # Deadline includes queue waiting, connection, model loading and response reading.
        async with asyncio.timeout(timeout_sec):
            async with gate:
                async with httpx.AsyncClient(timeout=timeout_sec) as client:
                    response = await client.post(f"{base_url.rstrip('/')}/api/chat", json=body)
        outcome = str(response.status_code)
        return response
    except TimeoutError as exc:
        outcome = "timeout"
        raise httpx.TimeoutException("local inference deadline exceeded") from exc
    finally:
        _pending[loop] -= 1
        logger.info("local_llm outcome=%s elapsed_ms=%d", outcome, (time.monotonic() - started) * 1000)
