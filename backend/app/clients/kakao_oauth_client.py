"""카카오 OAuth 2.0 클라이언트 — 인가코드 교환 + 사용자 정보 조회 (2026-08-17 신설).

`google_oauth_client.py`와 완전히 동일한 3단계 구조(인가URL 생성 → code→token 교환 →
userinfo 조회)를 그대로 따른다 — 카카오도 표준 OAuth 2.0 Authorization Code 흐름이다.
액세스/리프레시 토큰은 저장하지 않는다(구글과 동일 원칙 — userinfo 조회 1회에만 쓰고 버림).
"""

from __future__ import annotations

import logging

import httpx

from ..config import settings

logger = logging.getLogger("sumeungil.auth.kakao")

AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
USERINFO_URL = "https://kapi.kakao.com/v2/user/me"

# 카카오 개발자 콘솔의 "동의항목"에서 닉네임(profile_nickname)·카카오계정(account_email)을
# 둘 다 켜둬야 실제로 값이 내려온다(deploy/DEPLOY.md 카카오 절 참고) — 콘솔에서 안 켰다면
# scope를 요청해도 userinfo 응답에 해당 필드가 아예 없다.
SCOPE = "profile_nickname account_email"


class KakaoOAuthError(Exception):
    """토큰 교환/사용자 정보 조회 실패(코드 재사용, 만료, 네트워크 오류 등을 구분하지 않는다)."""


def build_authorize_url(*, state: str) -> str:
    """사용자를 리디렉션시킬 카카오 인가 URL. client_secret은 여기 안 실린다(공개돼도 무해)."""
    params = {
        "client_id": settings.kakao_client_id,
        "redirect_uri": settings.kakao_redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
    }
    # state는 선택 파라미터도 있지만 카카오도 표준 OAuth state를 지원한다(CSRF 방어,
    # user_auth.issue_state/verify_state가 이미 provider 무관하게 처리한다).
    if state:
        params["state"] = state
    return f"{AUTH_URL}?{httpx.QueryParams(params)}"


async def exchange_code(code: str) -> dict:
    """인가코드 → 토큰 응답(access_token 등). client_secret은 절대 로그에 남기지 않는다."""
    data = {
        "grant_type": "authorization_code",
        "client_id": settings.kakao_client_id,
        "client_secret": settings.kakao_client_secret,  # 로그 금지
        "redirect_uri": settings.kakao_redirect_uri,
        "code": code,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
            resp = await client.post(TOKEN_URL, data=data)
    except httpx.HTTPError as exc:
        logger.warning("카카오 토큰 교환 요청 실패: %s", exc)
        raise KakaoOAuthError("token exchange request failed") from exc
    if resp.status_code != 200:
        # 응답 본문에 code/token이 섞여 나올 수 있는 원천이라 본문은 로그에 남기지 않는다.
        logger.warning("카카오 토큰 교환 실패: status=%s", resp.status_code)
        raise KakaoOAuthError(f"token exchange failed: status={resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise KakaoOAuthError("token response not JSON") from exc


async def fetch_userinfo(access_token: str) -> dict:
    """{id, kakao_account: {email, is_email_verified, profile: {nickname, ...}, ...}}.
    access_token은 로그에 남기지 않는다."""
    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_sec) as client:
            resp = await client.get(
                USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
    except httpx.HTTPError as exc:
        logger.warning("카카오 사용자 정보 조회 요청 실패: %s", exc)
        raise KakaoOAuthError("userinfo request failed") from exc
    if resp.status_code != 200:
        logger.warning("카카오 사용자 정보 조회 실패: status=%s", resp.status_code)
        raise KakaoOAuthError(f"userinfo failed: status={resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise KakaoOAuthError("userinfo response not JSON") from exc


__all__ = ("KakaoOAuthError", "build_authorize_url", "exchange_code", "fetch_userinfo")
