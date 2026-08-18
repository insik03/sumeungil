"""reviews / review_reports 테이블 SQL — 부록 R.

여기 있는 함수는 전부 **동기**이며 첫 인자로 `psycopg.Connection` 을 받는다. 호출은 반드시
`Database.aread/awrite` 를 통해서만 한다(서비스 레이어 책임) — 그래야 이벤트 루프가 막히지
않고, 여러 문장이 한 트랜잭션으로 묶인다.

SQL 은 **전부 파라미터 바인딩(`%s`)** 이다. 문자열 포매팅으로 값을 넣은 곳이 하나도 없어야
한다(IN 절의 플레이스홀더 생성도 값이 아니라 개수만 문자열로 만든다).

2026-08-17: PostgreSQL 전환(db/postgres.py)으로 `?` → `%s`, `cur.lastrowid` → `RETURNING id`,
`INSERT OR IGNORE` → `ON CONFLICT ... DO NOTHING`으로 바뀌었다(로직은 무변경).
"""

from __future__ import annotations

from typing import Any, Iterable

import psycopg

# 목록 1회 조회 상한 — 페이지네이션 남용으로 한 번에 수천 건을 긁어가지 못하게 한다.
MAX_LIMIT = 50
# 일괄 요약(N+1 방지 엔드포인트)이 한 번에 받는 target_id 개수 상한.
MAX_SUMMARY_IDS = 100


def _row(r: dict[str, Any] | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


# --- 조회 ---------------------------------------------------------------------


def get_review(conn: psycopg.Connection, review_id: int) -> dict[str, Any] | None:
    """숨김 여부와 무관하게 원본 1건(소유권 판정·신고 처리에 필요)."""
    return _row(conn.execute("SELECT * FROM reviews WHERE id = %s", (review_id,)).fetchone())


def find_by_device_target(
    conn: psycopg.Connection, *, device_id: str, target_type: str, target_id: str
) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            "SELECT * FROM reviews WHERE device_id = %s AND target_type = %s AND target_id = %s",
            (device_id, target_type, target_id),
        ).fetchone()
    )


def list_reviews(
    conn: psycopg.Connection,
    *,
    target_type: str,
    target_id: str,
    limit: int,
    offset: int,
    viewer_device_id: str | None = None,
) -> list[dict[str, Any]]:
    """최신순. `hidden=1`(신고 누적 자동 숨김)은 **타인에게** 보이지 않는다.

    QA M-3(2026-08-01): 숨김 처리된 글이 작성자 화면에서도 사라지면, 작성자는 자기 글을
    수정·삭제할 수단이 없고 새로 쓰면 유니크 인덱스에 막혀(409) **자력 복구 경로가 0** 이 된다.
    그래서 `viewer_device_id` 가 주어지면 그 기기가 쓴 글은 숨김이어도 포함한다.
    (요약·평균·분포는 여전히 `hidden=0` 만 센다 — `rating_histogram` 은 손대지 않았다.)

    SQL 은 두 갈래로 **분기해서 하드코딩**한다. 하나로 합치면 viewer 가 없을 때
    `device_id = NULL` 같은 미묘한 조건이 남는다 — 노출 판정은 애매함이 곧 사고다.
    """
    if viewer_device_id:
        rows = conn.execute(
            """
            SELECT id, nickname, rating, comment, created_at, updated_at, device_id, hidden
              FROM reviews
             WHERE target_type = %s AND target_id = %s AND (hidden = 0 OR device_id = %s)
             ORDER BY created_at DESC, id DESC
             LIMIT %s OFFSET %s
            """,
            (target_type, target_id, viewer_device_id, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, nickname, rating, comment, created_at, updated_at, device_id, hidden
              FROM reviews
             WHERE target_type = %s AND target_id = %s AND hidden = 0
             ORDER BY created_at DESC, id DESC
             LIMIT %s OFFSET %s
            """,
            (target_type, target_id, limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


def rating_histogram(
    conn: psycopg.Connection, *, target_type: str, target_id: str
) -> dict[int, int]:
    """{별점: 건수}. 평균·총건수는 이 히스토그램에서 파생한다(쿼리 1회로 3개 값을 만든다)."""
    rows = conn.execute(
        """
        SELECT rating, COUNT(*) AS c
          FROM reviews
         WHERE target_type = %s AND target_id = %s AND hidden = 0
         GROUP BY rating
        """,
        (target_type, target_id),
    ).fetchall()
    return {int(r["rating"]): int(r["c"]) for r in rows}


def bulk_rating_histogram(
    conn: psycopg.Connection, *, target_type: str, target_ids: Iterable[str]
) -> dict[str, dict[int, int]]:
    """여러 대상의 히스토그램을 **쿼리 1회**로. 카드 목록 N+1 방지의 핵심.

    IN 절 플레이스홀더는 개수만큼 `%s` 를 이어 붙인다 — 값 자체는 바인딩되므로 인젝션 여지가 없다.
    """
    ids = [t for t in target_ids if t]
    if not ids:
        return {}
    ids = ids[:MAX_SUMMARY_IDS]
    placeholders = ",".join("%s" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT target_id, rating, COUNT(*) AS c
          FROM reviews
         WHERE target_type = %s AND hidden = 0 AND target_id IN ({placeholders})
         GROUP BY target_id, rating
        """,
        (target_type, *ids),
    ).fetchall()
    out: dict[str, dict[int, int]] = {}
    for r in rows:
        out.setdefault(str(r["target_id"]), {})[int(r["rating"])] = int(r["c"])
    return out


# --- 쓰기 ---------------------------------------------------------------------


def insert_review(
    conn: psycopg.Connection,
    *,
    target_type: str,
    target_id: str,
    device_id: str,
    nickname: str,
    rating: int,
    comment: str | None,
    now_iso: str,
) -> int:
    """새 리뷰 id. 같은 기기+대상이 이미 있으면 `psycopg.errors.UniqueViolation`(유니크 인덱스)."""
    cur = conn.execute(
        """
        INSERT INTO reviews
            (target_type, target_id, device_id, nickname, rating, comment, created_at, updated_at, hidden)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)
        RETURNING id
        """,
        (target_type, target_id, device_id, nickname, rating, comment, now_iso, now_iso),
    )
    return int(cur.fetchone()["id"])


def update_review(
    conn: psycopg.Connection,
    *,
    review_id: int,
    nickname: str | None,
    rating: int | None,
    comment: str | None,
    clear_comment: bool,
    now_iso: str,
) -> None:
    """소유권 확인은 **호출부(서비스)가 같은 트랜잭션 안에서** 먼저 한다.

    부분 수정이라 SET 절을 동적으로 만들지만, 컬럼명은 이 함수 안에 하드코딩된 리터럴이고
    값은 전부 바인딩된다(사용자 입력이 SQL 문자열에 들어가지 않는다).
    """
    sets: list[str] = []
    params: list[Any] = []
    if nickname is not None:
        sets.append("nickname = %s")
        params.append(nickname)
    if rating is not None:
        sets.append("rating = %s")
        params.append(rating)
    if clear_comment:
        sets.append("comment = NULL")
    elif comment is not None:
        sets.append("comment = %s")
        params.append(comment)
    if not sets:
        return
    sets.append("updated_at = %s")
    params.append(now_iso)
    params.append(review_id)
    conn.execute(f"UPDATE reviews SET {', '.join(sets)} WHERE id = %s", params)


def delete_review(conn: psycopg.Connection, *, review_id: int) -> None:
    """review_reports 는 FK ON DELETE CASCADE 로 함께 지워진다(Postgres는 FK를 항상 강제)."""
    conn.execute("DELETE FROM reviews WHERE id = %s", (review_id,))


def insert_report_and_count(
    conn: psycopg.Connection,
    *,
    review_id: int,
    device_id: str,
    reason: str,
    now_iso: str,
) -> int:
    """신고 1건 기록 후 그 리뷰의 **고유 신고자 수**를 반환.

    같은 기기의 중복 신고는 `ON CONFLICT ... DO NOTHING` + UNIQUE(review_id, device_id) 로
    무시된다 — 한 사람이 3번 눌러 남의 리뷰를 숨기는 것을 막는 최소 장치다.
    """
    conn.execute(
        """
        INSERT INTO review_reports (review_id, device_id, reason, created_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (review_id, device_id) DO NOTHING
        """,
        (review_id, device_id, reason, now_iso),
    )
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM review_reports WHERE review_id = %s", (review_id,)
    ).fetchone()
    return int(row["c"]) if row else 0


def hide_review(conn: psycopg.Connection, *, review_id: int) -> None:
    conn.execute("UPDATE reviews SET hidden = 1 WHERE id = %s", (review_id,))


__all__ = (
    "MAX_LIMIT",
    "MAX_SUMMARY_IDS",
    "bulk_rating_histogram",
    "delete_review",
    "find_by_device_target",
    "get_review",
    "hide_review",
    "insert_report_and_count",
    "insert_review",
    "list_reviews",
    "rating_histogram",
    "update_review",
)
