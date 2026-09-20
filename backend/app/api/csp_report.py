"""CSP 위반 보고 수집 (2026-09-14, 보안감사 Mn-7 "완전한 CSP" 준비 단계).

nginx 가 `Content-Security-Policy-Report-Only` 로 정책을 **적용하지 않고 보고만** 받게 해 두었다.
브라우저가 위반을 발견하면 여기(`POST /api/v1/csp-report`)로 JSON 을 보낸다. 우리는 어떤 지시어가
어떤 호스트 때문에 걸리는지 **집계만** 하고(개인정보·본문 없음), `GET /api/v1/health/csp` 로 읽는다.
며칠 지켜본 뒤 위반이 0 이면 nginx 에서 Report-Only 를 떼고 강제 모드로 바꾼다.

- 인증 없음(브라우저가 쿠키 없이 보낸다). 레이트리밋은 공통 미들웨어가 건다.
- 본문은 최대 8KB 만 읽고, 파싱 실패는 조용히 204(브라우저에 알릴 것이 없다).
- 저장은 프로세스 메모리 Counter(상위 200 키만) — 재시작하면 0 부터.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response

logger = logging.getLogger("sumeungil.api.csp_report")

router = APIRouter(tags=["health"])

MAX_BODY_BYTES = 8 * 1024
MAX_KEYS = 200

_violations: Counter[str] = Counter()
_total = 0


def _host_of(uri: object) -> str:
    """blocked-uri 는 URL·'inline'·'eval'·'data' 같은 키워드가 섞여 온다 — 호스트만 남긴다."""
    if not isinstance(uri, str) or not uri:
        return "-"
    if "://" not in uri:
        return uri[:40]
    return (urlsplit(uri).hostname or "-")[:80]


def record(report: dict) -> str | None:
    """보고 1건 → 집계 키("directive @ host"). 형식이 아니면 None."""
    global _total
    if not isinstance(report, dict):
        return None
    body = report.get("csp-report") if isinstance(report.get("csp-report"), dict) else report
    if not isinstance(body, dict):
        return None
    directive = body.get("effective-directive") or body.get("violated-directive") or body.get("effectiveDirective")
    if not isinstance(directive, str) or not directive:
        return None
    if not directive.strip():
        return None
    key = f"{directive.split()[0][:40]} @ {_host_of(body.get('blocked-uri') or body.get('blockedURL'))}"
    _total += 1
    if key in _violations or len(_violations) < MAX_KEYS:
        _violations[key] += 1
    return key


def snapshot() -> dict:
    return {"total": _total, "distinct": len(_violations), "top": _violations.most_common(30)}


def reset() -> None:
    global _total
    _violations.clear()
    _total = 0


@router.post("/api/v1/csp-report", status_code=204)
async def csp_report(request: Request) -> Response:
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BODY_BYTES:
            return Response(status_code=204)
        raw.extend(chunk)
    if raw and len(raw) <= MAX_BODY_BYTES:
        try:
            data = json.loads(raw)
            if isinstance(data, list):  # Reporting API 형식([{body:{...}}])
                for item in data:
                    if isinstance(item, dict):
                        record(item.get("body") or item)
            elif isinstance(data, dict):
                record(data)
        except (ValueError, TypeError):
            pass
    return Response(status_code=204)


@router.get("/api/v1/health/csp")
async def health_csp() -> dict:
    """Report-Only 기간의 위반 집계. 강제 모드 전환 판단 근거."""
    return snapshot()


__all__ = ("router", "record", "snapshot", "reset")
