# jpzip — Python SDK

> 日本の郵便番号を CDN 配信の JSON データから引く Python SDK。

- 配信ドメイン: `https://jpzip.nadai.dev`
- プロトコル仕様: [`jpzip/spec`](https://github.com/jpzip/spec)
- データ ETL: [`jpzip/data`](https://github.com/jpzip/data)

```sh
pip install jpzip
```

Python 3.10 以上が必要です。

## 使い方

### モジュール関数 API (同期、L1 のみ)

```python
import jpzip

entry = jpzip.lookup("2310017")
# entry is None なら見つからなかった

dict_ = jpzip.lookup_group("23")   # 2 桁は 10 並列 fetch
all_ = jpzip.lookup_all()
meta = jpzip.get_meta()
```

### 同期クライアント API (L2 キャッシュ・複数インスタンス用)

```python
from jpzip import JpzipClient

with JpzipClient(
    base_url="https://jpzip.nadai.dev",
    memory_cache_size=200,
    cache=my_cache,           # Cache プロトコルを満たす任意の実装
) as client:
    client.preload("all")
    entry = client.lookup("2310017")
```

### 非同期クライアント API

```python
import asyncio
from jpzip import AsyncJpzipClient

async def main():
    async with AsyncJpzipClient() as client:
        entry = await client.lookup("2310017")
        print(entry)

asyncio.run(main())
```

## Cache プロトコル

同期版 `Cache` と非同期版 `AsyncCache` の 2 つを提供しています。クライアントに合わせて使い分けてください。

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

ファイル / SQLite / Redis / S3 等の任意の実装を渡せます。
プロトコルなので継承宣言は不要で、構造的に満たしていれば OK です。

## キャッシュ層

- **L1**: メモリ内 LRU (URL キー、デフォルト 100 prefix)。常時 ON。
- **L2**: `cache=` で渡したときのみ ON。デフォルト OFF。
- **L3**: HTTP 層のキャッシュは httpx / OS / CDN に委ねる。

## 入力検証

`lookup()` は `^\d{7}$` にマッチしない入力には fetch せず `None` を返します。
書式チェックだけしたい場合は `jpzip.is_valid_zipcode(s)` を使ってください。

## バージョン整合性

`get_meta()` で `spec_version` が SDK のサポート版と異なる場合、
`on_spec_mismatch` で渡したコールバックが 1 度だけ呼ばれます。
データバージョン (`version`) が変わった場合は L1/L2 を自動 invalidate します。

```python
client = JpzipClient(
    on_spec_mismatch=lambda expected, received: print(
        f"spec mismatch: expected={expected} received={received}"
    ),
)
```

## リトライ

5xx 応答とネットワークエラーには指数バックオフ (200ms × 2^n) で最大 3 回リトライします。
404 は「該当なし」として `None` を返し、リトライしません。

## ライセンス

[MIT](./LICENSE)
