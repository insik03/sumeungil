"""SQLite -> PostgreSQL 데이터 이관 (2026-08-17, DB 전환 1회성 스크립트).

`db/sqlite.py`가 쓰던 파일 1개(기본 `data/sumeungil.db`)에 남아있는 기존 행을 새
PostgreSQL(`DATABASE_URL`)로 옮긴다. Postgres 쪽 테이블은 앱이 이미 `ensure_ready()`로
스키마를 만들어둔 상태를 전제한다(이 스크립트는 스키마를 만들지 않는다 — 앱을 한 번
기동시켜 두거나, `db.postgres.Database(...).ensure_ready()`를 먼저 호출할 것).

PK 보존: `users`/`reviews`/`review_reports`/`admin_actions`는 `GENERATED ALWAYS AS
IDENTITY` PK라 기본적으로 명시 삽입이 거부된다 — `OVERRIDING SYSTEM VALUE`로 원래 id를
그대로 넣고, 이관 후 시퀀스를 `MAX(id)`로 재조정한다(다음 INSERT가 중복 PK로 안 튕기게).
`review_reports.review_id`가 `reviews.id`를 FK로 참조하므로 **반드시 reviews를 먼저**
이관한다(순서 하드코딩, 실수 방지).

실행:
    cd backend && py scripts/migrate_sqlite_to_postgres.py [sqlite 경로]
    (인자 생략 시 backend/data/sumeungil.db)

멱등성: 대상 Postgres 테이블에 이미 행이 있으면 그 테이블은 건너뛴다(중복 이관 방지) —
재실행해도 안전하지만, "이번엔 최신 SQLite 상태로 다시 밀어넣고 싶다"는 시나리오는
지원하지 않는다(그런 경우 Postgres 쪽 테이블을 수동으로 비우고 재실행할 것).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.db.postgres import Database  # noqa: E402

DEFAULT_SQLITE_PATH = BACKEND_DIR / "data" / "sumeungil.db"

# (테이블명, 컬럼 목록, identity PK 컬럼명 또는 None) — 이 순서 그대로 이관한다.
_TABLES: tuple[tuple[str, tuple[str, ...], str | None], ...] = (
    ("users", ("id", "google_sub", "email", "display_name", "created_at", "last_login_at"), "id"),
    (
        "reviews",
        (
            "id", "target_type", "target_id", "device_id", "nickname", "rating",
            "comment", "created_at", "updated_at", "hidden",
        ),
        "id",
    ),
    (
        "review_reports",
        ("id", "review_id", "device_id", "reason", "created_at"),
        "id",
    ),
    (
        "shared_courses",
        (
            "share_code", "device_id", "nickname", "title", "payload",
            "spot_count", "created_at", "view_count", "hidden",
        ),
        None,  # PK가 share_code(TEXT) — seq는 이관 순서대로 자동 채번(정렬 타이브레이커일 뿐 값 무의미)
    ),
    (
        "admin_actions",
        ("id", "action", "target_type", "target_id", "at", "ip_hash"),
        "id",
    ),
    ("visit_daily", ("day", "ip_hash", "hits", "first_seen", "last_seen"), None),
    ("visit_path_daily", ("day", "path", "hits"), None),
    ("visit_hour_daily", ("day", "hour", "hits"), None),
)


def _migrate_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn,
    table: str,
    columns: tuple[str, ...],
    identity_pk: str | None,
) -> int:
    existing = pg_conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
    if existing:
        print(f"  [스킵] {table}: Postgres에 이미 {existing}행 있음")
        return 0

    # 2026-08-18(운영 이관 실전 대응) — 원본 SQLite가 이 앱의 여러 버전에 걸쳐 만들어졌을 수
    # 있어(예: users 테이블은 로그인 기능 도입 이후에만 존재), 아예 없는 테이블은 조용히
    # 건너뛴다. sqlite_master에 없으면 그 기능 자체가 그 배포 시점엔 없었다는 뜻이라
    # 데이터 손실이 아니다 — 원래도 없던 데이터다.
    exists = sqlite_conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        print(f"  [건너뜀] {table}: SQLite에 테이블 자체가 없음(이 배포 시점엔 없던 기능)")
        return 0

    rows = sqlite_conn.execute(
        f"SELECT {', '.join(columns)} FROM {table} ORDER BY "
        + (f"{identity_pk}" if identity_pk else "created_at" if "created_at" in columns else "day")
    ).fetchall()
    if not rows:
        print(f"  [건너뜀] {table}: SQLite에 행 없음")
        return 0

    placeholders = ", ".join(["%s"] * len(columns))
    col_list = ", ".join(columns)
    overriding = " OVERRIDING SYSTEM VALUE" if identity_pk else ""
    sql = f"INSERT INTO {table} ({col_list}){overriding} VALUES ({placeholders})"
    for row in rows:
        pg_conn.execute(sql, tuple(row[c] for c in columns))

    if identity_pk:
        pg_conn.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', '{identity_pk}'), "
            f"(SELECT MAX({identity_pk}) FROM {table}))"
        )

    print(f"  [완료] {table}: {len(rows)}행 이관")
    return len(rows)


def main() -> None:
    sqlite_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SQLITE_PATH
    if not sqlite_path.exists():
        print(f"SQLite 파일이 없습니다: {sqlite_path} — 이관할 데이터가 없으므로 종료합니다.")
        return

    print(f"원본: {sqlite_path}")
    print(f"대상: {settings.database_url.split('@')[-1] if settings.database_url else '(DATABASE_URL 미설정)'}")
    if not settings.database_url:
        print("DATABASE_URL이 비어 있습니다 — .env를 확인하세요.")
        sys.exit(1)

    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row

    pg_db = Database(settings.database_url)
    pg_db.ensure_ready()

    total = 0

    def _tx(pg_conn):
        nonlocal total
        for table, columns, identity_pk in _TABLES:
            total += _migrate_table(sqlite_conn, pg_conn, table, columns, identity_pk)

    pg_db.write(_tx)
    pg_db.close()
    sqlite_conn.close()
    print(f"\n총 {total}행 이관 완료.")


if __name__ == "__main__":
    main()
