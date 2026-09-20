"""Preprocess both TourAPI and standard-data festivals using the existing collectors."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.summarizer import create_summarizer_from_settings
from app.cache.memory import MemoryCache
from app.config import settings
from app.repositories.summary_repo import SummaryRepository
from app.services import festival_service
from app.services.festival_detail_service import clean_description
from app.services.summary_batch_service import process_one
from scripts.build_spot_summaries import RateLimiter, QuotaExhausted, _fetch_overview_with_backoff

logger = logging.getLogger("sumeungil.festival_batch")


async def run_batch(entries, store, summarizer, limiter) -> Counter:
    stats = Counter()
    with store.batch_lock():
        for entry in entries:
            festival = entry.festival
            if festival_service.is_synthetic_id(festival.id):
                raw = entry.description
            else:
                try:
                    raw = await _fetch_overview_with_backoff(festival.id, limiter)
                except QuotaExhausted:
                    stats["quota_aborted"] += 1
                    break
            # Exact same normalization as the detail response, so hashes are comparable.
            outcome = await process_one(store, summarizer, "festival", festival.id, clean_description(raw))
            stats[outcome] += 1
    logger.info("festival batch counts=%s", dict(stats))
    return stats


async def main() -> int:
    parser = argparse.ArgumentParser(description="Local LLM 축제 요약 배치")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--rate-limit-per-min", type=int, default=25)
    args = parser.parse_args()
    if args.limit <= 0 or args.rate_limit_per_min <= 0:
        parser.error("limit과 rate-limit-per-min은 양수여야 합니다")
    entries = await festival_service._load_nationwide(MemoryCache())
    if not entries:
        logger.error("축제 원천이 비어 있습니다. API 상태 및 날짜 범위를 확인하세요.")
        return 1
    stats = await run_batch(entries if args.all else entries[:args.limit],
                            SummaryRepository(settings.summary_store_dir, settings.ollama_model),
                            create_summarizer_from_settings(settings), RateLimiter(args.rate_limit_per_min))
    print(dict(stats))
    return 1 if stats["failed"] or stats["quota_aborted"] else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    raise SystemExit(asyncio.run(main()))
