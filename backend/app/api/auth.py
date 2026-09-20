"""/api/v1/auth — 구글·카카오 로그인(2026-08-17 대표 지시, 카카오는 같은 날 추가).
데모 닉네임 로그인을 완전히 대체.

## 존재 조건
세션 서명키(`USER_SESSION_SECRET` 또는 `JWT_SECRET_KEY`)가 없으면 **main.py가 이
라우터 자체를 등록하지 않는다**(admin.py와 동일 원칙 — security/user_auth.py의
`enabled` 참고). 세션키는 있지만 구글/카카오 중 한쪽만 설정돼 있으면, 그 provider의
`/{provider}/login`·`/{provider}/callback`만 개별적으로 404가 된다(각 핸들러 시작부의
`auth.google_enabled`/`auth.kakao_enabled` 체크) — `/me`·`/logout`·`/display-name`·
`DELETE /me`는 provider 설정과 무관하게 항상 살아있다(세션만 있으면 로그인 상태 판별
가능하므로).

## 흐름 (팝업 기반, 구글·카카오 공용)
프론트가 `window.open()`으로 `/{provider}/login`을 새 창에 띄운다(페이지 전체 이동이
아님 — 로그인 게이트가 "로그인 후 원래 하려던 동작을 이어서 실행"하는 기존 UX를 유지하기
위해서다).
    1. GET /{provider}/login  → state+nonce 발급, nonce는 HttpOnly 쿠키로 브라우저에 바인딩
       → provider 인가 화면으로 302
    2. 사용자가 동의 → provider가 GET /{provider}/callback?code=&state= 로 리디렉션
    3. state 서명·만료·**쿠키 nonce 일치**를 전부 검증(2026-08-17 보안검토 M-1) → code를
       토큰으로 교환 → 사용자 정보 조회 → users 테이블 upsert(계정 통합 규칙은
       repositories/user_repo.py 모듈 docstring 참고 — 최초 로그인만 display_name을
       provider 이름으로 초기화, 그 이름도 리뷰 nickname과 동일한 정제·사칭차단을
       통과시킨다 — 보안검토 C-2) → user_id를 담은 세션 쿠키 발급
    4. 팝업 안에서 window.opener로 (DB의 현재) display_name을 postMessage하고 스스로
       닫는다(부모 창은 그대로) — 프론트가 "표시 이름 정하기" 확인 단계를 보여준다
    5. 사용자가 확인/수정한 이름을 PATCH /display-name 으로 저장

## 세션 쿠키
관리자 쿠키(admin_auth.py)와 이름·서명 키가 다르다 — 서로 위조에 쓸 수 없다.
쿠키엔 user_id/email만 있고 display_name은 없다 — 매 요청마다 DB에서 최신값을 읽는다
(security/user_auth.py 모듈 docstring 참고). email은 provider·계정 통합 상태에 따라
없을 수 있다(UserIdentity.email이 `str | None`인 이유).
"""

from __future__ import annotations

import html
import json
import logging
from typing import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from ..clients.google_oauth_client import GoogleOAuthError
from ..clients.google_oauth_client import build_authorize_url as google_authorize_url
from ..clients.google_oauth_client import exchange_code as google_exchange_code
from ..clients.google_oauth_client import fetch_userinfo as google_fetch_userinfo
from ..clients.kakao_oauth_client import KakaoOAuthError
from ..clients.kakao_oauth_client import build_authorize_url as kakao_authorize_url
from ..clients.kakao_oauth_client import exchange_code as kakao_exchange_code
from ..clients.kakao_oauth_client import fetch_userinfo as kakao_fetch_userinfo
from ..clients.naver_oauth_client import NaverOAuthError
from ..clients.naver_oauth_client import build_authorize_url as naver_authorize_url
from ..clients.naver_oauth_client import exchange_code as naver_exchange_code
from ..clients.naver_oauth_client import fetch_userinfo as naver_fetch_userinfo
from ..config import settings
from ..deps import get_database, get_user_auth
from ..repositories import user_repo
from .auth_deps import require_login
from ..schemas.auth import (
    ConsentRequest,
    SignupCompleteRequest,
    UpdateDisplayNameRequest,
    UserSessionResponse,
)

# 약관·개인정보처리방침 동의 버전 (2026-09-14). 프론트 lib/consent.ts 와 같은 값. 실질 변경 시 둘 다 올린다.
TERMS_VERSION = "2026-09-14"


def _terms_agreed(user: dict | None) -> bool:
    return bool(user) and user.get("terms_version") == TERMS_VERSION
from ..schemas.community import NICKNAME_MAX
from ..security.user_auth import UserAuth, UserIdentity
from ..util.time import now_kst, to_iso_kst
from ..util.user_text import clean_user_text, is_impersonating_staff
from .community_common import error_response

logger = logging.getLogger("sumeungil.api.auth")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# OAuth state nonce 쿠키 — 로그인 왕복(login→provider→callback) 동안만 산다. 세션 쿠키와
# 완전히 별개(이름·용도·수명 전부 다름). 이 라우터 하위 경로에서만 필요해 path를 좁힌다.
# 구글·카카오가 공유한다(한 번에 한 팝업만 여는 UX 전제 — LoginModal.tsx 참고).
STATE_COOKIE_NAME = "sumeungil_oauth_state"
STATE_COOKIE_PATH = "/api/v1/auth"
# 2026-09-20 — 가입 보류 쿠키(약관 동의 전). 세션 쿠키가 아니다 — 이것만으로는 아무 API 도 못 쓴다.
SIGNUP_COOKIE_NAME = "sumeungil_signup"

# 팝업이 postMessage로 보내는 결과 봉투의 source 값. 2026-08-17 카카오 추가 전에는
# "sumeungil-google-login"으로 구글 전용이었는데, 프론트(LoginModal.tsx)가 provider를
# 구분할 필요가 없어(성공하면 그냥 표시 이름 확인 단계로 넘어갈 뿐) 공용값으로 바꿨다.
POPUP_MESSAGE_SOURCE = "sumeungil-login"


def _require_session(request: Request) -> tuple[UserAuth, UserIdentity]:
    """세션 쿠키 검증. 통과하지 못하면 401(admin.py의 동일 이름 함수와 같은 패턴,
    도메인이 달라 별도 모듈에 둔다)."""
    auth = get_user_auth()
    identity = auth.verify_token(request.cookies.get(auth.cookie_name)) if auth.enabled else None
    if identity is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return auth, identity


def _start_oauth_login(
    *, next_path: str, authorize_url_builder: Callable[..., str]
) -> RedirectResponse:
    """provider 인가 화면으로 리디렉션(구글·카카오 공용). `next_path`는 로그인 완료 후
    팝업이 부모에게 알려줄 복귀 경로(쿼리 없는 경로만 — user_auth.issue_state가 오픈
    리다이렉트를 막는다).

    nonce를 HttpOnly 쿠키로 심어 이 브라우저가 시작한 로그인임을 콜백에서 대조한다
    (2026-08-17 보안검토 M-1 — state 서명만으로는 브라우저를 증명하지 못했다)."""
    auth = get_user_auth()
    state, nonce = auth.issue_state(next_path=next_path)
    response = RedirectResponse(authorize_url_builder(state=state), status_code=302)
    response.set_cookie(
        key=STATE_COOKIE_NAME,
        value=nonce,
        max_age=600,  # user_auth.STATE_TTL_SEC와 동일(10분) — 여기서 상수 임포트 대신 값만 맞춘다.
        httponly=True,
        secure=auth.cookie_secure,
        samesite="lax",
        path=STATE_COOKIE_PATH,
    )
    return response


# 2026-09-18 계정 연결 — 로그인 중인 사용자가 `?link=1` 로 시작하면 콜백에서 새 세션을 만들지 않고
# **현재 세션 계정에 그 provider 를 붙인다**(user_repo.link_provider). state 의 next_path 자리에 이
# 표식을 넣어 왕복시킨다(안전 경로 정규식에 맞는 값). 완료 후 팝업은 부모에게 linked 결과를 보낸다.
LINK_NEXT = "/__link"


@router.get("/google/login")
async def google_login(next: str = Query(default="/"), link: bool = Query(default=False)):
    if link:
        next = LINK_NEXT
    auth = get_user_auth()
    if not auth.google_enabled:
        raise HTTPException(status_code=404)
    return _start_oauth_login(next_path=next, authorize_url_builder=google_authorize_url)


@router.get("/kakao/login")
async def kakao_login(next: str = Query(default="/"), link: bool = Query(default=False)):
    if link:
        next = LINK_NEXT
    auth = get_user_auth()
    if not auth.kakao_enabled:
        raise HTTPException(status_code=404)
    return _start_oauth_login(next_path=next, authorize_url_builder=kakao_authorize_url)


def _js_safe_json(value: object) -> str:
    """<script> 블록 안에 안전하게 삽입할 수 있는 JSON 직렬화.

    2026-08-17 보안검토 C-2 — `html.escape`는 `<script>` 안에서 HTML 엔티티가 디코딩되지
    않아 애초에 맞지 않는 방어였다(엔티티 그대로 렌더될 뿐). HTML 파서는 JS 문법과 무관하게
    `</script` 리터럴을 만나면 그 자리에서 스크립트 블록을 끊어버리므로, `<`를 유니코드
    이스케이프로 바꿔 그 시퀀스 자체가 나타나지 않게 한다. `\\u2028`/`\\u2029`(JS 줄
    종결자, JSON에서는 유효한 문자지만 JS 파서에서는 개행으로 취급돼 문 종료를 유발할 수
    있다)도 함께 이스케이프한다."""
    raw = json.dumps(value)
    return raw.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _popup_close_html(
    *, ok: bool, name: str = "", is_new: bool = False, next_path: str = "/", linked: str | None = None
) -> HTMLResponse:
    """팝업 안에서만 뜨는 최소 HTML. window.opener로 결과를 postMessage하고 스스로 닫는다.
    postMessage target origin을 FRONTEND_BASE_URL로 고정해(외부 페이지 위조 방지) 부모가
    이 오리진에서만 온 메시지를 신뢰하게 한다(LoginModal.tsx가 origin을 한 번 더 검사).

    `is_new`(2026-08-18, 대표 지시 — "로그인할 때마다 닉네임 정하게 할 건 아니지?") — 신규
    가입일 때만 프론트가 "표시 이름 정하기" 확인 단계를 보여주게 하는 신호다. 재로그인마다
    매번 물어보면 성가시다는 지적에 따라, LoginModal.tsx가 이 값이 false면 그 단계를
    건너뛰고 바로 로그인을 완료 처리한다(_complete_oauth_login 참고)."""
    payload = _js_safe_json(
        {"source": POPUP_MESSAGE_SOURCE, "ok": ok, "name": name, "is_new": is_new, "linked": linked}
    )
    frontend_origin_js = _js_safe_json(settings.frontend_base_url)  # 이미 따옴표 포함(JSON 문자열)
    fallback_link = html.escape(f"{settings.frontend_base_url}{next_path}", quote=True)
    status_text = "로그인 완료" if ok else "로그인 실패"
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8"><title>{status_text}</title></head>
<body style="font-family:system-ui;padding:32px;text-align:center;color:#1f3b48">
<p>{status_text}. 이 창은 자동으로 닫힙니다…</p>
<p><a href="{fallback_link}">닫히지 않으면 여기를 눌러 돌아가세요</a></p>
<script>
(function() {{
  try {{ window.opener && window.opener.postMessage({payload}, {frontend_origin_js}); }} catch (e) {{}}
  window.close();
}})();
</script>
</body></html>"""
    )


def _set_session_cookie(response: Response, auth: UserAuth, token: str) -> None:
    """로그인 완료·/me 슬라이딩 재발급이 같은 플래그로 쿠키를 심는다."""
    response.set_cookie(
        key=auth.cookie_name,
        value=token,
        max_age=auth.session_ttl_sec,
        httponly=True,
        secure=auth.cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_state_cookie(response: Response) -> None:
    """state nonce 쿠키를 지운다 — 성공/실패 무관하게 콜백 응답에 항상 붙여 1회용을
    보장한다(2026-08-17 보안검토 M-1)."""
    response.delete_cookie(key=STATE_COOKIE_NAME, path=STATE_COOKIE_PATH)


def _sanitize_display_name(raw_name: str, email: str | None) -> str:
    """로그인 제공자가 돌려준 이름을 표시 이름으로 쓰기 전 정제한다(구글·카카오 공용,
    2026-08-17 보안검토 C-2) — 리뷰 nickname과 동일한 파이프라인(clean_user_text:
    제어문자·HTML 태그 제거 + 길이 상한, is_impersonating_staff: 사칭차단). 실패하면
    이메일 로컬파트로, 그것도 없으면 "여행자"로 떨어진다."""
    name = clean_user_text((raw_name or "").strip(), max_chars=NICKNAME_MAX)
    if not name or is_impersonating_staff(name):
        local_part = (email or "").split("@")[0] if email else ""
        name = clean_user_text(local_part, max_chars=NICKNAME_MAX) or "여행자"
    return name


async def _complete_oauth_login(
    *,
    request: Request,
    provider: user_repo.Provider,
    provider_sub: str,
    email: str | None,
    email_verified: bool,
    raw_name: str,
    next_path: str,
) -> Response:
    """provider_sub/이메일(검증 여부 포함)을 받아 계정 upsert(계정 통합 규칙은
    user_repo.upsert_login 참고) + 세션 토큰 발급 + 팝업 종료 HTML까지 끝낸다.
    google_callback/kakao_callback이 각자 userinfo를 해석한 뒤 이 함수 하나로 수렴한다."""
    auth = get_user_auth()
    display_name = _sanitize_display_name(raw_name, email)
    db = get_database()

    if next_path == LINK_NEXT:
        # 계정 연결 모드 — 현재 세션이 있어야 한다(팝업은 같은 브라우저라 쿠키가 같이 온다).
        try:
            identity = await require_login(request)
        except HTTPException:
            identity = None
        except Exception:  # DB unavailable: finish the OAuth popup cleanly.
            logger.exception("계정 연결 세션 확인 실패")
            response = _popup_close_html(ok=False, next_path="/mypage", linked="error")
            _clear_state_cookie(response)
            return response
        if identity is None:
            response = _popup_close_html(ok=False, next_path="/mypage", linked="not_logged_in")
            _clear_state_cookie(response)
            return response
        try:
            linked_user, outcome = await db.awrite(
                lambda conn: user_repo.link_provider(
                    conn,
                    user_id=identity.user_id,
                    provider=provider,
                    provider_sub=provider_sub,
                    email=email,
                    email_verified=email_verified,
                    now_iso=to_iso_kst(now_kst()),
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception("%s 계정 연결 실패", provider)
            response = _popup_close_html(ok=False, next_path="/mypage", linked="error")
            _clear_state_cookie(response)
            return response
        response = _popup_close_html(
            ok=outcome != "conflict", name=linked_user["display_name"], next_path="/mypage", linked=outcome
        )
        _clear_state_cookie(response)
        return response  # 세션 쿠키는 그대로(현재 계정 유지)

    # 2026-09-20 대표 지시 — "약관 동의 안 하면 가입이 안 돼야". 신규 사용자(같은 provider sub 도,
    # 검증된 같은 이메일 계정도 없음)는 여기서 계정·세션을 만들지 않는다. provider 가 증명한 신원을
    # 15분짜리 서명 쿠키로 맡기고, /auth/signup/complete 가 동의+표시 이름을 받은 뒤에야 만든다.
    try:
        def _find_existing(conn):
            found = user_repo.get_by_provider_sub(conn, provider=provider, provider_sub=provider_sub)
            if found is None and email and email_verified:
                found = user_repo.get_by_email(conn, email)
            return found

        existing = await db.aread(_find_existing)
    except Exception:  # noqa: BLE001
        logger.exception("%s 로그인 계정 조회 실패", provider)
        response = _popup_close_html(ok=False, next_path=next_path)
        _clear_state_cookie(response)
        return response
    if existing is None:
        pending = auth.issue_pending_signup(
            {
                "provider": provider,
                "sub": provider_sub,
                "email": email,
                "email_verified": bool(email_verified),
                "name": display_name,
            }
        )
        response = _popup_close_html(ok=True, name=display_name, is_new=True, next_path=next_path)
        _clear_state_cookie(response)
        response.set_cookie(
            key=SIGNUP_COOKIE_NAME,
            value=pending,
            max_age=15 * 60,
            httponly=True,
            secure=auth.cookie_secure,
            samesite="lax",
            path=STATE_COOKIE_PATH,
        )
        return response

    try:
        user = await db.awrite(
            lambda conn: user_repo.upsert_login(
                conn,
                provider=provider,
                provider_sub=provider_sub,
                email=email,
                email_verified=email_verified,
                default_display_name=display_name,
                now_iso=to_iso_kst(now_kst()),
            )
        )
    except Exception:  # noqa: BLE001 — DB 장애로 팝업이 무한 로딩되지 않게 실패로 수렴
        logger.exception("%s 로그인 계정 upsert 실패", provider)
        response = _popup_close_html(ok=False, next_path=next_path)
        _clear_state_cookie(response)
        return response

    token, _exp = auth.issue_token(user_id=user["id"], email=user["email"], epoch=user_repo.session_epoch_of(user))
    # 팝업엔 provider 원본 이름이 아니라 **DB의 현재 display_name**을 돌려준다 — 재로그인한
    # 사용자라면 이전에 직접 정한 이름이 그대로 뜬다(매번 원본 이름으로 되돌아가지 않음).
    #
    # is_new 판정 — upsert_login이 신규/기존 여부를 별도 플래그로 돌려주지 않아, created_at
    # == last_login_at(초 단위)로 판정한다. 신규 생성 시 두 값이 같은 now_iso로 함께
    # 채워지고(user_repo.py INSERT 참고), 재로그인부터는 last_login_at만 갱신되어 반드시
    # created_at보다 뒤가 된다 — 사람이 브라우저 팝업+버튼 클릭을 1초 안에 두 번 왕복할 수
    # 없으므로 초 단위 비교로 충분하다.
    # 신규는 위에서 가입 보류로 빠졌으므로 여기는 항상 기존 사용자(재로그인 또는 이메일 통합).
    response = _popup_close_html(ok=True, name=user["display_name"], is_new=False, next_path=next_path)
    _clear_state_cookie(response)
    _set_session_cookie(response, auth, token)
    return response


@router.get("/google/callback")
async def google_callback(request: Request, code: str | None = None, state: str | None = None):
    auth = get_user_auth()
    cookie_nonce = request.cookies.get(STATE_COOKIE_NAME)
    next_path = auth.verify_state(state, cookie_nonce=cookie_nonce)
    if next_path is None:
        logger.warning("구글 콜백 state 검증 실패(서명/만료/nonce 불일치 구분 안 함)")
        response = _popup_close_html(ok=False)
        _clear_state_cookie(response)
        return response
    if not code:
        response = _popup_close_html(ok=False, next_path=next_path)
        _clear_state_cookie(response)
        return response

    try:
        tokens = await google_exchange_code(code)
        access_token = tokens.get("access_token")
        if not access_token:
            raise GoogleOAuthError("no access_token in response")
        userinfo = await google_fetch_userinfo(access_token)
    except GoogleOAuthError as exc:
        logger.warning("구글 로그인 실패: %s", exc)
        response = _popup_close_html(ok=False, next_path=next_path)
        _clear_state_cookie(response)
        return response

    email = (userinfo.get("email") or "").strip() or None
    google_sub = (userinfo.get("sub") or "").strip()
    # email_verified가 명시적으로 true인 이메일만 계정 통합에 사용한다(누락도 거부).
    # 값 누락 또는 문자열 "true"를 인증 완료로 승격하지 않는다.
    if not email or not google_sub or userinfo.get("email_verified") is not True:
        logger.warning("구글 로그인 실패: 이메일/sub 없음 또는 이메일 미검증")
        response = _popup_close_html(ok=False, next_path=next_path)
        _clear_state_cookie(response)
        return response

    raw_name = (userinfo.get("name") or "").strip()
    # 구글은 여기까지 왔다는 것 자체가 "미검증으로 거부"를 통과했다는 뜻이라
    # email_verified=True로 계정 통합 판정에 넘긴다(user_repo.upsert_login 참고).
    return await _complete_oauth_login(
        request=request,
        provider="google",
        provider_sub=google_sub,
        email=email,
        email_verified=True,
        raw_name=raw_name,
        next_path=next_path,
    )


@router.get("/kakao/callback")
async def kakao_callback(request: Request, code: str | None = None, state: str | None = None):
    auth = get_user_auth()
    cookie_nonce = request.cookies.get(STATE_COOKIE_NAME)
    next_path = auth.verify_state(state, cookie_nonce=cookie_nonce)
    if next_path is None:
        logger.warning("카카오 콜백 state 검증 실패(서명/만료/nonce 불일치 구분 안 함)")
        response = _popup_close_html(ok=False)
        _clear_state_cookie(response)
        return response
    if not code:
        response = _popup_close_html(ok=False, next_path=next_path)
        _clear_state_cookie(response)
        return response

    try:
        tokens = await kakao_exchange_code(code)
        access_token = tokens.get("access_token")
        if not access_token:
            raise KakaoOAuthError("no access_token in response")
        userinfo = await kakao_fetch_userinfo(access_token)
    except KakaoOAuthError as exc:
        logger.warning("카카오 로그인 실패: %s", exc)
        response = _popup_close_html(ok=False, next_path=next_path)
        _clear_state_cookie(response)
        return response

    kakao_sub = str(userinfo.get("id") or "").strip()
    if not kakao_sub:
        logger.warning("카카오 로그인 실패: id 없음")
        response = _popup_close_html(ok=False, next_path=next_path)
        _clear_state_cookie(response)
        return response

    # 카카오는 이메일 동의가 선택이라 kakao_account 자체가 없거나 email 필드가 없을 수
    # 있다(구글과 다른 점) — 그래도 로그인은 성공으로 처리한다(계정 통합만 못 할 뿐).
    kakao_account = userinfo.get("kakao_account") or {}
    email = (kakao_account.get("email") or "").strip() or None
    # 계정 통합 규칙의 핵심 방어선 — is_email_verified가 명시적으로 true일 때만 신뢰한다.
    # false거나 필드 자체가 없으면(동의 안 함) 통합하지 않고 새 계정으로 떨어진다
    # (user_repo.py 모듈 docstring "계정 통합 규칙" 참고 — 검증 안 된 이메일로 통합을
    # 허용하면 남의 이메일만 알아도 계정을 가로챌 수 있게 된다).
    email_verified = kakao_account.get("is_email_verified") is True
    raw_name = ((kakao_account.get("profile") or {}).get("nickname") or "").strip()

    return await _complete_oauth_login(
        request=request,
        provider="kakao",
        provider_sub=kakao_sub,
        email=email,
        email_verified=email_verified,
        raw_name=raw_name,
        next_path=next_path,
    )


@router.get("/providers")
async def auth_providers():
    """설정된 로그인 방식(2026-09-20). 프론트가 설정 안 된 provider 버튼을 숨긴다. 비밀값 없음."""
    auth = get_user_auth()
    return {"google": auth.google_enabled, "kakao": auth.kakao_enabled, "naver": auth.naver_enabled}


@router.get("/naver/login")
async def naver_login(next: str = Query(default="/"), link: bool = Query(default=False)):
    """네이버 로그인 시작(2026-09-20). 설정이 없으면 404 — 프론트가 버튼을 숨긴다."""
    if link:
        next = LINK_NEXT
    auth = get_user_auth()
    if not auth.naver_enabled:
        return error_response(404, "NOT_FOUND", "네이버 로그인이 설정되지 않았습니다.")
    return _start_oauth_login(next_path=next, authorize_url_builder=naver_authorize_url)


@router.get("/naver/callback")
async def naver_callback(request: Request, code: str | None = None, state: str | None = None):
    auth = get_user_auth()
    cookie_nonce = request.cookies.get(STATE_COOKIE_NAME)
    next_path = auth.verify_state(state, cookie_nonce=cookie_nonce)
    if next_path is None:
        logger.warning("네이버 콜백 state 검증 실패")
        response = _popup_close_html(ok=False)
        _clear_state_cookie(response)
        return response
    if not code or not state:
        response = _popup_close_html(ok=False, next_path=next_path)
        _clear_state_cookie(response)
        return response

    try:
        tokens = await naver_exchange_code(code, state)
        access_token = tokens.get("access_token")
        if not access_token:
            raise NaverOAuthError("no access_token in response")
        userinfo = await naver_fetch_userinfo(access_token)
    except NaverOAuthError as exc:
        logger.warning("네이버 로그인 실패: %s", exc)
        response = _popup_close_html(ok=False, next_path=next_path)
        _clear_state_cookie(response)
        return response

    naver_sub = str(userinfo.get("id") or "").strip()
    if not naver_sub:
        logger.warning("네이버 로그인 실패: id 없음")
        response = _popup_close_html(ok=False, next_path=next_path)
        _clear_state_cookie(response)
        return response

    # 네이버의 email 은 "연락처 이메일"이라 계정 통합 기준(검증된 이메일)으로는 쓰지 않는다 —
    # 보안검토 K-C1(미검증 이메일 자동 통합 = 계정 탈취) 원칙. 같은 사람의 구글/카카오 계정과 묶는 건
    # 마이페이지 "로그인 연결"(두 provider 모두 로그인으로 증명)로 한다. 이메일은 표시 이름 폴백에만.
    email = (userinfo.get("email") or "").strip() or None
    raw_name = (userinfo.get("nickname") or userinfo.get("name") or "").strip()

    return await _complete_oauth_login(
        request=request,
        provider="naver",
        provider_sub=naver_sub,
        email=email,
        email_verified=False,
        raw_name=raw_name,
        next_path=next_path,
    )


@router.post("/logout")
async def logout(request: Request):
    """쿠키 삭제 + **users.session_epoch +1** (2026-09-14) — 이 계정으로 발급된 세션 토큰이 모든 기기에서
    즉시 무효가 된다. 서명 토큰이라 서버가 끊을 수단이 없던 한계(보안검토 M-2) 해소."""
    auth = get_user_auth()
    identity = auth.verify_token(request.cookies.get(auth.cookie_name)) if auth.enabled else None
    if identity is not None:
        db = get_database()
        await db.awrite(lambda conn: user_repo.bump_session_epoch(conn, user_id=identity.user_id))
    response = Response(status_code=204)
    response.delete_cookie(
        key=auth.cookie_name,
        path="/",
        httponly=True,
        secure=auth.cookie_secure,
        samesite="lax",
    )
    return response


@router.get("/me", response_model=UserSessionResponse)
async def me(request: Request, response: Response):
    """프론트 가드용. 유효한 세션이면 표시 이름, 아니면 authenticated:false(401 아님 —
    비로그인은 실패가 아니라 정상 상태다).

    2026-09-04(대표 C안) — **슬라이딩 세션**: 프론트가 페이지 부팅마다 이걸 부르므로
    (authStorage.syncSessionFromServer) 여기서 매번 쿠키를 새로 발급해 만료를 "지금+TTL" 로
    민다. 쓰는 동안은 안 풀리고, TTL(기본 24h) 동안 안 들어오면 풀린다.
    QA(2026-09-05 P1): 처음엔 "남은 수명 절반 아래일 때만" 갱신했는데, 그러면 로그인 11시간째
    이용자가 13시간 뒤 풀려 방침의 "마지막 이용 후 24시간" 과 어긋났다 → 호출마다 갱신.

    2026-08-17 보안검토 m-4 — email은 응답에 담지 않는다. 프론트(authStorage.ts)가 쓰는
    값은 표시 이름뿐이라, 최소노출 원칙상 필요 없는 개인정보를 API 응답에 얹지 않는다."""
    auth = get_user_auth()
    identity = auth.verify_token(request.cookies.get(auth.cookie_name)) if auth.enabled else None
    if identity is None:
        return UserSessionResponse(authenticated=False)
    db = get_database()
    user = await db.aread(lambda conn: user_repo.get_by_id(conn, identity.user_id))
    if user is None:
        # 세션은 유효한데 계정 행이 사라진 상태(수동 DB 조작 등) — 비로그인으로 취급.
        return UserSessionResponse(authenticated=False)
    if user_repo.session_epoch_of(user) != identity.epoch:
        # 2026-09-14: 로그아웃 뒤 남은 토큰(다른 기기 포함) → 비로그인
        return UserSessionResponse(authenticated=False)
    token, _ = auth.issue_token(user_id=identity.user_id, email=identity.email, epoch=identity.epoch)
    _set_session_cookie(response, auth, token)
    return UserSessionResponse(
        authenticated=True,
        name=user["display_name"],
        terms_agreed=_terms_agreed(user),
        providers=user_repo.linked_providers(user),
    )


@router.delete("/me", status_code=204)
async def delete_account(request: Request):
    """계정 삭제(탈퇴, 2026-08-17 QA C-4 대응) — users 행을 즉시 삭제하고 세션 쿠키도
    지운다. legal-counsel 권고("이용자 권리")와 /privacy §8이 안내하는 삭제 수단의 실제
    구현. 게시물(리뷰 등)은 nickname을 텍스트로 이미 복사해 저장하므로 함께 지워지지
    않는다 — /privacy §4가 설명하는 기존 동작 그대로다."""
    _auth, identity = _require_session(request)
    db = get_database()
    user = await db.aread(lambda conn: user_repo.get_by_id(conn, identity.user_id))
    if user is None or user_repo.session_epoch_of(user) != identity.epoch:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    await db.awrite(lambda conn: user_repo.delete_account(conn, user_id=identity.user_id))
    response = Response(status_code=204)
    response.delete_cookie(
        key=_auth.cookie_name,
        path="/",
        httponly=True,
        secure=_auth.cookie_secure,
        samesite="lax",
    )
    return response


@router.post("/signup/complete", response_model=UserSessionResponse)
async def signup_complete(request: Request, body: SignupCompleteRequest, response: Response):
    """약관 동의 + 표시 이름 → 이때 비로소 계정을 만들고 세션을 발급한다(2026-09-20).
    가입 보류 쿠키(콜백이 신규 사용자에게만 심음)가 없거나 만료·변조면 401 — 다시 로그인부터."""
    auth = get_user_auth()
    pending = auth.verify_pending_signup(request.cookies.get(SIGNUP_COOKIE_NAME)) if auth.enabled else None
    if not pending:
        return error_response(401, "SIGNUP_EXPIRED", "가입 정보가 만료됐어요. 다시 로그인해 주세요.")
    if body.terms_version != TERMS_VERSION:
        return error_response(400, "TERMS_VERSION_MISMATCH", "약관 버전이 바뀌었어요. 화면을 새로고침해 주세요.")
    cleaned = clean_user_text(body.display_name, max_chars=NICKNAME_MAX)
    if not cleaned:
        return error_response(400, "INVALID_NAME", "표시 이름을 입력해주세요.")
    if is_impersonating_staff(cleaned):
        return error_response(400, "NAME_RESERVED", "운영자로 오인될 수 있는 이름은 쓸 수 없어요.")
    provider = pending.get("provider")
    if provider not in ("google", "kakao", "naver") or not pending.get("sub"):
        return error_response(401, "SIGNUP_EXPIRED", "가입 정보가 올바르지 않아요. 다시 로그인해 주세요.")
    now_iso = to_iso_kst(now_kst())
    db = get_database()

    def _tx(conn):
        user = user_repo.upsert_login(
            conn,
            provider=provider,  # type: ignore[arg-type]
            provider_sub=str(pending["sub"]),
            email=pending.get("email"),
            email_verified=bool(pending.get("email_verified")),
            default_display_name=cleaned,
            now_iso=now_iso,
        )
        user = user_repo.update_display_name(conn, user_id=user["id"], display_name=cleaned) or user
        return user_repo.set_terms_agreed(conn, user_id=user["id"], version=TERMS_VERSION, now_iso=now_iso) or user

    user = await db.awrite(_tx)
    token, _ = auth.issue_token(user_id=user["id"], email=user["email"], epoch=user_repo.session_epoch_of(user))
    _set_session_cookie(response, auth, token)
    response.delete_cookie(SIGNUP_COOKIE_NAME, path=STATE_COOKIE_PATH)
    return UserSessionResponse(
        authenticated=True,
        name=user["display_name"],
        terms_agreed=_terms_agreed(user),
        providers=user_repo.linked_providers(user),
    )


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
    current = await db.aread(lambda conn: user_repo.get_by_id(conn, identity.user_id))
    if current is None or user_repo.session_epoch_of(current) != identity.epoch:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    user = await db.awrite(
        lambda conn: user_repo.update_display_name(conn, user_id=identity.user_id, display_name=cleaned)
    )
    if user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    # 2026-09-14 — 첫 로그인의 "표시 이름 정하기" 단계에서 약관·처리방침 동의를 함께 받는다.
    if body.terms_version == TERMS_VERSION:
        user = await db.awrite(
            lambda conn: user_repo.set_terms_agreed(
                conn, user_id=identity.user_id, version=TERMS_VERSION, now_iso=to_iso_kst(now_kst())
            )
        ) or user
    return UserSessionResponse(
        authenticated=True,
        name=user["display_name"],
        terms_agreed=_terms_agreed(user),
        providers=user_repo.linked_providers(user),
    )


@router.post("/consent", response_model=UserSessionResponse)
async def record_consent(request: Request, body: ConsentRequest):
    """기존 회원·약관 개정 후 재동의(ConsentModal.tsx). 현재 버전만 받는다."""
    _auth, identity = _require_session(request)
    if body.terms_version != TERMS_VERSION:
        raise HTTPException(status_code=400, detail="약관 버전이 맞지 않아요. 새로고침 후 다시 시도해주세요.")
    db = get_database()
    current = await db.aread(lambda conn: user_repo.get_by_id(conn, identity.user_id))
    if current is None or user_repo.session_epoch_of(current) != identity.epoch:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    user = await db.awrite(
        lambda conn: user_repo.set_terms_agreed(
            conn, user_id=identity.user_id, version=TERMS_VERSION, now_iso=to_iso_kst(now_kst())
        )
    )
    return UserSessionResponse(
        authenticated=True, name=(user or current)["display_name"], terms_agreed=_terms_agreed(user)
    )


__all__ = ("router",)
