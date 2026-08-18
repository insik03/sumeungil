"""shared_courses 테이블 SQL — 부록 R(코스 공유).

review_repo 와 같은 규칙: 동기 함수 + 첫 인자 `psycopg.Connection`, 모든 값은 바인딩.
payload(JSON 문자열)는 서버가 **해석하지 않고 그대로 보관**한다 — 코스 응답 구조가 바뀌어도
저장소는 영향을 받지 않는다(스키마 마이그레이션 없이 프론트가 진화할 수 있게).

2026-08-17: PostgreSQL 전환(db/postgres.py)으로 `?` → `%s`, SQLite 암시적 `rowid` 정렬
타이브레이커 → `seq`(신설 컬럼) 정렬로 바뀌었다(로직은 무변경).
"""

from __future__ import annotations

from typing import Any

import psycopg

MAX_LIMIT = 50

# 목록 조회에서 payload 를 절대 SELECT 하지 않는다(항목당 최대 32KB × 50 = 1.6MB).
_LIST_COLUMNS = "share_code, nickname, title, spot_count, created_at, view_count"


def insert_share(
    conn: psycopg.Connection,
    *,
    share_code: str,
    device_id: str,
    nickname: str,
    title: str,
    payload_json: str,
    spot_count: int,
    now_iso: str,
) -> None:
    """share_code 가 이미 있으면 `psycopg.errors.UniqueViolation`(PK) → 서비스가 재시도한다."""
    conn.execute(
        """
        INSERT INTO shared_courses
            (share_code, device_id, nickname, title, payload, spot_count, created_at, view_count, hidden)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0)
        """,
        (share_code, device_id, nickname, title, payload_json, spot_count, now_iso),
    )


def get_share(conn: psycopg.Connection, *, share_code: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM shared_courses WHERE share_code = %s", (share_code,)
    ).fetchone()
    return dict(row) if row else None


def bump_view_count(conn: psycopg.Connection, *, share_code: str) -> None:
    """UPDATE ... +1 은 한 트랜잭션 안에서 원자적이다(읽고-더하고-쓰기를 앱에서 하지 않는다)."""
    conn.execute(
        "UPDATE shared_courses SET view_count = view_count + 1 WHERE share_code = %s",
        (share_code,),
    )


def list_shares(conn: psycopg.Connection, *, limit: int, offset: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        SELECT {_LIST_COLUMNS}
          FROM shared_courses
         WHERE hidden = 0
         ORDER BY created_at DESC, seq DESC
         LIMIT %s OFFSET %s
        """,
        (limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def count_shares(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM shared_courses WHERE hidden = 0").fetchone()
    return int(row["c"]) if row else 0


def delete_share(conn: psycopg.Connection, *, share_code: str) -> None:
    conn.execute("DELETE FROM shared_courses WHERE share_code = %s", (share_code,))


# --- 보존정책 (QA M-2) ---------------------------------------------------------
#
# created_at 은 항상 `to_iso_kst()` 가 만든 `YYYY-MM-DDTHH:MM:SS+09:00` 형식이다.
# 오프셋이 고정이므로 **문자열 비교 = 시간 비교**가 성립한다(같은 자릿수·같은 오프셋).
# 다른 오프셋 문자열을 이 테이블에 넣기 시작하면 이 전제가 깨진다 — 넣지 말 것.
#
# 삭제는 전부 `DELETE ... WHERE share_code IN (SELECT ... LIMIT %s)` 형태다. LIMIT 없이
# 조건만으로 지우면 한 트랜잭션이 수천 행을 잡아 쓰기 락이 길어진다(그동안 모든 쓰기 대기).

# "최근에 만들어졌고 실제로 조회된" 행은 용량·보존 정리에서 제외한다.
_GRACE = "NOT (view_count > 0 AND created_at >= %s)"


def count_all_shares(conn: psycopg.Connection) -> int:
    """hidden 포함 **전체** 행 수 — 디스크를 차지하는 것은 숨김 여부와 무관하다.

    (`count_shares` 는 피드에 보이는 수 = hidden 제외. 용도가 다르므로 함수를 나눴다.)
    """
    row = conn.execute("SELECT COUNT(*) AS c FROM shared_courses").fetchone()
    return int(row["c"]) if row else 0


def count_shares_by_device(conn: psycopg.Connection, *, device_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM shared_courses WHERE device_id = %s", (device_id,)
    ).fetchone()
    return int(row["c"]) if row else 0


def delete_oldest_by_device(
    conn: psycopg.Connection, *, device_id: str, keep: int, batch: int
) -> int:
    """이 기기의 공유를 최신 `keep` 건만 남기고 오래된 것부터 지운다. 반환: 삭제 행 수.

    본인이 만든 자기 데이터라 유예(조회수) 규칙을 적용하지 않는다 — 규칙이 늘어날수록
    "왜 안 지워졌는지"를 설명하기 어려워지고, 사용자는 자기 링크를 직접 관리할 수 있다.
    """
    keep = max(0, keep)
    # 남길 건수를 뺀 나머지가 삭제 대상. take가 0 이하면 LIMIT 0(삭제 없음)으로 막는다
    # (Postgres는 SQLite와 달리 음수 LIMIT을 "제한 없음"으로 허용하지 않는다).
    excess = count_shares_by_device(conn, device_id=device_id) - keep
    take = max(0, min(batch, excess))
    if take <= 0:
        return 0
    cur = conn.execute(
        """
        DELETE FROM shared_courses
         WHERE share_code IN (
               SELECT share_code
                 FROM shared_courses
                WHERE device_id = %s
                ORDER BY created_at ASC, seq ASC
                LIMIT %s
         )
        """,
        (device_id, take),
    )
    return int(cur.rowcount or 0)


def delete_overflow(
    conn: psycopg.Connection,
    *,
    max_total: int,
    batch: int,
    grace_since_iso: str,
    reserve: int = 0,
) -> int:
    """전체 행이 `max_total` 을 넘으면 **조회수 0 → 오래된 순**으로 batch 만큼 지운다.

    정렬 키 `view_count = 0 DESC`: 불리언 표현식이 true(조회수 0인 행)를 먼저 오게 만든다.
    아무도 보지 않은 것부터 버리는 것이 사용자 체감 손실이 가장 작다.

    `reserve` 는 "곧 들어올 행 수"다. 생성 트랜잭션에서 1 을 주지 않으면 INSERT 직후마다
    상한+1 이 되어 실제 상한이 1건씩 초과된 상태로 유지된다(정리는 항상 한 박자 늦는다).
    """
    total = count_all_shares(conn)
    excess = total - max(1, max_total - max(0, reserve))
    if excess <= 0:
        return 0
    cur = conn.execute(
        f"""
        DELETE FROM shared_courses
         WHERE share_code IN (
               SELECT share_code
                 FROM shared_courses
                WHERE {_GRACE}
                ORDER BY (view_count = 0) DESC, created_at ASC, seq ASC
                LIMIT %s
         )
        """,
        (grace_since_iso, min(batch, excess)),
    )
    return int(cur.rowcount or 0)


def delete_expired(
    conn: psycopg.Connection, *, cutoff_iso: str, batch: int, grace_since_iso: str
) -> int:
    """`cutoff_iso`(= now - 보존기간) 이전에 만들어진 공유를 batch 만큼 지운다."""
    cur = conn.execute(
        f"""
        DELETE FROM shared_courses
         WHERE share_code IN (
               SELECT share_code
                 FROM shared_courses
                WHERE created_at < %s AND {_GRACE}
                ORDER BY created_at ASC, seq ASC
                LIMIT %s
         )
        """,
        (cutoff_iso, grace_since_iso, max(0, batch)),
    )
    return int(cur.rowcount or 0)


__all__ = (
    "MAX_LIMIT",
    "bump_view_count",
    "count_all_shares",
    "count_shares",
    "count_shares_by_device",
    "delete_expired",
    "delete_oldest_by_device",
    "delete_overflow",
    "delete_share",
    "get_share",
    "insert_share",
    "list_shares",
)
