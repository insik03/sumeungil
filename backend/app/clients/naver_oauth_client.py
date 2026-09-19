"""네이버 로그인(OAuth 2.0) 클라이언트 — 인가코드 교환 + 사용자 정보 조회 (2026-09-20, 대표 결정 "네이버까지만").

`kakao_oauth_client.py` 와 같은 3단계(인가 URL → code→token → userinfo). 토큰은 저장하지 않는다.
네이버 개발자센터 앱: 서비스 URL https://sumeungil.co.kr, Callback URL
https://sumeungil.co.kr/api/v1/auth/naver/callback, 제공 정보는 **이메일·별명**만 요청한다.
"""

from __future__ import annotations

import logging

import httpx

from ..config import settings

logger = logging.getLogger("sumeungil.auth.naver")

AUTH_URL = "https://nid.naver.com/oauth2.0/authorize"
TOKEN_URL = "https://nid.naver.com/oauth2.0/token"
USERINFO_URL = "https://openapi.naver.com/v1/nid/me"


class NaverOAuthError(Exception):
    """토큰 교환/사용자 정보 조회 실패(원인을 구분하지 않는다)."""


def build_authorize_url(*, state: str) -> str:
    """네이버는 state 가 필수다(우리 서명 state 를 그대로 싣는다). client_secret 은 여기 없다."""
    params = {
        "client_id": settings.naver_client_id,
        "redirect_uri": settings.naver_redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return f"{AUTH_URL}?{httpx.QueryParams(params)}"


async def exchange_code(code: str, state: str) -> dict:
    """인가코드 → 토큰. 네이버는 토큰 요청에도 state 를 요구한다. client_secret 은 로그 금지."""
    params = {
        "grant_type": "authorization_code",
        "client_id": settings.naver_client_id,
        "client_secret": settings.naver_client_secret,  # 로그 금지
        "code": code,
        "state": state,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
            resp = await client.post(TOKEN_URL, data=params)
    except httpx.HTTPError as exc:
        logger.warning("네이버 토큰 교환 요청 실패: %s", exc)
        raise NaverOAuthError("token exchange request failed") from exc
    if resp.status_code != 200:
        logger.warning("네이버 토큰 교환 실패: status=%s", resp.status_code)
        raise NaverOAuthError(f"token exchange failed: status={resp.status_code}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise NaverOAuthError("token response not JSON") from exc
    if body.get("error"):
        # 네이버는 200 으로도 {"error": "...", "error_description": "..."} 를 준다.
        logger.warning("네이버 토큰 교환 오류: %s", body.get("error"))
        raise NaverOAuthError(f"token error: {body.get('error')}")
    return body


async def fetch_userinfo(access_token: str) -> dict:
    """{"resultcode": "00", "message": "success", "response": {id, email, nickname, name, ...}} 의
    `response` 만 돌려준다. access_token 은 로그에 남기지 않는다."""
    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
            resp = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    except httpx.HTTPError as exc:
        logger.warning("네이버 사용자 정보 조회 요청 실패: %s", exc)
        raise NaverOAuthError("userinfo request failed") from exc
    if resp.status_code != 200:
        logger.warning("네이버 사용자 정보 조회 실패: status=%s", resp.status_code)
        raise NaverOAuthError(f"userinfo failed: status={resp.status_code}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise NaverOAuthError("userinfo response not JSON") from exc
    if body.get("resultcode") != "00":
        raise NaverOAuthError(f"userinfo resultcode={body.get('resultcode')}")
    return body.get("response") or {}


__all__ = ("NaverOAuthError", "build_authorize_url", "exchange_code", "fetch_userinfo")
