# jpzip

[![PyPI version](https://img.shields.io/pypi/v/jpzip.svg)](https://pypi.org/project/jpzip/)
[![Python versions](https://img.shields.io/pypi/pyversions/jpzip.svg)](https://pypi.org/project/jpzip/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Publish](https://github.com/jpzip/python/actions/workflows/publish.yml/badge.svg)](https://github.com/jpzip/python/actions/workflows/publish.yml)

> Python SDK for **jpzip** — a free, unlimited Japanese postal code (郵便番号) API.
> 日本の全郵便番号 120,677 件を CDN 配信 JSON から引く Python SDK (sync + async)。

**English** | [日本語](./README.ja.md)

`jpzip` looks up Japanese postal codes (郵便番号) from `jpzip.nadai.dev`,
a CDN-hosted dataset built from Japan Post's `KEN_ALL.csv` and `KEN_ALL_ROME.csv`
normalized to JSON. No registration, no rate limits, no API key.

- 🇯🇵 **Complete dataset** — 120,677 entries with kanji, kana, romaji, and government codes (JIS X 0401 / 総務省地方公共団体コード)
- ⚡️ **Fast** — L1 LRU + optional L2 persistent cache; `preload("all")` to serve lookups without per-request network round-trips
- 🔀 **Sync + async** — `JpzipClient` (httpx.Client) and `AsyncJpzipClient` (httpx.AsyncClient) share the same API surface
- 🛡️ **Resilient** — 3-attempt retry with exponential backoff on 5xx / network failures
- 🐍 **Typed** — frozen dataclasses, `Protocol`-based cache contract, fully type-hinted
- 🆓 **Free forever** — backed by Cloudflare Pages' free tier (no billing axis exists)
- 🔌 **Drop-in** — same API surface across [every jpzip SDK](#other-languages)

## Requirements

- Python 3.10+
- One runtime dependency: [`httpx`](https://www.python-httpx.org/) (`>=0.27`) — powers both the sync and async clients

## Install

```bash
pip install jpzip
```

## Quick Start

### Sync

```python
import jpzip

entry = jpzip.lookup("2310017")
if entry is None:
    print("not found")
else:
    print(entry.prefecture, entry.city, entry.towns[0].town)
    # Output: 神奈川県 横浜市中区 港町
```

Romaji and government codes are included on the same entry:

```python
print(entry.prefecture_roma, entry.city_roma, entry.towns[0].roma)
# Output: Kanagawa Ken Yokohama Shi Naka Ku Minatocho

print(entry.prefecture_code, entry.city_code)
# Output: 14 14104
```

### Async

```python
import asyncio
from jpzip import AsyncJpzipClient

async def main() -> None:
    async with AsyncJpzipClient() as client:
        entry = await client.lookup("2310017")
        if entry is not None:
            print(entry.prefecture, entry.city, entry.towns[0].town)

asyncio.run(main())
```

## Use Cases

### Zipcode lookup HTTP endpoint (FastAPI)

```python
from fastapi import FastAPI, HTTPException
from jpzip import AsyncJpzipClient

app = FastAPI()
client = AsyncJpzipClient()

@app.on_event("shutdown")
async def _shutdown() -> None:
    await client.aclose()

@app.get("/api/zipcode/{code}")
async def zipcode(code: str) -> dict:
    entry = await client.lookup(code)
    if entry is None:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "prefecture": entry.prefecture,
        "city": entry.city,
        "towns": [t.town for t in entry.towns],
        "city_code": entry.city_code,
    }
```

### Batch validation

```python
import jpzip

all_entries = jpzip.lookup_all()  # entire dataset in memory (~37 MiB JSON)
for code in csv_zipcodes:
    if code not in all_entries:
        print(f"invalid zipcode: {code}")
```

### Serve lookups from cache (BYO L2 backend)

The dataset is partitioned into 948 three-digit prefix buckets. The default
L1 (100 entries) keeps the hottest buckets; to cache the whole dataset, pair
`preload("all")` with an L2 cache or raise `memory_cache_size` above 948.

```python
from jpzip import JpzipClient, Cache

class FileCache:
    """Any object structurally matching jpzip.Cache works (Protocol)."""
    def get(self, key: str) -> bytes | None: ...
    def set(self, key: str, value: bytes) -> None: ...
    def delete(self, key: str) -> None: ...
    def clear(self) -> None: ...

with JpzipClient(memory_cache_size=1024, cache=FileCache()) as client:
    client.preload("all")
    # Subsequent lookups are served from L1/L2 without hitting the network.
    entry = client.lookup("2310017")
```

## API Reference

### Module-level shortcuts (sync, share a default `JpzipClient`)

| Function | Description |
|---|---|
| `lookup(zipcode)` | Look up a single 7-digit zipcode. Returns `None` if not found or malformed (no network call for malformed input). |
| `lookup_group(prefix)` | Look up by 1-, 2-, or 3-digit prefix. 1-digit fetches `/g/{d}.json`; 3-digit fetches `/p/{ddd}.json`; 2-digit fans out into 10 parallel 3-digit fetches and merges. Raises `ValueError` on a non-numeric / >3-digit prefix. |
| `lookup_all()` | Fetch entire dataset (120k entries, ~37 MiB) in parallel across `/g/0..9.json`. |
| `get_meta()` | Dataset version, generated-at, per-prefecture counts, spec version. Result is cached until `refresh()`. |
| `preload(scope)` | Warm L1 (and L2 when configured) for `"all"` or a specific prefix. |
| `is_valid_zipcode(s)` | Pure syntax check (`^\d{7}$`) — no network. |

### `JpzipClient` (sync, advanced)

Instantiate directly when you need L2 caching, a custom `httpx.Client`, an alternate base URL, or multiple isolated caches:

```python
from jpzip import JpzipClient

with JpzipClient(
    base_url="https://jpzip.nadai.dev",
    http_client=None,            # provide your own httpx.Client to share pools
    memory_cache_size=200,       # L1 capacity in prefix buckets, default 100
    cache=my_cache,              # optional L2 (Cache protocol)
    timeout=30.0,
    on_spec_mismatch=lambda expected, received: print(
        f"jpzip spec mismatch: SDK={expected} server={received}"
    ),
) as client:
    entry = client.lookup("2310017")
```

`JpzipClient` exposes `lookup` / `lookup_group` / `lookup_all` / `get_meta` / `preload` plus:

| Method | Description |
|---|---|
| `client.refresh()` | Wipe L1 (and L2 when configured) and forget the cached meta. |
| `client.close()` | Close the owned `httpx.Client`. Use the context manager (`with`) to do this automatically. |

When `get_meta()` observes that `/meta.json`'s `version` has changed since the last successful fetch, L1 and L2 are cleared automatically — call `get_meta()` periodically to pick up dataset rollovers.

### `AsyncJpzipClient` (async)

Same constructor surface and same methods, but `async`:

```python
import asyncio
from jpzip import AsyncJpzipClient

async def main() -> None:
    async with AsyncJpzipClient(memory_cache_size=200) as client:
        entry = await client.lookup("2310017")
        meta = await client.get_meta()
        await client.preload("231")
        await client.refresh()

asyncio.run(main())
```

The async client accepts an `AsyncCache` (async methods) instead of `Cache`, and an `httpx.AsyncClient` instead of `httpx.Client`. Use `await client.aclose()` (or `async with`) for cleanup.

### Errors

- `ValueError` — raised by `lookup_group` / `preload` when the prefix isn't 1–3 digits.
- `RuntimeError` — raised on non-404 4xx responses, or after exhausting retries on 5xx / network failures. Wraps the underlying `httpx.HTTPError` on transport-level failures.
- Network failures and 5xx responses are retried up to 3 attempts (initial + 2 retries) with exponential backoff sleeps of 400ms and 800ms. 404 responses yield `None` immediately without retrying. Other 4xx responses are raised immediately.

### `Cache` / `AsyncCache` protocols

Bring your own L2 backend (file, SQLite, Redis, S3, etc.):

```python
from typing import Protocol

class Cache(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def set(self, key: str, value: bytes) -> None: ...
    def delete(self, key: str) -> None: ...
    def clear(self) -> None: ...

class AsyncCache(Protocol):
    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def clear(self) -> None: ...
```

Both are `@runtime_checkable` `Protocol`s — no inheritance required, just structural matching. Keys are the full prefix-bucket URLs (e.g. `https://jpzip.nadai.dev/p/231.json`); values are raw JSON bytes.

### Dataclasses

`ZipcodeEntry`, `Town`, `Meta`, and `Endpoints` are frozen dataclasses (`slots=True`). All fields are typed and stable — see `src/jpzip/_types.py`.

## Why jpzip-python?

| | **jpzip-python** | [posuto][posuto] | [pgeocode][pgeocode] |
|---|---|---|---|
| Romaji (`Yokohama Shi`) | ✅ | ❌ ([explicitly dropped][posuto-romaji]) | ⚠️ romaji-only place names |
| Government codes (JIS / 総務省) | ✅ | ❌ | ❌ |
| No bundled CSV / DB in the wheel | ✅ (CDN-served) | ❌ (embeds SQLite) | ❌ (downloads CSV on first use) |
| Monthly updates | ✅ Auto | ✅ Monthly releases | ⚠️ GeoNames cadence |
| Sync **and** async client | ✅ | ❌ sync only | ❌ sync only |
| Offline after `preload("all")` | ✅ | ✅ (always) | ✅ (always) |
| Rate-limit-free | ✅ | ✅ | ✅ |
| L1 + pluggable L2 cache | ✅ | n/a | n/a |
| Wheel size | KB (no embedded data) | MB (embedded SQLite) | depends on GeoNames CSV |

[posuto]: https://github.com/polm/posuto
[posuto-romaji]: https://github.com/polm/posuto#romaji
[pgeocode]: https://github.com/symerio/pgeocode

## Other Languages

Same API surface across all SDKs:

[Go](https://github.com/jpzip/go) · [TypeScript](https://github.com/jpzip/js) · [Rust](https://github.com/jpzip/rust) · [Ruby](https://github.com/jpzip/ruby) · [PHP](https://github.com/jpzip/php) · [Swift](https://github.com/jpzip/swift) · [Dart](https://github.com/jpzip/dart)

## Resources

- **Website** — https://jpzip.nadai.dev
- **Protocol spec** — [jpzip/spec](https://github.com/jpzip/spec)
- **Data ETL** — [jpzip/data](https://github.com/jpzip/data)
- **MCP server** — [jpzip/mcp](https://github.com/jpzip/mcp) — use jpzip from Claude / ChatGPT / Cursor

## Keywords

japanese postal code, japan zipcode, 郵便番号, KEN_ALL, KEN_ALL_ROME, address validation, japan address api, postal code lookup python, python japanese address, async postal code, fastapi zipcode, httpx japanese address, JIS X 0401, 総務省地方公共団体コード

## License

[MIT](./LICENSE)
