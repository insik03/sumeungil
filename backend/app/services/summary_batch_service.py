"""Sequential, resumable tourism preprocessing; never used in an HTTP request."""
from __future__ import annotations

import asyncio
import logging
import time

from ..ai.summarizer import Summarizer
from ..repositories.summary_repo import SummaryRepository, now_iso, source_hash, source_text

logger = logging.getLogger("sumeungil.summary_batch")


async def process_one(repo: SummaryRepository, summarizer: Summarizer, kind: str, content_id: int,
                      raw: str | None, *, retries: int = 1) -> str:
    """Caller holds repo.batch_lock. Persist source BEFORE inference, checkpoint each result."""
    source = source_text(raw)
    if not source:
        return "no_source"
    record = repo.load(kind, content_id)
    if repo.current(record, source):
        return "cached"
    record.update(source=source, sourceHash=source_hash(source), status="pending", updatedAt=now_iso())
    repo.write(kind, content_id, record)
    started = time.monotonic()
    for attempt in range(min(max(retries, 0), 1) + 1):
        if attempt:
            logger.info("summary retry=1 kind=%s id=%s", kind, content_id)
            await asyncio.sleep(1)
        try:
            summary = await summarizer.summarize(source)
        except Exception as exc:
            # A model/server error must not discard the collected tourism record.
            logger.warning("summary error=%s kind=%s id=%s", type(exc).__name__, kind, content_id)
            summary = None
        if isinstance(summary, str) and summary.strip() and len(summary) <= 360:
            record.update(status="ready", result={
                "summary": summary, "sourceHash": record["sourceHash"],
                "modelName": repo.model, "promptVersion": repo.prompt_version, "generatedAt": now_iso(),
            })
            repo.write(kind, content_id, record)
            logger.info("summary success kind=%s id=%s elapsed_ms=%d", kind, content_id,
                        (time.monotonic() - started) * 1000)
            return "success"
    record.update(status="failed", updatedAt=now_iso())
    repo.write(kind, content_id, record)
    logger.info("summary failed kind=%s id=%s elapsed_ms=%d", kind, content_id,
                (time.monotonic() - started) * 1000)
    return "failed"
