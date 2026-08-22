"""이상행동(401/429 몰림) 슬랙 알림 미들웨어 실측 검증 (2026-08-22).

`app/middleware/anomaly_alert.py` 가 실제로 다음을 지키는지 확인한다.

  1. 401/429 가 문턱 아래에서는 알리지 않는다(오탐 없음)
  2. 문턱을 넘으면 알린다
  3. IP(client key)가 요청마다 달라도(4차 DAST 의 XFF 스푸핑 시나리오) 서비스 전체
     집계이므로 여전히 감지한다 — 이게 이 미들웨어를 만든 이유다
  4. 같은 상태코드는 쿨다운 동안 재알림하지 않는다
  5. 200/404 등 감시 대상이 아닌 상태코드는 절대 알리지 않는다

슬랙에는 실제로 보내지 않는다 — `_post` 를 가로채 전송될 문자열만 모은다.

실행:
    cd backend
    .venv/Scripts/python.exe scripts/verify_anomaly_alert.py     (Windows)
    python scripts/verify_anomaly_alert.py                       (그 외)
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

from app.middleware.anomaly_alert import AnomalyAlertMiddleware  # noqa: E402

sent: list[str] = []


async def _capture(self, text: str) -> None:  # _post 대체
    sent.append(text)


AnomalyAlertMiddleware._post = _capture  # type: ignore[method-assign]


async def unauthorized(request):
    return JSONResponse({"error": "unauthorized"}, status_code=401)


async def rate_limited(request):
    return PlainTextResponse("rate limited", status_code=429)


async def ok(request):
    return JSONResponse({"ok": True})


async def not_found(request):
    return JSONResponse({"error": "not found"}, status_code=404)


routes = [
    Route("/unauthorized", unauthorized),
    Route("/rate-limited", rate_limited),
    Route("/ok", ok),
    Route("/not-found", not_found),
]


def build_app(**overrides) -> Starlette:
    kwargs = dict(
        webhook_url="https://example.invalid/webhook",
        env="test",
        window_sec=60,
        threshold_401=5,
        threshold_429=5,
        cooldown_sec=600,
    )
    kwargs.update(overrides)
    app = Starlette(routes=routes)
    app.add_middleware(AnomalyAlertMiddleware, **kwargs)
    return app


def main() -> None:
    failures = 0

    # --- 1·2: 문턱 아래에서는 조용, 넘으면 알림 ---
    # SlidingWindowLimiter(limit=5)는 처음 5건을 "허용"으로 세고(카운트만 증가), 6번째
    # 요청에서 len(hits)>=limit 이 되어 처음으로 not-allowed 를 반환한다.
    sent.clear()
    app = build_app()
    client = TestClient(app)
    for _ in range(5):
        client.get("/unauthorized")
    ok1 = len(sent) == 0
    print(f"[{'PASS' if ok1 else 'FAIL'}] 문턱(5) 이내(5회)에서는 알림 없음 (sent={len(sent)})")
    failures += 0 if ok1 else 1

    client.get("/unauthorized")  # 6번째 — 문턱 초과
    ok2 = len(sent) == 1 and "401" in sent[0]
    print(f"[{'PASS' if ok2 else 'FAIL'}] 문턱(5) 초과 시 알림 발송 (sent={len(sent)})")
    failures += 0 if ok2 else 1

    # --- 3: IP 스푸핑 시나리오 — client key 를 매번 바꿔도 서비스 전체 집계라 여전히 감지 ---
    sent.clear()
    app = build_app()
    client = TestClient(app)
    for i in range(6):
        # 매 요청 다른 X-Forwarded-For — 4차 DAST 재현. 이 미들웨어는 IP 를 아예 안 보므로
        # 헤더 값과 무관하게 문턱에 도달해야 한다.
        client.get("/rate-limited", headers={"X-Forwarded-For": f"9.9.9.{i}"})
    ok3 = len(sent) == 1
    print(f"[{'PASS' if ok3 else 'FAIL'}] IP(XFF)를 매번 바꿔도 전체 집계로 감지 (sent={len(sent)})")
    failures += 0 if ok3 else 1

    # --- 4: 쿨다운 동안 재알림 안 함 ---
    sent.clear()
    app = build_app(cooldown_sec=600)
    client = TestClient(app)
    for _ in range(10):
        client.get("/unauthorized")
    ok4 = len(sent) == 1
    print(f"[{'PASS' if ok4 else 'FAIL'}] 쿨다운 중 재알림 없음, 10회 요청에 알림 1건 (sent={len(sent)})")
    failures += 0 if ok4 else 1

    # --- 5: 감시 대상 아닌 상태코드는 절대 알리지 않음 ---
    sent.clear()
    app = build_app()
    client = TestClient(app)
    for _ in range(50):
        client.get("/ok")
        client.get("/not-found")
    ok5 = len(sent) == 0
    print(f"[{'PASS' if ok5 else 'FAIL'}] 200/404 는 아무리 많아도 알리지 않음 (sent={len(sent)})")
    failures += 0 if ok5 else 1

    print()
    if failures:
        print(f">> {failures}건 실패")
        sys.exit(1)
    print(">> 전부 통과")


if __name__ == "__main__":
    main()
