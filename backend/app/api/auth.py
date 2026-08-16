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
    3. state 검증 → code를 토큰으로 교환 → 사용자 정보(email/name/sub) 조회 →
       users 테이블 upsert(최초 로그인만 display_name을 구글 이름으로 초기화) →
       user_id를 담은 세션 쿠키 발급
    4. 팝업 안에서 window.opener로 (DB의 현재) display_name을 postMessage하고 스스로
       닫는다(부모 창은 그대로) — 프론트가 "표시 이름 정하기" 확인 단계를 보여준다
    5. 사용자가 확인/수정한 이름을 PATCH /display-name 으로 저장

## 세션 쿠키
관리자 쿠키(admin_auth.py)와 이름·서명 키가 다르다 — 서로 위조에 쓸 수 없다.
쿠키엔 user_id/email만 있고 display_name은 없다 — 매 요청마다 DB에서 최신값을 읽는다
(security/user_auth.py 모듈 docstring 참고).
"""

from __future__ import annotations

import html
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..clients.google_oauth_client import GoogleOAuthError, build_authorize_url, exchange_code, fetch_userinfo
from ..config import settings
from ..deps import get_database, get_user_auth
from ..repositories import user_repo
from ..schemas.auth import UpdateDisplayNameRequest, UserSessionResponse
from ..schemas.community import NICKNAME_MAX
from ..security.user_auth import UserAuth, UserIdentity
from ..util.time import now_kst, to_iso_kst
from ..util.user_text import clean_user_text, is_impersonating_staff

logger = logging.getLogger("sumeungil.api.auth")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _require_session(request: Request) -> tuple[UserAuth, UserIdentity]:
    """세션 쿠키 검증. 통과하지 못하면 401(admin.py의 동일 이름 함수와 같은 패턴,
    도메인이 달라 별도 모듈에 둔다)."""
    auth = get_user_auth()
    identity = auth.verify_token(request.cookies.get(auth.cookie_name)) if auth.enabled else None
    if identity is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return auth, identity


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
    google_sub = (userinfo.get("sub") or "").strip()
    # email_verified가 명시적으로 false인 경우만 거른다(필드 자체가 없는 계정 유형도 있어
    # 존재 여부만으로는 판단하지 않는다 — 과도한 차단 방지).
    if not email or not google_sub or userinfo.get("email_verified") is False:
        logger.warning("구글 로그인 실패: 이메일/sub 없음 또는 이메일 미검증")
        return _popup_close_html(ok=False, next_path=next_path)
    google_name = (userinfo.get("name") or email.split("@")[0]).strip()

    db = get_database()
    try:
        user = await db.awrite(
            lambda conn: user_repo.upsert_login(
                conn,
                google_sub=google_sub,
                email=email,
                default_display_name=google_name,
                now_iso=to_iso_kst(now_kst()),
            )
        )
    except Exception:  # noqa: BLE001 — DB 장애로 팝업이 무한 로딩되지 않게 실패로 수렴
        logger.exception("구글 로그인 계정 upsert 실패")
        return _popup_close_html(ok=False, next_path=next_path)

    token, _exp = auth.issue_token(user_id=user["id"], email=email)
    # 팝업엔 구글 원본 이름이 아니라 **DB의 현재 display_name**을 돌려준다 — 재로그인한
    # 사용자라면 이전에 직접 정한 이름이 그대로 뜬다(매번 구글 이름으로 되돌아가지 않음).
    response = _popup_close_html(ok=True, name=user["display_name"], next_path=next_path)
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
    """프론트 가드용. 유효한 세션이면 이름·이메일, 아니면 authenticated:false(401 아님 —
    비로그인은 실패가 아니라 정상 상태다)."""
    auth = get_user_auth()
    identity = auth.verify_token(request.cookies.get(auth.cookie_name)) if auth.enabled else None
    if identity is None:
        return UserSessionResponse(authenticated=False)
    db = get_database()
    user = await db.aread(lambda conn: user_repo.get_by_id(conn, identity.user_id))
    if user is None:
        # 세션은 유효한데 계정 행이 사라진 상태(수동 DB 조작 등) — 비로그인으로 취급.
        return UserSessionResponse(authenticated=False)
    return UserSessionResponse(authenticated=True, name=user["display_name"], email=user["email"])


@router.patch("/display-name", response_model=UserSessionResponse)
async def update_display_name(request: Request, body: UpdateDisplayNameRequest):
    """로그인 직후 "표시 이름 정하기" 단계(LoginModal.tsx)와, 추후 설정 화면에서 재사용할
    수 있는 닉네임 변경 엔드포인트. 리뷰 nickname과 동일한 정제·사칭차단 파이프라인을
    통과시킨다(util/user_text.py — 이 값도 결국 리뷰 표시 이름으로 쓰이는 공개 텍스트다)."""
    _auth, identity = _require_session(request)
    cleaned = clean_user_text(body.display_name, max_chars=NICKNAME_MAX)
    if not cleaned:
        raise HTTPException(status_code=400, detail="표시 이름을 입력해주세요.")
    if is_impersonating_staff(cleaned):
        raise HTTPException(status_code=400, detail="운영자로 오인될 수 있는 이름은 쓸 수 없어요.")
    db = get_database()
    user = await db.awrite(
        lambda conn: user_repo.update_display_name(conn, user_id=identity.user_id, display_name=cleaned)
    )
    if user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return UserSessionResponse(authenticated=True, name=user["display_name"], email=user["email"])


__all__ = ("router",)
