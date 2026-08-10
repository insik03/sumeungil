"""관리자(운영) 화면 전용 SQL — 부록 T.

`review_repo` / `shared_course_repo` 와 같은 규칙: 동기 함수 + 첫 인자 `sqlite3.Connection`,
모든 **값**은 파라미터 바인딩(`?`). 호출은 서비스 레이어가 `Database.aread/awrite` 로만 한다.

## 왜 기존 repo 에 얹지 않고 파일을 나눴나
공개 API 의 repo 는 "숨김(`hidden=1`)은 절대 보이지 않는다"가 불변식이다. 관리자 조회는
정확히 그 반대(숨김도 봐야 한다)라, 같은 파일에 섞으면 언젠가 관리자용 쿼리가 공개 경로로
새어 들어간다. 파일 경계가 그 사고를 막는다.

## SQL 문자열 조립 규칙
`WHERE`/`ORDER BY` 는 사용자 입력을 문자열로 붙이지 않는다. **미리 정의된 리터럴 딕셔너리에서
고른 값**만 f-string 에 들어간다(키가 없으면 기본값으로 수렴). 값은 전부 바인딩된다.
"""

from __future__ import annotations

import sqlite3
from typing import Any

MAX_LIMIT = 100
DEFAULT_LIMIT = 30

# 리뷰 목록 필터 — 키는 라우터가 검증한 Literal 과 1:1. 값은 이 파일 안의 상수 리터럴이다.
_REVIEW_WHERE: dict[str, str] = {
    "all": "1 = 1",
    "hidden": "r.hidden = 1",
    # "신고된 것" = 신고가 1건 이상 쌓인 리뷰(숨김 여부 무관 — 임계 미달분이 여기서 보인다).
    "reported": "EXISTS (SELECT 1 FROM review_reports rr WHERE rr.review_id = r.id)",
}
_REVIEW_ORDER: dict[str, str] = {
    "recent": "r.created_at DESC, r.id DESC",
    # 신고 많은 순 — 처리 대기열로 쓰는 정렬.
    "reported": "report_count DESC, r.created_at DESC, r.id DESC",
}

_COURSE_WHERE: dict[str, str] = {
    "all": "1 = 1",
    "hidden": "hidden = 1",
}

# device_id 는 **여기서만** SELECT 한다(서비스가 즉시 actor_hash 로 바꿔 떨어뜨린다).
# 원본은 어떤 응답에도 나가지 않는다 — 부록 R.0 불변식은 관리자에게도 동일하게 적용된다.
_REVIEW_COLUMNS = """
    r.id, r.target_type, r.target_id, r.nickname, r.rating, r.comment,
    r.created_at, r.updated_at, r.hidden, r.device_id,
    (SELECT COUNT(*) FROM review_reports rr WHERE rr.review_id = r.id) AS report_count
"""


# --- 리뷰 ---------------------------------------------------------------------


def list_reviews(
    conn: sqlite3.Connection, *, status: str, sort: str, limit: int, offset: int
) -> list[dict[str, Any]]:
    where = _REVIEW_WHERE.get(status, _REVIEW_WHERE["all"])
    order = _REVIEW_ORDER.get(sort, _REVIEW_ORDER["recent"])
    rows = conn.execute(
        f"""
        SELECT {_REVIEW_COLUMNS}
          FROM reviews r
         WHERE {where}
         ORDER BY {order}
         LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def count_reviews(conn: sqlite3.Connection, *, status: str) -> int:
    where = _REVIEW_WHERE.get(status, _REVIEW_WHERE["all"])
    row = conn.execute(f"SELECT COUNT(*) AS c FROM reviews r WHERE {where}").fetchone()
    return int(row["c"]) if row else 0


def get_review(conn: sqlite3.Connection, *, review_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_REVIEW_COLUMNS} FROM reviews r WHERE r.id = ?", (review_id,)
    ).fetchone()
    return dict(row) if row else None


def set_review_hidden(conn: sqlite3.Connection, *, review_id: int, hidden: bool) -> int:
    """변경된 행 수. 0 이면 그런 리뷰가 없다(라우터가 404 로 만든다)."""
    cur = conn.execute(
        "UPDATE reviews SET hidden = ? WHERE id = ?", (1 if hidden else 0, review_id)
    )
    return int(cur.rowcount)


def delete_review(conn: sqlite3.Connection, *, review_id: int) -> int:
    """신고 기록은 FK ON DELETE CASCADE 로 함께 사라진다(PRAGMA foreign_keys=ON 전제)."""
    cur = conn.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
    return int(cur.rowcount)


# --- 공유 코스 ------------------------------------------------------------------


def list_courses(
    conn: sqlite3.Connection, *, status: str, limit: int, offset: int
) -> list[dict[str, Any]]:
    """payload(최대 32KB/건)는 절대 SELECT 하지 않는다 — 목록 응답 폭발 방지."""
    where = _COURSE_WHERE.get(status, _COURSE_WHERE["all"])
    rows = conn.execute(
        f"""
        SELECT share_code, nickname, title, spot_count, created_at, view_count, hidden, device_id
          FROM shared_courses
         WHERE {where}
         ORDER BY created_at DESC, rowid DESC
         LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def count_courses(conn: sqlite3.Connection, *, status: str) -> int:
    where = _COURSE_WHERE.get(status, _COURSE_WHERE["all"])
    row = conn.execute(f"SELECT COUNT(*) AS c FROM shared_courses WHERE {where}").fetchone()
    return int(row["c"]) if row else 0


def set_course_hidden(conn: sqlite3.Connection, *, share_code: str, hidden: bool) -> int:
    cur = conn.execute(
        "UPDATE shared_courses SET hidden = ? WHERE share_code = ?",
        (1 if hidden else 0, share_code),
    )
    return int(cur.rowcount)


def delete_course(conn: sqlite3.Connection, *, share_code: str) -> int:
    cur = conn.execute("DELETE FROM shared_courses WHERE share_code = ?", (share_code,))
    return int(cur.rowcount)


# --- 통계 ---------------------------------------------------------------------


def stats(conn: sqlite3.Connection, *, today_prefix: str) -> dict[str, int]:
    """가벼운 COUNT 만. 대시보드 첫 화면이 무거워지면 관리자가 쓰지 않게 된다.

    `today_prefix` 는 KST 기준 `YYYY-MM-DD`. created_at 이 ISO8601+09:00 문자열이라
    사전순 비교가 곧 시간순 비교다(`>= '2026-08-01'` 이 그날 0시 이후를 의미한다).
    """

    def one(sql: str, params: tuple[Any, ...] = ()) -> int:
        row = conn.execute(sql, params).fetchone()
        return int(row["c"]) if row else 0

    return {
        "reviews_total": one("SELECT COUNT(*) AS c FROM reviews"),
        "reviews_hidden": one("SELECT COUNT(*) AS c FROM reviews WHERE hidden = 1"),
        "reviews_today": one(
            "SELECT COUNT(*) AS c FROM reviews WHERE created_at >= ?", (today_prefix,)
        ),
        # 처리 대기 = 신고가 쌓였는데 아직 숨겨지지 않은 리뷰 수(관리자가 볼 유일한 대기열).
        "reports_pending": one(
            """
            SELECT COUNT(*) AS c FROM reviews r
             WHERE r.hidden = 0
               AND EXISTS (SELECT 1 FROM review_reports rr WHERE rr.review_id = r.id)
            """
        ),
        "reports_total": one("SELECT COUNT(*) AS c FROM review_reports"),
        "courses_total": one("SELECT COUNT(*) AS c FROM shared_courses"),
        "courses_hidden": one("SELECT COUNT(*) AS c FROM shared_courses WHERE hidden = 1"),
    }


# --- 감사 로그 ------------------------------------------------------------------


def insert_action(
    conn: sqlite3.Connection,
    *,
    action: str,
    target_type: str,
    target_id: str,
    at: str,
    ip_hash: str,
) -> None:
    """**변경 동작과 같은 트랜잭션 안에서** 호출한다 — 기록 없는 변경이 생기지 않게."""
    conn.execute(
        """
        INSERT INTO admin_actions (action, target_type, target_id, at, ip_hash)
        VALUES (?, ?, ?, ?, ?)
        """,
        (action, target_type, target_id, at, ip_hash),
    )


def list_actions(conn: sqlite3.Connection, *, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, action, target_type, target_id, at, ip_hash FROM admin_actions "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


__all__ = (
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "count_courses",
    "count_reviews",
    "delete_course",
    "delete_review",
    "get_review",
    "insert_action",
    "list_actions",
    "list_courses",
    "list_reviews",
    "set_course_hidden",
    "set_review_hidden",
    "stats",
)
