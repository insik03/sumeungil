"""구글 OAuth 2.0 클라이언트 — 인가코드 교환 + 사용자 정보 조회.

표준 OAuth 2.0 Authorization Code 흐름(PKCE 없음 — confidential client, 서버가
client_secret을 보관하므로 불필요). 액세스/리프레시 토큰은 저장하지 않는다 —
userinfo 조회 1회에만 쓰고 버린다(우리 세션은 security/user_auth.py의 자체 서명
토큰으로 관리, 구글 토큰 재사용 없음).
"""

from __future__ import annotations

import logging

import httpx

from ..config import settings

logger = logging.getLogger("sumeungil.auth.google")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

SCOPE = "openid email profile"


class GoogleOAuthError(Exception):
    """토큰 교환/사용자 정보 조회 실패(코드 재사용, 만료, 네트워크 오류 등을 구분하지 않는다)."""


def build_authorize_url(*, state: str) -> str:
    """사용자를 리디렉션시킬 구글 인가 URL. client_secret은 여기 안 실린다(공개돼도 무해)."""
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        # 매번 계정 선택 화면을 보여준다 — 여러 구글 계정을 쓰는 사람이 실수로 이전 세션
        # 계정으로 자동 로그인되는 걸 막는다(임시 데모 성격상 명시적 선택이 안전한 기본값).
        "prompt": "select_account",
    }
    return f"{AUTH_URL}?{httpx.QueryParams(params)}"


async def exchange_code(code: str) -> dict:
    """인가코드 → 토큰 응답(access_token 등). client_secret은 절대 로그에 남기지 않는다."""
    data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,  # 로그 금지
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
            resp = await client.post(TOKEN_URL, data=data)
    except httpx.HTTPError as exc:
        logger.warning("구글 토큰 교환 요청 실패: %s", exc)
        raise GoogleOAuthError("token exchange request failed") from exc
    if resp.status_code != 200:
        # 응답 본문에 code/token이 섞여 나올 수 있는 원천이라 본문은 로그에 남기지 않는다.
        logger.warning("구글 토큰 교환 실패: status=%s", resp.status_code)
        raise GoogleOAuthError(f"token exchange failed: status={resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise GoogleOAuthError("token response not JSON") from exc


async def fetch_userinfo(access_token: str) -> dict:
    """{sub, email, email_verified, name, picture, ...}. access_token은 로그에 남기지 않는다."""
    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
            resp = await client.get(
                USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
    except httpx.HTTPError as exc:
        logger.warning("구글 사용자 정보 조회 요청 실패: %s", exc)
        raise GoogleOAuthError("userinfo request failed") from exc
    if resp.status_code != 200:
        logger.warning("구글 사용자 정보 조회 실패: status=%s", resp.status_code)
        raise GoogleOAuthError(f"userinfo failed: status={resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise GoogleOAuthError("userinfo response not JSON") from exc


__all__ = ("GoogleOAuthError", "build_authorize_url", "exchange_code", "fetch_userinfo")
