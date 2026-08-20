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
# 2026-08-20(부록 R.14): like_count 는 비정규화 컬럼이라 조인 없이 그대로 읽는다.
_LIST_COLUMNS = "share_code, nickname, title, spot_count, created_at, view_count, like_count"

# 정렬 화이트리스트 — `sort` 값은 **이 dict 조회로만** SQL 에 들어간다(문자열 보간 금지 =
# SQL 인젝션 표면 0). 키에 없는 값은 라우터 단계에서 이미 422 로 걸러진다.
# "latest" 는 종전 SQL 문자열과 **완전히 동일**해야 한다(무회귀 계약, 부록 R.14.4).
_ORDER = {
    "latest": "ORDER BY created_at DESC, seq DESC",
    "popular": "ORDER BY like_count DESC, created_at DESC, seq DESC",
}
# 로그인 목록은 JOIN 이 붙어 컬럼을 한정해야 한다. 문자열 치환으로 만들지 않고 **따로 적어**
# 두 경로의 정렬 키가 눈으로 대조되게 한다(치환은 컬럼명이 늘면 조용히 어긋난다).
_ORDER_JOINED = {
    "latest": "ORDER BY s.created_at DESC, s.seq DESC",
    "popular": "ORDER BY s.like_count DESC, s.created_at DESC, s.seq DESC",
}
SORT_VALUES = tuple(_ORDER)


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


def list_shares(
    conn: psycopg.Connection,
    *,
    limit: int,
    offset: int,
    sort: str = "latest",
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """피드 목록. `sort`·`user_id` 는 **기본값이 있는 additive 인자**다.

    비로그인(=user_id None) 경로는 종전 쿼리를 그대로 쓰고 `liked_by_me` 를 상수 False 로
    채운다 — 이렇게 나눠야 "파라미터 없는 기존 호출은 SQL 까지 동일"이 성립한다(무회귀).
    로그인 시에만 LEFT JOIN 을 태워 목록 한 번에 계산한다(카드마다 별도 호출 = N+1 금지).
    """
    if user_id is None:
        rows = conn.execute(
            f"""
            SELECT {_LIST_COLUMNS}
              FROM shared_courses
             WHERE hidden = 0
             {_ORDER.get(sort) or _ORDER["latest"]}
             LIMIT %s OFFSET %s
            """,
            (limit, offset),
        ).fetchall()
        return [dict(r) | {"liked_by_me": False} for r in rows]

    prefixed = ", ".join(f"s.{c}" for c in _LIST_COLUMNS.split(", "))
    rows = conn.execute(
        f"""
        SELECT {prefixed}, (l.user_id IS NOT NULL) AS liked_by_me
          FROM shared_courses s
          LEFT JOIN course_likes l
                 ON l.share_code = s.share_code AND l.user_id = %s
         WHERE s.hidden = 0
         {_ORDER_JOINED.get(sort) or _ORDER_JOINED["latest"]}
         LIMIT %s OFFSET %s
        """,
        (user_id, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def count_shares(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM shared_courses WHERE hidden = 0").fetchone()
    return int(row["c"]) if row else 0


def delete_share(conn: psycopg.Connection, *, share_code: str) -> None:
    conn.execute("DELETE FROM shared_courses WHERE share_code = %s", (share_code,))


# --- 좋아요 (부록 R.14) --------------------------------------------------------
#
# 두 함수 모두 `db.awrite` 한 트랜잭션 안에서 실행된다(bump_view_count 와 같은 관례).
# 중간에 실패하면 둘 다 롤백되어 course_likes 행 수와 like_count 가 갈리지 않는다.
# 락 순서는 등록·취소 모두 course_likes -> shared_courses 로 **고정**한다(교차 데드락 방지).


def get_share_visibility(conn: psycopg.Connection, *, share_code: str) -> bool | None:
    """존재 + 노출 여부만 본다. 없으면 None, hidden=1 이면 False, 정상이면 True.

    좋아요 경로가 `get_share`(=`SELECT *`)를 쓰면 하트를 누를 때마다 최대 32KB 의 payload 를
    읽는다 — 목록에서 연달아 눌리는 동작이라 그 비용이 그대로 쌓인다. 필요한 것은 두 비트뿐이다.
    """
    row = conn.execute(
        "SELECT hidden FROM shared_courses WHERE share_code = %s", (share_code,)
    ).fetchone()
    return None if row is None else int(row["hidden"]) == 0


def _current_like_count(conn: psycopg.Connection, share_code: str) -> int:
    row = conn.execute(
        "SELECT like_count FROM shared_courses WHERE share_code = %s", (share_code,)
    ).fetchone()
    return int(row["like_count"]) if row else 0


def toggle_like(
    conn: psycopg.Connection, *, share_code: str, user_id: int, now_iso: str
) -> tuple[bool, int]:
    """좋아요 등록. 반환 (liked, like_count). **멱등** — 이미 눌렀어도 (True, 현재값).

    삽입 성공 여부가 곧 "처음 눌렀는가"다 — SELECT 후 INSERT 하는 경쟁 구간이 없다.
    대상이 이미 사라졌으면 INSERT 가 `psycopg.errors.ForeignKeyViolation` 을 던진다
    (서비스가 404 로 변환한다 — 좋아요 도중 보존정책이 지운 경우라 500 이 아니다).
    """
    cur = conn.execute(
        """
        INSERT INTO course_likes (share_code, user_id, created_at)
        VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
        """,
        (share_code, user_id, now_iso),
    )
    if int(cur.rowcount or 0) != 1:
        return True, _current_like_count(conn, share_code)
    row = conn.execute(
        """
        UPDATE shared_courses SET like_count = like_count + 1
         WHERE share_code = %s RETURNING like_count
        """,
        (share_code,),
    ).fetchone()
    return True, int(row["like_count"]) if row else 0


def untoggle_like(conn: psycopg.Connection, *, share_code: str, user_id: int) -> tuple[bool, int]:
    """좋아요 취소. 반환 (False, like_count). **멱등** — 누른 적 없어도 (False, 현재값)."""
    cur = conn.execute(
        "DELETE FROM course_likes WHERE share_code = %s AND user_id = %s",
        (share_code, user_id),
    )
    if int(cur.rowcount or 0) != 1:
        return False, _current_like_count(conn, share_code)
    row = conn.execute(
        """
        UPDATE shared_courses SET like_count = GREATEST(like_count - 1, 0)
         WHERE share_code = %s RETURNING like_count
        """,
        (share_code,),
    ).fetchone()
    # GREATEST(...,0) 는 방어선이다. 정상 경로에서는 음수가 될 수 없지만, 과거 데이터가
    # 손상돼 있어도 피드에 -1 이 표시되지 않게 한다.
    return False, int(row["like_count"]) if row else 0


def get_like_state(
    conn: psycopg.Connection, *, share_code: str, user_id: int | None
) -> tuple[bool, int]:
    """상세 조회용 (liked_by_me, like_count). user_id=None 이면 (False, like_count)."""
    count = _current_like_count(conn, share_code)
    if user_id is None:
        return False, count
    row = conn.execute(
        "SELECT 1 AS hit FROM course_likes WHERE share_code = %s AND user_id = %s",
        (share_code, user_id),
    ).fetchone()
    return row is not None, count


# --- 보존정책 (QA M-2) ---------------------------------------------------------
#
# created_at 은 항상 `to_iso_kst()` 가 만든 `YYYY-MM-DDTHH:MM:SS+09:00` 형식이다.
# 오프셋이 고정이므로 **문자열 비교 = 시간 비교**가 성립한다(같은 자릿수·같은 오프셋).
# 다른 오프셋 문자열을 이 테이블에 넣기 시작하면 이 전제가 깨진다 — 넣지 말 것.
#
# 삭제는 전부 `DELETE ... WHERE share_code IN (SELECT ... LIMIT %s)` 형태다. LIMIT 없이
# 조건만으로 지우면 한 트랜잭션이 수천 행을 잡아 쓰기 락이 길어진다(그동안 모든 쓰기 대기).

# "최근에 만들어졌고 실제로 반응이 있었던" 행은 용량·보존 정리에서 제외한다.
# 2026-08-20(부록 R.14.5): 하트는 **피드 카드(목록)** 에서 눌리고 view_count 는 상세에서만
# 오른다 → `like_count>0 AND view_count=0` 이 정상 동작으로 만들어진다. 유예를 좋아요까지
# 넓히지 않으면 "반응이 가장 좋은 코스가 가장 먼저 삭제"된다.
# delete_expired 에는 영향이 0 이다: _GRACE 는 created_at >= now-30일을 요구하고 기간 정리는
# created_at < now-180일만 대상으로 해 두 조건이 동시에 참일 수 없다(기본값 기준).
# **SHARE_RETENTION_DAYS <= SHARE_RECENT_VIEW_GRACE_DAYS 로 뒤집으면 이 성질이 깨진다** —
# 그런 조합을 쓰지 말 것(운영 메모).
_GRACE = "NOT ((view_count > 0 OR like_count > 0) AND created_at >= %s)"


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
    """전체 행이 `max_total` 을 넘으면 **반응 없음 → 오래된 순**으로 batch 만큼 지운다.

    정렬 키 `(like_count = 0) DESC, (view_count = 0) DESC`: 불리언 표현식이 true(반응이 0인
    행)를 먼저 오게 만든다. 아무도 반응하지 않은 것부터 버리는 것이 사용자 체감 손실이 가장 작다.
    2026-08-20(부록 R.14.5): 좋아요를 like_count 로 **먼저** 본다 — 하트는 목록에서 눌리고
    조회수는 상세에서만 오르므로, view_count 만 보면 반응이 좋은 코스가 먼저 지워진다.

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
                ORDER BY (like_count = 0) DESC, (view_count = 0) DESC, created_at ASC, seq ASC
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
    "SORT_VALUES",
    "bump_view_count",
    "count_all_shares",
    "count_shares",
    "count_shares_by_device",
    "delete_expired",
    "delete_oldest_by_device",
    "delete_overflow",
    "delete_share",
    "get_like_state",
    "get_share",
    "get_share_visibility",
    "insert_share",
    "list_shares",
    "toggle_like",
    "untoggle_like",
)
