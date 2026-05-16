"""jpzip — Python SDK for the Japanese postal-code CDN at jpzip.nadai.dev.

Two clients are exposed:

* :class:`JpzipClient` — synchronous, built on ``httpx.Client``.
* :class:`AsyncJpzipClient` — asyncio, built on ``httpx.AsyncClient``.

Module-level shortcuts (``lookup``, ``lookup_group`` …) delegate to a lazily
created default synchronous client. Use the class directly when you need an
L2 cache, a custom base URL, or multiple instances.
"""

from __future__ import annotations

import threading

from ._async_client import AsyncJpzipClient
from ._cache import AsyncCache, Cache, MemoryLRU
from ._client import JpzipClient
from ._http import is_valid_zipcode
from ._types import (
    DEFAULT_BASE_URL,
    SPEC_VERSION,
    Endpoints,
    Meta,
    Town,
    ZipcodeEntry,
)

__all__ = [
    "AsyncCache",
    "AsyncJpzipClient",
    "Cache",
    "DEFAULT_BASE_URL",
    "Endpoints",
    "JpzipClient",
    "MemoryLRU",
    "Meta",
    "SPEC_VERSION",
    "Town",
    "ZipcodeEntry",
    "get_meta",
    "is_valid_zipcode",
    "lookup",
    "lookup_all",
    "lookup_group",
    "preload",
]

__version__ = "0.1.1"

_default_lock = threading.Lock()
_default_client: JpzipClient | None = None


def _default() -> JpzipClient:
    global _default_client
    if _default_client is None:
        with _default_lock:
            if _default_client is None:
                _default_client = JpzipClient()
    return _default_client


def lookup(zipcode: str) -> ZipcodeEntry | None:
    """Shortcut for ``JpzipClient().lookup``."""

    return _default().lookup(zipcode)


def lookup_group(prefix: str) -> dict[str, ZipcodeEntry]:
    """Shortcut for ``JpzipClient().lookup_group``."""

    return _default().lookup_group(prefix)


def lookup_all() -> dict[str, ZipcodeEntry]:
    """Shortcut for ``JpzipClient().lookup_all``."""

    return _default().lookup_all()


def preload(scope: str) -> None:
    """Shortcut for ``JpzipClient().preload``."""

    _default().preload(scope)


def get_meta() -> Meta | None:
    """Shortcut for ``JpzipClient().get_meta``."""

    return _default().get_meta()
