"""슬랙에 보낼 운영 리포트 문구 생성 (2026-08-18, 대표 지시 — #알림-봇).

세 가지를 만든다. 전부 **읽는 쿼리만** 하고 아무것도 바꾸지 않는다.

| 함수 | 쓰이는 곳 |
|---|---|
| `build_daily_summary` | 매일 아침 요약 (main.py `_daily_summary_loop`) |
| `build_server_status`  | 슬래시 명령어 `/서버상태` |
| `build_inquiry_status` | 슬래시 명령어 `/문의` |

## 문구에 담지 않는 것
- **관리자 콘솔 경로**. 경로 자체를 비밀로 두기로 한 결정(2026-08-17)이 있고, 팀원에게도
  아직 전달하지 않았다. 슬랙 채널에 적으면 그 결정이 무의미해진다 — 건수만 알린다.
- **개인정보**. 방문자 수는 ip_hash 고유 개수(추정치)이고 원본 IP 는 저장 자체를 안 한다.
- **시크릿**. 이 모듈은 설정값을 문구에 넣지 않는다.

## 왜 헬스체크 로직을 다시 쓰지 않는가
`api/health.py::_build_health` 를 그대로 쓴다. 밑줄로 시작하는 이름이지만 같은 패키지
안이고, 판정 규칙(무엇이 degraded 인가)이 두 곳으로 갈라지면 슬랙이 "정상"이라 하고
헬스체크 URL 은 "degraded"라 하는 상황이 생긴다. 판정은 한 곳에만 둔다.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import httpx
import psycopg

from ..api.health import _build_health
from ..cache.base import Cache
from ..db.postgres import Database
from ..repositories import admin_repo, visit_repo
from ..repositories.congestion_repo import CongestionRepository
from ..util.time import now_kst

logger = logging.getLogger("sumeungil.services.slack_report")

_WEEKDAY_KO = ("월", "화", "수", "목", "금", "토", "일")

# 2026-08-22(대표 지시) — 아침 요약에 넣을 Prometheus 지표 4종. 전부 24h 윈도우(=대략
# "어제")로 계산한다. status 라벨은 개별 코드(200/404 등)가 아니라 "2xx"/"5xx" 처럼
# 그룹으로 나온다(prometheus-fastapi-instrumentator 실측 확인, 2026-08-22).
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
_PROM_TIMEOUT_SEC = 5.0


async def _prometheus_line(base_url: str) -> str | None:
    """24시간 요청수·평균/p95 응답시간·5xx 비율 한 줄. 조회 실패·트래픽 0이면 None
    (요약 문구에서 그 줄만 조용히 빠진다 — 이 조회 하나 때문에 아침 요약 전체가
    깨지면 안 된다. slack_notify.post 와 같은 원칙).
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
    except Exception:  # noqa: BLE001
        logger.warning("Prometheus 지표 조회 실패 — 요약에서 이 줄만 생략", exc_info=True)
        return None

    total = values.get("total")
    if not total:  # None 또는 0 — 트래픽이 없으면 평균·p95도 의미가 없다
        return None

    avg_ms = (values.get("avg_sec") or 0.0) * 1000
    p95_ms = (values.get("p95_sec") or 0.0) * 1000
    # err_ratio 가 None 인 건 5xx 표본이 아예 없었다는 뜻(PromQL 벡터 나눗셈이 빈 결과를
    # 낸다) — "확인 불가"가 아니라 "0%"로 취급하는 게 맞는다.
    err_pct = (values.get("err_ratio") or 0.0) * 100

    return (
        f"· 지표(최근 24h): 요청 {int(total)}건 · 평균 {avg_ms:.0f}ms · p95 {p95_ms:.0f}ms"
        f" · 5xx {err_pct:.1f}%"
    )


def _stamp() -> str:
    now = now_kst()
    return f"{now:%Y-%m-%d %H:%M} KST"


async def _health_line(cache: Cache, repo: CongestionRepository) -> tuple[str, str]:
    """(종합상태, 한 줄 요약). 실패해도 예외를 내지 않는다 — 리포트가 이것 때문에 죽으면 안 된다."""
    try:
        h = await _build_health(cache, repo)
        detail = f"공공데이터 {h.checks.upstream_kto} · 캐시 {h.checks.cache}"
        return h.status, detail
    except Exception:  # noqa: BLE001
        logger.warning("헬스체크 조회 실패 — 리포트에는 '확인 불가'로 적는다", exc_info=True)
        return "unknown", "확인 불가(헬스체크 조회 실패)"


async def build_daily_summary(
    db: Database, cache: Cache, repo: CongestionRepository, prometheus_base_url: str = ""
) -> str:
    """아침 브리핑. **어제 실적 + 지금 처리 대기 + 서버 상태 + 운영 지표**로 구성한다.

    '오늘' 수치는 아침에 보면 거의 0이라 넣지 않는다 — 아침에 알고 싶은 건 어제 무슨 일이
    있었고, 지금 내가 처리할 게 뭐가 남았는지다.

    `prometheus_base_url` 을 비워두면(로컬 개발 기본) 지표 줄만 조용히 빠진다.
    """
    now = now_kst()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    def _tx(conn: psycopg.Connection):
        return (
            admin_repo.stats(conn, today_prefix=today),
            visit_repo.summary(conn, today=today, days=7),
        )

    try:
        counts, traffic = await db.aread(_tx)
    except Exception:  # noqa: BLE001 — DB 가 죽어도 서버 상태는 알려야 한다
        logger.warning("아침 요약 집계 조회 실패 — 서버 상태만 보낸다", exc_info=True)
        counts, traffic = None, None

    status, detail = await _health_line(cache, repo)
    icon = "🟢" if status == "ok" else ("🟠" if status == "degraded" else "⚪")

    lines = [f"📋 *숨은길 아침 브리핑* — {now:%Y-%m-%d} ({_WEEKDAY_KO[now.weekday()]})"]

    if traffic is not None:
        prev = next((d for d in traffic.get("daily", []) if d["day"] == yesterday), None)
        if prev:
            lines.append(
                f"· 어제({yesterday[5:]}) 방문자 {prev['visitors']}명(추정) · 조회 {prev['hits']}회"
            )
        else:
            lines.append(f"· 어제({yesterday[5:]}) 방문 기록 없음")

    if counts is not None:
        pending = []
        if counts["inquiries_new"]:
            pending.append(f"미답변 문의 {counts['inquiries_new']}건")
        if counts["reports_pending"]:
            pending.append(f"신고 후 미조치 후기 {counts['reports_pending']}건")
        lines.append("· 처리 대기: " + (" · ".join(pending) if pending else "없음 ✨"))
        lines.append(
            f"· 누적: 후기 {counts['reviews_total']}건 · 공유코스 {counts['courses_total']}건"
            f" · 문의 {counts['inquiries_total']}건"
        )

    lines.append(f"{icon} 서버 {status} — {detail}")

    metrics_line = await _prometheus_line(prometheus_base_url)
    if metrics_line:
        lines.append(metrics_line)

    return "\n".join(lines)


async def build_server_status(
    db: Database, cache: Cache, repo: CongestionRepository
) -> str:
    """`/서버상태` 응답. 슬랙은 3초 안에 응답을 요구하므로 가벼운 조회만 한다."""
    now = now_kst()
    today = now.strftime("%Y-%m-%d")
    status, detail = await _health_line(cache, repo)
    icon = "🟢" if status == "ok" else ("🟠" if status == "degraded" else "⚪")

    lines = [f"{icon} *서버 상태* — sumeungil.co.kr", f"· 종합: {status} ({detail})"]

    def _tx(conn: psycopg.Connection):
        return visit_repo.summary(conn, today=today, days=1)

    try:
        traffic = await db.aread(_tx)
        lines.append(
            f"· 오늘 방문자 {traffic['today_visitors']}명(추정) · 조회 {traffic['today_hits']}회"
        )
    except Exception:  # noqa: BLE001
        lines.append("· 오늘 방문 집계: 조회 실패(DB 확인 필요)")

    lines.append(f"확인 시각: {_stamp()}")
    return "\n".join(lines)


async def build_inquiry_status(db: Database) -> str:
    """`/문의` 응답. 건수만 — 답변 내용·연락처는 슬랙으로 내보내지 않는다(개인정보)."""
    today = now_kst().strftime("%Y-%m-%d")

    def _tx(conn: psycopg.Connection):
        return admin_repo.stats(conn, today_prefix=today)

    try:
        counts = await db.aread(_tx)
    except Exception:  # noqa: BLE001
        logger.warning("문의 집계 조회 실패", exc_info=True)
        return "✉️ *고객문의* — 집계 조회 실패. DB 상태를 확인하세요."

    new = counts["inquiries_new"]
    head = "✉️ *고객문의*" + ("" if new else " — 미답변 없음 ✨")
    lines = [head, f"· 미답변 {new}건 / 누적 {counts['inquiries_total']}건"]
    if new:
        lines.append("· 답변은 관리자 콘솔 '고객문의' 탭에서 작성하세요.")
    lines.append(f"확인 시각: {_stamp()}")
    return "\n".join(lines)
