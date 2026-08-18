"""inquiries 테이블 SQL (2026-08-18 신설) — 로그인 계정이 남긴 고객문의.

ai_course_repo.py와 동일한 규약: 동기 함수 + 첫 인자 `psycopg.Connection`, 모든 값은
`%s` 바인딩. 이 파일의 함수는 본인 문의 조회/작성만 다룬다 — 남의 문의를 볼 수단은 없다
(user_id로 소유권 확인). 전체 문의 조회·답변은 admin_repo.py(관리자 콘솔, 2026-08-18 추가)가
따로 맡는다 — 공개 API가 실수로 남의 문의를 반환하지 않도록 파일을 나눈다(admin_repo.py
상단 주석의 "왜 기존 repo에 얹지 않고 파일을 나눴나"와 같은 이유).
"""

from __future__ import annotations

from typing import Any

import psycopg

MAX_LIMIT = 50


def create(
    conn: psycopg.Connection,
    *,
    user_id: int,
    message: str,
    contact_email: str | None,
    now_iso: str,
) -> dict[str, Any]:
    cur = conn.execute(
        """
        INSERT INTO inquiries (user_id, contact_email, message, status, created_at)
        VALUES (%s, %s, %s, 'new', %s)
        RETURNING id, status, created_at
        """,
        (user_id, contact_email, message, now_iso),
    )
    return dict(cur.fetchone())


def list_by_user(
    conn: psycopg.Connection, *, user_id: int, limit: int = MAX_LIMIT, offset: int = 0
) -> list[dict[str, Any]]:
    """message 전문은 목록에서 SELECT 하지 않는다(ai_course_repo의 payload 생략 관례와 동일).
    reply는 짧고(관리자 육안 작성) 목록에서도 바로 보여야 의미가 있어 함께 뽑는다."""
    rows = conn.execute(
        """
        SELECT id, status, created_at, reply, replied_at
          FROM inquiries
         WHERE user_id = %s
         ORDER BY created_at DESC, id DESC
         LIMIT %s OFFSET %s
        """,
        (user_id, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def get(conn: psycopg.Connection, *, inquiry_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM inquiries WHERE id = %s", (inquiry_id,)).fetchone()
    return dict(row) if row else None


def set_reply(
    conn: psycopg.Connection, *, inquiry_id: int, reply: str, replied_by: str, replied_at: str
) -> int:
    """답변 등록 → status도 함께 'resolved'로 바꾼다. 변경된 행 수(0이면 그런 문의가 없다)."""
    cur = conn.execute(
        """
        UPDATE inquiries
           SET reply = %s, replied_by = %s, replied_at = %s, status = 'resolved'
         WHERE id = %s
        """,
        (reply, replied_by, replied_at, inquiry_id),
    )
    return int(cur.rowcount)


__all__ = ("MAX_LIMIT", "create", "get", "list_by_user", "set_reply")
