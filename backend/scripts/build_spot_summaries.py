"""스팟 AI 요약(ai_summary) 사전 생성 배치 — 실시간 LLM 의존을 끊는다.

배경(오케스트레이터 진단, 2026-07-31): 운영 서버는 2 vCPU 라 7B 추론이 50초+ 걸려
OLLAMA_BASE_URL 을 사실상 비워두고 폴백 모드로 운영 중이다. 그 결과 ai_summary 가 서버에서
100% null. 스팟 소개글은 거의 안 바뀌는 정적 콘텐츠라, "요청마다 생성"할 이유가 없다 —
이 스크립트로 **미리** 만들어 파일로 배포하고, 서버는 그 파일을 읽기만 한다
(app/services/spot_detail_service.py 의 "사전 생성 → 캐시 → 라이브" 순서와 짝을 이룬다).

무엇을 하는가:
  1) 우선순위 순으로 스팟 id 후보를 고른다 — ① 9권역 board 상위(trending), ② 테마 컬렉션
     후보(collections_service 재사용), ③ is_hidden_gem, ④ 나머지.
  2) 스팟마다 detailCommon2 로 overview 를 얻고(쿼터 상한 준수), 로컬 Ollama Summarizer 로
     3줄 요약을 만든다.
  3) 성공분만 `app/spots/data/spot_summaries.json` 에 append 한다. **실패(overview 없음/LLM
     실패)는 파일에 기록하지 않는다** — null 을 캐시하면 다음 실행에서 영영 재시도가 안 되기
     때문이다(스팟 상세 조회 서비스의 기존 null-비캐시 정책과 동일 원칙).
  4) 이미 파일에 있는 id 는 건너뛴다 → **몇 번을 나눠 돌려도 재개 가능**.

절대 하지 않는 것(금지):
  - 요약을 지어내지 않는다. overview 가 없으면 그 스팟은 요약 없음(null)이 정답이다.
  - 원문 overview 를 저장하지 않는다(용량·저작권 — 요약만 저장).
  - 신규 유료 API·의존성을 쓰지 않는다. 사용자 텍스트(리뷰)를 프롬프트에 넣지 않는다.

실행 예시:
    cd projects/sumeungil-build/backend
    py scripts/build_spot_summaries.py --limit 300              # 우선순위 상위 300곳 생성/재개
    py scripts/build_spot_summaries.py --limit 300 --report-only # API 호출 없이 커버리지만 출력
    py scripts/build_spot_summaries.py --region 26350 --limit 50 # 특정 시군구만
    py scripts/build_spot_summaries.py --all                     # 전체 스팟(21,019곳) 대상

쿼터 방어: --rate-limit-per-min (기본 25) 으로 detailCommon2 호출 간격을 둔다. 429(그 오퍼레이션
일일 한도 초과로 실측 확인됨, tourapi_detail_client.py) 감지 시 지수 백오프 재시도 후에도
실패하면 **배치 전체를 중단**하고 지금까지의 진행분을 저장한다(쿼터를 더 태우지 않는다).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.summarizer import Summarizer, create_summarizer_from_settings  # noqa: E402
from app.cache.memory import MemoryCache  # noqa: E402
from app.clients import tourapi_detail_client as detail_client  # noqa: E402
from app.clients.tourapi_detail_client import TourApiDetailError  # noqa: E402
from app.config import settings  # noqa: E402
from app.regions.nationwide import REGION_BLOCKS  # noqa: E402
from app.repositories.congestion_repo import LiveCongestionRepository  # noqa: E402
from app.repositories.spot_repo import JsonSpotRepository, SpotRecord, SpotRepository  # noqa: E402
from app.services import collections_service  # noqa: E402
from app.util.names import name_matches, norm_name  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("sumeungil.scripts.build_spot_summaries")

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "app" / "spots" / "data" / "spot_summaries.json"
KST = ZoneInfo("Asia/Seoul")

# board 상위에서 트렌딩 후보로 끌어올 지역당 상한(9권역 × 15 ≈ 135개 후보 풀).
TRENDING_TOP_PER_REGION = 15
# 429 재시도 백오프(초). 전부 실패하면 배치를 중단한다(쿼터 방어).
QUOTA_BACKOFF_SEC = (10.0, 30.0, 60.0)


def _now_iso() -> str:
    return datetime.now(KST).isoformat()


# ---------- 출력 파일 로드/저장 ----------


@dataclass
class SummaryStore:
    path: Path
    model: str
    summaries: dict[str, dict]  # spot_id(str) -> {"summary","source","at"}

    @classmethod
    def load(cls, path: Path, model: str) -> "SummaryStore":
        if not path.exists():
            return cls(path=path, model=model, summaries={})
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            logger.warning("기존 요약 파일 파싱 실패(새로 시작): %s: %s", path, exc)
            return cls(path=path, model=model, summaries={})
        summaries = data.get("summaries")
        if not isinstance(summaries, dict):
            summaries = {}
        return cls(path=path, model=model, summaries=summaries)

    def has(self, spot_id: int) -> bool:
        return str(spot_id) in self.summaries

    def put(self, spot_id: int, summary: str) -> None:
        self.summaries[str(spot_id)] = {"summary": summary, "source": "llm", "at": _now_iso()}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "generated_at": _now_iso(),
            "model": self.model,
            "summaries": self.summaries,
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)  # 원자적 교체 — 중간에 죽어도 기존 파일이 깨지지 않는다


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
    last_exc: Exception | None = None
    for attempt, backoff in enumerate((0.0, *QUOTA_BACKOFF_SEC)):
        if backoff:
            logger.warning("429 감지 → %.0f초 대기 후 재시도(contentId=%s)", backoff, content_id)
            await asyncio.sleep(backoff)
        await limiter.wait()
        try:
            item = await detail_client.fetch_detail_common(content_id)
        except TourApiDetailError as exc:
            last_exc = exc
            if "429" in str(exc):
                continue  # 다음 백오프 단계
            logger.info("overview 조회 실패(스킵, contentId=%s): %s", content_id, exc)
            return None
        if item is None:
            return None
        raw = item.get("overview")
        return raw.strip() if isinstance(raw, str) and raw.strip() else None
    raise QuotaExhausted(f"429 재시도({len(QUOTA_BACKOFF_SEC)}회) 소진: {last_exc}")


# ---------- 배치 실행 ----------


@dataclass
class RunStats:
    attempted: int = 0
    success: int = 0
    no_overview: int = 0
    llm_fail: int = 0
    already_cached: int = 0
    quota_aborted: bool = False


async def run_batch(
    target_ids: list[int],
    spot_repo: SpotRepository,
    store: SummaryStore,
    summarizer: Summarizer,
    limiter: RateLimiter,
    checkpoint_every: int,
) -> RunStats:
    stats = RunStats()
    by_id = {s.id: s for s in spot_repo.all_spots()}
    since_checkpoint = 0

    for idx, sid in enumerate(target_ids, start=1):
        if store.has(sid):
            stats.already_cached += 1
            continue

        spot = by_id.get(sid)
        if spot is None:
            continue

        stats.attempted += 1
        try:
            overview = await _fetch_overview_with_backoff(sid, limiter)
        except QuotaExhausted as exc:
            logger.error("쿼터 소진으로 배치 중단: %s", exc)
            stats.quota_aborted = True
            break

        if not overview:
            stats.no_overview += 1
            print(f"[{idx}/{len(target_ids)}] id={sid} name={spot.name} overview 없음 → 스킵")
            continue

        summary = await summarizer.summarize(overview)
        if not summary:
            stats.llm_fail += 1
            print(f"[{idx}/{len(target_ids)}] id={sid} name={spot.name} LLM 요약 실패 → 스킵")
            continue

        store.put(sid, summary)
        stats.success += 1
        since_checkpoint += 1
        print(f"[{idx}/{len(target_ids)}] id={sid} name={spot.name} 요약 완료")

        if since_checkpoint >= checkpoint_every:
            store.save()
            since_checkpoint = 0

    store.save()
    return stats


def print_report(target_n: int, store: SummaryStore, target_ids: list[int], stats: RunStats | None) -> None:
    have = sum(1 for sid in target_ids if store.has(sid))
    pct = (have / target_n * 100) if target_n else 0.0
    print("\n=== 커버리지 리포트 ===")
    print(f"대상 {target_n}곳 중 요약 보유 {have}곳 ({pct:.1f}%)")
    if stats is not None:
        print(
            f"이번 실행: 시도 {stats.attempted}곳 / 성공 {stats.success}곳 / "
            f"overview 없음 {stats.no_overview}곳 / LLM 실패 {stats.llm_fail}곳 / "
            f"이미 보유(스킵) {stats.already_cached}곳"
        )
        if stats.quota_aborted:
            print("⚠ 429(쿼터 소진)로 배치가 중간에 중단됐습니다. 나중에 같은 명령으로 재개하세요.")
    print(f"파일: {store.path} (존재={'예' if store.path.exists() else '아니오'})")


async def main() -> int:
    parser = argparse.ArgumentParser(description="스팟 AI 요약 사전 생성 배치")
    parser.add_argument("--limit", type=int, default=None, help="우선순위 상위 N곳을 대상으로 처리")
    parser.add_argument("--region", type=str, default=None, help="특정 region_code(시군구 5자리)만 대상")
    parser.add_argument("--all", action="store_true", help="전 스팟을 대상(우선순위 순서는 유지)")
    parser.add_argument(
        "--rate-limit-per-min", type=int, default=25, help="detailCommon2 분당 호출 상한(기본 25)"
    )
    parser.add_argument(
        "--checkpoint-every", type=int, default=5, help="N건 성공마다 파일 저장(기본 5)"
    )
    parser.add_argument(
        "--report-only", action="store_true", help="API 호출 없이 현재 파일 기준 커버리지만 출력"
    )
    args = parser.parse_args()

    if not args.all and args.limit is None:
        parser.error("--limit N 또는 --all 중 하나는 필수입니다.")

    spot_repo = JsonSpotRepository()
    if spot_repo.total() == 0:
        print("[FATAL] 스팟 시드가 비어 있습니다. app/spots/data/spots_seed.json 확인 필요.")
        return 1

    store = SummaryStore.load(OUTPUT_PATH, settings.ollama_model)

    print("우선순위 후보 목록 구성 중(9권역 board + 테마 컬렉션 + hidden_gem)...")
    priority_ids = await build_priority_order(spot_repo, args.region)
    target_ids = priority_ids if args.all else priority_ids[: args.limit]
    print(f"대상 스팟 {len(target_ids)}곳 확정(전체 후보 풀 {len(priority_ids)}곳 중).")

    if args.report_only:
        print_report(len(target_ids), store, target_ids, stats=None)
        return 0

    summarizer = create_summarizer_from_settings(settings)
    limiter = RateLimiter(args.rate_limit_per_min)

    t0 = time.time()
    stats = await run_batch(target_ids, spot_repo, store, summarizer, limiter, args.checkpoint_every)
    elapsed = time.time() - t0

    print(f"\n소요 시간: {elapsed:.1f}초 ({elapsed / 60:.1f}분)")
    print_report(len(target_ids), store, target_ids, stats)
    return 1 if stats.quota_aborted else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
