"""Tests for the synchronous and asynchronous jpzip clients.

We use :class:`httpx.MockTransport` to intercept all requests, which lets us
assert exactly how many times each path is fetched.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

import httpx
import pytest

from jpzip import (
    AsyncJpzipClient,
    Cache,
    JpzipClient,
    is_valid_zipcode,
)
from jpzip._types import parse_dict  # noqa: F401 - exercised via clients


# ---------------------------- fixtures / helpers ----------------------------


BASE_ENTRY: dict[str, Any] = {
    "prefecture": "神奈川県",
    "prefecture_kana": "カナガワケン",
    "prefecture_roma": "Kanagawa",
    "prefecture_code": "14",
    "city": "横浜市中区",
    "city_kana": "ヨコハマシナカク",
    "city_roma": "Yokohama Shi Naka Ku",
    "city_code": "14104",
    "towns": [
        {"town": "矢口台", "kana": "ヤグチダイ", "roma": "Yaguchidai"},
    ],
}


def _json_response(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


class Recorder:
    """Mutable counter capturing path access counts."""

    def __init__(self) -> None:
        self.hits: Counter[str] = Counter()


def _make_sync(handler) -> tuple[JpzipClient, Recorder]:
    rec = Recorder()

    def transport_handler(request: httpx.Request) -> httpx.Response:
        rec.hits[request.url.path] += 1
        return handler(request)

    transport = httpx.MockTransport(transport_handler)
    http = httpx.Client(transport=transport, base_url="https://test.invalid")
    client = JpzipClient(base_url="https://test.invalid", http_client=http)
    return client, rec


def _make_async(handler) -> tuple[AsyncJpzipClient, Recorder]:
    rec = Recorder()

    def transport_handler(request: httpx.Request) -> httpx.Response:
        rec.hits[request.url.path] += 1
        return handler(request)

    transport = httpx.MockTransport(transport_handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://test.invalid")
    client = AsyncJpzipClient(base_url="https://test.invalid", http_client=http)
    return client, rec


# ----------------------------------- tests ----------------------------------


def test_is_valid_zipcode() -> None:
    assert is_valid_zipcode("2310831") is True
    assert is_valid_zipcode("231-0831") is False
    assert is_valid_zipcode("abcdefg") is False
    assert is_valid_zipcode("12345") is False
    assert is_valid_zipcode("") is False


def test_lookup_malformed_no_fetch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client, rec = _make_sync(handler)
    with client:
        assert client.lookup("abc") is None
    assert sum(rec.hits.values()) == 0


def test_lookup_hit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/p/231.json":
            return _json_response({"2310831": BASE_ENTRY})
        return _json_response({}, status=404)

    client, _ = _make_sync(handler)
    with client:
        entry = client.lookup("2310831")
    assert entry is not None
    assert entry.prefecture == "神奈川県"
    assert entry.towns[0].town == "矢口台"


def test_lookup_l1_caching() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"2310831": BASE_ENTRY})

    client, rec = _make_sync(handler)
    with client:
        for _ in range(5):
            client.lookup("2310831")
    assert rec.hits["/p/231.json"] == 1


def test_lookup_404_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client, _ = _make_sync(handler)
    with client:
        assert client.lookup("9999999") is None


def test_lookup_group_three_digit() -> None:
    payload = {"2310831": BASE_ENTRY}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/p/231.json":
            return _json_response(payload)
        return httpx.Response(404)

    client, _ = _make_sync(handler)
    with client:
        out = client.lookup_group("231")
    assert set(out) == {"2310831"}


def test_lookup_group_one_digit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/g/2.json":
            return _json_response({"2310831": BASE_ENTRY})
        return httpx.Response(404)

    client, _ = _make_sync(handler)
    with client:
        out = client.lookup_group("2")
    assert "2310831" in out


def test_lookup_group_two_digit_fanout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/p/231.json":
            return _json_response({"2310831": BASE_ENTRY})
        return httpx.Response(404)

    client, rec = _make_sync(handler)
    with client:
        out = client.lookup_group("23")
    assert set(out) == {"2310831"}
    # Should have fanned out to all 10 of /p/23{0..9}.json
    fan_paths = {f"/p/23{i}.json" for i in range(10)}
    assert fan_paths.issubset(rec.hits.keys())


def test_lookup_all_fans_g0_to_g9() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/g/2.json":
            return _json_response({"2310831": BASE_ENTRY})
        # Other groups are empty but valid 200s
        if request.url.path.startswith("/g/"):
            return _json_response({})
        return httpx.Response(404)

    client, rec = _make_sync(handler)
    with client:
        out = client.lookup_all()
    assert "2310831" in out
    assert {f"/g/{i}.json" for i in range(10)} == {
        p for p in rec.hits if p.startswith("/g/")
    }


def test_preload_all_then_lookup_no_fetch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/g/2.json":
            return _json_response({"2310831": BASE_ENTRY})
        if request.url.path.startswith("/g/"):
            return _json_response({})
        return httpx.Response(404)

    client, rec = _make_sync(handler)
    with client:
        client.preload("all")
        rec.hits.clear()
        entry = client.lookup("2310831")
        assert entry is not None and entry.city == "横浜市中区"
    # After preload, lookup must be cache-only.
    assert sum(rec.hits.values()) == 0


def test_refresh_clears_l1() -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return _json_response({"2310831": BASE_ENTRY})

    client, _ = _make_sync(handler)
    with client:
        client.lookup("2310831")
        client.lookup("2310831")  # cached
        client.refresh()
        client.lookup("2310831")  # forced refetch
    assert call_count["n"] == 2


def test_meta_version_change_invalidates_l1() -> None:
    """Switching ``meta.version`` should drop the L1 cache."""

    state = {"meta_version": "2026-04"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/meta.json":
            return _json_response(
                {
                    "version": state["meta_version"],
                    "generated_at": "2026-04-01T00:00:00Z",
                    "spec_version": "1.0",
                    "total_zipcodes": 1,
                    "prefix_count": 1,
                    "by_pref": {"14": 1},
                    "data_source": "https://example.invalid",
                    "endpoints": {
                        "group": "/g/{prefix1}.json",
                        "prefix": "/p/{prefix3}.json",
                    },
                }
            )
        if request.url.path == "/p/231.json":
            return _json_response({"2310831": BASE_ENTRY})
        return httpx.Response(404)

    client, rec = _make_sync(handler)
    with client:
        # 1) seed meta + L1
        meta = client.get_meta()
        assert meta is not None and meta.version == "2026-04"
        client.lookup("2310831")
        before = rec.hits["/p/231.json"]
        assert before == 1

        # 2) Trigger version change — refresh forces re-fetch of meta.
        state["meta_version"] = "2026-05"
        client.refresh()
        meta2 = client.get_meta()
        assert meta2 is not None and meta2.version == "2026-05"

        # 3) Lookup should re-fetch the prefix (L1 was cleared).
        client.lookup("2310831")
        assert rec.hits["/p/231.json"] == 2


def test_spec_mismatch_callback_fires_once() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/meta.json":
            return _json_response(
                {
                    "version": "2026-05",
                    "generated_at": "2026-05-01T00:00:00Z",
                    "spec_version": "9.9",
                    "total_zipcodes": 0,
                    "prefix_count": 0,
                    "by_pref": {},
                    "data_source": "",
                    "endpoints": {"group": "", "prefix": ""},
                }
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    client = JpzipClient(
        base_url="https://test.invalid",
        http_client=http,
        on_spec_mismatch=lambda e, r: calls.append((e, r)),
    )
    with client:
        client.get_meta()
        client.get_meta()  # cached — must not refire
    assert calls == [("1.0", "9.9")]


def test_retry_on_5xx_then_success() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 2:
            return httpx.Response(503)
        return _json_response({"2310831": BASE_ENTRY})

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    client = JpzipClient(base_url="https://test.invalid", http_client=http)
    with client:
        # Use a smaller backoff window by patching MAX_ATTEMPTS-safe path: the
        # first retry waits backoff_seconds(1) = 400ms which is fine for tests.
        entry = client.lookup("2310831")
    assert entry is not None
    assert attempts["n"] == 2


def test_l2_cache_round_trip() -> None:
    class DictCache:
        def __init__(self) -> None:
            self.data: dict[str, bytes] = {}

        def get(self, key: str) -> bytes | None:
            return self.data.get(key)

        def set(self, key: str, value: bytes) -> None:
            self.data[key] = value

        def delete(self, key: str) -> None:
            self.data.pop(key, None)

        def clear(self) -> None:
            self.data.clear()

    # Type-only sanity check — DictCache satisfies the Cache protocol.
    assert isinstance(DictCache(), Cache)

    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        return _json_response({"2310831": BASE_ENTRY})

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    cache = DictCache()

    # First client populates the cache.
    c1 = JpzipClient(base_url="https://test.invalid", http_client=http, cache=cache)
    with c1:
        c1.lookup("2310831")
    assert hits["n"] == 1
    assert "https://test.invalid/p/231.json" in cache.data

    # Second client (fresh L1) should be served from L2 with zero new fetches.
    http2 = httpx.Client(transport=transport)
    c2 = JpzipClient(base_url="https://test.invalid", http_client=http2, cache=cache)
    with c2:
        entry = c2.lookup("2310831")
    assert entry is not None and entry.prefecture == "神奈川県"
    assert hits["n"] == 1  # no new network hit


# ----------------------------- async coverage ------------------------------


@pytest.mark.asyncio
async def test_async_lookup_and_caching() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"2310831": BASE_ENTRY})

    client, rec = _make_async(handler)
    async with client:
        e1 = await client.lookup("2310831")
        e2 = await client.lookup("2310831")
    assert e1 is not None and e2 is not None
    assert e1.prefecture == "神奈川県"
    assert rec.hits["/p/231.json"] == 1


@pytest.mark.asyncio
async def test_async_lookup_all() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/g/2.json":
            return _json_response({"2310831": BASE_ENTRY})
        if request.url.path.startswith("/g/"):
            return _json_response({})
        return httpx.Response(404)

    client, _ = _make_async(handler)
    async with client:
        out = await client.lookup_all()
    assert "2310831" in out
