"""방문 스탬프(계정 보관함) 리포지토리 — 2026-09-20 대표 지시
"방문 스탬프도 기기가 아니라 계정에, 브라우저 위치로 찍는 것".

스팟 본문은 저장하지 않는다(spot_id 만 신뢰, 읽을 때 스토어에서 재구성 — saved_spots 와 같은 관례).
**좌표는 어디에도 저장하지 않는다** — 위치 대조는 요청 처리 중에만 쓰고 버린다(위치정보 최소화).
"""

from __future__ import annotations

from typing import Any

import psycopg

MAX_PER_USER = 500


class StampLimitError(ValueError):
    pass


def list_by_user(conn: psycopg.Connection, *, user_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT spot_id, stamped_at
          FROM visit_stamps
         WHERE user_id = %s
         ORDER BY stamped_at DESC, spot_id DESC
         LIMIT %s
        """,
        (user_id, MAX_PER_USER),
    ).fetchall()
    return [dict(r) for r in rows]


def add(conn: psycopg.Connection, *, user_id: int, spot_id: int, now_iso: str) -> dict[str, Any]:
    """이미 찍은 곳이면 처음 찍은 시각을 그대로 둔다(멱등 — 재인증으로 날짜가 바뀌지 않게)."""
    conn.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user_id,))  # 상한 검사 직렬화
    exists = conn.execute(
        "SELECT spot_id, stamped_at FROM visit_stamps WHERE user_id = %s AND spot_id = %s", (user_id, spot_id)
    ).fetchone()
    if exists:
        return dict(exists)
    n = conn.execute("SELECT COUNT(*) AS n FROM visit_stamps WHERE user_id = %s", (user_id,)).fetchone()["n"]
    if int(n) >= MAX_PER_USER:
        raise StampLimitError()
    cur = conn.execute(
        "INSERT INTO visit_stamps (user_id, spot_id, stamped_at) VALUES (%s, %s, %s) RETURNING spot_id, stamped_at",
        (user_id, spot_id, now_iso),
    )
    return dict(cur.fetchone())


def delete(conn: psycopg.Connection, *, user_id: int, spot_id: int) -> bool:
    cur = conn.execute("DELETE FROM visit_stamps WHERE user_id = %s AND spot_id = %s", (user_id, spot_id))
    return cur.rowcount > 0
