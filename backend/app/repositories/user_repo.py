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
    /privacy §4가 이미 설명하는 동작이고 이번 변경과 무관하다."""
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
