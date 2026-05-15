"""L1 in-memory LRU and the L2 user-supplied :class:`Cache` protocol."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Protocol, runtime_checkable

from ._types import ZipcodeEntry


@runtime_checkable
class Cache(Protocol):
    """L2 persistent cache contract (synchronous)."""

    def get(self, key: str) -> bytes | None: ...
    def set(self, key: str, value: bytes) -> None: ...
    def delete(self, key: str) -> None: ...
    def clear(self) -> None: ...


@runtime_checkable
class AsyncCache(Protocol):
    """L2 persistent cache contract (asynchronous)."""

    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def clear(self) -> None: ...


class MemoryLRU:
    """Thread-safe LRU keyed by URL, bounded by a fixed prefix count."""

    __slots__ = ("_capacity", "_items", "_lock")

    def __init__(self, capacity: int = 100) -> None:
        if capacity < 1:
            capacity = 1
        self._capacity = capacity
        self._items: OrderedDict[str, dict[str, ZipcodeEntry]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, ZipcodeEntry] | None:
        with self._lock:
            value = self._items.get(key)
            if value is None:
                return None
            self._items.move_to_end(key)
            return value

    def set(self, key: str, value: dict[str, ZipcodeEntry]) -> None:
        with self._lock:
            if key in self._items:
                self._items[key] = value
                self._items.move_to_end(key)
                return
            self._items[key] = value
            if len(self._items) > self._capacity:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:  # pragma: no cover - trivial
        with self._lock:
            return len(self._items)


__all__ = ["AsyncCache", "Cache", "MemoryLRU"]
