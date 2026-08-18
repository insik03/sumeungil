"""5xx 슬랙 알림 미들웨어 실측 검증 (2026-08-18).

`app/middleware/error_alert.py` 가 실제로 다음을 지키는지 확인한다.
운영 서버에 올리기 전 이 스크립트가 5개 항목 전부 PASS 여야 한다.

  1. 미처리 예외(500)를 잡고, 예외는 그대로 다시 올라간다(응답 동작 무회귀)
  2. 라우터가 직접 반환한 5xx 도 잡는다
  3. 2xx/4xx 는 알리지 않는다(오탐 없음)
  4. **쿼리스트링·예외 메시지의 시크릿이 알림에 실리지 않는다**  ← 가장 중요
  5. 같은 (경로, 예외) 조합은 중복 창 안에서 1회만 알린다

슬랙에는 실제로 보내지 않는다 — _post 를 가로채 전송될 문자열만 모은다.

실행:
    cd backend
    .venv/Scripts/python.exe scripts/verify_error_alert.py     (Windows)
    python scripts/verify_error_alert.py                       (그 외)
"""

from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.applications import Starlette  # noqa: E402
from starlette.responses import JSONResponse, PlainTextResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app.middleware.error_alert import ErrorAlertMiddleware, _scrub  # noqa: E402

# 실제 키처럼 보이는 더미 — 이 문자열이 알림에 나타나면 실패다.
FAKE_KEY = "abcd1234EFGH5678ijkl9012MNOP3456"

sent: list[str] = []


async def _capture(self, text: str) -> None:  # _post 대체
    sent.append(text)


ErrorAlertMiddleware._post = _capture  # type: ignore[method-assign]


async def boom(request):
    # httpx 계열 예외처럼 **메시지 안에 URL+시크릿이 들어간 예외**를 재현한다.
    raise RuntimeError(
        f"upstream failed: GET https://apis.data.go.kr/x?serviceKey={FAKE_KEY}&pageNo=1"
    )


async def five_hundred(request):
    return JSONResponse({"detail": "internal"}, status_code=500)


async def ok(request):
    return PlainTextResponse("ok")


async def not_found(request):
    return PlainTextResponse("nope", status_code=404)


def build(window: int = 600) -> TestClient:
    app = Starlette(
        routes=[
            Route("/boom", boom),
            Route("/five", five_hundred),
            Route("/ok", ok),
            Route("/missing", not_found),
        ]
    )
    app.add_middleware(
        ErrorAlertMiddleware,
        webhook_url="https://hooks.slack.example/T/B/X",
        env="verify",
        dedup_window_sec=window,
    )
    return TestClient(app, raise_server_exceptions=False)


def main() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, note: str = "") -> None:
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + note) if note else ''}")
        if not cond:
            failures.append(name)

    # --- 1) 미처리 예외 ---------------------------------------------------
    print("\n[1] 미처리 예외(500) 감지 + 응답 무회귀")
    sent.clear()
    c = build()
    r = c.get(f"/boom?serviceKey={FAKE_KEY}")
    check("500 응답이 그대로 나간다", r.status_code == 500, f"status={r.status_code}")
    check("알림 1건 발생", len(sent) == 1, f"{len(sent)}건")
    body = sent[0] if sent else ""
    check("예외 이름이 담긴다", "RuntimeError" in body)
    check("트레이스백이 담긴다", "```" in body and "boom" in body)

    # --- 2) 라우터가 직접 만든 5xx ---------------------------------------
    print("\n[2] 라우터가 반환한 5xx 감지")
    sent.clear()
    c = build()
    r = c.get("/five")
    check("알림 1건 발생", len(sent) == 1, f"{len(sent)}건")
    check("트레이스백 없음을 명시", "예외 없이 반환된 5xx" in (sent[0] if sent else ""))

    # --- 3) 정상/4xx 는 조용 ---------------------------------------------
    print("\n[3] 2xx·4xx 는 알리지 않음(오탐 없음)")
    sent.clear()
    c = build()
    c.get("/ok")
    c.get("/missing")
    check("알림 0건", len(sent) == 0, f"{len(sent)}건")

    # --- 4) 시크릿 유출 ---------------------------------------------------
    print("\n[4] 시크릿 유출 차단 (가장 중요)")
    sent.clear()
    c = build()
    c.get(f"/boom?serviceKey={FAKE_KEY}&token={FAKE_KEY}")
    body = sent[0] if sent else ""
    check("실키 문자열이 알림에 없다", FAKE_KEY not in body)
    check("쿼리스트링이 붙지 않는다", "?" not in body.split("\n")[0])
    check("serviceKey 는 *** 로 가려진다", "serviceKey=***" in body)
    check("_scrub 단위 동작", _scrub(f"access_token={FAKE_KEY}") == "access_token=***")
    check(
        '_scrub JSON 형태도 처리',
        '"password": "***' in _scrub('"password": "hunter2xyz"'),
        _scrub('"password": "hunter2xyz"'),
    )

    # --- 5) 중복 억제 -----------------------------------------------------
    print("\n[5] 중복 억제 (같은 경로·예외)")
    sent.clear()
    c = build(window=600)
    for _ in range(5):
        c.get("/boom")
    check("5회 요청 → 알림 1건", len(sent) == 1, f"{len(sent)}건")

    sent.clear()
    c = build(window=0)  # 창 0 이면 매번
    for _ in range(3):
        c.get("/boom")
    check("창 0초 → 3회 모두 알림", len(sent) == 3, f"{len(sent)}건")

    sent.clear()
    c = build(window=600)
    c.get("/boom")
    c.get("/five")  # 다른 경로 → 별개로 알린다
    check("다른 경로는 각각 알림", len(sent) == 2, f"{len(sent)}건")

    print("\n" + "=" * 60)
    if failures:
        print(f"❌ 실패 {len(failures)}건: {', '.join(failures)}")
        return 1
    print("✅ 전 항목 PASS — 운영 배포 가능")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
