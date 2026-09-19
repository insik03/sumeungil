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

## 보안 검토 반영 (2026-08-17, security-engineer 풀검수 — Critical 2건/Major 2건)
- **C-1**: `enabled`가 OAuth 클라이언트 설정만 확인하고 **세션 서명키가 실제로 채워졌는지는
  확인하지 않았다.** `USER_SESSION_SECRET`도 `JWT_SECRET_KEY`도 미설정이면 키가
  `HMAC(_KEY_LABEL, b"")`로 고정되는데, `_KEY_LABEL`은 소스에 공개된 상수라 **누구나 계산
  가능한 값**이 된다 — 임의 user_id로 세션을 위조해 전체 이메일을 열람할 수 있었다.
  `enabled`가 이제 시크릿 존재 여부도 함께 확인한다(admin_auth.py의 `misconfigured` 패턴과
  동일 사상 — "설정 안 하면 없는 기능").
- **M-1**: state가 서버 서명만 증명하고 "이 브라우저가 시작한 로그인"이라는 건 증명하지
  못해(브라우저에 바인딩되지 않고 재사용도 가능) 로그인 CSRF/세션 고정에 열려 있었다.
  이제 `issue_state`가 별도 nonce를 발급하고(HttpOnly 쿠키로 브라우저에 바인딩, 호출부
  책임) `verify_state`가 쿠키값과 state 안의 nonce를 대조한다 — 실질적 1회용·브라우저
  고정이 된다.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass

SCHEME_VERSION = "v2"  # 2026-09-14: payload 에 session_epoch 추가(v1 토큰은 거부 → 1회 재로그인)
_KEY_LABEL = b"sumeungil.user.session.v1"

# state 파라미터(OAuth CSRF 방어) 서명 — 세션 토큰과 같은 키에서 다른 라벨로 파생한다.
_STATE_LABEL = b"sumeungil.user.oauth-state.v1"
STATE_TTL_SEC = 10 * 60  # 로그인 시작~구글 리디렉션 왕복이 10분을 넘으면 재시도하게 한다.
STATE_NONCE_BYTES = 16

EMAIL_MAX_LEN = 254

# 오픈 리다이렉트 방지용 화이트리스트 — "/"로 시작하는 내부 경로만 허용한다(스킴·이중 슬래시·
# 백슬래시·제어문자·과도한 길이를 전부 거부). 현재 next_path는 HTML 앵커 href로만 쓰여
# 당장 악용 경로는 없지만(security-engineer m-1), 향후 실제 리다이렉트로 바뀌었을 때도
# 안전하도록 발급 시점부터 형식을 좁혀둔다.
#
# 주의: 문자 클래스에 "/"가 포함돼 있어 이 정규식 단독으로는 "//evil.com"(스킴-상대
# URL — 브라우저가 프로토콜만 현재 걸로 채워 외부 호스트로 취급)을 걸러내지 못한다
# (2026-08-17 자체 검증 스크립트에서 발견, security-engineer M-1 수정 중 회귀). 그래서
# _is_safe_next_path가 정규식 통과 후에도 "//" 접두를 별도로 다시 거부한다.
_SAFE_PATH_RE = re.compile(r"^/[A-Za-z0-9/_\-.]{0,200}$")


def _is_safe_next_path(next_path: str | None) -> bool:
    if not next_path or not _SAFE_PATH_RE.match(next_path):
        return False
    return not next_path.startswith("//")


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


@dataclass(frozen=True)
class UserIdentity:
    user_id: int
    # 2026-08-17(카카오 추가) — 이메일이 없을 수 있다(카카오는 이메일 동의가 선택이고,
    # 동의해도 미인증 계정이면 애초에 신뢰 안 함 — user_repo.py 계정 통합 규칙 참고).
    email: str | None
    # 토큰 만료 시각(epoch 초). /me 의 슬라이딩 재발급이 "남은 수명"을 계산하는 데 쓴다.
    exp: int = 0
    # 발급 시점의 users.session_epoch. DB 값과 다르면(로그아웃 뒤) 무효 — 호출부가 비교한다.
    epoch: int = 0


class UserAuth:
    """로그인 세션 핸들(프로세스당 1개, deps.get_user_auth) — 구글·카카오 공용.

    `enabled`는 **세션 서명 인프라(시크릿)** 준비 여부만 본다 — provider별 설정 여부는
    `google_enabled`/`kakao_enabled`로 따로 확인한다(2026-08-17 카카오 추가 전에는
    구글 설정까지 `enabled`가 함께 봤었는데, 그러면 "카카오만 설정 안 해도 구글 로그인
    전체가 죽는" 게 돼서 분리했다). `enabled`가 False면 main.py가 /api/v1/auth/* 라우터
    자체를 등록하지 않는다(admin_auth.py와 동일 원칙) — 시크릿 없이는 어떤 provider도
    안전하게 세션을 발급할 수 없으므로 이건 여전히 라우터 전체를 막는 조건이다.
    """

    def __init__(
        self,
        *,
        google_client_id: str,
        google_client_secret: str,
        google_redirect_uri: str,
        kakao_client_id: str,
        kakao_client_secret: str,
        kakao_redirect_uri: str,
        naver_client_id: str = "",
        naver_client_secret: str = "",
        naver_redirect_uri: str = "",
        session_secret: str,
        session_ttl_sec: int,
        cookie_name: str,
        cookie_secure: bool,
    ) -> None:
        self.google_client_id = (google_client_id or "").strip()
        self.google_client_secret = (google_client_secret or "").strip()
        self.google_redirect_uri = (google_redirect_uri or "").strip()
        self.kakao_client_id = (kakao_client_id or "").strip()
        self.kakao_client_secret = (kakao_client_secret or "").strip()
        self.kakao_redirect_uri = (kakao_redirect_uri or "").strip()
        self.naver_client_id = (naver_client_id or "").strip()
        self.naver_client_secret = (naver_client_secret or "").strip()
        self.naver_redirect_uri = (naver_redirect_uri or "").strip()
        self.cookie_name = cookie_name
        self.cookie_secure = cookie_secure
        self.session_ttl_sec = max(60, int(session_ttl_sec))
        secret = (session_secret or "").strip()
        # C-1(2026-08-17 보안검토) — 시크릿이 비어 있으면 이 뒤로도 키 계산 자체는 되지만
        # (빈 문자열도 유효한 HMAC 입력이라 예외가 안 난다) 그 키는 소스에 공개된 _KEY_LABEL
        # 상수만으로 누구나 재현 가능하다. `enabled`가 이 플래그를 봐서 그 상태로는 절대
        # 라우터를 켜지 않는다.
        self._secret_present = bool(secret)
        self._key = hmac.new(_KEY_LABEL, secret.encode("utf-8"), hashlib.sha256).digest()
        self._state_key = hmac.new(_STATE_LABEL, secret.encode("utf-8"), hashlib.sha256).digest()

    @property
    def enabled(self) -> bool:
        """세션 서명 인프라만 본다 — provider 설정 여부와 무관(위 클래스 docstring 참고)."""
        return self._secret_present

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.google_redirect_uri)

    @property
    def kakao_enabled(self) -> bool:
        return bool(self.kakao_client_id and self.kakao_client_secret and self.kakao_redirect_uri)

    @property
    def naver_enabled(self) -> bool:
        return bool(self.naver_client_id and self.naver_client_secret and self.naver_redirect_uri)

    # --- OAuth state(CSRF 방어) ---------------------------------------------------

    def issue_state(self, *, next_path: str, now: int | None = None) -> tuple[str, str]:
        """로그인 시작 시 발급 — (state, nonce)를 돌려준다.

        state는 구글이 그대로 되돌려주는 값(URL 파라미터, 남 눈에 보일 수 있다). nonce는
        호출부(api/auth.py)가 **별도의 HttpOnly 쿠키**로 브라우저에 심어야 한다 — state
        서명 자체는 "우리 서버가 발급했다"만 증명하고 "이 브라우저가 시작한 로그인이다"는
        증명하지 못하므로(M-1, 2026-08-17 보안검토), nonce 쿠키 대조로 브라우저를 묶는다.

        next_path는 **경로만**(쿼리 없이) 담는다 — 이메일 등 개인정보를 URL에 실어 브라우저
        히스토리·리퍼러·서버 로그에 남기지 않기 위해서다(로그인 완료 후 이메일/이름은 세션
        쿠키로만 전달된다). 형식이 안전 경로가 아니면 발급 시점에 "/"로 좁힌다.
        """
        safe_next = next_path if _is_safe_next_path(next_path) else "/"
        nonce = secrets.token_urlsafe(STATE_NONCE_BYTES)
        issued = int(time.time()) if now is None else int(now)
        exp = issued + STATE_TTL_SEC
        payload = (
            f"{exp}:{_b64e(safe_next.encode('utf-8'))}:{_b64e(nonce.encode('utf-8'))}"
        ).encode("utf-8")
        body = f"{SCHEME_VERSION}.{_b64e(payload)}"
        sig = hmac.new(self._state_key, body.encode("ascii"), hashlib.sha256).digest()
        return f"{body}.{_b64e(sig)}", nonce

    def verify_state(
        self, state: str | None, *, cookie_nonce: str | None, now: int | None = None
    ) -> str | None:
        """서명·만료·**쿠키 nonce 일치**가 전부 통과해야 next_path를 돌려준다. 하나라도
        어긋나면 None(사유를 구분해 알려주지 않는다 — 사유가 다르면 탐색 신호가 된다)."""
        if not state or not cookie_nonce:
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
            exp_str, next_b64, nonce_b64 = _b64d(parts[1]).decode("utf-8").split(":", 2)
            exp = int(exp_str)
            next_path = _b64d(next_b64).decode("utf-8")
            nonce = _b64d(nonce_b64).decode("utf-8")
        except (ValueError, TypeError, UnicodeDecodeError, binascii.Error):
            return None
        current = int(time.time()) if now is None else int(now)
        if exp <= current:
            return None
        if not hmac.compare_digest(nonce, cookie_nonce):
            return None
        # 오픈 리다이렉트 방지 — issue_state가 이미 좁혀 발급하지만, 저장/전송 과정에서
        # 조작됐을 가능성을 상정해 검증 시점에도 동일 화이트리스트로 다시 확인한다.
        if not _is_safe_next_path(next_path):
            return "/"
        return next_path

    # --- 세션 토큰 -------------------------------------------------------------

    def issue_token(
        self, *, user_id: int, email: str | None, now: int | None = None, epoch: int = 0
    ) -> tuple[str, int]:
        issued = int(time.time()) if now is None else int(now)
        exp = issued + self.session_ttl_sec
        # 2026-08-17(카카오 추가) — email이 없으면(카카오 미인증/미동의) 빈 문자열로 싣는다.
        # verify_token이 빈 문자열을 다시 None으로 되돌린다 — "" 자체가 유효 이메일이 될
        # 일은 없으므로 이 왕복 변환은 안전하다.
        e = (email or "").strip()[:EMAIL_MAX_LEN]
        payload = f"{exp}:{int(user_id)}:{_b64e(e.encode('utf-8'))}:{int(epoch)}".encode("utf-8")
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
            exp_str, user_id_str, email_b64, epoch_str = _b64d(parts[1]).decode("utf-8").split(":", 3)
            exp = int(exp_str)
            user_id = int(user_id_str)
            email = _b64d(email_b64).decode("utf-8")
            epoch = int(epoch_str)
        except (ValueError, TypeError, UnicodeDecodeError, binascii.Error):
            return None
        current = int(time.time()) if now is None else int(now)
        if exp <= current:
            return None
        return UserIdentity(user_id=user_id, email=email or None, exp=exp, epoch=epoch)


__all__ = ("UserAuth", "UserIdentity", "STATE_TTL_SEC")
