"""onboarding_profiles 테이블 SQL (2026-08-17 신설).

review_repo.py와 같은 규약: 동기 함수 + 첫 인자 `psycopg.Connection`, 모든 값은 `%s`
바인딩. `tags`/`tag_vector`/`scoring_weights`는 이미 JSON 문자열로 직렬화된 값을 받는다
(이 파일은 JSON을 해석하지 않는다 — `shared_course_repo.py`의 `payload` 관례와 동일).

계정당 **최신 프로필 1건만** 보관한다(history 아님) — `user_id`가 PK라 `upsert` 하나로
"있으면 갱신, 없으면 생성"이 끝난다(`user_repo.upsert_login`과 같은 패턴).
"""

from __future__ import annotations

from typing import Any

import psycopg


def _row(r: dict[str, Any] | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


def get_by_user_id(conn: psycopg.Connection, user_id: int) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            "SELECT * FROM onboarding_profiles WHERE user_id = %s", (user_id,)
        ).fetchone()
    )


def upsert(
    conn: psycopg.Connection,
    *,
    user_id: int,
    tags_json: str,
    tag_vector_json: str,
    vector_version: int,
    scoring_weights_json: str,
    extraction_confidence: float,
    extracted_by: str,
    fallback_used: bool,
    now_iso: str,
) -> dict[str, Any]:
    """온보딩을 다시 완료할 때마다 호출 — 이전 프로필을 최신 결과로 완전히 덮어쓴다
    (표시 이름과 달리 "이전 값을 보존"할 이유가 없다 — 취향은 최신 것이 곧 정답)."""
    conn.execute(
        """
        INSERT INTO onboarding_profiles
            (user_id, tags, tag_vector, vector_version, scoring_weights,
             extraction_confidence, extracted_by, fallback_used, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            tags = excluded.tags,
            tag_vector = excluded.tag_vector,
            vector_version = excluded.vector_version,
            scoring_weights = excluded.scoring_weights,
            extraction_confidence = excluded.extraction_confidence,
            extracted_by = excluded.extracted_by,
            fallback_used = excluded.fallback_used,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            tags_json,
            tag_vector_json,
            vector_version,
            scoring_weights_json,
            extraction_confidence,
            extracted_by,
            1 if fallback_used else 0,
            now_iso,
        ),
    )
    return get_by_user_id(conn, user_id)  # type: ignore[return-value]


__all__ = ("get_by_user_id", "upsert")
