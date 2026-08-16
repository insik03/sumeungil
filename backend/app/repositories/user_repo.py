"""users 테이블 SQL — 구글 로그인 계정(2026-08-17 신설, schema_version 4).

review_repo.py와 동일한 규약: 전부 동기 함수, 첫 인자로 `sqlite3.Connection`, 호출은
반드시 `Database.aread/awrite`를 통해서만(서비스/라우터 레이어 책임). SQL은 전부 파라미터
바인딩(`?`) — 문자열 포매팅으로 값을 넣지 않는다.
"""

from __future__ import annotations

import sqlite3
from typing import Any


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


def get_by_id(conn: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def get_by_google_sub(conn: sqlite3.Connection, google_sub: str) -> dict[str, Any] | None:
    return _row(
        conn.execute("SELECT * FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
    )


def upsert_login(
    conn: sqlite3.Connection,
    *,
    google_sub: str,
    email: str,
    default_display_name: str,
    now_iso: str,
) -> dict[str, Any]:
    """로그인마다 호출. 기존 계정이면 email/last_login_at만 갱신하고 **display_name은
    건드리지 않는다**(사용자가 이전에 직접 정한 이름을 구글 원본 이름으로 되돌리지 않기
    위해서 — db/sqlite.py schema_version 4 주석 참고). 신규 계정이면 display_name을
    default_display_name(구글 이름)으로 초기화해 만든다."""
    existing = get_by_google_sub(conn, google_sub)
    if existing is not None:
        conn.execute(
            "UPDATE users SET email = ?, last_login_at = ? WHERE id = ?",
            (email, now_iso, existing["id"]),
        )
        return get_by_id(conn, existing["id"])  # type: ignore[return-value]
    cur = conn.execute(
        """
        INSERT INTO users (google_sub, email, display_name, created_at, last_login_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (google_sub, email, default_display_name, now_iso, now_iso),
    )
    return get_by_id(conn, cur.lastrowid)  # type: ignore[return-value]


def update_display_name(
    conn: sqlite3.Connection, *, user_id: int, display_name: str
) -> dict[str, Any] | None:
    conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (display_name, user_id))
    return get_by_id(conn, user_id)


__all__ = ("get_by_google_sub", "get_by_id", "update_display_name", "upsert_login")
