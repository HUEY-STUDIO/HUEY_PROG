"""단순 TTL 인메모리 캐시.

공공 API 는 일일 호출 건수 제한(예: LURIS 개발계정 1,000건/일)이 있어
같은 주소를 반복 조회할 때 원본 호출을 줄이는 것이 중요하다.
단일 프로세스 기준이며, 다중 워커로 운영할 때는 Redis 등으로 교체한다.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, TypeVar

from app.config import get_settings

T = TypeVar("T")

_store: dict[str, tuple[float, Any]] = {}
_lock = asyncio.Lock()


async def get_or_set(key: str, producer: Callable[[], Awaitable[T]]) -> T:
    """캐시에 있으면 그대로, 없으면 producer() 결과를 저장 후 반환."""
    ttl = get_settings().cache_ttl_seconds
    if ttl <= 0:
        return await producer()

    now = time.monotonic()
    async with _lock:
        hit = _store.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]

    value = await producer()

    async with _lock:
        _store[key] = (time.monotonic() + ttl, value)
    return value


def clear() -> None:
    """테스트/운영 점검용 캐시 비우기."""
    _store.clear()


def size() -> int:
    return len(_store)
