"""관리자 비밀번호 해시 생성기 — **대표(사람)만 실행한다.** 계약 부록 T.

    cd backend && py scripts/make_admin_hash.py

## 이 스크립트가 하는 일
비밀번호를 화면에 보이지 않게(`getpass`) 두 번 입력받아, `.env` 에 넣을 **scrypt 해시 한 줄**을
출력한다. 평문 비밀번호는 파일·로그·터미널 히스토리 어디에도 남지 않는다.

## 왜 사람만 실행하나
AI 에이전트도, 배포 스크립트도 비밀번호를 만들거나 알아서는 안 된다. 서버 코드는 이 스크립트가
만든 해시를 **읽기만** 한다(원본 복원 불가).

## 출력물 취급
출력되는 `ADMIN_PASSWORD_HASH=scrypt$...` 한 줄을 서버의 `deploy/.env` 에 붙여넣고,
`docker compose up -d backend` 로 반영한다. 이 줄은 비밀번호 자체는 아니지만 **검증자(verifier)**
이므로 공개 저장소·채팅에 올리지 않는다.

의존성 없음(표준 라이브러리만). 서버 `.env`(PUBLIC_DATA_API_KEY 등)가 없어도 동작한다 —
`app.config` 를 import 하지 않는다.
"""

from __future__ import annotations

import getpass
import sys
import unicodedata
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.security.admin_auth import (  # noqa: E402
    DEFAULT_N,
    DEFAULT_P,
    DEFAULT_R,
    PASSWORD_MAX_LEN,
    PASSWORD_MIN_LEN,
    make_password_hash,
    parse_password_hash,
    verify_password,
)


def _read_password() -> str:
    """두 번 입력받아 일치를 확인한다. 입력은 화면에 표시되지 않는다."""
    first = getpass.getpass("관리자 비밀번호 입력 (화면에 표시되지 않습니다): ")
    second = getpass.getpass("한 번 더 입력: ")
    if first != second:
        print("\n[중단] 두 입력이 일치하지 않습니다. 다시 실행해 주세요.")
        raise SystemExit(1)
    # NFC 정규화: macOS/Windows 한글 입력의 자모 분리 차이로 "맞게 쳤는데 로그인 실패"가
    # 나는 것을 막는다. 서버 검증 경로는 입력을 그대로 쓰므로, 여기서 정규화한 문자열을
    # 기준으로 해시를 만들면 영문·숫자 비밀번호에서는 아무 영향이 없다.
    normalized = unicodedata.normalize("NFC", first)
    if len(normalized) < PASSWORD_MIN_LEN:
        print(f"\n[중단] 비밀번호가 너무 짧습니다. 최소 {PASSWORD_MIN_LEN}자 이상으로 정해 주세요.")
        raise SystemExit(1)
    if len(normalized) > PASSWORD_MAX_LEN:
        print(f"\n[중단] 비밀번호가 너무 깁니다(최대 {PASSWORD_MAX_LEN}자).")
        raise SystemExit(1)
    if normalized.strip() != normalized:
        print("\n[중단] 앞뒤 공백은 입력 실수로 이어집니다. 공백 없이 다시 정해 주세요.")
        raise SystemExit(1)
    return normalized


def main() -> int:
    # 출력이 파이프·리다이렉트로 연결되면 파이썬은 콘솔 API 대신 로케일 인코딩(한국어
    # Windows 는 cp949)을 쓴다. 그 상태에서 표현 불가 문자가 섞이면 UnicodeEncodeError 로
    # 죽는다 — **해시를 이미 출력한 뒤** 죽으면 화면이 트레이스백으로 덮여 못 보게 된다.
    #
    # encoding 은 건드리지 않고 errors 만 바꾸는 것이 핵심이다. utf-8 로 강제하면 cp949
    # 콘솔에서 한글이 통째로 깨진다(2026-08-09 실제로 그렇게 만들 뻔했다).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    print("=" * 72)
    print(" 숨은길 관리자 비밀번호 해시 생성 (부록 T)")
    print(" - 입력한 비밀번호는 저장되지 않습니다. 출력되는 해시만 서버 .env 에 넣습니다.")
    print(" - 한글 비밀번호는 입력기(IME)에 따라 값이 달라질 수 있어 영문+숫자+기호를 권장합니다.")
    print("=" * 72)

    password = _read_password()
    hashed = make_password_hash(password, n=DEFAULT_N, r=DEFAULT_R, p=DEFAULT_P)

    # 생성 직후 자기검증 — 서버가 쓰는 것과 **완전히 같은 경로**로 한 번 통과시켜 본다.
    params = parse_password_hash(hashed)
    if params is None or not verify_password(password, params):
        print("\n[실패] 생성한 해시의 자기검증에 실패했습니다. 이 값을 사용하지 마세요.")
        return 1
    del password  # 프로세스 안에서도 필요 이상으로 들고 있지 않는다

    print("\n아래 한 줄을 서버의 deploy/.env 에 추가하세요 (따옴표 없이 그대로):\n")
    print(f"ADMIN_PASSWORD_HASH={hashed}")
    print(
        "\n다음 단계:\n"
        "  1) 서버에서  nano deploy/.env   → 위 줄 붙여넣기\n"
        "  2) 같은 파일에 관리자 표시 이름도 추가 (부록 V):\n"
        "       ADMIN_OPERATORS=지훈,인식,태준\n"
        "  3) docker compose up -d backend\n"
        "  4) 브라우저에서  https://sumeungil.co.kr/admin  접속 후 로그인\n"
        "\n[ADMIN_COOKIE_SECURE 에 대하여]\n"
        "  예전 안내에 있던  ADMIN_COOKIE_SECURE=false  는 **더 이상 넣지 마세요.**\n"
        "  2026-08-09 HTTPS 적용이 끝나 기본값 true 가 맞습니다. false 로 내리면 세션\n"
        "  쿠키가 평문으로 흐릅니다.\n"
        "\n주의: 이 해시 줄은 채팅·이슈·공개 저장소에 올리지 마세요. .env 는 커밋 대상이 아닙니다."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
