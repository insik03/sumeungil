"""캐시 추상 인터페이스.

MVP-1은 프로세스 인메모리 TTL 구현(MemoryCache)을 쓴다.
상용 전환 시 동일 인터페이스로 RedisCache 를 구현해 드롭인 교체한다.
서비스/리포지토리 코드는 이 추상만 의존하므로 변경 불필요.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Cache(ABC):
    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """유효한(만료 전) 값을 반환. 없거나 만료면 None."""
        raise NotImplementedError

    @abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        """TTL(초)과 함께 값을 저장."""
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> bool:
        """캐시 백엔드가 정상 동작하면 True."""
        raise NotImplementedError
