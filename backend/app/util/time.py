"""시간 유틸 — KST 고정."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(KST)


def to_iso_kst(dt: datetime) -> str:
    """ISO 8601 + KST 오프셋 문자열 (예: 2026-07-24T15:00:00+09:00)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST).replace(microsecond=0).isoformat()


def today_yyyymmdd() -> str:
    return now_kst().strftime("%Y%m%d")
