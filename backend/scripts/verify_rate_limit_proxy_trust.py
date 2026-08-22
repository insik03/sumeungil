"""X-Forwarded-For 신뢰 경계 강화(2026-08-22) 검증 스크립트.

배경: 4차 보안 감사(DAST, 2026-08-19) — backend에 직접 붙어 매 요청마다 다른
X-Forwarded-For 값을 실어 보내면 레이트리밋·관리자 로그인 브루트포스 방어가 전부
무제한 통과됨을 실증. 원인은 `extract_client_ip()`가 소켓 peer를 검증하지 않고
X-Forwarded-For 첫 값을 무조건 신뢰한 것 — nginx가 항상 그 헤더를 $remote_addr로
덮어써주는 배포 전제 하나에만 의존하는 단일 방어선이었다.

2026-08-22 독립 보안 검증(security-engineer)이 이 첫 패치 자체의 구멍을 실제로 재현
했다: `ipaddress.*.is_private` 가 loopback(127.0.0.1)까지 "사설"로 취급해서, uvicorn
자신의 기본 동작(loopback 접속에서 X-Forwarded-For 로 request.client.host 를 이미
치환함)과 겹쳐 4차 감사의 재현 방식("로컬에서 backend에 직접 붙기")이 패치 후에도
그대로 통과됐다. 대응: ① Dockerfile CMD 에 `--no-proxy-headers` 추가 ② 신뢰 판정을
RFC1918(10/8, 172.16/12, 192.168/16) + IPv6 ULA(fc00::/7) 명시적 대역으로 좁혀
loopback·link-local·문서용 대역(TEST-NET 등)을 신뢰 대상에서 제외.

이 스크립트는 실서버 없이(Ollama·DB 불필요) `extract_client_ip()` 순수 함수만 호출해
(1) 신뢰할 수 없는(공인) peer에서는 X-Forwarded-For를 무시하는지,
(2) 신뢰할 수 있는(RFC1918 사설, 즉 docker 내부망을 흉내낸) peer에서는 기존처럼
    헤더를 쓰는지,
(3) **loopback 은 더 이상 신뢰하지 않는지**(위 재발 방지 — 4차 감사 재현 방식 차단),
(4) is_private 가 잘못 "사설"로 분류하던 문서용/예약 대역(TEST-NET 등)도 신뢰하지
    않는지,
(5) trust_proxy=False면 peer와 무관하게 항상 소켓 IP를 쓰는지를 확인한다.

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
        "loopback peer + XFF (4차 감사 재현 방식) — 이제는 신뢰하면 안 됨 (H-1 재발 방지)",
        _FakeRequest(_FakeClient("127.0.0.1"), {"x-forwarded-for": "9.9.9.9"}),
        True,
        "127.0.0.1",
    ),
    (
        "IPv4-mapped IPv6 loopback(::ffff:127.0.0.1) — 마찬가지로 신뢰하면 안 됨",
        _FakeRequest(_FakeClient("::ffff:127.0.0.1"), {"x-forwarded-for": "9.9.9.9"}),
        True,
        "::ffff:127.0.0.1",
    ),
    (
        "TEST-NET 문서용 대역(203.0.113.9) peer — is_private 오분류 재발 방지, 신뢰 안 함",
        _FakeRequest(_FakeClient("203.0.113.9"), {"x-forwarded-for": "9.9.9.9"}),
        True,
        "203.0.113.9",
    ),
    (
        "IPv4-mapped IPv6 사설대역(::ffff:172.20.0.5) — 언랩 후 RFC1918 매칭, 신뢰해야 함",
        _FakeRequest(_FakeClient("::ffff:172.20.0.5"), {"x-forwarded-for": "1.2.3.4"}),
        True,
        "1.2.3.4",
    ),
    (
        "IPv6 ULA(fc00::1) peer — 신뢰해야 함",
        _FakeRequest(_FakeClient("fc00::1"), {"x-forwarded-for": "1.2.3.4"}),
        True,
        "1.2.3.4",
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
