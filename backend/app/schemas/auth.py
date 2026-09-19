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
    # 2026-09-14 — 현재 약관 버전에 동의했는가. false 면 프론트가 ConsentModal 을 띄운다.
    terms_agreed: bool = False
    # 2026-09-18 — 연결된 로그인 방식(google/kakao → bool). 마이페이지 "로그인 연결" 표시용. 값(sub)은 절대 내리지 않는다.
    providers: dict[str, bool] = Field(default_factory=dict)


class UpdateDisplayNameRequest(BaseModel):
    # 리뷰 nickname과 동일한 상한 재사용(schemas/community.py) — 표시 이름이라는 같은
    # 성격의 값이라 별도 상한을 만들지 않는다.
    display_name: str = Field(min_length=1, max_length=NICKNAME_MAX)
    # 2026-09-14 — 첫 로그인 표시 이름 단계에서 함께 보내는 약관 동의 버전(선택).
    terms_version: str | None = Field(default=None, max_length=20)


class ConsentRequest(BaseModel):
    terms_version: str = Field(min_length=1, max_length=20)


class AuthOkResponse(BaseModel):
    ok: bool = True


__all__ = ("AuthOkResponse", "UpdateDisplayNameRequest", "UserSessionResponse")
