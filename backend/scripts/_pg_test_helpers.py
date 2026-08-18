"""검증 스크립트 공용 — PostgreSQL 임시 스키마 격리 (2026-08-17, SQLite -> Postgres 전환).

예전 verify_*.py 는 매 실행마다 `tempfile.gettempdir()`에 SQLite 파일을 하나 만들어
완전히 격리된(다른 실행과 안 섞이고, 끝나면 지워지는) 저장소를 얻었다. Postgres는 파일이
아니라 **스키마** 단위로 그 격리를 흉내낸다 — `search_path`를 새로 만든 스키마 하나로
좁힌 DSN을 만들어 `DATABASE_URL`에 주입하면, 앱 코드(`db/postgres.py`, 리포지토리 전부)는
평소와 똑같이 동작하지만 실제로는 이번 실행만의 빈 테이블 세트를 본다.

사용법(각 verify_*.py 최상단, **다른 `app.*` import 전에**):
    from _pg_test_helpers import isolated_database_url, drop_schema
    _ISOLATED_DSN, _BASE_DSN, _SCHEMA = isolated_database_url()
    os.environ["DATABASE_URL"] = _ISOLATED_DSN
    ...(기존처럼 app.* import 및 테스트 진행)...
    ...(끝에서) drop_schema(_BASE_DSN, _SCHEMA)

`load_dotenv()`는 이미 `os.environ`에 있는 키를 덮어쓰지 않는다(기본 `override=False`) —
그래서 이 순서(스크립트가 먼저 DATABASE_URL을 격리된 값으로 세팅 → 이후 `app.config`가
로드될 때 `load_dotenv`가 그 값을 그대로 둔다)가 예전 `SQLITE_PATH` 패턴과 동일하게 먹힌다.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import psycopg
from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _read_base_dsn() -> str:
    """`app.config`를 로드하지 않고 .env에서 원본 DATABASE_URL만 읽는다(순환 방지 —
    config.py를 먼저 import해버리면 그 시점 os.environ 값으로 Settings가 고정된다)."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env_path = BACKEND_DIR / ".env"
    values = dotenv_values(env_path) if env_path.exists() else {}
    dsn = values.get("DATABASE_URL") or ""
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL을 찾을 수 없습니다 — backend/.env에 로컬 Postgres 접속 문자열이 "
            "있는지 확인하세요(README/.env.example 참고)."
        )
    return dsn


def isolated_database_url() -> tuple[str, str, str]:
    """새 스키마를 만들고 (격리된 DSN, 원본 DSN, 스키마명)을 반환한다."""
    base_dsn = _read_base_dsn()
    schema = f"verify_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    sep = "&" if "?" in base_dsn else "?"
    isolated_dsn = f"{base_dsn}{sep}options=-csearch_path%3D{schema}"
    return isolated_dsn, base_dsn, schema


def drop_schema(base_dsn: str, schema: str) -> None:
    """스크립트 종료 시 호출 — 임시 스키마와 그 안의 테이블 전부를 지운다."""
    try:
        with psycopg.connect(base_dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    except Exception:  # noqa: BLE001 — 정리 실패가 검증 결과를 가리면 안 된다
        pass


__all__ = ("drop_schema", "isolated_database_url")
