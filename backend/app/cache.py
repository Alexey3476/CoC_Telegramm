"""Bounded in-memory TTL cache for a single-container Home Assistant add-on."""
import asyncio
import json
import time
from collections import OrderedDict
from typing import Any, Optional


class TTLCache:
    def __init__(self, max_entries: int = 512):
        self.max_entries = max_entries
        self._values = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[str]:
        async with self._lock:
            entry = self._values.get(key)
            if entry is None:
                return None
            expires, value = entry
            if expires <= time.monotonic():
                del self._values[key]
                return None
            self._values.move_to_end(key)
            return value

    async def set(self, key: str, value: str, ex: int = 300) -> None:
        async with self._lock:
            self._values[key] = (time.monotonic() + max(1, ex), value)
            self._values.move_to_end(key)
            now = time.monotonic()
            for old_key, (expires, _) in list(self._values.items()):
                if expires <= now:
                    del self._values[old_key]
            while len(self._values) > self.max_entries:
                self._values.popitem(last=False)

    async def close(self) -> None:
        async with self._lock:
            self._values.clear()


async def get_cached_json(redis: TTLCache, key: str) -> Optional[dict[str, Any]]:
    value = await redis.get(key)
    return json.loads(value) if value is not None else None


async def set_cached_json(redis: TTLCache, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
    await redis.set(key, json.dumps(value), ex=ttl_seconds)
