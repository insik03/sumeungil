"""SQLite 저장소 — 표준 라이브러리 `sqlite3` 만 사용(신규 의존성 0).

## 왜 SQLite 인가
부록 R(리뷰·코스 공유)은 **데모 수준**이다. 정식 회원제·다중 인스턴스가 없으므로 단일 파일
DB 로 충분하다. 서버·드라이버·커넥션 풀을 새로 들이면 배포 표면만 커진다(requirements.txt
불변 = ARM 빌드 리스크 0).

## 이벤트 루프를 막지 않는 법
`sqlite3` 는 동기 API 다. 모든 호출은 `asyncio.to_thread` 로 워커 스레드에서 돌린다
(`aread`/`awrite`). 라우터에서 절대 `read`/`write` 를 직접 부르지 말 것 — 그 순간 이벤트
루프가 디스크 I/O 만큼 멈춘다.

## 커넥션 1개 + 락 (의도적 단순화)
스레드마다 커넥션을 만들면 WAL 이라도 write 경합·파일 핸들 관리가 늘어난다. 여기서는
`check_same_thread=False` 커넥션 **1개**를 `threading.RLock` 으로 감싸 직렬화한다.
데모 트래픽(리뷰 몇 건/분)에서 이 직렬화는 체감되지 않고, "동시 쓰기로 인한 이상 상태"라는
디버깅하기 가장 어려운 부류의 버그를 원천 차단한다.
멀티 워커로 갈 일이 생기면 그때는 SQLite 가 아니라 PostgreSQL 로 가야 한다(Dockerfile 주석
참고: 워커는 반드시 1개).

## 트랜잭션
`isolation_level=None`(autocommit) + 쓰기 경로에서만 명시적 `BEGIN IMMEDIATE`.
"신고 INSERT → 누적 3건이면 hidden=1 UPDATE" 처럼 여러 문장이 한 덩어리여야 하는 곳이
있어서, 쓰기는 항상 하나의 트랜잭션 안에서 실행된다(중간 실패 시 전부 롤백).

## 데이터 보존 (배포 시 반드시)
컨테이너 파일시스템은 재빌드하면 사라진다. `deploy/docker-compose.yml` backend 서비스에
named volume(`sumeungil-data:/app/data`)이 **반드시** 있어야 한다. 없으면 사용자가 쓴
리뷰·공유 코스가 배포할 때마다 통째로 증발한다.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

logger = logging.getLogger("sumeungil.db.sqlite")

T = TypeVar("T")

SCHEMA_VERSION = 4

# --- 스키마 (기동 시 CREATE TABLE IF NOT EXISTS 로 멱등 적용) ----------------------
#
# 설계 메모
#  - `device_id` 는 **인증 수단이 아니다**(클라이언트가 만든 임의 UUID). 소유권 대조 용도로만
#    쓰고 어떤 응답에도 내보내지 않는다.
#  - **2026-08-17부터는 위 문장이 절대적이지 않다.** 구글 로그인 도입으로 `users` 테이블에
#    이메일이 처음 들어왔다(schema_version 4 참고) — 이 DB가 처음으로 개인정보를 담게 된
#    지점이다. `reviews`/`shared_courses`의 `device_id` 자체는 여전히 인증 수단이 아니라는
#    원래 원칙 그대로다.
#  - `target_id` 는 TEXT — 스팟 id(정수)와 축제 contentid(문자열)를 한 테이블에 담기 위해서.
#    서비스 레이어에서 `[A-Za-z0-9_-]{1,40}` 로 강제한다.
#  - 시각은 전부 ISO8601 + KST 오프셋 문자열(계약 §0 규약과 동일 — 프론트가 파싱 로직을
#    새로 만들 필요가 없다).
#  - `hidden` 은 신고 누적 자동 숨김용. 삭제가 아니라 플래그다(오탐 시 되돌릴 수 있게).
_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version     INTEGER NOT NULL,
        applied_at  TEXT    NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reviews (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        target_type TEXT    NOT NULL CHECK (target_type IN ('spot', 'festival')),
        target_id   TEXT    NOT NULL,
        device_id   TEXT    NOT NULL,
        nickname    TEXT    NOT NULL,
        rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
        comment     TEXT,
        created_at  TEXT    NOT NULL,
        updated_at  TEXT    NOT NULL,
        hidden      INTEGER NOT NULL DEFAULT 0
    )
    """,
    # 같은 기기 + 같은 대상 = 1건 (409 REVIEW_EXISTS 의 근거를 DB 가 보증한다.
    # 서비스 레이어 사전 조회만으로는 동시 요청에서 두 건이 들어갈 수 있다).
    """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_reviews_device_target
        ON reviews (device_id, target_type, target_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_reviews_target
        ON reviews (target_type, target_id, hidden)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_reviews_created
        ON reviews (created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS shared_courses (
        share_code  TEXT    PRIMARY KEY,
        device_id   TEXT    NOT NULL,
        nickname    TEXT    NOT NULL,
        title       TEXT    NOT NULL,
        payload     TEXT    NOT NULL,
        spot_count  INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT    NOT NULL,
        view_count  INTEGER NOT NULL DEFAULT 0,
        hidden      INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_shared_courses_created
        ON shared_courses (hidden, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS review_reports (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        review_id   INTEGER NOT NULL REFERENCES reviews (id) ON DELETE CASCADE,
        device_id   TEXT    NOT NULL,
        reason      TEXT    NOT NULL,
        created_at  TEXT    NOT NULL,
        UNIQUE (review_id, device_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_review_reports_review
        ON review_reports (review_id)
    """,
    # --- schema_version 2 (부록 T, 2026-08-01): 관리자 감사 로그 -------------------
    #
    # 관리자가 남의 글을 숨기거나 지운 사실을 되짚을 수 있어야 한다(오조작·분쟁 대응).
    # 운영자는 1명이라 "누가" 컬럼은 두지 않는다. 대신 `ip_hash` 만 남긴다 —
    # **원본 IP 를 저장하지 않는다**(키가 붙은 HMAC 앞 16자, security/admin_auth.ip_hash).
    # `target_id` 는 TEXT: 리뷰 id(정수)와 공유 코스 share_code(문자열)를 한 테이블에 담는다.
    """
    CREATE TABLE IF NOT EXISTS admin_actions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        action      TEXT    NOT NULL,
        target_type TEXT    NOT NULL,
        target_id   TEXT    NOT NULL,
        at          TEXT    NOT NULL,
        ip_hash     TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_admin_actions_at
        ON admin_actions (at DESC)
    """,
    # --- schema_version 3 (부록 X, 2026-08-10): 운영 트래픽 집계 -------------------
    #
    # 대표 지시: "관리자 화면에서 트래픽·접속 IP·오늘 방문자를 봐야 한다".
    # 그때까지 앱은 방문을 **전혀 기록하지 않았고**, nginx 로그는 컨테이너를 다시 만들 때마다
    # 통째로 사라졌다(배포할 때마다 리셋). 그래서 앱이 직접 집계를 쌓는다.
    #
    # ## 원본 IP 를 저장하지 않는다 (대표 결정, 2026-08-10)
    # `ip_hash` 는 키가 붙은 HMAC 앞 16자다. 서버 시크릿 없이는 후보 IP 대입으로도 역산할 수
    # 없다. 이렇게 하면 **개인정보 수집이 아니게 되어** 처리방침·보관기간·파기 절차 의무가
    # 생기지 않는다(공모전 '개인정보 미수집' 강점 유지). 대신 "어느 나라인지"는 알 수 없고
    # 특정 IP 차단도 못 한다 — 그 대가는 알고 선택한 것이다.
    # 어뷰징 감지는 그대로 된다: 같은 해시의 hits 가 튀면 한 명이 두드리는 것이다.
    #
    # ## 요청마다 행을 남기지 않는다
    # (날짜, ip_hash) 단위로 **UPSERT 누적**한다. 행 수가 방문자 수에 비례하고 요청 수에는
    # 비례하지 않아, SQLite 한 파일로도 오래 버틴다.
    """
    CREATE TABLE IF NOT EXISTS visit_daily (
        day        TEXT    NOT NULL,          -- KST YYYY-MM-DD
        ip_hash    TEXT    NOT NULL,          -- 원본 IP 아님(HMAC 앞 16자)
        hits       INTEGER NOT NULL DEFAULT 0,
        first_seen TEXT    NOT NULL,
        last_seen  TEXT    NOT NULL,
        PRIMARY KEY (day, ip_hash)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visit_path_daily (
        day   TEXT    NOT NULL,
        path  TEXT    NOT NULL,               -- 동적 구간은 :id 로 접어 저장(경로 폭발 방지)
        hits  INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (day, path)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visit_hour_daily (
        day   TEXT    NOT NULL,
        hour  INTEGER NOT NULL,               -- KST 0~23
        hits  INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (day, hour)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_visit_daily_day ON visit_daily (day)
    """,
    # --- schema_version 4 (2026-08-17): 구글 로그인 계정 --------------------------
    #
    # 대표 지시: "구글로 로그인하고 닉네임 설정할 수 있게" + "로그인 붙였으니 DB도 그에
    # 맞게". 그 전까지 로그인 세션은 DB에 전혀 닿지 않는 자체 서명 쿠키뿐이었다
    # (security/user_auth.py) — 표시 이름을 사용자가 한 번 정해도 다음 로그인(다른
    # 기기·브라우저 초기화)에서 다시 구글 원본 이름으로 되돌아가는 문제가 있었다.
    #
    # `google_sub`(구글 OpenID `sub` 클레임 — 이메일보다 안정적인 식별자, 이메일은
    # 이론상 바뀔 수 있다)을 유니크 키로 쓴다. `display_name`은 **최초 로그인 때만**
    # 구글 이름으로 초기화하고, 이후 로그인마다 덮어쓰지 않는다(사용자가 직접 바꾼 값을
    # 보존 — user_repo.upsert_login 참고). 리뷰 등 게시물의 `nickname`은 여전히 그
    # 게시물 자체에 스냅샷으로 저장된다(계정과 별개, §07-legal-review-google-login.md
    # §1-④ — 리뷰를 지우지 않는 한 표시 이름이 바뀌어도 과거 리뷰의 이름은 그대로 남는
    # 것이 맞는 동작이라는 판단, 실명 변경 이력 추적 방지 목적도 겸함).
    """
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        google_sub    TEXT    NOT NULL UNIQUE,
        email         TEXT    NOT NULL,
        display_name  TEXT    NOT NULL,
        created_at    TEXT    NOT NULL,
        last_login_at TEXT    NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_users_email ON users (email)
    """,
)


class Database:
    """파일 1개짜리 SQLite 핸들. 프로세스당 1 인스턴스(deps.get_database)."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    @property
    def path(self) -> Path:
        return self._path

    # --- 커넥션 / 스키마 ---------------------------------------------------------

    def _ensure_conn(self) -> sqlite3.Connection:
        """락을 잡은 상태에서만 호출된다. 최초 1회 커넥션 생성 + 스키마 적용."""
        if self._conn is not None:
            return self._conn

        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self._path),
            check_same_thread=False,  # 락으로 직렬화하므로 안전(위 모듈 독스트링)
            timeout=5.0,
            isolation_level=None,  # autocommit — 쓰기는 명시적 BEGIN IMMEDIATE 로 감싼다
        )
        conn.row_factory = sqlite3.Row
        # WAL: 읽기와 쓰기가 서로를 막지 않는다. 프로세스가 죽어도 커밋된 데이터가 남는다.
        conn.execute("PRAGMA journal_mode=WAL")
        # FK CASCADE(리뷰 삭제 시 신고 동반 삭제)는 이 PRAGMA 가 켜져 있을 때만 동작한다.
        # sqlite3 는 커넥션마다 기본 OFF 라 매번 켜야 한다 — 빠뜨리면 고아 행이 남는다.
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")

        for stmt in _SCHEMA_STATEMENTS:
            conn.execute(stmt)
        # 이미 존재하는 DB 도 위 CREATE ... IF NOT EXISTS 로 새 테이블을 얻는다. 여기서는
        # "언제 어떤 버전이 적용됐는지"만 기록한다(행을 지우지 않고 append — 이력 보존).
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current = None if row is None or row["v"] is None else int(row["v"])
        if current is None or current < SCHEMA_VERSION:
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
                (SCHEMA_VERSION,),
            )

        self._conn = conn
        logger.info("sqlite 준비 완료 path=%s schema_version=%d", self._path, SCHEMA_VERSION)
        return conn

    def ensure_ready(self) -> bool:
        """기동 시 1회 호출(lifespan). 실패해도 앱은 뜬다 — 기존 조회 기능은 DB 와 무관하다."""
        try:
            with self._lock:
                self._ensure_conn()
            return True
        except Exception:  # noqa: BLE001 — 저장소 장애로 부팅을 막지 않는다
            logger.exception("sqlite 초기화 실패 — 리뷰/공유 기능만 비활성 상태로 동작합니다")
            return False

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # --- 실행 (동기) -------------------------------------------------------------

    @contextmanager
    def _session(self, *, write: bool) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._ensure_conn()
            if not write:
                yield conn
                return
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            else:
                conn.commit()

    def read(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        with self._session(write=False) as conn:
            return fn(conn)

    def write(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        with self._session(write=True) as conn:
            return fn(conn)

    # --- 실행 (async 래퍼) --------------------------------------------------------

    async def aread(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        return await asyncio.to_thread(self.read, fn)

    async def awrite(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        return await asyncio.to_thread(self.write, fn)


def rows_to_dicts(rows: Any) -> list[dict[str, Any]]:
    """sqlite3.Row 를 그대로 상위 레이어에 흘리지 않기 위한 변환(레이어 경계 고정)."""
    return [dict(r) for r in rows]


__all__ = ("Database", "SCHEMA_VERSION", "rows_to_dicts")
