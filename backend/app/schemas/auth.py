"""/api/v1/auth 응답 스키마.

2026-08-17부터 `users` 테이블(db/sqlite.py schema_version 4)이 생겨 display_name은
매 요청마다 DB에서 최신값을 읽는다(security/user_auth.py 모듈 docstring 참고) — 세션
토큰 자체엔 user_id/email만 있다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .community import NICKNAME_MAX


class UserSessionResponse(BaseModel):
    authenticated: bool
    # 비로그인이면 전부 None. 이메일은 화면에 굳이 보여줄 필요가 없어(닉네임 자리엔 이름만
    # 쓴다) optional로 열어두되, 프론트가 필요하면 쓸 수 있게 내려는 준다.
    name: str | None = None
    email: str | None = None


class UpdateDisplayNameRequest(BaseModel):
    # 리뷰 nickname과 동일한 상한 재사용(schemas/community.py) — 표시 이름이라는 같은
    # 성격의 값이라 별도 상한을 만들지 않는다.
    display_name: str = Field(min_length=1, max_length=NICKNAME_MAX)


class AuthOkResponse(BaseModel):
    ok: bool = True


__all__ = ("AuthOkResponse", "UpdateDisplayNameRequest", "UserSessionResponse")
