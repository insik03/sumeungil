"""ai_courses 테이블 SQL (2026-08-17 신설) — 계정에 저장한 AI 코스짜기 결과.

shared_course_repo.py와 같은 규약: 동기 함수 + 첫 인자 `psycopg.Connection`, 모든 값은
`%s` 바인딩. `payload`는 `CourseResponse`를 그대로 JSON 직렬화한 문자열 — 이 파일은
내용을 해석하지 않는다(`shared_courses.payload`와 동일 관례, 코스 응답 스키마가 바뀌어도
저장소는 영향받지 않는다).

`shared_courses`(공개 공유 링크)와는 별개다 — 이건 **본인만 보는 개인 보관함**이라
`device_id` 대신 `user_id`로 소유권을 확인하고, 목록/삭제 전부 로그인 필수다.
"""

from __future__ import annotations

from typing import Any

import psycopg

MAX_LIMIT = 50


def create(
    conn: psycopg.Connection,
    *,
    user_id: int,
    region_code: str,
    mode: str,
    payload_json: str,
    now_iso: str,
) -> dict[str, Any]:
    cur = conn.execute(
        """
        INSERT INTO ai_courses (user_id, region_code, mode, payload, created_at)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, user_id, region_code, mode, created_at
        """,
        (user_id, region_code, mode, payload_json, now_iso),
    )
    return dict(cur.fetchone())


def list_by_user(
    conn: psycopg.Connection, *, user_id: int, limit: int = MAX_LIMIT, offset: int = 0
) -> list[dict[str, Any]]:
    """payload는 목록에서 절대 SELECT 하지 않는다(항목당 클 수 있음 — shared_courses 관례)."""
    rows = conn.execute(
        """
        SELECT id, region_code, mode, created_at
          FROM ai_courses
         WHERE user_id = %s
         ORDER BY created_at DESC, id DESC
         LIMIT %s OFFSET %s
        """,
        (user_id, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def get(conn: psycopg.Connection, *, course_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM ai_courses WHERE id = %s", (course_id,)
    ).fetchone()
    return dict(row) if row else None


def delete(conn: psycopg.Connection, *, course_id: int, user_id: int) -> bool:
    """본인 것만 지운다 — `user_id`가 안 맞으면 조용히 0행 삭제(호출부가 소유권 판단)."""
    cur = conn.execute(
        "DELETE FROM ai_courses WHERE id = %s AND user_id = %s", (course_id, user_id)
    )
    return cur.rowcount > 0


__all__ = ("MAX_LIMIT", "create", "delete", "get", "list_by_user")
