"""Asynchronous :class:`AsyncJpzipClient`."""

from __future__ import annotations

import asyncio
import json
from typing import Callable

import httpx

from ._cache import AsyncCache, MemoryLRU
from ._http import (
    ACCEPT_HEADER,
    MAX_ATTEMPTS,
    backoff_seconds,
    is_valid_prefix,
    is_valid_zipcode,
)
from ._types import (
    DEFAULT_BASE_URL,
    SPEC_VERSION,
    Meta,
    ZipcodeEntry,
    parse_dict,
)

SpecMismatchCallback = Callable[[str, str], None]


class AsyncJpzipClient:
    """Asynchronous SDK client (asyncio-friendly)."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        http_client: httpx.AsyncClient | None = None,
        memory_cache_size: int = 100,
        cache: AsyncCache | None = None,
        on_spec_mismatch: SpecMismatchCallback | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_http = http_client is None
        self._http: httpx.AsyncClient = http_client or httpx.AsyncClient(
            timeout=timeout
        )
        self._mem = MemoryLRU(memory_cache_size)
        self._cache = cache
        self._on_spec_mismatch = on_spec_mismatch

        self._meta_lock = asyncio.Lock()
        self._meta_cached: Meta | None = None
        self._meta_resolved = False
        self._known_version: str | None = None

    # ----------------------------- lifecycle -----------------------------

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> "AsyncJpzipClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    # ------------------------------ public API ----------------------------

    async def lookup(self, zipcode: str) -> ZipcodeEntry | None:
        if not is_valid_zipcode(zipcode):
            return None
        dct = await self._fetch_prefix_dict(zipcode[:3])
        if dct is None:
            return None
        return dct.get(zipcode)

    async def lookup_group(self, prefix: str) -> dict[str, ZipcodeEntry]:
        if not is_valid_prefix(prefix):
            raise ValueError(f"jpzip: invalid prefix {prefix!r} (must be 1-3 digits)")
        if len(prefix) == 3:
            return (await self._fetch_prefix_dict(prefix)) or {}
        if len(prefix) == 1:
            return (await self._fetch_group_dict(prefix)) or {}
        results = await asyncio.gather(
            *(self._fetch_prefix_dict(f"{prefix}{i}") for i in range(10))
        )
        out: dict[str, ZipcodeEntry] = {}
        for d in results:
            if d:
                out.update(d)
        return out

    async def lookup_all(self) -> dict[str, ZipcodeEntry]:
        results = await asyncio.gather(
            *(self._fetch_group_dict(str(i)) for i in range(10))
        )
        out: dict[str, ZipcodeEntry] = {}
        for d in results:
            if d:
                out.update(d)
        return out

    async def get_meta(self) -> Meta | None:
        async with self._meta_lock:
            if self._meta_resolved:
                return self._meta_cached
            body, status = await self._get_raw(f"{self._base_url}/meta.json")
            if status == 404:
                self._meta_resolved = True
                self._meta_cached = None
                return None
            assert body is not None
            try:
                raw = json.loads(body)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"jpzip: parse meta: {exc}") from exc
            meta = Meta.from_dict(raw)
            if meta.spec_version != SPEC_VERSION and self._on_spec_mismatch is not None:
                self._on_spec_mismatch(SPEC_VERSION, meta.spec_version)
            if self._known_version and self._known_version != meta.version:
                self._mem.clear()
                if self._cache is not None:
                    await self._cache.clear()
            self._known_version = meta.version
            self._meta_cached = meta
            self._meta_resolved = True
            return meta

    async def preload(self, scope: str) -> None:
        if scope == "all":
            dct = await self.lookup_all()
            buckets: dict[str, dict[str, ZipcodeEntry]] = {}
            for zip_, entry in dct.items():
                buckets.setdefault(zip_[:3], {})[zip_] = entry
            for p, bucket in buckets.items():
                url = self._prefix_url(p)
                self._mem.set(url, bucket)
                await self._write_l2(url, bucket)
            return
        if not is_valid_prefix(scope):
            raise ValueError(f"jpzip: invalid preload scope {scope!r}")
        await self.lookup_group(scope)

    async def refresh(self) -> None:
        self._mem.clear()
        async with self._meta_lock:
            self._meta_cached = None
            self._meta_resolved = False
            self._known_version = None
        if self._cache is not None:
            await self._cache.clear()

    # ------------------------------- internals -----------------------------

    def _prefix_url(self, prefix3: str) -> str:
        return f"{self._base_url}/p/{prefix3}.json"

    async def _fetch_prefix_dict(
        self, prefix3: str
    ) -> dict[str, ZipcodeEntry] | None:
        url = self._prefix_url(prefix3)
        cached = self._mem.get(url)
        if cached is not None:
            return cached
        from_l2 = await self._read_l2(url)
        if from_l2 is not None:
            self._mem.set(url, from_l2)
            return from_l2
        dct = await self._fetch_url(url)
        if dct is not None:
            self._mem.set(url, dct)
            await self._write_l2(url, dct)
        return dct

    async def _fetch_group_dict(
        self, prefix1: str
    ) -> dict[str, ZipcodeEntry] | None:
        url = f"{self._base_url}/g/{prefix1}.json"
        cached = self._mem.get(url)
        if cached is not None:
            return cached
        dct = await self._fetch_url(url)
        if dct is not None:
            self._mem.set(url, dct)
        return dct

    async def _fetch_url(self, url: str) -> dict[str, ZipcodeEntry] | None:
        body, status = await self._get_raw(url)
        if status == 404:
            return None
        assert body is not None
        try:
            raw = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"jpzip: parse {url}: {exc}") from exc
        return parse_dict(raw)

    async def _read_l2(self, url: str) -> dict[str, ZipcodeEntry] | None:
        if self._cache is None:
            return None
        blob = await self._cache.get(url)
        if not blob:
            return None
        try:
            raw = json.loads(blob)
        except (json.JSONDecodeError, UnicodeDecodeError):
            await self._cache.delete(url)
            return None
        return parse_dict(raw)

    async def _write_l2(self, url: str, dct: dict[str, ZipcodeEntry]) -> None:
        if self._cache is None:
            return
        payload = {
            zip_: {
                "prefecture": e.prefecture,
                "prefecture_kana": e.prefecture_kana,
                "prefecture_roma": e.prefecture_roma,
                "prefecture_code": e.prefecture_code,
                "city": e.city,
                "city_kana": e.city_kana,
                "city_roma": e.city_roma,
                "city_code": e.city_code,
                "towns": [
                    {
                        "town": t.town,
                        "kana": t.kana,
                        "roma": t.roma,
                        **({"note": t.note} if t.note is not None else {}),
                    }
                    for t in e.towns
                ],
            }
            for zip_, e in dct.items()
        }
        await self._cache.set(
            url, json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )

    async def _get_raw(self, url: str) -> tuple[bytes | None, int]:
        last_exc: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            if attempt > 0:
                await asyncio.sleep(backoff_seconds(attempt))
            try:
                resp = await self._http.get(url, headers=ACCEPT_HEADER)
            except httpx.HTTPError as exc:
                last_exc = exc
                continue
            if resp.status_code == 404:
                return None, 404
            if resp.status_code >= 500:
                last_exc = RuntimeError(f"jpzip: {url} returned {resp.status_code}")
                continue
            if resp.status_code >= 400:
                raise RuntimeError(f"jpzip: {url} returned {resp.status_code}")
            return resp.content, resp.status_code
        assert last_exc is not None
        raise last_exc


__all__ = ["AsyncJpzipClient", "SpecMismatchCallback"]
