"""Prometheus 운영 지표 공용 조회 (2026-08-23).

`slack_report._prometheus_line`(아침 요약용 문구)와 관리자 콘솔 `/api/v1/admin/
server-status`(2026-08-23, 대표 지시 "그라파나랑 운영대시보드랑 붙여야 한다") 둘 다
같은 4개 PromQL을 쓴다 — 쿼리 문자열이 두 곳으로 갈라지면 언젠가 하나만 고쳐서
숫자가 어긋난다. 원본 값(초 단위·비율)을 반환하고, 포맷(ms 변환·문자열 조립)은
호출자가 한다.

같은 docker 네트워크 안의 prometheus 컨테이너를 직접 쿼리한다(nginx의 `/prom/`
Basic Auth 는 그라파나 등 **외부** 조회용이라 여긴 우회 — 내부망이라 인증 불필요).
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("sumeungil.services.metrics_service")

# status 라벨은 개별 코드(200/404 등)가 아니라 "2xx"/"5xx" 처럼 그룹으로 나온다
# (prometheus-fastapi-instrumentator 실측 확인, 2026-08-22).
_PROM_QUERIES: dict[str, str] = {
    "avg_sec": (
        "sum(rate(http_request_duration_seconds_sum[24h]))"
        " / sum(rate(http_request_duration_seconds_count[24h]))"
    ),
    "p95_sec": (
        "histogram_quantile(0.95,"
        " sum(rate(http_request_duration_seconds_bucket[24h])) by (le))"
    ),
    "err_ratio": (
        'sum(rate(http_requests_total{status="5xx"}[24h]))'
        " / sum(rate(http_requests_total[24h]))"
    ),
    "total": "sum(increase(http_requests_total[24h]))",
}
_UP_QUERY = 'up{job="sumeungil-backend"}'
_PROM_TIMEOUT_SEC = 5.0


async def fetch_operational_metrics(base_url: str) -> dict[str, float | None] | None:
    """24시간 요청수·평균/p95 응답시간(초)·5xx 비율·백엔드 up 여부를 원본 값으로 반환.

    조회 자체가 실패하면(Prometheus 응답 없음 등) None — 호출자가 "지금 확인 불가"로
    처리한다. 트래픽이 0인 것과는 다르다: 트래픽 0은 `total=0.0`으로 정상 반환되고,
    호출자가 필요하면 그 경우를 따로 판단한다(slack_report는 줄 생략, admin API는
    "트래픽 없음"으로 표시하는 식으로 용도가 다르다 — 판단은 여기서 안 한다).
    """
    if not base_url:
        return None
    values: dict[str, float | None] = {}
    try:
        async with httpx.AsyncClient(timeout=_PROM_TIMEOUT_SEC) as client:
            for key, query in _PROM_QUERIES.items():
                resp = await client.get(f"{base_url}/api/v1/query", params={"query": query})
                resp.raise_for_status()
                result = resp.json().get("data", {}).get("result", [])
                values[key] = float(result[0]["value"][1]) if result else None

            up_resp = await client.get(f"{base_url}/api/v1/query", params={"query": _UP_QUERY})
            up_resp.raise_for_status()
            up_result = up_resp.json().get("data", {}).get("result", [])
            values["up"] = float(up_result[0]["value"][1]) if up_result else None
    except Exception:  # noqa: BLE001
        logger.warning("Prometheus 지표 조회 실패", exc_info=True)
        return None
    return values
