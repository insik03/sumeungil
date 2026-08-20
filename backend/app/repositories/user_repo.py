"""users 테이블 SQL — 구글·카카오 로그인 계정(2026-08-17 신설, 2026-08-17 카카오 확장,
schema_version 6).

review_repo.py와 동일한 규약: 전부 동기 함수, 첫 인자로 `psycopg.Connection`, 호출은
반드시 `Database.aread/awrite`를 통해서만(서비스/라우터 레이어 책임). SQL은 전부 파라미터
바인딩(`%s`) — 문자열 포매팅으로 값을 넣지 않는다.

## 계정 통합 규칙 (2026-08-17, 카카오 추가 — 대표 확인)
같은 사람이 구글·카카오를 둘 다 쓰면 자동으로 같은 계정에 묶는다 — 단 이번 로그인의
이메일이 **그 provider로부터 검증된 상태일 때만**. 검증 안 된(또는 없는) 이메일로 통합을
허용하면 "남이 내 구글 이메일만 알면 카카오로 내 계정을 가로챈다"는 실제 계정 탈취
경로가 생긴다 — `upsert_login`의 우선순위(provider_sub 일치 → 검증된 이메일 일치 →
신규 생성)가 이걸 막는다. `_PROVIDER_COLUMNS`는 admin_repo.py의 `_REVIEW_WHERE`/
`_REVIEW_ORDER`와 같은 화이트리스트 딕셔너리 패턴이다 — 컬럼명이 사용자 입력이 아니라
이 고정 딕셔너리에서만 나오므로 f-string으로 SQL에 넣어도 인젝션 경로가 없다.
"""

from __future__ import annotations

from typing import Any, Literal

import psycopg

Provider = Literal["google", "kakao"]

_PROVIDER_COLUMNS: dict[str, str] = {"google": "google_sub", "kakao": "kakao_sub"}


def _row(r: dict[str, Any] | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


def get_by_id(conn: psycopg.Connection, user_id: int) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone())


def get_by_provider_sub(
    conn: psycopg.Connection, *, provider: Provider, provider_sub: str
) -> dict[str, Any] | None:
    column = _PROVIDER_COLUMNS[provider]
    return _row(
        conn.execute(f"SELECT * FROM users WHERE {column} = %s", (provider_sub,)).fetchone()
    )


def get_by_email(conn: psycopg.Connection, email: str) -> dict[str, Any] | None:
    """계정 통합 판정에만 쓴다 — 호출부(upsert_login)가 이메일 검증 여부를 먼저 확인한다."""
    return _row(conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone())


def upsert_login(
    conn: psycopg.Connection,
    *,
    provider: Provider,
    provider_sub: str,
    email: str | None,
    email_verified: bool,
    default_display_name: str,
    now_iso: str,
) -> dict[str, Any]:
    """로그인마다 호출. 세 단계로 계정을 찾는다(모듈 docstring의 통합 규칙 참고):

    1. 이 provider의 sub로 기존 행이 있으면 그 행(email/last_login_at만 갱신,
       **display_name은 건드리지 않는다** — 사용자가 이전에 직접 정한 이름을 로그인
       제공자의 원본 이름으로 되돌리지 않기 위해서).
    2. 1이 없고, 이번 이메일이 **검증됐고**, 그 이메일로 기존 행이 있으면 그 행에 이번
       provider의 sub만 채워 계정을 통합한다(email/display_name은 기존 값 유지).
    3. 1·2 둘 다 없으면 새 계정을 만든다(display_name은 이번 로그인 이름으로 초기화).

    2026-08-18 보안검토 K-C1(Critical, 계정 탈취) 수정 — **이메일은 검증된 값만 DB에
    저장한다.** 예전엔 미검증 이메일도 `email` 컬럼에 그대로 저장해버려서, 공격자가
    "victim@example.com"을 미검증 상태로 먼저 카카오 로그인해 선점해두면(is_email_verified
    가짜/False), 나중에 실제 피해자가 그 이메일로 **검증된** 구글 로그인을 했을 때
    `get_by_email`이 공격자 행을 찾아 그 행에 병합돼버렸다(피해자의 구글 sub가 공격자
    행에 붙고, 공격자의 카카오 sub는 그대로 남아 공격자가 계속 그 계정에 접근 가능).
    이메일을 애초에 검증됐을 때만 저장하면 이 매칭 자체가 성립하지 않는다. 같은 이유로
    재로그인(1번 분기)에서도 이번 로그인이 검증된 이메일을 안 줬으면(예: 카카오 이메일
    동의 안 함) 기존에 저장해둔 이메일을 **덮어쓰지 않는다**(K-M1 — 검증된 이메일이
    미검증 로그인 한 번으로 지워지거나 낮은 신뢰도 값으로 바뀌는 것을 막는다).
    """
    column = _PROVIDER_COLUMNS[provider]
    stored_email = email if email_verified else None

    existing = get_by_provider_sub(conn, provider=provider, provider_sub=provider_sub)
    if existing is not None:
        if stored_email is not None:
            conn.execute(
                "UPDATE users SET email = %s, last_login_at = %s WHERE id = %s",
                (stored_email, now_iso, existing["id"]),
            )
        else:
            conn.execute(
                "UPDATE users SET last_login_at = %s WHERE id = %s",
                (now_iso, existing["id"]),
            )
        return get_by_id(conn, existing["id"])  # type: ignore[return-value]

    if stored_email is not None:
        by_email = get_by_email(conn, stored_email)
        if by_email is not None:
            conn.execute(
                f"UPDATE users SET {column} = %s, last_login_at = %s WHERE id = %s",
                (provider_sub, now_iso, by_email["id"]),
            )
            return get_by_id(conn, by_email["id"])  # type: ignore[return-value]

    cur = conn.execute(
        f"""
        INSERT INTO users ({column}, email, display_name, created_at, last_login_at)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (provider_sub, stored_email, default_display_name, now_iso, now_iso),
    )
    new_id = cur.fetchone()["id"]
    return get_by_id(conn, new_id)  # type: ignore[return-value]


def update_display_name(
    conn: psycopg.Connection, *, user_id: int, display_name: str
) -> dict[str, Any] | None:
    conn.execute("UPDATE users SET display_name = %s WHERE id = %s", (display_name, user_id))
    return get_by_id(conn, user_id)


def delete_account(conn: psycopg.Connection, *, user_id: int) -> bool:
    """계정 삭제(탈퇴, 2026-08-17 QA C-4 대응) — users 행을 즉시 영구 삭제한다.

    리뷰 등 게시물의 `nickname`은 작성 시점에 텍스트로 복사돼 저장되므로(리뷰 테이블이
    users를 FK로 참조하지 않는다) 계정을 지워도 기존 게시물은 그대로 남는다 — 이는
    /privacy §4가 이미 설명하는 동작이고 이번 변경과 무관하다.

    ## 좋아요 카운터 보정 (2026-08-20 보안검수 M-1)
    `course_likes`는 `users`를 FK CASCADE로 참조하므로 탈퇴하면 그 계정의 좋아요 **행**은
    사라지지만, 비정규화 컬럼인 `shared_courses.like_count`는 CASCADE가 건드리지 않는다.
    보정 경로가 없으면 "가입 → 좋아요 → 탈퇴"를 반복해 `sort=popular` 랭킹을 부풀릴 수
    있고, `delete_overflow`의 유예 조건(`like_count > 0`)이 실제 좋아요 0인 코스를 영구
    보존해버린다. 그래서 users를 지우기 **전에** 같은 트랜잭션에서 감산한다.

    감산은 `DELETE ... RETURNING` 으로 지운 행의 share_code 를 받아서 한다(보안팀이 제시한
    `IN (SELECT ... FROM course_likes ...)` 서브쿼리와 결과는 같다). 이렇게 쓰는 이유 두 가지:
      - `course_likes` -> `shared_courses` 라는 **락 순서**가 toggle_like/untoggle_like
        (shared_course_repo.py:128 주석)와 같아진다. 순서를 뒤집으면 같은 사용자가 좋아요와
        탈퇴를 동시에 날렸을 때 교차 데드락이 성립한다.
      - 읽은 뒤 지우는 게 아니라 지우면서 읽으므로, 읽기와 CASCADE 사이에 끼어든 좋아요가
        카운터에만 남는 틈이 없다(끼어든 INSERT 는 users 삭제 커밋 후 FK 위반으로 롤백된다).
    `GREATEST(...,0)` 는 이미 손상된 과거 데이터가 음수로 표시되지 않게 하는 방어선이다
    (untoggle_like 와 동일 규약). `ix_course_likes_user` 인덱스가 있어 비용은 낮다.
    """
    liked_codes = [
        row["share_code"]
        for row in conn.execute(
            "DELETE FROM course_likes WHERE user_id = %s RETURNING share_code", (user_id,)
        ).fetchall()
    ]
    if liked_codes:
        # PK 가 (share_code, user_id) 라 한 계정이 같은 코스를 두 번 누를 수 없다
        # = liked_codes 에 중복이 없다 = 코스당 정확히 1 만큼 감산된다.
        conn.execute(
            """
            UPDATE shared_courses SET like_count = GREATEST(like_count - 1, 0)
             WHERE share_code = ANY(%s)
            """,
            (liked_codes,),
        )
    cur = conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
    return cur.rowcount > 0


__all__ = (
    "Provider",
    "delete_account",
    "get_by_email",
    "get_by_id",
    "get_by_provider_sub",
    "update_display_name",
    "upsert_login",
)
