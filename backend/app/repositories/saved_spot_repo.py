"""저장한 스팟(계정 보관함) 리포지토리 — 2026-09-16 대표 지시
"저장한 스팟도 브라우저나 기기가 아닌 그 계정의 데이터로서 저장".

종전엔 프론트 localStorage 단독(savedSpotsStorage.ts)이라 기기·브라우저를 바꾸면 사라졌다.
스팟 본문(이름·좌표·카테고리)은 저장하지 않는다 — spot_id 만 믿고 읽을 때 스토어에서 재구성한다
(ai_course_repo 의 "스팟 id 만 신뢰" 관례). 혼잡도만 "저장 시점 스냅샷"으로 함께 둔다(프론트
SavedSpotCard 가 저장 시점 값임을 표기해 보여주던 기능 유지).
"""

from __future__ import annotations

from typing import Any

import psycopg

MAX_PER_USER = 500

class SavedSpotLimitError(ValueError):
    pass


def list_by_user(conn: psycopg.Connection, *, user_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT spot_id, congestion, saved_at
          FROM saved_spots
         WHERE user_id = %s
         ORDER BY saved_at DESC, spot_id DESC
         LIMIT %s
        """,
        (user_id, MAX_PER_USER),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert(
    conn: psycopg.Connection,
    *,
    user_id: int,
    spot_id: int,
    congestion_json: str | None,
    now_iso: str,
) -> dict[str, Any]:
    """같은 스팟을 다시 저장하면 저장 시각·스냅샷만 갱신한다(중복 행 없음)."""
    # 저장 트랜잭션 안에서 계정 단위로 직렬화한다 — 상한 검사와 INSERT 사이에 다른 요청이
    # 끼어들어 상한을 넘기지 못하게(FOR UPDATE).
    conn.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user_id,))
    exists = conn.execute("SELECT 1 FROM saved_spots WHERE user_id = %s AND spot_id = %s", (user_id, spot_id)).fetchone()
    if not exists and count_by_user(conn, user_id=user_id) >= MAX_PER_USER:
        raise SavedSpotLimitError()
    cur = conn.execute(
        """
        INSERT INTO saved_spots (user_id, spot_id, congestion, saved_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id, spot_id)
        DO UPDATE SET congestion = EXCLUDED.congestion, saved_at = EXCLUDED.saved_at
        RETURNING spot_id, congestion, saved_at
        """,
        (user_id, spot_id, congestion_json, now_iso),
    )
    return dict(cur.fetchone())


def count_by_user(conn: psycopg.Connection, *, user_id: int) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM saved_spots WHERE user_id = %s", (user_id,)).fetchone()
    return int(row["n"]) if row else 0


def delete(conn: psycopg.Connection, *, user_id: int, spot_id: int) -> bool:
    cur = conn.execute(
        "DELETE FROM saved_spots WHERE user_id = %s AND spot_id = %s", (user_id, spot_id)
    )
    return cur.rowcount > 0
