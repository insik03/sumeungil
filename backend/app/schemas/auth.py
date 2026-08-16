"""/api/v1/auth 응답 스키마. 계정 테이블이 없어(security/user_auth.py) 전부 세션 토큰에서
바로 만든다 — DB round-trip 없음.
"""

from __future__ import annotations

from pydantic import BaseModel


class UserSessionResponse(BaseModel):
    authenticated: bool
    # 비로그인이면 전부 None. 이메일은 화면에 굳이 보여줄 필요가 없어(닉네임 자리엔 이름만
    # 쓴다) optional로 열어두되, 프론트가 필요하면 쓸 수 있게 내려는 준다.
    name: str | None = None
    email: str | None = None


class AuthOkResponse(BaseModel):
    ok: bool = True


__all__ = ("AuthOkResponse", "UserSessionResponse")
