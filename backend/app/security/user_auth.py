"""구글 로그인 사용자 세션 — admin_auth.py와 동일한 "서버가 서명한 만료시각" 방식.

## 이 모듈이 존재하는 이유
데모 닉네임 로그인(§R.0)을 완전히 대체하는 임시 구글 로그인(2026-08-17, 대표 지시)의
세션 저장소.

## 계정 테이블과의 관계 (2026-08-17 갱신)
처음엔 계정 테이블 없이 이메일·이름을 토큰에 직접 담았다. 그런데 그러면 사용자가 표시
이름을 바꿔도 **다음 로그인에서 토큰이 다시 발급되며 구글 원본 이름으로 되돌아가는**
문제가 있었다(대표 지적, "로그인 붙였으니 DB도 그에 맞게"). 그래서 `users` 테이블
(db/sqlite.py schema_version 4, repositories/user_repo.py)을 두고, **이 모듈은 그
테이블의 정수 id(user_id)만 서명해 나른다** — 이메일은 참고용으로 함께 싣지만, 표시
이름(display_name)은 토큰에 아예 넣지 않고 매 요청마다 DB에서 최신값을 읽는다
(api/auth.py). 그래야 닉네임을 바꾼 즉시 모든 기존 세션에 반영되고, 토큰 재발급도
필요 없다.

## 세션 토큰
JWT 라이브러리를 쓰지 않는다. admin_auth.py의 토큰 스킴을 그대로 재사용한다:
    v1.<b64url payload>.<b64url HMAC-SHA256>
payload = `<만료 epoch>:<user_id>:<b64url(email)>`

admin과 **다른 도메인 라벨**로 서명 키를 파생한다(_KEY_LABEL) — 같은
USER_SESSION_SECRET/JWT_SECRET_KEY를 공유하더라도 사용자 세션 토큰으로 관리자 세션을
위조할 수 없다(반대도 마찬가지).

## 절대 규칙
- 이메일·토큰을 로그에 남기지 않는다.
- 구글 액세스 토큰/리프레시 토큰은 저장하지 않는다(userinfo 조회 1회 쓰고 버림) —
  탈취 시 노출 범위를 세션 토큰(우리 서버 서명, 우리가 언제든 무효화 가능)으로 국한한다.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time
from dataclasses import dataclass

SCHEME_VERSION = "v1"
_KEY_LABEL = b"sumeungil.user.session.v1"

# state 파라미터(OAuth CSRF 방어) 서명 — 세션 토큰과 같은 키에서 다른 라벨로 파생한다.
_STATE_LABEL = b"sumeungil.user.oauth-state.v1"
STATE_TTL_SEC = 10 * 60  # 로그인 시작~구글 리디렉션 왕복이 10분을 넘으면 재시도하게 한다.

EMAIL_MAX_LEN = 254


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


@dataclass(frozen=True)
class UserIdentity:
    user_id: int
    email: str


class UserAuth:
    """구글 로그인 세션 핸들(프로세스당 1개, deps.get_user_auth).

    `enabled`가 False면(GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI 중 하나라도 미설정)
    main.py가 /api/v1/auth/* 라우터 자체를 등록하지 않는다(admin_auth.py와 동일 원칙).
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        session_secret: str,
        session_ttl_sec: int,
        cookie_name: str,
        cookie_secure: bool,
    ) -> None:
        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()
        self.redirect_uri = (redirect_uri or "").strip()
        self.cookie_name = cookie_name
        self.cookie_secure = cookie_secure
        self.session_ttl_sec = max(60, int(session_ttl_sec))
        secret = (session_secret or "").strip()
        self._key = hmac.new(_KEY_LABEL, secret.encode("utf-8"), hashlib.sha256).digest()
        self._state_key = hmac.new(_STATE_LABEL, secret.encode("utf-8"), hashlib.sha256).digest()

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)

    # --- OAuth state(CSRF 방어) ---------------------------------------------------

    def issue_state(self, *, next_path: str, now: int | None = None) -> str:
        """로그인 시작 시 발급 — 구글이 그대로 되돌려주는 값이라 서버가 검증할 수 있어야 한다.

        next_path는 **경로만**(쿼리 없이) 담는다 — 이메일 등 개인정보를 URL에 실어 브라우저
        히스토리·리퍼러·서버 로그에 남기지 않기 위해서다(로그인 완료 후 이메일/이름은 세션
        쿠키로만 전달된다).
        """
        issued = int(time.time()) if now is None else int(now)
        exp = issued + STATE_TTL_SEC
        payload = f"{exp}:{_b64e(next_path.encode('utf-8'))}".encode("utf-8")
        body = f"{SCHEME_VERSION}.{_b64e(payload)}"
        sig = hmac.new(self._state_key, body.encode("ascii"), hashlib.sha256).digest()
        return f"{body}.{_b64e(sig)}"

    def verify_state(self, state: str | None, *, now: int | None = None) -> str | None:
        """유효하면 next_path, 아니면 None(서명 불일치/만료/형식오류 전부 뭉뚱그려 거부)."""
        if not state:
            return None
        parts = state.split(".")
        if len(parts) != 3 or parts[0] != SCHEME_VERSION:
            return None
        body = f"{parts[0]}.{parts[1]}"
        try:
            expected = hmac.new(self._state_key, body.encode("ascii"), hashlib.sha256).digest()
            actual = _b64d(parts[2])
        except (ValueError, TypeError, binascii.Error):
            return None
        if not hmac.compare_digest(expected, actual):
            return None
        try:
            exp_str, next_b64 = _b64d(parts[1]).decode("utf-8").split(":", 1)
            exp = int(exp_str)
            next_path = _b64d(next_b64).decode("utf-8")
        except (ValueError, TypeError, UnicodeDecodeError, binascii.Error):
            return None
        current = int(time.time()) if now is None else int(now)
        if exp <= current:
            return None
        # 오픈 리다이렉트 방지 — 반드시 우리 사이트 안의 경로("/"로 시작, "//"·스킴 없음)만 허용.
        if not next_path.startswith("/") or next_path.startswith("//"):
            return "/"
        return next_path

    # --- 세션 토큰 -------------------------------------------------------------

    def issue_token(self, *, user_id: int, email: str, now: int | None = None) -> tuple[str, int]:
        issued = int(time.time()) if now is None else int(now)
        exp = issued + self.session_ttl_sec
        e = email.strip()[:EMAIL_MAX_LEN]
        payload = f"{exp}:{int(user_id)}:{_b64e(e.encode('utf-8'))}".encode("utf-8")
        body = f"{SCHEME_VERSION}.{_b64e(payload)}"
        sig = hmac.new(self._key, body.encode("ascii"), hashlib.sha256).digest()
        return f"{body}.{_b64e(sig)}", exp

    def verify_token(self, token: str | None, *, now: int | None = None) -> UserIdentity | None:
        if not token:
            return None
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != SCHEME_VERSION:
            return None
        body = f"{parts[0]}.{parts[1]}"
        try:
            expected = hmac.new(self._key, body.encode("ascii"), hashlib.sha256).digest()
            actual = _b64d(parts[2])
        except (ValueError, TypeError, binascii.Error):
            return None
        if not hmac.compare_digest(expected, actual):
            return None
        try:
            exp_str, user_id_str, email_b64 = _b64d(parts[1]).decode("utf-8").split(":", 2)
            exp = int(exp_str)
            user_id = int(user_id_str)
            email = _b64d(email_b64).decode("utf-8")
        except (ValueError, TypeError, UnicodeDecodeError, binascii.Error):
            return None
        current = int(time.time()) if now is None else int(now)
        if exp <= current:
            return None
        return UserIdentity(user_id=user_id, email=email)


__all__ = ("UserAuth", "UserIdentity", "STATE_TTL_SEC")
