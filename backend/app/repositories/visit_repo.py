"""운영 트래픽 집계 저장·조회 (부록 X, 2026-08-10).

## 왜 만들었나
대표 지시로 관리자 화면에 트래픽·오늘 방문자·인기 경로를 보여주게 됐다. 그전까지 앱은
방문을 **전혀 기록하지 않았고**, nginx 로그는 컨테이너를 재생성할 때마다 통째로 사라져
배포할 때마다 리셋됐다. 그래서 앱이 직접 집계를 쌓는다.

## 원본 IP 를 저장하지 않는다
`ip_hash`(키 붙은 HMAC 앞 16자)만 남긴다 — 대표 결정(2026-08-10). 개인정보 수집이
아니게 되어 처리방침·보관기간·파기 의무가 생기지 않는다. 대신 국가 판별과 IP 차단은
불가능하다. 어뷰징 감지는 그대로 된다(같은 해시의 hits 가 튀는 것으로 보인다).

## 요청마다 행을 남기지 않는다
(날짜, ip_hash) 단위 UPSERT 누적이라 행 수가 **방문자 수**에 비례하고 요청 수와는 무관하다.
"""

from __future__ import annotations

import sqlite3

# 보관 기간. 넘은 날짜는 기동 시 지운다 — 무기한 보관은 그 자체가 리스크다.
RETENTION_DAYS = 90


def record(
    conn: sqlite3.Connection,
    *,
    day: str,
    hour: int,
    ip_hash: str,
    path: str,
    now_iso: str,
) -> None:
    """요청 1건을 세 집계에 반영한다. 실패해도 요청 처리를 막지 않는 것은 호출부 책임."""
    conn.execute(
        """
        INSERT INTO visit_daily (day, ip_hash, hits, first_seen, last_seen)
        VALUES (?, ?, 1, ?, ?)
        ON CONFLICT (day, ip_hash) DO UPDATE SET
            hits = hits + 1,
            last_seen = excluded.last_seen
        """,
        (day, ip_hash, now_iso, now_iso),
    )
    conn.execute(
        """
        INSERT INTO visit_path_daily (day, path, hits) VALUES (?, ?, 1)
        ON CONFLICT (day, path) DO UPDATE SET hits = hits + 1
        """,
        (day, path),
    )
    conn.execute(
        """
        INSERT INTO visit_hour_daily (day, hour, hits) VALUES (?, ?, 1)
        ON CONFLICT (day, hour) DO UPDATE SET hits = hits + 1
        """,
        (day, hour),
    )


def prune(conn: sqlite3.Connection, *, before_day: str) -> int:
    """보관 기간이 지난 집계를 지운다. 지운 행 수를 돌려준다."""
    total = 0
    for table in ("visit_daily", "visit_path_daily", "visit_hour_daily"):
        cur = conn.execute(f"DELETE FROM {table} WHERE day < ?", (before_day,))
        total += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    return total


def summary(conn: sqlite3.Connection, *, today: str, days: int) -> dict:
    """관리자 화면용 집계.

    `visitors` 는 **고유 ip_hash 수**다. 같은 사람이 여러 번 와도 1로 센다.
    다만 이동통신 IP 는 바뀌고 사무실은 공유되므로 **정확한 사람 수가 아니라 추정치**다 —
    화면에서도 그렇게 표기해야 한다.
    """
    row = conn.execute(
        """
        SELECT COUNT(*) AS visitors, COALESCE(SUM(hits), 0) AS hits,
               COALESCE(MAX(hits), 0) AS top_hits
        FROM visit_daily WHERE day = ?
        """,
        (today,),
    ).fetchone()
    today_visitors = int(row["visitors"] or 0)
    today_hits = int(row["hits"] or 0)
    today_top_hits = int(row["top_hits"] or 0)

    daily = [
        {"day": r["day"], "visitors": int(r["visitors"]), "hits": int(r["hits"])}
        for r in conn.execute(
            """
            SELECT day, COUNT(*) AS visitors, SUM(hits) AS hits
            FROM visit_daily
            GROUP BY day ORDER BY day DESC LIMIT ?
            """,
            (days,),
        ).fetchall()
    ]

    top_paths = [
        {"path": r["path"], "hits": int(r["hits"])}
        for r in conn.execute(
            "SELECT path, hits FROM visit_path_daily WHERE day = ? ORDER BY hits DESC LIMIT 10",
            (today,),
        ).fetchall()
    ]

    hours = {int(r["hour"]): int(r["hits"]) for r in conn.execute(
        "SELECT hour, hits FROM visit_hour_daily WHERE day = ?", (today,)
    ).fetchall()}

    # 어뷰징 감지용 — 오늘 가장 많이 두드린 상위 5개 해시. 신원은 알 수 없고,
    # "한 명이 몇 번 두드렸나"만 보인다. 그것이 이 목록의 유일한 목적이다.
    heavy = [
        {"ip_hash": r["ip_hash"], "hits": int(r["hits"]),
         "first_seen": r["first_seen"], "last_seen": r["last_seen"]}
        for r in conn.execute(
            """
            SELECT ip_hash, hits, first_seen, last_seen FROM visit_daily
            WHERE day = ? ORDER BY hits DESC LIMIT 5
            """,
            (today,),
        ).fetchall()
    ]

    return {
        "today_visitors": today_visitors,
        "today_hits": today_hits,
        "today_top_hits": today_top_hits,
        "daily": daily,
        "top_paths": top_paths,
        "hourly": [{"hour": h, "hits": hours.get(h, 0)} for h in range(24)],
        "heavy_clients": heavy,
        "retention_days": RETENTION_DAYS,
    }


__all__ = ("RETENTION_DAYS", "prune", "record", "summary")
