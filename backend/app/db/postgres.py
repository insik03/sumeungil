"""PostgreSQL 저장소 — SQLite(`db/sqlite.py`)를 대체한다 (2026-08-17, 대표 지시).

## 왜 지금 옮기는가
`db/sqlite.py` 모듈 독스트링은 원래 "멀티 워커로 갈 일이 생기면 그때 PostgreSQL로"를
기준으로 삼았었다(현재도 워커 1개, 데이터량도 SQLite로 충분한 수준). 그 기준상으로는 아직
이르지만, 대표가 로그인 기반 개인화 기능(온보딩 취향 프로필·AI 코스 저장)을 계정에 영구
저장하기로 결정하면서 "지금 전환"을 명시적으로 선택했다 — 그 결정을 따른다.

## 인터페이스는 그대로 둔다
`deps.py:get_database()` 한 곳만 바꾸면 라우터·서비스는 무변경이라는 게 `sqlite.py`의
원래 설계 의도였다(`01-interface-contract.md` §R.9). 이 클래스도 `read`/`write`/`aread`/
`awrite`/`ensure_ready`/`close` 시그니처를 그대로 유지한다 — 리포지토리 함수들의
`db.awrite(lambda conn: repo_fn(conn, ...))` 호출부는 한 줄도 안 바뀐다. 리포지토리 함수
내부의 SQL만 방언이 다르다(`?` → `%s`, `AUTOINCREMENT` → `GENERATED ALWAYS AS IDENTITY`).

## SQLite와 달라지는 점
- **단일 커넥션 + RLock 직렬화가 사라진다.** SQLite는 파일 락 경합을 피하려고 일부러
  커넥션 1개로 모든 요청을 순서대로 처리했다(sqlite.py 참고). Postgres는 여러 커넥션의
  동시 트랜잭션을 정상 지원하므로, 여기서는 `psycopg_pool.ConnectionPool`로 대체한다 —
  이게 이번 전환의 실질적 이득이다(진짜 동시 쓰기).
- **트랜잭션 경계**: `BEGIN IMMEDIATE`를 명시하지 않는다. psycopg3 커넥션은 기본
  `autocommit=False`라 첫 쿼리에서 트랜잭션이 자동 시작되고, `pool.connection()` 컨텍스트가
  블록을 예외 없이 빠져나가면 자동 `commit()`, 예외면 자동 `rollback()`한다(SQLite의
  `_session`이 하던 일을 pool이 대신한다).
- **PRAGMA 없음**: `foreign_keys=ON`은 Postgres에서 기본 강제(끌 수 없음), `journal_mode`/
  `synchronous`는 Postgres 자체 WAL·durability로 대체된다. 전부 삭제.
- **행 변환**: `sqlite3.Row` 대신 `psycopg.rows.dict_row`를 커넥션 기본 row factory로
  써서 `dict(row)` 없이 이미 dict가 나온다(리포지토리의 `_row()` 헬퍼는 `None` 방어만 하면
  되도록 단순해진다).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from typing import Any, Callable, Iterator, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

logger = logging.getLogger("sumeungil.db.postgres")

T = TypeVar("T")

SCHEMA_VERSION = 10

# --- 스키마 (기동 시 CREATE TABLE IF NOT EXISTS 로 멱등 적용) ----------------------
#
# sqlite.py의 schema_version 1~4를 그대로 옮긴 것 — 테이블·컬럼·제약 전부 동일 의미다.
# 방언 차이만 고쳤다(AUTOINCREMENT -> GENERATED ALWAYS AS IDENTITY, PRAGMA 제거).
# schema_version 5(신규, Phase C)는 onboarding_profiles/ai_courses — 각 리포지토리
# 신설 시점에 이 튜플에 추가한다(현재는 아직 미포함, 태스크 순서상 다음 커밋에서 추가).
_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version     INTEGER NOT NULL,
        applied_at  TEXT    NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reviews (
        id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
        -- seq: SQLite의 암시적 rowid를 대체하는 정렬 타이브레이커(Postgres는 rowid가 없다).
        -- share_code가 PK라 정수 자동증가 컬럼이 따로 없었는데, shared_course_repo.py의
        -- "ORDER BY created_at ..., rowid ..." 정렬이 여기에 의존했다 — 값 자체는 어디에도
        -- 노출되지 않는다(정렬 전용).
        seq         BIGINT  GENERATED ALWAYS AS IDENTITY,
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
        id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    """
    CREATE TABLE IF NOT EXISTS admin_actions (
        id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    """
    CREATE TABLE IF NOT EXISTS visit_daily (
        day        TEXT    NOT NULL,
        ip_hash    TEXT    NOT NULL,
        hits       INTEGER NOT NULL DEFAULT 0,
        first_seen TEXT    NOT NULL,
        last_seen  TEXT    NOT NULL,
        PRIMARY KEY (day, ip_hash)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visit_path_daily (
        day   TEXT    NOT NULL,
        path  TEXT    NOT NULL,
        hits  INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (day, path)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visit_hour_daily (
        day   TEXT    NOT NULL,
        hour  INTEGER NOT NULL,
        hits  INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (day, hour)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_visit_daily_day ON visit_daily (day)
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    # --- schema_version 6 (2026-08-17): 카카오 로그인 추가(대표 지시) ------------------
    #
    # 구글 전용이던 users를 구글·카카오 공용으로 넓힌다. 두 provider 다 필수였던
    # google_sub/email을 nullable로 완화(카카오 전용 계정은 google_sub가 없고, 카카오는
    # 이메일 동의 자체가 선택이라 email도 없을 수 있다) + kakao_sub 컬럼 신설.
    #
    # 아래 3줄은 멱등이다: ALTER ... DROP NOT NULL은 이미 nullable이어도 에러 없이
    # 통과하고(Postgres 표준 동작), ADD COLUMN IF NOT EXISTS도 이미 있으면 스킵된다.
    # kakao_sub는 UNIQUE지만 Postgres는 UNIQUE 컬럼에 NULL을 여러 개 허용하므로(NULL은
    # 서로 같다고 보지 않음) 구글 전용 계정이 여러 개 있어도 충돌하지 않는다.
    """
    ALTER TABLE users ALTER COLUMN google_sub DROP NOT NULL
    """,
    """
    ALTER TABLE users ALTER COLUMN email DROP NOT NULL
    """,
    """
    ALTER TABLE users ADD COLUMN IF NOT EXISTS kakao_sub TEXT UNIQUE
    """,
    # --- 2026-09-14: 로그아웃 즉시 무효화 + 약관 동의 기록 ------------------------------
    #   session_epoch: 세션 토큰에 박히는 정수. 로그아웃하면 +1 → 그 전에 발급된 토큰은 전부 무효
    #   (무상태 서명 토큰의 "서버가 끊을 수단 없음" 한계 해소, 보안검토 M-2/M-5 후속).
    #   terms_agreed_at/terms_version: 첫 로그인(표시 이름 단계) 또는 동의 모달에서 기록.
    """
    ALTER TABLE users ADD COLUMN IF NOT EXISTS session_epoch INTEGER NOT NULL DEFAULT 0
    """,
    """
    ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_agreed_at TEXT
    """,
    """
    ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_version TEXT
    """,
    # --- 2026-08-17 신설: 로그인 기반 개인화(대표 지시 — 온보딩·AI문답·AI코스짜기 로그인 필수화) ---
    #
    # onboarding_profiles: 계정당 최신 취향 프로필 1건만 보관(upsert) — history가 아니다.
    # "재로그인해도 취향이 남아있어야 한다"는 요구를 충족하는 목적뿐이라 과거 이력은 안 쌓는다.
    # tags/tag_vector/scoring_weights는 app.ai.schemas.OnboardingResult와 동일한 JSON을
    # TEXT로 저장한다(shared_courses.payload와 같은 관례 — 서버가 내용을 해석하지 않는다).
    """
    CREATE TABLE IF NOT EXISTS onboarding_profiles (
        user_id               INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
        tags                  TEXT    NOT NULL,
        tag_vector            TEXT    NOT NULL,
        vector_version        INTEGER NOT NULL,
        scoring_weights       TEXT    NOT NULL,
        extraction_confidence REAL    NOT NULL,
        extracted_by          TEXT    NOT NULL,
        fallback_used         INTEGER NOT NULL DEFAULT 0,
        updated_at            TEXT    NOT NULL
    )
    """,
    # ai_courses: AI 코스짜기(추천·직접만들기) 결과를 사용자가 명시적으로 "저장하기" 눌렀을 때만
    # 남긴다(생성될 때마다 자동 저장 아님 — 실험적으로 여러 번 눌러도 테이블이 안 불어난다).
    # payload는 CourseResponse를 그대로 JSON 직렬화(shared_courses.payload와 동일 관례).
    """
    CREATE TABLE IF NOT EXISTS ai_courses (
        id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        region_code TEXT    NOT NULL,
        mode        TEXT    NOT NULL CHECK (mode IN ('ai', 'custom')),
        payload     TEXT    NOT NULL,
        created_at  TEXT    NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_ai_courses_user ON ai_courses (user_id, created_at DESC)
    """,
    # --- 2026-08-18 신설: 고객문의(대표 지시 — "고객문의창도 있어야 할 거 같은데?") ---
    # 접수 시스템이 전무했던 상태(발송 이메일/티켓 시스템 없음)라 "간단한 문의 폼 + DB 저장"
    # 범위로 합의(대표 확인) — admin 콘솔 조회 화면은 별도 후속 작업, 이번엔 저장까지만.
    # 마이페이지에서만 접근 가능해 로그인 필수 → user_id NOT NULL(ai_courses와 동일 관례).
    # contact_email은 선택 — 카카오 로그인처럼 계정에 이메일이 아예 없는 경우, 답장받을
    # 연락처를 문의 시점에 직접 받기 위한 용도(계정 이메일과 다를 수 있음을 감안).
    """
    CREATE TABLE IF NOT EXISTS inquiries (
        id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id       INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        contact_email TEXT,
        message       TEXT    NOT NULL,
        status        TEXT    NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'resolved')),
        created_at    TEXT    NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_inquiries_user ON inquiries (user_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_inquiries_created ON inquiries (created_at DESC)
    """,
    # --- schema_version 8 (2026-08-18): 보안검토 K-M2 대응 — users.email UNIQUE 강제 ---
    # K-C1(계정 탈취) 수정으로 애플리케이션 로직은 검증된 이메일만 저장하게 됐지만, DB
    # 자체에는 email 중복을 막는 제약이 없었다(기존 ix_users_email은 조회용 일반 인덱스일
    # 뿐 UNIQUE가 아니었다) — 코드에 버그가 재발해도 같은 이메일로 행이 두 개 생기는
    # 사태를 DB 레벨에서 한 번 더 막는다(defense in depth). Postgres UNIQUE는 NULL을
    # 여러 개 허용하므로(NULL은 서로 다르다고 봄) 이메일 없는 카카오 전용 계정이 여러
    # 개 있어도 충돌하지 않는다 — kakao_sub UNIQUE와 동일한 성질.
    """
    DROP INDEX IF EXISTS ix_users_email
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email ON users (email)
    """,
    # --- schema_version 9 (2026-08-18): 관리자 콘솔 문의 답변 기능(대표 지시 —
    # "고객문의 들어온거에 답변도 작성하는 칸이 있었으면 좋겠어") ---
    # 답변은 문의 1건당 1개만 보관한다(스레드형 대화 아님 — 티켓 시스템이 아니라 "문의 폼 +
    # 답변 한 번"이 지금 범위). replied_by는 admin_actions처럼 감사용 표시 이름이지,
    # admin_repo.py 주석의 "관리자 표시 이름은 신원 인증이 아니다" 원칙이 그대로 적용된다.
    """
    ALTER TABLE inquiries ADD COLUMN IF NOT EXISTS reply TEXT
    """,
    """
    ALTER TABLE inquiries ADD COLUMN IF NOT EXISTS replied_at TEXT
    """,
    """
    ALTER TABLE inquiries ADD COLUMN IF NOT EXISTS replied_by TEXT
    """,
    # --- schema_version 10 (2026-08-20): 공유 코스 좋아요(부록 R.14) --------------------
    #
    # 좋아요는 `shared_courses.payload` **밖에만** 존재한다 — payload 는 2026-08-18 보안감사
    # A-6(콘텐츠 위조 차단)의 재구성 규칙이 걸린 영역이라 한 글자도 건드리지 않는다.
    #
    # PK(share_code, user_id) = **계정당 1회**를 DB가 강제한다. 애플리케이션 로직이 아니라
    # 제약이므로 동시 요청 2건이 들어와도 두 번 세어지지 않는다.
    # 양쪽 CASCADE 는 필수다: shared_courses 는 보존정책이 상시 삭제하고(delete_overflow/
    # delete_expired), users 는 탈퇴로 사라진다 — 없으면 고아 행이 쌓이거나 삭제가 FK 위반으로
    # 실패한다.
    """
    CREATE TABLE IF NOT EXISTS course_likes (
        share_code  TEXT    NOT NULL REFERENCES shared_courses (share_code) ON DELETE CASCADE,
        user_id     INTEGER NOT NULL REFERENCES users (id)         ON DELETE CASCADE,
        created_at  TEXT    NOT NULL,
        PRIMARY KEY (share_code, user_id)
    )
    """,
    # like_count 비정규화는 정렬 때문이다. ORDER BY COUNT(*) 는 매 페이지마다 전체 집계가
    # 필요하고, 목록 SELECT 에 조인 집계를 넣으면 "payload 미SELECT"로 아낀 비용을 다시 쓴다.
    """
    ALTER TABLE shared_courses ADD COLUMN IF NOT EXISTS like_count INTEGER NOT NULL DEFAULT 0
    """,
    # 인덱스 선두가 hidden 인 이유는 기존 ix_shared_courses_created 와 같다 — 피드는 항상
    # WHERE hidden = 0 이므로 선두 컬럼이 맞아야 인덱스가 실제로 쓰인다.
    """
    CREATE INDEX IF NOT EXISTS ix_shared_courses_likes
        ON shared_courses (hidden, like_count DESC, created_at DESC, seq DESC)
    """,
    # 탈퇴/관리자 삭제 시의 역방향 조회용(PK 는 share_code 선두라 user_id 단독 조회에 못 쓴다).
    """
    CREATE INDEX IF NOT EXISTS ix_course_likes_user
        ON course_likes (user_id)
    """,
)


class Database:
    """PostgreSQL 커넥션 풀 핸들. 프로세스당 1 인스턴스(deps.get_database)."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 5) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: ConnectionPool | None = None

    @property
    def dsn(self) -> str:
        return self._dsn

    @property
    def safe_target(self) -> str:
        """로그에 안전하게 남길 수 있는 접속 대상(호스트:포트/DB명만) — `dsn`은 사용자명·
        비밀번호를 담고 있어 **절대 로그에 그대로 찍으면 안 된다**(main.py 참고)."""
        return self._dsn.split("@")[-1].split("?")[0]

    # --- 커넥션 풀 / 스키마 -------------------------------------------------------

    def _ensure_pool(self) -> ConnectionPool:
        if self._pool is not None:
            return self._pool
        pool = ConnectionPool(
            conninfo=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            kwargs={"row_factory": dict_row, "autocommit": False},
            open=False,
        )
        pool.open(wait=True, timeout=10.0)
        self._apply_schema(pool)
        self._pool = pool
        logger.info("postgres 준비 완료 schema_version=%d", SCHEMA_VERSION)
        return pool

    def _apply_schema(self, pool: ConnectionPool) -> None:
        with pool.connection() as conn:
            for stmt in _SCHEMA_STATEMENTS:
                conn.execute(stmt)
            row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            current = None if row is None or row["v"] is None else int(row["v"])
            if current is None or current < SCHEMA_VERSION:
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (%s, NOW()::text)",
                    (SCHEMA_VERSION,),
                )

    def ensure_ready(self) -> bool:
        """기동 시 1회 호출(lifespan). 실패해도 앱은 뜬다 — 기존 조회 기능은 DB와 무관하다."""
        try:
            self._ensure_pool()
            return True
        except Exception:  # noqa: BLE001 — 저장소 장애로 부팅을 막지 않는다
            logger.exception("postgres 초기화 실패 — 리뷰/공유/로그인 기능만 비활성 상태로 동작합니다")
            return False

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    # --- 실행 (동기) -------------------------------------------------------------

    @contextmanager
    def _session(self) -> Iterator[psycopg.Connection]:
        pool = self._ensure_pool()
        # pool.connection()이 커넥션을 빌려주고, 블록이 예외 없이 끝나면 commit,
        # 예외면 rollback한 뒤 반납한다(SQLite의 _session이 하던 일을 pool이 대신함).
        with pool.connection() as conn:
            yield conn

    def read(self, fn: Callable[[psycopg.Connection], T]) -> T:
        with self._session() as conn:
            return fn(conn)

    def write(self, fn: Callable[[psycopg.Connection], T]) -> T:
        with self._session() as conn:
            return fn(conn)

    # --- 실행 (async 래퍼) --------------------------------------------------------

    async def aread(self, fn: Callable[[psycopg.Connection], T]) -> T:
        return await asyncio.to_thread(self.read, fn)

    async def awrite(self, fn: Callable[[psycopg.Connection], T]) -> T:
        return await asyncio.to_thread(self.write, fn)


def rows_to_dicts(rows: Any) -> list[dict[str, Any]]:
    """dict_row factory가 이미 dict를 주므로 원소 그대로 리스트화(레이어 경계 고정 목적으로
    sqlite.py와 동일한 헬퍼명을 유지 — 호출부가 바뀔 필요 없게)."""
    return [dict(r) for r in rows]


__all__ = ("Database", "SCHEMA_VERSION", "rows_to_dicts")
