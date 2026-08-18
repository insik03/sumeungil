"""표본 조사 — firstimage 없는 스팟이 기존 폴백 체인(photo_service.fallback_photo, ③④단계)
실행 후 실제로 사진이 채워지는 비율. 대표 요청(2026-08-13): "크롤링 전에 기존 폴백으로
얼마나 채워지는지 먼저 확인". 전수(2,501곳) 대신 표본만 호출해 일일 쿼터를 보호한다.

실행:
    cd backend
    py scripts/sample_missing_photo_coverage.py [표본크기(기본 80)]
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cache.memory import MemoryCache  # noqa: E402
from app.services import photo_service  # noqa: E402

SEED_PATH = Path(__file__).resolve().parent.parent / "app" / "spots" / "data" / "spots_seed.json"
SAMPLE_SEED = 20260813
CALL_DELAY_SEC = 0.4


async def main(sample_size: int) -> None:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    spots = data if isinstance(data, list) else data.get("spots", data)
    no_image = [s for s in spots if not s.get("image_url")]
    print(f"사진 없는 스팟 전체: {len(no_image)}곳")

    rng = random.Random(SAMPLE_SEED)
    sample = rng.sample(no_image, min(sample_size, len(no_image)))
    print(f"표본 크기: {len(sample)}곳 (seed={SAMPLE_SEED}, 기존 폴백 체인 ③detailImage2+④갤러리 전체 실행)\n")

    cache = MemoryCache()
    filled = 0
    empty = 0
    cat_filled: Counter[str] = Counter()
    cat_empty: Counter[str] = Counter()
    source_count: Counter[str] = Counter()

    for i, spot in enumerate(sample, 1):
        cid = spot.get("id")
        name = spot.get("name", "?")
        cat = spot.get("category", "?")
        addr = spot.get("address")

        photo = await photo_service.fallback_photo(int(cid), name, addr, cache)

        if photo.url:
            filled += 1
            cat_filled[cat] += 1
            source_count[photo.source or "?"] += 1
            print(f"[{i}/{len(sample)}] 채워짐({photo.source}) — {name} ({cat})")
        else:
            empty += 1
            cat_empty[cat] += 1
            print(f"[{i}/{len(sample)}] 진짜 없음 — {name} ({cat})")

        await asyncio.sleep(CALL_DELAY_SEC)

    n = len(sample)
    print("\n=== 결과 (기존 폴백 체인 전체 적용 후) ===")
    print(f"표본 {n}곳 중 채워짐: {filled}곳 ({filled/n*100:.1f}%)")
    print(f"원천에 진짜 없음: {empty}곳 ({empty/n*100:.1f}%)")
    print(f"채워진 경로: {dict(source_count)}")
    print(f"\n전체 {len(no_image)}곳에 표본 비율 적용 시 추정:")
    print(f"  기존 폴백으로 이미 채워지는 곳 ≈ {round(len(no_image) * filled / n)}곳")
    print(f"  정말 크롤링 없인 방법 없는 곳 ≈ {round(len(no_image) * empty / n)}곳")
    print(f"\n카테고리별 채워짐: {dict(cat_filled)}")
    print(f"카테고리별 진짜 없음: {dict(cat_empty)}")


if __name__ == "__main__":
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    asyncio.run(main(size))
