# -*- coding: utf-8 -*-
"""관광지 소개글 → 분위기·스팟선호 태그 배치 → 영구 캐시 (2026-09-20).

한 번 만든 태그는 `<SUMMARY_STORE_DIR>/spot_tags.json` 에 저장해 두고, 다음 실행부터는
  - stale_days 이내에 확인한 스팟은 API 를 다시 부르지 않는다,
  - 다시 받아온 소개글의 해시가 같고 규칙 버전도 같으면 추출도 다시 하지 않는다,
소개글이 바뀌었거나 규칙 버전(RULES_VERSION)이 올랐을 때만 다시 만든다.
서버는 이 파일을 읽기만 하며(재시작 없이 1분 안에 반영), 요청 처리 중에는 추출도 API 호출도 하지 않는다.

    python scripts/build_spot_tags.py --limit 200          # 우선순위 상위 200곳
    python scripts/build_spot_tags.py --all                # 전체(429 쿼터에 걸리면 저장하고 멈춤 → 내일 이어서)
    python scripts/build_spot_tags.py --report-only        # API 호출 없이 현황만

우선순위·소개글 수집·분당 상한·429 백오프는 build_spot_summaries.py 와 같은 것을 그대로 쓴다.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.ai.spot_tagger import RULES_VERSION, derive_tags  # noqa: E402
from app.config import settings  # noqa: E402
from app.repositories.spot_repo import JsonSpotRepository  # noqa: E402
from app.repositories.spot_tag_cache import SpotTagCache  # noqa: E402
from app.repositories.summary_repo import SummaryRepository, source_hash, source_text  # noqa: E402
from build_spot_summaries import (  # noqa: E402
    QuotaExhausted,
    RateLimiter,
    _fetch_overview_with_backoff,
    build_priority_order,
)

logger = logging.getLogger("sumeungil.scripts.build_spot_tags")

SAVE_EVERY = 50


@dataclass
class TagRunStats:
    attempted: int = 0
    fresh_skipped: int = 0   # stale_days 이내라 API 도 안 부름
    generated: int = 0       # 소개글이 새로/바뀌었거나 규칙이 올라 다시 추출
    unchanged: int = 0       # API 는 불렀지만 소개글 해시·규칙 버전이 같아 추출 생략
    no_overview: int = 0
    quota_aborted: bool = False


async def run_batch(target_ids, spot_ids: set[int], cache: SpotTagCache, limiter, stale_days: int,
                    fetch=_fetch_overview_with_backoff) -> TagRunStats:
    stats = TagRunStats()
    done_since_save = 0
    for sid in target_ids:
        if sid not in spot_ids:
            continue
        stats.attempted += 1
        if cache.is_fresh(sid, stale_days):
            stats.fresh_skipped += 1
            continue
        try:
            overview = await fetch(sid, limiter)
        except QuotaExhausted:
            stats.quota_aborted = True
            break
        text = source_text(overview)
        if not text:
            # 소개글이 없다는 사실도 캐시한다 — 다음 실행에서 같은 스팟을 또 조회하지 않는다.
            cache.put(sid, source_hash(""), [])
            stats.no_overview += 1
        else:
            h = source_hash(text)
            if cache.needs_extract(sid, h):
                cache.put(sid, h, derive_tags(text))
                stats.generated += 1
            else:
                cache.touch(sid)
                stats.unchanged += 1
        done_since_save += 1
        if done_since_save >= SAVE_EVERY:
            cache.save()
            done_since_save = 0
    cache.save()  # 429 로 멈춰도 지금까지 만든 것은 남는다
    logger.info("spot tags attempted=%d generated=%d unchanged=%d fresh_skipped=%d no_overview=%d",
                stats.attempted, stats.generated, stats.unchanged, stats.fresh_skipped, stats.no_overview)
    return stats


async def main() -> int:
    parser = argparse.ArgumentParser(description="관광지 소개글 → 태그 배치(영구 캐시)")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--region")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--rate-limit-per-min", type=int, default=25)
    parser.add_argument("--stale-days", type=int, default=60,
                        help="이 기간 안에 확인한 스팟은 소개글을 다시 받아오지 않는다(기본 60일)")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    if not args.all and not args.report_only and (args.limit is None or args.limit <= 0):
        parser.error("--limit 양수 또는 --all이 필요합니다")
    if args.rate_limit_per_min <= 0 or args.stale_days < 0:
        parser.error("--rate-limit-per-min은 양수, --stale-days는 0 이상이어야 합니다")

    spots = JsonSpotRepository()
    if spots.total() == 0:
        logger.error("관광지 시드가 비어 있습니다. 먼저 관광지 수집을 실행하세요.")
        return 1
    cache = SpotTagCache(settings.summary_store_dir).load()
    ids_all = [s.id for s in spots.all_spots() if not args.region or s.region_code == args.region]

    if args.report_only:
        current = sum(1 for sid in ids_all if cache.is_fresh(sid, 10**6))
        with_tags = sum(1 for sid in ids_all if cache.tags(sid))
        print(f"규칙 v{RULES_VERSION} 캐시: {current}/{len(ids_all)}곳 확인됨, 그중 태그가 붙은 곳 {with_tags} (API 호출 없음)")
        return 0

    order = await build_priority_order(spots, args.region)
    order = order if args.all else order[:args.limit]
    # 같은 API 쿼터를 쓰는 요약 배치와 동시에 돌지 않게 같은 잠금을 쓴다.
    store = SummaryRepository(settings.summary_store_dir, settings.ollama_model)
    with store.batch_lock():
        stats = await run_batch(order, set(ids_all), cache, RateLimiter(args.rate_limit_per_min), args.stale_days)
    print(stats)
    return 1 if stats.quota_aborted else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    raise SystemExit(asyncio.run(main()))
