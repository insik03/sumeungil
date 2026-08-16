"""/api/v1/auth — 구글 로그인(임시, 2026-08-17 대표 지시). 데모 닉네임 로그인을 완전히 대체.

## 존재 조건
`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`/`GOOGLE_REDIRECT_URI` 중 하나라도 없으면
**main.py가 이 라우터를 등록하지 않는다** — admin.py와 동일 원칙. 즉 미설정 서버에서는
`/api/v1/auth/*`가 404이고 OpenAPI에도 나타나지 않는다.

## 흐름 (팝업 기반)
프론트가 `window.open()`으로 `/google/login`을 새 창에 띄운다(페이지 전체 이동이 아님 —
로그인 게이트가 "로그인 후 원래 하려던 동작을 이어서 실행"하는 기존 UX를 유지하기 위해서다).
    1. GET /google/login  → state(서명된 CSRF 토큰) 발급 → 구글 인가 화면으로 302
    2. 사용자가 구글에서 동의 → 구글이 GET /google/callback?code=&state= 로 리디렉션
    3. state 검증 → code를 토큰으로 교환 → 사용자 정보(email/name) 조회 → 세션 쿠키 발급
    4. 팝업 안에서 window.opener로 결과를 postMessage하고 스스로 닫는다(부모 창은 그대로)

## 세션 쿠키
관리자 쿠키(admin_auth.py)와 이름·서명 키가 다르다 — 서로 위조에 쓸 수 없다.
계정 테이블이 없다(security/user_auth.py 모듈 docstring 참고) — 이메일/이름이 곧 세션이다.
"""

from __future__ import annotations

import html
import json
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..clients.google_oauth_client import GoogleOAuthError, build_authorize_url, exchange_code, fetch_userinfo
from ..config import settings
from ..deps import get_user_auth
from ..schemas.auth import UserSessionResponse

logger = logging.getLogger("sumeungil.api.auth")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/google/login")
async def google_login(next: str = Query(default="/")):
    """구글 인가 화면으로 리디렉션. `next`는 로그인 완료 후 팝업이 부모에게 알려줄 복귀
    경로(쿼리 없는 경로만 — user_auth.issue_state가 오픈 리다이렉트를 막는다)."""
    auth = get_user_auth()
    state = auth.issue_state(next_path=next)
    return RedirectResponse(build_authorize_url(state=state), status_code=302)


def _popup_close_html(*, ok: bool, name: str = "", next_path: str = "/") -> HTMLResponse:
    """팝업 안에서만 뜨는 최소 HTML. window.opener로 결과를 postMessage하고 스스로 닫는다.
    postMessage target origin을 FRONTEND_BASE_URL로 고정해(외부 페이지 위조 방지) 부모가
    이 오리진에서만 온 메시지를 신뢰하게 한다(LoginModal.tsx가 origin을 한 번 더 검사)."""
    payload = json.dumps({"source": "sumeungil-google-login", "ok": ok, "name": name})
    frontend_origin = html.escape(settings.frontend_base_url, quote=True)
    fallback_link = html.escape(f"{settings.frontend_base_url}{next_path}", quote=True)
    status_text = "로그인 완료" if ok else "로그인 실패"
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8"><title>{status_text}</title></head>
<body style="font-family:system-ui;padding:32px;text-align:center;color:#1f3b48">
<p>{status_text}. 이 창은 자동으로 닫힙니다…</p>
<p><a href="{fallback_link}">닫히지 않으면 여기를 눌러 돌아가세요</a></p>
<script>
(function() {{
  try {{ window.opener && window.opener.postMessage({payload}, "{frontend_origin}"); }} catch (e) {{}}
  window.close();
}})();
</script>
</body></html>"""
    )


@router.get("/google/callback")
async def google_callback(request: Request, code: str | None = None, state: str | None = None):
    auth = get_user_auth()
    next_path = auth.verify_state(state)
    if next_path is None:
        logger.warning("구글 콜백 state 검증 실패(만료/위조/재사용 구분 안 함)")
        return _popup_close_html(ok=False)
    if not code:
        return _popup_close_html(ok=False, next_path=next_path)

    try:
        tokens = await exchange_code(code)
        access_token = tokens.get("access_token")
        if not access_token:
            raise GoogleOAuthError("no access_token in response")
        userinfo = await fetch_userinfo(access_token)
    except GoogleOAuthError as exc:
        logger.warning("구글 로그인 실패: %s", exc)
        return _popup_close_html(ok=False, next_path=next_path)

    email = (userinfo.get("email") or "").strip()
    # email_verified가 명시적으로 false인 경우만 거른다(필드 자체가 없는 계정 유형도 있어
    # 존재 여부만으로는 판단하지 않는다 — 과도한 차단 방지).
    if not email or userinfo.get("email_verified") is False:
        logger.warning("구글 로그인 실패: 이메일 없음/미검증")
        return _popup_close_html(ok=False, next_path=next_path)
    name = (userinfo.get("name") or email.split("@")[0]).strip()

    token, exp = auth.issue_token(email=email, name=name)
    response = _popup_close_html(ok=True, name=name, next_path=next_path)
    response.set_cookie(
        key=auth.cookie_name,
        value=token,
        max_age=auth.session_ttl_sec,
        httponly=True,
        secure=auth.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout")
async def logout():
    auth = get_user_auth()
    response = HTMLResponse(content="", status_code=204)
    response.delete_cookie(
        key=auth.cookie_name,
        path="/",
        httponly=True,
        secure=auth.cookie_secure,
        samesite="lax",
    )
    return response


@router.get("/me", response_model=UserSessionResponse)
async def me(request: Request):
    """프론트 가드용. 유효한 세션이면 이름·만료시각, 아니면 authenticated:false(401 아님 —
    비로그인은 실패가 아니라 정상 상태다)."""
    auth = get_user_auth()
    identity = auth.verify_token(request.cookies.get(auth.cookie_name))
    if identity is None:
        return UserSessionResponse(authenticated=False)
    # 만료시각을 다시 계산하려면 토큰을 재파싱해야 하는데(verify_token은 신원만 반환)
    # 화면에서 실제로 쓰는 값이 아니라 생략한다 — 필요해지면 verify_token 반환 타입에 exp를 더한다.
    return UserSessionResponse(authenticated=True, name=identity.name, email=identity.email)


__all__ = ("router",)
