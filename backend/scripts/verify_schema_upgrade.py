# -*- coding: utf-8 -*-
"""이미 운영 중인 DB(옛 스키마)에 새 스키마를 적용해도 죽지 않는지 — 2026-09-20 v0.6.3 배포 사고 회귀.

CI 는 항상 빈 DB 라서 `CREATE TABLE IF NOT EXISTS` 뒤에 붙는 인덱스·ALTER 의 순서 오류를 못 잡는다
(reviews 에 user_id 가 없는 운영 DB 에서 "column user_id does not exist" 로 초기화 전체 실패).
여기서는 전체 스키마를 한 번 적용한 뒤 reviews 를 v10 이전 모양(user_id 없음)으로 되돌리고
후기 한 건을 넣은 채 다시 적용한다.

    py scripts/verify_schema_upgrade.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from _pg_test_helpers import drop_schema, isolated_database_url  # noqa: E402

_ISOLATED_DSN, _BASE_DSN, _SCHEMA = isolated_database_url()
os.environ["DATABASE_URL"] = _ISOLATED_DSN
os.environ.setdefault("PUBLIC_DATA_API_KEY", "verify-only")

from app.db.postgres import Database  # noqa: E402

FAIL: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAIL.append(name)


try:
    first = Database(_ISOLATED_DSN)
    check("빈 DB 에 전체 스키마 적용", first.ensure_ready())
    first.close()

    # 운영 상태 재현: reviews 를 기기 소유(user_id 없음) 모양으로 되돌린다.
    import psycopg

    with psycopg.connect(_ISOLATED_DSN, autocommit=True) as c:
        c.execute("DROP TABLE reviews CASCADE")
        c.execute(
            """CREATE TABLE reviews (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                target_type TEXT NOT NULL CHECK (target_type IN ('spot','festival')),
                target_id TEXT NOT NULL, device_id TEXT NOT NULL, nickname TEXT NOT NULL,
                rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5), comment TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, hidden INTEGER NOT NULL DEFAULT 0)"""
        )
        c.execute("CREATE UNIQUE INDEX ux_reviews_device_target ON reviews (device_id, target_type, target_id)")
        c.execute(
            "INSERT INTO reviews (target_type,target_id,device_id,nickname,rating,created_at,updated_at)"
            " VALUES ('spot','1','dev-1','옛후기',5,'2026-01-01','2026-01-01')"
        )

    upgraded = Database(_ISOLATED_DSN)
    check("옛 reviews(user_id 없음)가 있는 DB 에 스키마 적용", upgraded.ensure_ready())
    with psycopg.connect(_ISOLATED_DSN, autocommit=True) as c:
        cols = {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='reviews' AND table_schema=current_schema()")}
        check("user_id 컬럼 생성", "user_id" in cols)
        check("기기 소유 옛 후기 삭제(대표 결정)", c.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0)
        idx = {r[0] for r in c.execute("SELECT indexname FROM pg_indexes WHERE tablename='reviews' AND schemaname=current_schema()")}
        check("계정 기준 유일 인덱스 생성", "ux_reviews_user_target" in idx)
        check("기기 기준 옛 인덱스 제거", "ux_reviews_device_target" not in idx)
    upgraded.close()
    again = Database(_ISOLATED_DSN)
    check("한 번 더 적용해도 멱등", again.ensure_ready())
    again.close()
finally:
    drop_schema(_BASE_DSN, _SCHEMA)

print("\n== FAIL ==" if FAIL else "\n== ALL PASS ==", FAIL or "")
sys.exit(1 if FAIL else 0)
