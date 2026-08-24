"""아침 요약에 추가한 Prometheus 지표 한 줄(2026-08-22, 대표 지시) 검증 스크립트.

`app/services/slack_report.py::_prometheus_line()` 이 다음을 지키는지 실제 Prometheus
서버 없이(httpx.AsyncClient.get 을 가로채서) 확인한다.

  1. 정상 응답 -> "요청/평균/p95/5xx" 한 줄로 정확히 포맷
  2. 5xx 표본이 아예 없음(빈 벡터) -> "0.0%"로 표시(조회 실패가 아님)
  3. 트래픽 자체가 0(total 없음) -> 줄 자체를 생략(None)
  4. base_url 이 비어있음(로컬 개발 기본) -> 조회 자체를 안 하고 None
  5. Prometheus 연결 실패(예외) -> None(요약 전체를 죽이지 않음)

실행:
    cd backend && .venv/Scripts/python.exe scripts/verify_prometheus_summary_line.py
"""

from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.services import slack_report  # noqa: E402


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _vector_result(value: str) -> dict:
    return {"status": "success", "data": {"result": [{"value": [0, value]}]}}


_EMPTY = {"status": "success", "data": {"result": []}}


class _FakeClient:
    """httpx.AsyncClient 대체 — 쿼리 문자열로 어떤 지표를 요청했는지 구분해 응답한다."""

    def __init__(self, responses: dict[str, dict], *, raise_exc: Exception | None = None):
        self._responses = responses
        self._raise_exc = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str, params: dict):
        if self._raise_exc:
            raise self._raise_exc
        query = params["query"]
        for needle, payload in self._responses.items():
            if needle in query:
                return _FakeResponse(payload)
        raise AssertionError(f"예상 못한 쿼리: {query}")


def _patch_client(monkey_responses: dict[str, dict] | None, *, raise_exc: Exception | None = None):
    def factory(timeout):
        return _FakeClient(monkey_responses or {}, raise_exc=raise_exc)

    httpx.AsyncClient = factory  # type: ignore[assignment]


import asyncio  # noqa: E402


async def main() -> None:
    failures = 0
    _orig_client = httpx.AsyncClient

    # `fetch_operational_metrics`는 avg_sec/p95_sec/err_ratio/total(각각 이미 Prometheus
    # 쪽에서 sum/count 나눗셈까지 끝난 단일 값) + up{job="sumeungil-backend"} 까지 5개 쿼리를
    # 보낸다. needle 은 서로 안 겹치는 부분으로 골랐다:
    #   avg_sec="_count[24h]))" / p95_sec="histogram_quantile" / err_ratio='status="5xx"'
    #   / total="increase(" / up='job="sumeungil-backend"'

    # --- 1: 정상 케이스 ---
    _patch_client(
        {
            "_count[24h]))": _vector_result("0.03"),  # avg_sec = 30ms
            "histogram_quantile": _vector_result("0.15"),  # p95_sec = 150ms
            'status="5xx"': _vector_result("0.02"),  # err_ratio = 2%
            "increase(": _vector_result("1200"),  # total
            'job="sumeungil-backend"': _vector_result("1"),  # up
        }
    )
    line1 = await slack_report._prometheus_line("http://fake-prometheus:9090")
    ok1 = (
        line1 is not None
        and "요청 1200건" in line1
        and "평균 30ms" in line1
        and "p95 150ms" in line1
        and "5xx 2.0%" in line1
    )
    print(f"[{'PASS' if ok1 else 'FAIL'}] 정상 케이스 포맷: {line1!r}")
    failures += 0 if ok1 else 1

    # --- 2: 5xx 표본 없음(빈 벡터) -> 0.0%로 표시(조회 실패 아님) ---
    _patch_client(
        {
            "_count[24h]))": _vector_result("0.01"),
            "histogram_quantile": _vector_result("0.05"),
            'status="5xx"': _EMPTY,  # 5xx 자체가 없어 빈 결과
            "increase(": _vector_result("500"),
            'job="sumeungil-backend"': _vector_result("1"),
        }
    )
    line2 = await slack_report._prometheus_line("http://fake-prometheus:9090")
    ok2 = line2 is not None and "5xx 0.0%" in line2
    print(f"[{'PASS' if ok2 else 'FAIL'}] 5xx 표본 없음 -> 0.0% (조회실패 아님): {line2!r}")
    failures += 0 if ok2 else 1

    # --- 3: 트래픽 0(total 빈 벡터) -> 줄 자체 생략 ---
    _patch_client(
        {
            "_count[24h]))": _EMPTY,
            "histogram_quantile": _EMPTY,
            'status="5xx"': _EMPTY,
            "increase(": _EMPTY,
            'job="sumeungil-backend"': _vector_result("1"),
        }
    )
    line3 = await slack_report._prometheus_line("http://fake-prometheus:9090")
    ok3 = line3 is None
    print(f"[{'PASS' if ok3 else 'FAIL'}] 트래픽 0 -> 줄 생략: {line3!r}")
    failures += 0 if ok3 else 1

    # --- 4: base_url 빈 문자열 -> 조회 자체 안 함 ---
    line4 = await slack_report._prometheus_line("")
    ok4 = line4 is None
    print(f"[{'PASS' if ok4 else 'FAIL'}] base_url 빈값 -> None: {line4!r}")
    failures += 0 if ok4 else 1

    # --- 5: 연결 실패(예외) -> None, 예외가 밖으로 안 나감 ---
    _patch_client(None, raise_exc=ConnectionError("연결 거부"))
    try:
        line5 = await slack_report._prometheus_line("http://fake-prometheus:9090")
        ok5 = line5 is None
    except Exception as exc:  # noqa: BLE001
        ok5 = False
        line5 = f"<예외 유출: {exc}>"
    print(f"[{'PASS' if ok5 else 'FAIL'}] Prometheus 연결 실패 -> 예외 안 유출, None: {line5!r}")
    failures += 0 if ok5 else 1

    httpx.AsyncClient = _orig_client

    print()
    if failures:
        print(f">> {failures}건 실패")
        sys.exit(1)
    print(">> 전부 통과")


if __name__ == "__main__":
    asyncio.run(main())
