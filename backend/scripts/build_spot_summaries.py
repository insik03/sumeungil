"""관광지 원문 수집 → 로컬 요약 → 영구 캐시. 매 실행 원문을 확인하고 동일 해시는 추론을 생략한다."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.summarizer import create_summarizer_from_settings  # noqa: E402
from app.cache.memory import MemoryCache  # noqa: E402
from app.clients import tourapi_detail_client as detail_client  # noqa: E402
from app.clients.tourapi_detail_client import TourApiDetailError  # noqa: E402
from app.repositories.summary_repo import SummaryRepository
from app.services.summary_batch_service import process_one
from app.config import settings  # noqa: E402
from app.regions.nationwide import REGION_BLOCKS  # noqa: E402
from app.repositories.congestion_repo import LiveCongestionRepository  # noqa: E402
from app.repositories.spot_repo import JsonSpotRepository, SpotRepository  # noqa: E402
from app.services import collections_service  # noqa: E402
from app.util.names import name_matches, norm_name  # noqa: E402

logger = logging.getLogger("sumeungil.scripts.build_spot_summaries")

TRENDING_TOP_PER_REGION = 15
QUOTA_BACKOFF_SEC = (10.0, 30.0, 60.0)

# ---------- 우선순위 후보 목록 ----------


async def _trending_ids(spot_repo: SpotRepository) -> list[int]:
    """9권역 board 상위 스팟 id(트렌딩). 원천 실패는 그 권역만 건너뛴다(배치를 막지 않음).

    detailCommon2 와 **다른 오퍼레이션**(tatsCnctrRatedList)이라 별도 쿼터다 — 여기서 9회
    호출해도 아래 detailCommon2 배치 쿼터는 소모하지 않는다.
    """
    congestion_repo = LiveCongestionRepository(
        cache=MemoryCache(),
        ttl_seconds=settings.cache_ttl_sec,
        forecast_ttl_seconds=settings.forecast_cache_ttl_sec,
    )
    ids: list[int] = []
    seen: set[int] = set()
    for block in REGION_BLOCKS:
        try:
            result = await congestion_repo.get_board(block.area_cd, block.region_code)
        except Exception as exc:  # noqa: BLE001 — 한 권역 실패가 전체를 막지 않는다
            logger.warning("트렌딩 후보 스킵(원천 실패) region=%s: %s", block.region_code, exc)
            continue
        ranked = sorted(
            result.records,
            key=lambda r: r.congestion_rate if r.congestion_rate is not None else -1.0,
            reverse=True,
        )[:TRENDING_TOP_PER_REGION]
        region_spots = spot_repo.by_region(block.region_code, None)
        norm_index = [(norm_name(s.name), s.id) for s in region_spots]
        for rec in ranked:
            target = norm_name(rec.spot_name)
            matched_id = next(
                (sid for nn, sid in norm_index if nn == target or name_matches(target, nn)),
                None,
            )
            if matched_id is not None and matched_id not in seen:
                seen.add(matched_id)
                ids.append(matched_id)
    return ids


def _collection_candidate_ids(spot_repo: SpotRepository) -> list[int]:
    """테마 컬렉션(홈/발견 화면에 실제로 노출) 후보. 원천 호출 없음(시드 판정값만 사용)."""
    pools = collections_service._theme_pool_ids(spot_repo)  # {theme_key: {region_code: [id,...]}}
    ids: list[int] = []
    seen: set[int] = set()
    for theme in collections_service.THEMES:
        by_region = pools.get(theme.key, {})
        for block in REGION_BLOCKS:
            for sid in by_region.get(block.region_code, []):
                if sid not in seen:
                    seen.add(sid)
                    ids.append(sid)
    return ids


async def build_priority_order(spot_repo: SpotRepository, region_filter: str | None) -> list[int]:
    """① trending → ② 컬렉션 후보 → ③ is_hidden_gem → ④ 나머지. 중복 제거(첫 등장 우선)."""
    ordered: list[int] = []
    seen: set[int] = set()

    def extend(ids: list[int]) -> None:
        for sid in ids:
            if sid not in seen:
                seen.add(sid)
                ordered.append(sid)

    extend(await _trending_ids(spot_repo))
    extend(_collection_candidate_ids(spot_repo))

    all_spots = spot_repo.all_spots()
    extend([s.id for s in all_spots if s.is_hidden_gem])
    extend([s.id for s in all_spots])

    if region_filter:
        by_id = {s.id: s for s in all_spots}
        ordered = [sid for sid in ordered if (sp := by_id.get(sid)) and sp.region_code == region_filter]

    return ordered


# ---------- 쿼터 방어(분당 상한) ----------


class RateLimiter:
    def __init__(self, per_min: int) -> None:
        self._min_interval = 60.0 / per_min if per_min > 0 else 0.0
        self._last_call: float | None = None

    async def wait(self) -> None:
        if self._min_interval <= 0:
            return
        now = time.monotonic()
        if self._last_call is not None:
            elapsed = now - self._last_call
            remaining = self._min_interval - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
        self._last_call = time.monotonic()


class QuotaExhausted(Exception):
    """detailCommon2 429 가 백오프 재시도 후에도 회복되지 않음 — 배치를 중단해야 한다."""


async def _fetch_overview_with_backoff(content_id: int, limiter: RateLimiter) -> str | None:
    """overview 1건. 429 는 지수 백오프 재시도, 그래도 안 되면 QuotaExhausted 를 던진다.

    429 가 아닌 실패(타임아웃/파싱오류/데이터없음)는 그 스팟만 None 처리(배치는 계속).
    """
    for attempt, backoff in enumerate((0.0, *QUOTA_BACKOFF_SEC)):
        if backoff:
            logger.warning("429 감지 → %.0f초 대기 후 재시도(contentId=%s)", backoff, content_id)
            await asyncio.sleep(backoff)
        await limiter.wait()
        try:
            item = await detail_client.fetch_detail_common(content_id)
        except TourApiDetailError as exc:
            if "429" in str(exc):
                continue  # 다음 백오프 단계
            logger.info("overview 조회 실패(스킵, contentId=%s): %s", content_id, type(exc).__name__)
            return None
        if item is None:
            return None
        raw = item.get("overview")
        return raw.strip() if isinstance(raw, str) and raw.strip() else None
    raise QuotaExhausted(f"429 재시도({len(QUOTA_BACKOFF_SEC)}회) 소진")


# ---------- 배치 실행 ----------


@dataclass
class RunStats:
    attempted: int = 0
    success: int = 0
    no_overview: int = 0
    short_skipped: int = 0
    llm_fail: int = 0
    already_cached: int = 0
    quota_aborted: bool = False


async def run_batch(target_ids, spot_repo, store, summarizer, limiter, checkpoint_every=1,
                    min_overview_chars: int = 0) -> RunStats:
    stats = RunStats()
    by_id = {s.id: s for s in spot_repo.all_spots()}
    with store.batch_lock():
        for sid in target_ids:
            if sid not in by_id:
                continue
            stats.attempted += 1
            try:
                overview = await _fetch_overview_with_backoff(sid, limiter)
            except QuotaExhausted:
                stats.quota_aborted = True
                break
            # 2026-09-21 대표 지시 "설명이 긴 것 위주로 3줄 요약": 짧은 소개글은 요약할 가치가 없고
            # 화면에서도 원문 발췌로 충분하다. LLM(건당 30~75초)이 병목이라 여기서 거른다(API 호출은 이미 씀).
            if overview is not None and len(overview) < min_overview_chars:
                stats.short_skipped += 1
                continue
            outcome = await process_one(store, summarizer, "spot", sid, overview)
            if outcome == "success":
                stats.success += 1
            elif outcome == "cached":
                stats.already_cached += 1
            elif outcome == "no_source":
                stats.no_overview += 1
            else:
                stats.llm_fail += 1
    logger.info("spot batch attempted=%d generated=%d cached=%d failed=%d no_source=%d short_skipped=%d",
                stats.attempted, stats.success, stats.already_cached, stats.llm_fail, stats.no_overview,
                stats.short_skipped)
    return stats


async def main() -> int:
    parser = argparse.ArgumentParser(description="Local LLM 관광지 요약 배치")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--region")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--rate-limit-per-min", type=int, default=25)
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--min-overview-chars", type=int, default=0,
                        help="소개글이 이 글자 수보다 짧으면 요약하지 않는다(0=전부). 긴 설명 위주로 돌릴 때 사용")
    args = parser.parse_args()
    if not args.all and (args.limit is None or args.limit <= 0):
        parser.error("--limit 양수 또는 --all이 필요합니다")
    if args.rate_limit_per_min <= 0:
        parser.error("--rate-limit-per-min은 양수여야 합니다")
    spots = JsonSpotRepository()
    if spots.total() == 0:
        logger.error("관광지 시드가 비어 있습니다. 먼저 관광지 수집을 실행하세요.")
        return 1
    store = SummaryRepository(settings.summary_store_dir, settings.ollama_model)
    if args.report_only:
        ids = [s.id for s in spots.all_spots() if not args.region or s.region_code == args.region]
        ids = ids if args.all else ids[:args.limit]
        ready = sum(bool(store.current(store.load("spot", sid))) for sid in ids)
        print(f"현재 유효 요약: {ready}/{len(ids)} (원천 API·LLM 호출 없음)")
        return 0
    ids = await build_priority_order(spots, args.region)
    ids = ids if args.all else ids[:args.limit]
    stats = await run_batch(ids, spots, store, create_summarizer_from_settings(settings),
                            RateLimiter(args.rate_limit_per_min), min_overview_chars=args.min_overview_chars)
    print(stats)
    return 1 if stats.quota_aborted or stats.llm_fail else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    raise SystemExit(asyncio.run(main()))
