"""관리자 비밀번호를 **.env 에 직접 기록**한다 (부록 T·V) — 대표(사람)만 실행.

    ssh 로 서버 접속 후:
        cd ~/sumeungil/backend && python3 scripts/set_admin_password.py

## make_admin_hash.py 와 뭐가 다른가
`make_admin_hash.py` 는 해시를 **화면에 출력**하고, 사람이 그것을 복사해 `.env` 에 붙여넣는다.
2026-08-09 대표가 이 복사·붙여넣기 단계에서 막혔다(터미널에서 붙여넣기가 들어가지 않아
`.env` 에 아무것도 기록되지 않았고, 서버 어디에도 `scrypt$` 문자열이 없었다).

이 스크립트는 그 단계를 없앤다:
  - 해시를 **화면에 절대 출력하지 않는다** (어깨너머 노출·터미널 스크롤백 잔존도 함께 사라진다)
  - `.env` 를 직접 열어 `ADMIN_PASSWORD_HASH` 줄을 추가하거나 교체한다
  - 쓰기 전에 타임스탬프 백업을 남긴다

## 안전장치
  - 기존 값이 있으면 덮어쓸지 먼저 물어본다(비밀번호 교체 = 전원 즉시 로그아웃).
  - 임시 파일에 먼저 쓰고 원자적으로 교체한다 — 중간에 죽어도 `.env` 가 깨지지 않는다.
  - 파일 권한 600 을 유지한다.
  - 생성 직후 서버와 **같은 경로**로 자기검증한다. 실패하면 아무것도 쓰지 않는다.
"""

from __future__ import annotations

import getpass
import os
import shutil
import sys
import time
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

KEY = "ADMIN_PASSWORD_HASH"
# 기본 위치: 이 저장소 배치 기준(backend/ 와 deploy/ 는 형제 디렉터리).
DEFAULT_ENV = BACKEND_DIR.parent / "deploy" / ".env"


def _read_password() -> str:
    """두 번 입력받아 일치를 확인한다. 입력은 화면에 표시되지 않는다(정상 동작)."""
    first = getpass.getpass("관리자 비밀번호 입력 (화면에 표시되지 않는 것이 정상입니다): ")
    second = getpass.getpass("한 번 더 입력: ")
    if first != second:
        print("\n[중단] 두 입력이 일치하지 않습니다. 다시 실행해 주세요.")
        raise SystemExit(1)
    # NFC 정규화 — 윈도우/맥 한글 입력기의 자모 분리 차이로 "맞게 쳤는데 로그인 실패"가
    # 나는 것을 막는다. 서버 검증 경로도 같은 정규화를 한다.
    normalized = unicodedata.normalize("NFC", first)
    if len(normalized) < PASSWORD_MIN_LEN:
        print(f"\n[중단] 너무 짧습니다. 최소 {PASSWORD_MIN_LEN}자 이상으로 정해 주세요.")
        raise SystemExit(1)
    if len(normalized) > PASSWORD_MAX_LEN:
        print(f"\n[중단] 너무 깁니다(최대 {PASSWORD_MAX_LEN}자).")
        raise SystemExit(1)
    if normalized.strip() != normalized:
        print("\n[중단] 앞뒤 공백은 입력 실수로 이어집니다. 공백 없이 다시 정해 주세요.")
        raise SystemExit(1)
    return normalized


def _needs_compose_escape(env_path: Path) -> bool:
    """이 `.env` 를 docker compose 가 읽는가.

    compose 는 `.env` 값 안의 `$` 를 **변수 치환 기호로 해석한다.** scrypt 해시는
    `scrypt$N$r$p$솔트$해시` 라 `$` 가 5개 들어가므로, 그대로 두면 솔트·해시가 통째로
    빈 문자열로 치환돼 컨테이너에는 `scrypt$16384$8$1` 만 도착한다(2026-08-09 실제 발생).
    `$$` 로 써야 compose 가 리터럴 `$` 하나로 전달한다.
    """
    if env_path.name != ".env":
        return False
    return any(
        (env_path.parent / name).is_file()
        for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
    )


def _write_env(env_path: Path, hashed: str) -> str:
    """`.env` 의 ADMIN_PASSWORD_HASH 를 추가하거나 교체한다. 반환값은 '추가'/'교체'."""
    if _needs_compose_escape(env_path):
        hashed = hashed.replace("$", "$$")
        print("  (docker compose 용으로 $ 를 $$ 로 이스케이프했습니다)")

    original = env_path.read_text(encoding="utf-8")
    lines = original.splitlines()

    replaced = False
    out: list[str] = []
    for line in lines:
        if line.strip().startswith(f"{KEY}="):
            out.append(f"{KEY}={hashed}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append("# 관리자 비밀번호 검증자 (부록 T). 평문이 아니라 scrypt 해시다.")
        out.append(f"{KEY}={hashed}")

    backup = env_path.with_name(f"{env_path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(env_path, backup)

    # 임시 파일 → 원자적 교체. 중간에 죽어도 .env 가 반쯤 쓰인 상태로 남지 않는다.
    tmp = env_path.with_name(f"{env_path.name}.tmp-{os.getpid()}")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, env_path)

    print(f"  백업: {backup.name}")
    return "교체" if replaced else "추가"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    env_path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_ENV
    env_path = env_path.resolve()

    print("=" * 72)
    print(" 숨은길 관리자 비밀번호 설정")
    print(f" 대상 파일: {env_path}")
    print(" 해시는 화면에 출력되지 않고 이 파일에 바로 기록됩니다.")
    print("=" * 72)

    if not env_path.is_file():
        print(f"\n[중단] 파일이 없습니다: {env_path}")
        print("       경로를 인자로 넘길 수 있습니다:")
        print("       python3 scripts/set_admin_password.py ~/sumeungil/deploy/.env")
        return 1

    existing = any(
        line.strip().startswith(f"{KEY}=") and line.strip() != f"{KEY}="
        for line in env_path.read_text(encoding="utf-8").splitlines()
    )
    if existing:
        print("\n이미 관리자 비밀번호가 설정돼 있습니다.")
        print("교체하면 **지금 로그인해 있는 사람 전원이 즉시 로그아웃**됩니다.")
        if input("교체할까요? (y/N): ").strip().lower() not in {"y", "yes"}:
            print("취소했습니다. 아무것도 바꾸지 않았습니다.")
            return 0

    password = _read_password()
    hashed = make_password_hash(password, n=DEFAULT_N, r=DEFAULT_R, p=DEFAULT_P)

    # 서버가 쓰는 것과 완전히 같은 경로로 자기검증. 실패하면 파일에 손대지 않는다.
    params = parse_password_hash(hashed)
    if params is None or not verify_password(password, params):
        print("\n[실패] 생성한 해시의 자기검증에 실패했습니다. .env 는 그대로 둡니다.")
        return 1
    del password

    action = _write_env(env_path, hashed)
    del hashed

    print(f"\n완료 — {KEY} {action}함. (해시는 화면에 출력하지 않았습니다.)")
    print("\n다음 단계: 담당자에게 '넣었다'고 알리면 백엔드 재시작과 검증을 진행합니다.")
    print("직접 하시려면:")
    print("  cd ~/sumeungil/deploy && docker compose up -d backend")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
