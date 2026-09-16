"""프로세스 인메모리 TTL 캐시.

단일 프로세스/이벤트루프 기준. asyncio Lock 으로 동시 접근을 직렬화한다.
상용에서 RedisCache 로 교체 시 이 파일만 대체된다.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .base import Cache


# 보안감사 F-05(2026-09): 항목 수 상한. 넘으면 만료분을 먼저 걷어내고, 그래도 넘치면 만료가 가장
# 가까운 것부터 버린다. 한 항목 크기는 세지 않는다(값 대부분이 원천 API 응답 1페이지라 편차가 작다).
DEFAULT_MAX_ENTRIES = 5000


class MemoryCache(Cache):
    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        # key -> (value, expires_at_epoch)
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()
        self._max_entries = max(1, int(max_entries))

    def _sweep_expired(self, now: float) -> None:
        dead = [k for k, (_v, exp) in self._store.items() if now >= exp]
        for k in dead:
            self._store.pop(k, None)

    def _evict_to_fit(self, now: float) -> None:
        """상한 초과 시: 만료분 제거 → 그래도 초과면 만료가 이른 순으로 제거."""
        if len(self._store) < self._max_entries:
            return
        self._sweep_expired(now)
        overflow = len(self._store) - self._max_entries + 1
        if overflow <= 0:
            return
        for k, _ in sorted(self._store.items(), key=lambda kv: kv[1][1])[:overflow]:
            self._store.pop(k, None)

    def __len__(self) -> int:
        return len(self._store)

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() >= expires_at:
                # 만료: 제거하고 None
                self._store.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        async with self._lock:
            now = time.monotonic()
            if key not in self._store:
                self._evict_to_fit(now)
            self._store[key] = (value, now + max(0, ttl_seconds))

    async def health(self) -> bool:
        # 인메모리는 프로세스가 살아있으면 항상 정상
        return True
