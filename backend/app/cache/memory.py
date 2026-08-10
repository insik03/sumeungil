"""프로세스 인메모리 TTL 캐시.

단일 프로세스/이벤트루프 기준. asyncio Lock 으로 동시 접근을 직렬화한다.
상용에서 RedisCache 로 교체 시 이 파일만 대체된다.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .base import Cache


class MemoryCache(Cache):
    def __init__(self) -> None:
        # key -> (value, expires_at_epoch)
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()

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
            self._store[key] = (value, time.monotonic() + max(0, ttl_seconds))

    async def health(self) -> bool:
        # 인메모리는 프로세스가 살아있으면 항상 정상
        return True
