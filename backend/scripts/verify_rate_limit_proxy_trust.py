"""X-Forwarded-For 신뢰 경계 강화(2026-08-22) 검증 스크립트.

배경: 4차 보안 감사(DAST, 2026-08-19) — backend에 직접 붙어 매 요청마다 다른
X-Forwarded-For 값을 실어 보내면 레이트리밋·관리자 로그인 브루트포스 방어가 전부
무제한 통과됨을 실증. 원인은 `extract_client_ip()`가 소켓 peer를 검증하지 않고
X-Forwarded-For 첫 값을 무조건 신뢰한 것 — nginx가 항상 그 헤더를 $remote_addr로
덮어써주는 배포 전제 하나에만 의존하는 단일 방어선이었다.

이 스크립트는 실서버 없이(Ollama·DB 불필요) `extract_client_ip()` 순수 함수만 호출해
(1) 신뢰할 수 없는(공인) peer에서는 X-Forwarded-For를 무시하는지,
(2) 신뢰할 수 있는(사설, 즉 docker 내부망을 흉내낸) peer에서는 기존처럼 헤더를 쓰는지,
(3) trust_proxy=False면 peer와 무관하게 항상 소켓 IP를 쓰는지를 확인한다.

실행:
    cd backend && .venv/Scripts/python.exe scripts/verify_rate_limit_proxy_trust.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.middleware.rate_limit import extract_client_ip  # noqa: E402


@dataclass
class _FakeClient:
    host: str | None


@dataclass
class _FakeRequest:
    client: _FakeClient | None
    headers: dict[str, str]


CASES = [
    (
        "공인 peer + XFF 스푸핑 (4차 감사 재현 시나리오) — 무시돼야 함",
        _FakeRequest(_FakeClient("8.8.8.8"), {"x-forwarded-for": "4.4.4.4"}),
        True,
        "8.8.8.8",
    ),
    (
        "사설(docker 내부망) peer + XFF — nginx를 실제로 거친 정상 경로, 신뢰해야 함",
        _FakeRequest(_FakeClient("172.20.0.5"), {"x-forwarded-for": "1.2.3.4"}),
        True,
        "1.2.3.4",
    ),
    (
        "loopback peer + XFF — 로컬 개발(프록시 없이 curl) 정상 경로, 신뢰해야 함",
        _FakeRequest(_FakeClient("127.0.0.1"), {"x-forwarded-for": "9.9.9.9"}),
        True,
        "9.9.9.9",
    ),
    (
        "trust_proxy=False — peer가 사설이어도 항상 소켓 IP",
        _FakeRequest(_FakeClient("172.20.0.5"), {"x-forwarded-for": "1.2.3.4"}),
        False,
        "172.20.0.5",
    ),
    (
        "헤더 없음 — 소켓 IP로 폴백",
        _FakeRequest(_FakeClient("8.8.8.8"), {}),
        True,
        "8.8.8.8",
    ),
    (
        "client 자체가 없음(테스트 더블) — unknown",
        _FakeRequest(None, {}),
        True,
        "unknown",
    ),
]


def main() -> None:
    failures = 0
    for label, request, trust_proxy, expected in CASES:
        got = extract_client_ip(request, trust_proxy=trust_proxy)
        ok = got == expected
        failures += 0 if ok else 1
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {label}")
        print(f"       trust_proxy={trust_proxy} expected={expected!r} got={got!r}")

    print()
    if failures:
        print(f">> {failures}건 실패")
        sys.exit(1)
    print(">> 전부 통과 — XFF 스푸핑이 사설 peer 검증으로 차단됨")


if __name__ == "__main__":
    main()
