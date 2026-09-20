# -*- coding: utf-8 -*-
"""QA 용 예시 데이터 시드(2026-09-20, 대표 지시 "예시 저장 스팟·공유 코스 줘서 QA 할 수 있게").

무엇을 넣나 — 전부 **실제 스팟·실제 혼잡도**로 만든다(지어낸 스팟 없음). 제목에 [예시] 를 붙여 샘플임을 밝힌다.
  1) 공유 코스: 지역별로 규칙 기반 코스(LLM 0회)를 만들어 공유 코스로 저장 → /courses 목록에 보인다.
  2) 저장한 스팟: 지정한 계정(--user-ids)에 그 코스의 스팟을 저장한다 → /saved 에 보인다.
  방문 스탬프는 브라우저 localStorage 전용(서버 무저장)이라 여기서 못 넣는다 — /saved 에서 "방문 확인"을 누르면 생긴다.

실행(운영 컨테이너 안):
    docker compose exec -T backend python scripts/seed_qa_samples.py --user-ids 2 3
멱등: 같은 제목의 공유 코스가 있으면 건너뛰고, 저장 스팟은 upsert 다.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from app.config import settings  # noqa: E402
from app.deps import get_cache, get_congestion_repository, get_database, get_spot_repository  # noqa: E402
from app.repositories import saved_spot_repo  # noqa: E402
from app.schemas.community import ShareCreateRequest  # noqa: E402
from app.services import course_service, share_service  # noqa: E402
from app.util.time import now_kst, to_iso_kst  # noqa: E402

# (region_code, 표시 이름) — 데모 4지역 + 서울·제주
REGIONS = [
    ("26350", "부산 해운대"),
    ("52111", "전주"),
    ("47130", "경주"),
    ("51150", "강릉"),
    ("11110", "서울 종로"),
    ("50110", "제주"),
]
NICKNAME = "샘플 여행자"
DEVICE_ID = "seed-qa-samples"


async def main(user_ids: list[int], dry_run: bool) -> int:
    db = get_database()
    spot_repo = get_spot_repository()
    cache = get_cache()
    congestion_repo = get_congestion_repository()
    made = 0
    saved_targets: list[tuple[int, dict | None]] = []

    for code, label in REGIONS:
        title = f"[예시] {label} 하루 코스"
        exists = await db.aread(
            lambda conn, t=title: conn.execute(
                "SELECT share_code FROM shared_courses WHERE title = %s LIMIT 1", (t,)
            ).fetchone()
        )
        if exists:
            print(f"skip  {title} (이미 있음 {exists['share_code']})")
            continue
        course = await course_service.build_course_response(
            code, None, spot_repo=spot_repo, congestion_repo=congestion_repo, cache=cache, summarizer=None
        )
        if len(course.spots) < 2:
            print(f"skip  {title} (스팟 {len(course.spots)}곳)")
            continue
        for s in course.spots:
            saved_targets.append((s.id, s.congestion.model_dump() if s.congestion else None))
        if dry_run:
            print(f"dry   {title}: {[s.name for s in course.spots]}")
            continue
        # 공유 저장 상한(SHARE_PAYLOAD_MAX_BYTES)을 넘으면 경로선(path)만 빼고 저장한다 — 스팟·구간 시간은 그대로.
        import json as _json

        payload = course.model_dump()
        if len(_json.dumps(payload, ensure_ascii=False).encode("utf-8")) > settings.share_payload_max_bytes:
            payload = course.model_dump(exclude={"legs": {"__all__": {"path"}}})
        res = await share_service.create_share(
            db,
            req=ShareCreateRequest(nickname=NICKNAME, title=title, course=payload),
            device_id=DEVICE_ID,
            max_bytes=settings.share_payload_max_bytes,
            spot_repo=spot_repo,
            cache=cache,
        )
        made += 1
        print(f"share {title}: {res.share_code} ({len(course.spots)}곳)")

    # 저장 스팟 — 계정당 최대 8곳(코스 앞쪽 스팟부터), 저장 시점 혼잡 스냅샷 포함
    seen: set[int] = set()
    picks = []
    for sid, cong in saved_targets:
        if sid in seen:
            continue
        seen.add(sid)
        picks.append((sid, cong))
        if len(picks) >= 8:
            break
    now_iso = to_iso_kst(now_kst())
    for uid in user_ids:
        if dry_run:
            print(f"dry   user {uid}: 저장 스팟 {[p[0] for p in picks]}")
            continue
        import json

        n = 0
        for sid, cong in picks:
            await db.awrite(
                lambda conn, sid=sid, cong=cong: saved_spot_repo.upsert(
                    conn,
                    user_id=uid,
                    spot_id=sid,
                    congestion_json=json.dumps(cong, ensure_ascii=False) if cong else None,
                    now_iso=now_iso,
                )
            )
            n += 1
        print(f"saved user {uid}: {n}곳")
    print(f"done: 공유 코스 {made}건 생성")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-ids", type=int, nargs="*", default=[])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.user_ids, a.dry_run)))
