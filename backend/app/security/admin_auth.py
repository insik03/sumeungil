"""관리자 인증 프리미티브 — 표준 라이브러리만 사용(신규 의존성 0). 계약 부록 T.

## 이 모듈이 존재하는 이유
사용자 "로그인"(닉네임 + localStorage)은 **인증이 아니다**(부록 R.0). 관리자는 그것과
**완전히 분리된** 경로여야 한다 — 닉네임을 무엇으로 정하든 관리자가 될 수 없어야 한다.
그래서 관리자 인증은 이 모듈 하나에만 존재하고, 리뷰/공유(부록 R) 코드와 어떤 값도
공유하지 않는다(`device_id` 는 관리자 판정에 절대 쓰이지 않는다).

## 계정 테이블이 없는 이유
운영자는 **1명(대표)** 이다. 계정 테이블·비밀번호 재설정 메일·세션 저장소를 만들면 공격면과
운영 부담만 늘어난다. 대신 `.env` 의 `ADMIN_PASSWORD_HASH` **하나**가 유일한 진실이다.

## 저장 형식 (env 에 들어가는 값)
    scrypt$<n>$<r>$<p>$<b64url salt>$<b64url digest>
- **평문 비밀번호를 env 에 두지 않는다.** 대표가 `scripts/make_admin_hash.py` 를 자기 PC 에서
  돌려 이 문자열만 서버 `.env` 에 붙여넣는다.
- `hashlib.scrypt` 는 메모리 하드 KDF 다(bcrypt/argon2 라이브러리를 새로 들이지 않아도 된다).
- 비교는 `hmac.compare_digest` — 바이트 단위 조기 반환이 없어 타이밍 공격에 강하다.

## 세션 토큰
JWT 라이브러리를 쓰지 않는다. 필요한 것은 "서버가 서명한 만료시각" 뿐이다:
    v1.<b64url payload>.<b64url HMAC-SHA256>
payload = `<만료 epoch>:<비밀번호 해시 지문 8자>`
지문을 넣은 이유: **비밀번호를 바꾸면 기존 세션이 전부 무효**가 된다(유출 대응 절차가
"해시 교체 + 재시작" 하나로 끝난다).

## 절대 규칙
- 비밀번호·해시·세션 토큰을 **로그에 남기지 않는다.** 실패 로그는 `ip_hash` + 시각만.
- 기본 비밀번호·백도어·하드코딩 토큰을 두지 않는다. 해시 미설정 = 관리자 기능 **전면 비활성**.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import secrets
import time
import unicodedata
from dataclasses import dataclass

logger = logging.getLogger("sumeungil.security.admin")

SCHEME = "scrypt"

# --- scrypt 파라미터 (해시 생성 시 기본값. 검증은 해시 문자열에 적힌 값을 따른다) -----------
# n=2^14, r=8, p=1 → 약 16MB 메모리 · 개발 PC 기준 0.05~0.15초. 로그인 1회짜리 경로라
# 충분히 비싸고, 로그인 5회/분 제한이 있어 서버 부하로 이어지지 않는다.
DEFAULT_N = 2 ** 14
DEFAULT_R = 8
DEFAULT_P = 1
DKLEN = 32
SALT_BYTES = 16

# 손상되거나 조작된 env 값으로 프로세스 메모리를 터뜨리지 않기 위한 상한(파싱 단계에서 거부).
MAX_N = 2 ** 20
MAX_R = 32
MAX_P = 16

# 비밀번호 입력 상한 — scrypt 는 입력 길이에 거의 비례하지 않지만, 무제한 바디를 KDF 에
# 넘기지 않는다는 원칙(라우터 스키마에서도 같은 값을 강제한다).
PASSWORD_MAX_LEN = 512
# 해시 생성 스크립트에서 강제하는 최소 길이(검증 시에는 강제하지 않는다 — 이미 만들어진
# 해시의 원본 길이를 서버는 알 수 없다).
PASSWORD_MIN_LEN = 12

TOKEN_VERSION = "v1"
DEFAULT_SESSION_TTL_SEC = 4 * 60 * 60  # 4시간(계약 부록 T, Mn-1로 8h→4h 단축)
DEFAULT_COOKIE_NAME = "sumeungil_admin"

# HKDF-extract 유사 도메인 분리 라벨. 같은 시크릿에서 용도별로 다른 키를 파생한다.
_KEY_LABEL = b"sumeungil.admin.session.v1"
_IP_LABEL = b"ip:"
_ACTOR_LABEL = b"dev:"


# --- base64url (패딩 없음) ------------------------------------------------------


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


# --- 비밀번호 해시 ---------------------------------------------------------------


@dataclass(frozen=True)
class ScryptParams:
    n: int
    r: int
    p: int
    salt: bytes
    digest: bytes

    @property
    def maxmem(self) -> int:
        """OpenSSL 이 요구하는 메모리 상한을 파라미터에서 계산한다.

        기본값(0)은 OpenSSL 기본 32MB 라 n 을 조금만 올려도 `ValueError` 가 난다.
        여기서 명시적으로 주면 대표가 더 강한 파라미터로 해시를 만들어도 그대로 동작한다.
        """
        return 128 * self.r * (self.n + self.p + 2) + (1 << 20)


def parse_password_hash(raw: str | None) -> ScryptParams | None:
    """`scrypt$n$r$p$salt$digest` → 파라미터. 형식이 조금이라도 어긋나면 None.

    None 은 곧 **관리자 기능 비활성**을 의미한다 — 애매하게 통과시키지 않는다.
    """
    if not raw:
        return None
    parts = raw.strip().split("$")
    if len(parts) != 6 or parts[0] != SCHEME:
        return None
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = _b64d(parts[4])
        digest = _b64d(parts[5])
    except (ValueError, TypeError, binascii.Error):
        return None
    if n < 2 or n > MAX_N or (n & (n - 1)) != 0:  # n 은 1보다 큰 2의 거듭제곱이어야 한다
        return None
    if not (1 <= r <= MAX_R) or not (1 <= p <= MAX_P):
        return None
    if not (8 <= len(salt) <= 64) or not (16 <= len(digest) <= 64):
        return None
    return ScryptParams(n=n, r=r, p=p, salt=salt, digest=digest)


def normalize_password(password: str) -> str:
    """유니코드 NFC 정규화 — **해시 생성과 검증이 반드시 같은 함수를 쓴다.**

    한글은 조합형(NFD)과 완성형(NFC)의 바이트열이 다르다. OS·입력기에 따라 같은 글자를
    쳐도 다른 바이트가 오므로, 정규화를 한쪽에만 넣으면 "분명히 맞게 쳤는데 로그인 실패"가
    난다. 영문·숫자 비밀번호에서는 아무 영향이 없다(NFC 가 항등이다).
    """
    return unicodedata.normalize("NFC", password)


def _derive(password: str, params: ScryptParams) -> bytes:
    return hashlib.scrypt(
        normalize_password(password).encode("utf-8"),
        salt=params.salt,
        n=params.n,
        r=params.r,
        p=params.p,
        dklen=len(params.digest),
        maxmem=params.maxmem,
    )


def make_password_hash(
    password: str, *, n: int = DEFAULT_N, r: int = DEFAULT_R, p: int = DEFAULT_P
) -> str:
    """해시 생성(스크립트 전용). 서버 런타임은 이 함수를 호출하지 않는다."""
    salt = secrets.token_bytes(SALT_BYTES)
    params = ScryptParams(n=n, r=r, p=p, salt=salt, digest=b"\x00" * DKLEN)
    digest = _derive(password, params)
    return f"{SCHEME}${n}${r}${p}${_b64e(salt)}${_b64e(digest)}"


def verify_password(password: str, params: ScryptParams) -> bool:
    """상수시간 비교. 예외(메모리 부족 등)는 실패로 수렴시킨다(스택트레이스 미노출)."""
    if not password or len(password) > PASSWORD_MAX_LEN:
        return False
    try:
        candidate = _derive(password, params)
    except (ValueError, MemoryError):
        logger.error("관리자 비밀번호 검증 실패 — scrypt 파라미터를 확인하세요(값은 로그하지 않음)")
        return False
    return hmac.compare_digest(candidate, params.digest)


# --- 세션 토큰 ------------------------------------------------------------------


def derive_signing_key(*, password_hash: str, session_secret: str | None) -> bytes:
    """서명 키.

    우선순위: `ADMIN_SESSION_SECRET` → `JWT_SECRET_KEY` → **비밀번호 해시에서 파생**.
    셋 다 서버 `.env` 안의 값이므로 보안 수준은 같다. 파생을 폴백으로 둔 이유는 대표가
    설정해야 할 키를 하나로 줄이기 위해서다(해시만 넣으면 바로 동작한다).
    프로세스마다 랜덤 키를 만들지 않는 이유: 재시작할 때마다 로그아웃되기 때문.
    """
    base = (session_secret or "").strip() or password_hash.strip()
    return hmac.new(_KEY_LABEL, base.encode("utf-8"), hashlib.sha256).digest()


def _fingerprint(password_hash: str) -> str:
    """비밀번호 해시의 짧은 지문. 해시가 바뀌면 기존 세션 토큰이 전부 무효가 된다."""
    return hashlib.sha256(password_hash.strip().encode("utf-8")).hexdigest()[:8]


class AdminAuth:
    """설정에서 조립되는 관리자 인증 핸들(프로세스당 1개, `deps.get_admin_auth`).

    `enabled` 가 False 면 이 객체는 어떤 요청도 통과시키지 않는다. main.py 는 그 경우
    라우터 자체를 등록하지 않아 `/api/v1/admin/*` 이 존재하지 않는 경로가 된다(404).
    """

    def __init__(
        self,
        *,
        password_hash: str | None,
        session_secret: str | None = None,
        session_ttl_sec: int = DEFAULT_SESSION_TTL_SEC,
        cookie_name: str = DEFAULT_COOKIE_NAME,
        cookie_secure: bool = True,
    ) -> None:
        self._raw_hash = (password_hash or "").strip()
        self._params = parse_password_hash(self._raw_hash)
        self.cookie_name = cookie_name
        self.cookie_secure = cookie_secure
        self.session_ttl_sec = max(60, int(session_ttl_sec))
        # 형식이 틀린 값을 넣어놓고 "설정했다"고 착각하는 상황을 로그로 잡아준다(값은 미노출).
        self.misconfigured = bool(self._raw_hash) and self._params is None
        if self._params is not None:
            self._key = derive_signing_key(
                password_hash=self._raw_hash, session_secret=session_secret
            )
            self._fp = _fingerprint(self._raw_hash)
        else:
            self._key = b""
            self._fp = ""

    @property
    def enabled(self) -> bool:
        return self._params is not None

    # --- 로그인 ----------------------------------------------------------------

    def verify_password(self, password: str) -> bool:
        if self._params is None:
            return False
        return verify_password(password, self._params)

    # --- 토큰 ------------------------------------------------------------------

    def issue_token(
        self,
        *,
        now: int | None = None,
        ttl_sec: int | None = None,
        operator: str = "",
    ) -> tuple[str, int]:
        """(토큰, 만료 epoch). `ttl_sec` 은 검증 스크립트가 만료 토큰을 만들 때만 쓴다.

        `operator` 는 관리자 **표시 이름**(부록 V). 세 명이 같은 비밀번호를 공유하므로
        "누가 지웠는지" 를 남기려면 이름이 필요한데, 이 값을 요청마다 받으면 클라이언트가
        마음대로 바꿀 수 있다. 그래서 로그인 시점에 확정해 **서명 안쪽 페이로드에 넣는다** —
        쿠키를 뜯어 이름만 바꾸면 서명이 깨져 세션 자체가 무효가 된다.

        보안 경계가 아니라 **책임 추적 장치**임을 분명히 해둔다. 비밀번호를 아는 세 사람은
        서로의 이름을 고를 수 있다(자기 신고 방식). 악의를 막는 것이 목적이 아니라
        실수를 되짚을 수 있게 하는 것이 목적이다.
        """
        if self._params is None:
            raise RuntimeError("admin auth disabled")  # 도달 불가(라우터 미등록)
        issued = int(time.time()) if now is None else int(now)
        ttl = self.session_ttl_sec if ttl_sec is None else int(ttl_sec)
        exp = issued + ttl
        # operator 를 b64 로 감싸는 이유: 이름에 ':' 가 들어와도 파싱이 어긋나지 않게 한다.
        payload = f"{exp}:{self._fp}:{_b64e((operator or '').encode('utf-8'))}".encode("utf-8")
        body = f"{TOKEN_VERSION}.{_b64e(payload)}"
        sig = hmac.new(self._key, body.encode("ascii"), hashlib.sha256).digest()
        return f"{body}.{_b64e(sig)}", exp

    def _decode_token(self, token: str | None, *, now: int | None = None) -> tuple[int, str] | None:
        """서명·지문·만료를 모두 통과하면 (만료 epoch, 표시 이름). 아니면 None."""
        if self._params is None or not token:
            return None
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != TOKEN_VERSION:
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
            segments = _b64d(parts[1]).decode("utf-8").split(":", 2)
            # 이름 도입(부록 V) 전에 발급된 2단 토큰도 그대로 받는다 — 배포 순간에
            # 로그인해 있던 세션이 통째로 끊기지 않게 하기 위한 호환 처리다.
            if len(segments) == 2:
                exp_str, fp, operator_b64 = segments[0], segments[1], ""
            elif len(segments) == 3:
                exp_str, fp, operator_b64 = segments
            else:
                return None
            exp = int(exp_str)
            operator = _b64d(operator_b64).decode("utf-8") if operator_b64 else ""
        except (ValueError, TypeError, UnicodeDecodeError, binascii.Error):
            return None
        # 비밀번호가 교체되면 지문이 달라져 과거 세션이 즉시 무효가 된다.
        if not hmac.compare_digest(fp, self._fp):
            return None
        current = int(time.time()) if now is None else int(now)
        if exp <= current:
            return None
        return exp, operator

    def verify_token(self, token: str | None, *, now: int | None = None) -> int | None:
        """유효하면 만료 epoch, 아니면 None. 실패 사유는 구분해 알려주지 않는다."""
        decoded = self._decode_token(token, now=now)
        return None if decoded is None else decoded[0]

    def token_operator(self, token: str | None, *, now: int | None = None) -> str:
        """토큰에 서명돼 있는 표시 이름. 유효하지 않거나 이름이 없으면 빈 문자열."""
        decoded = self._decode_token(token, now=now)
        return "" if decoded is None else decoded[1]

    # --- 가명화 해시 ------------------------------------------------------------

    def ip_hash(self, ip: str | None) -> str:
        """감사 로그·실패 로그용. **원본 IP 를 저장하지 않는다.**

        키가 붙은 HMAC 이라 서버 시크릿 없이는 후보 IP 대입으로도 역산할 수 없다.
        """
        if not self._key:
            return ""
        raw = (ip or "unknown").encode("utf-8")
        return hmac.new(self._key, _IP_LABEL + raw, hashlib.sha256).hexdigest()[:16]

    def actor_hash(self, device_id: str | None) -> str:
        """관리자 화면에서 "같은 사람이 쓴 글"을 묶어 보기 위한 8자 지문.

        `device_id` 원본은 **관리자에게도** 내보내지 않는다(부록 R.0 불변식). 이 값은
        키가 붙은 HMAC 의 앞 8자라 원본을 복원할 수 없다.
        """
        if not self._key or not device_id:
            return ""
        return hmac.new(
            self._key, _ACTOR_LABEL + device_id.encode("utf-8"), hashlib.sha256
        ).hexdigest()[:8]


__all__ = (
    "AdminAuth",
    "DEFAULT_COOKIE_NAME",
    "DEFAULT_SESSION_TTL_SEC",
    "PASSWORD_MAX_LEN",
    "PASSWORD_MIN_LEN",
    "ScryptParams",
    "make_password_hash",
    "normalize_password",
    "parse_password_hash",
    "verify_password",
)
