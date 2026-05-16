# jpzip

[![PyPI version](https://img.shields.io/pypi/v/jpzip.svg)](https://pypi.org/project/jpzip/)
[![Python versions](https://img.shields.io/pypi/pyversions/jpzip.svg)](https://pypi.org/project/jpzip/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Publish](https://github.com/jpzip/python/actions/workflows/publish.yml/badge.svg)](https://github.com/jpzip/python/actions/workflows/publish.yml)

> **jpzip** の Python SDK — 無料・無制限の日本郵便番号 API。
> 日本郵便の `KEN_ALL.csv` / `KEN_ALL_ROME.csv` を JSON 正規化し CDN 配信。sync / async 両対応。

[English](./README.md) | **日本語**

`jpzip` は `jpzip.nadai.dev` から日本の郵便番号 120,677 件を引く Python SDK です。
登録不要、レート制限なし、API キー不要。

- 🇯🇵 **全件収録** — 漢字・カナ・ローマ字・自治体コード(JIS X 0401 / 総務省地方公共団体コード)
- ⚡️ **高速** — L1 LRU + 任意の L2 永続キャッシュ。`preload("all")` でネットワーク往復なしのルックアップが可能
- 🔀 **sync + async** — `JpzipClient` (httpx.Client) / `AsyncJpzipClient` (httpx.AsyncClient) が同じ API を提供
- 🛡️ **堅牢** — 5xx / ネットワーク失敗時は指数バックオフで最大 3 回リトライ
- 🐍 **型完備** — `frozen` dataclass、`Protocol` ベースのキャッシュ契約、完全な型ヒント
- 🆓 **永久無料** — Cloudflare Pages 無料枠で運用(課金軸が存在しない)
- 🔌 **同一 API** — [全 jpzip SDK](#他言語版) で API が揃う

## 必要環境

- Python 3.10 以上
- 実行時依存は [`httpx`](https://www.python-httpx.org/) (`>=0.27`) のみ — sync / async 両クライアントが利用

## インストール

```bash
pip install jpzip
```

## クイックスタート

### 同期

```python
import jpzip

entry = jpzip.lookup("2310017")
if entry is None:
    print("見つかりません")
else:
    print(entry.prefecture, entry.city, entry.towns[0].town)
    # 出力: 神奈川県 横浜市中区 港町
```

ローマ字・自治体コードも同じエントリに含まれます:

```python
print(entry.prefecture_roma, entry.city_roma, entry.towns[0].roma)
# 出力: Kanagawa Ken Yokohama Shi Naka Ku Minatocho

print(entry.prefecture_code, entry.city_code)
# 出力: 14 14104
```

### 非同期

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

## ユースケース

### 郵便番号ルックアップ HTTP エンドポイント (FastAPI)

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

### CSV のバッチ検証

```python
import jpzip

all_entries = jpzip.lookup_all()  # 全件をメモリに展開(JSON 約 37 MiB)
for code in csv_zipcodes:
    if code not in all_entries:
        print(f"不正な郵便番号: {code}")
```

### キャッシュからの提供(任意の L2 バックエンド)

データは 948 個の 3 桁 prefix バケットに分割されています。デフォルト L1 (100 件) は
ホットなバケットを保持しますが、全件を常駐させるには L2 を併用するか
`memory_cache_size` を 948 超に設定してください。

```python
from jpzip import JpzipClient, Cache

class FileCache:
    """jpzip.Cache を構造的に満たすクラスならなんでも渡せる (Protocol)。"""
    def get(self, key: str) -> bytes | None: ...
    def set(self, key: str, value: bytes) -> None: ...
    def delete(self, key: str) -> None: ...
    def clear(self) -> None: ...

with JpzipClient(memory_cache_size=1024, cache=FileCache()) as client:
    client.preload("all")
    # 以降の lookup は L1/L2 で完結し、ネットワークにアクセスしない
    entry = client.lookup("2310017")
```

## API リファレンス

### モジュール関数(同期、内部の既定 `JpzipClient` を共有)

| 関数 | 説明 |
|---|---|
| `lookup(zipcode)` | 7 桁の郵便番号で 1 件引く。見つからない / 不正な入力は `None`(不正入力時はネットワーク不使用)。 |
| `lookup_group(prefix)` | 1〜3 桁の prefix で引く。1 桁は `/g/{d}.json` を 1 回、3 桁は `/p/{ddd}.json` を 1 回、2 桁は 10 並列 fetch して結合。数字でない / 4 桁以上は `ValueError`。 |
| `lookup_all()` | `/g/0..9.json` を並列取得して全件(120k 件、約 37 MiB)を返す。 |
| `get_meta()` | データバージョン・生成日時・都道府県別件数・spec version。`refresh()` までは結果をキャッシュ。 |
| `preload(scope)` | `"all"` または特定 prefix で L1(L2 設定時は L2 も)を温める。 |
| `is_valid_zipcode(s)` | 純粋な書式チェック(`^\d{7}$`)。ネットワーク不使用。 |

### `JpzipClient`(同期、高度な用途)

L2 キャッシュ、`httpx.Client` 差し替え、配信元変更、複数の独立キャッシュが必要な場合に直接インスタンス化:

```python
from jpzip import JpzipClient

with JpzipClient(
    base_url="https://jpzip.nadai.dev",
    http_client=None,            # 自前の httpx.Client を渡してプールを共有可能
    memory_cache_size=200,       # L1 容量(prefix バケット数)、デフォルト 100
    cache=my_cache,              # L2(任意、Cache プロトコル)
    timeout=30.0,
    on_spec_mismatch=lambda expected, received: print(
        f"jpzip spec 不一致: SDK={expected} server={received}"
    ),
) as client:
    entry = client.lookup("2310017")
```

`JpzipClient` は `lookup` / `lookup_group` / `lookup_all` / `get_meta` / `preload` に加えて:

| メソッド | 説明 |
|---|---|
| `client.refresh()` | L1(L2 設定時は L2 も)を消し、キャッシュ済み meta を破棄。 |
| `client.close()` | 自前で生成した `httpx.Client` を閉じる。`with` で自動化推奨。 |

`get_meta()` が `/meta.json` の `version` 変更を検知すると L1/L2 が自動クリアされます。データ切り替えに追従するには `get_meta()` を定期的に呼んでください。

### `AsyncJpzipClient`(非同期)

コンストラクタもメソッドも同じシグネチャで、`async` 化されたバージョン:

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

非同期版は `Cache` の代わりに `AsyncCache`(メソッドが `async`)を、`httpx.Client` の代わりに `httpx.AsyncClient` を受け取ります。後片付けは `await client.aclose()`(または `async with`)。

### エラー

- `ValueError` — `lookup_group` / `preload` で prefix が 1〜3 桁の数字でない場合に送出。
- `RuntimeError` — 404 以外の 4xx、もしくは 5xx / ネットワーク失敗を 3 回リトライしても回復しない場合に送出。トランスポート層失敗時は `httpx.HTTPError` をラップ。
- ネットワーク失敗と 5xx は最大 3 回試行(初回 + リトライ 2 回)、指数バックオフのスリープは 400ms / 800ms。404 はリトライせず即 `None`。

### `Cache` / `AsyncCache` プロトコル

任意の L2 バックエンド(ファイル / SQLite / Redis / S3 など)を渡せます:

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

どちらも `@runtime_checkable` `Protocol` です。継承不要、構造的に満たしていれば OK。キーは prefix バケットの完全 URL(例: `https://jpzip.nadai.dev/p/231.json`)、値は生 JSON バイト列。

### データクラス

`ZipcodeEntry` / `Town` / `Meta` / `Endpoints` は `frozen` + `slots=True` の dataclass です。フィールドは全て型付きで安定 — 詳細は `src/jpzip/_types.py` を参照。

## なぜ jpzip-python か

| | **jpzip-python** | [posuto][posuto] | [pgeocode][pgeocode] |
|---|---|---|---|
| ローマ字(`Yokohama Shi`) | ✅ | ❌([明示的に廃止][posuto-romaji]) | ⚠️ 地名がローマ字のみ |
| 自治体コード(JIS / 総務省) | ✅ | ❌ | ❌ |
| wheel に CSV / DB を同梱しない | ✅(CDN 配信) | ❌(SQLite 同梱) | ❌(初回 CSV ダウンロード) |
| 月次更新 | ✅ 自動 | ✅ 月次リリース | ⚠️ GeoNames 更新頻度 |
| sync **と** async 両対応 | ✅ | ❌ sync のみ | ❌ sync のみ |
| `preload("all")` 後オフライン | ✅ | ✅(常時) | ✅(常時) |
| レート制限なし | ✅ | ✅ | ✅ |
| L1 + 差し替え可能な L2 | ✅ | n/a | n/a |
| wheel サイズ | KB(データ非同梱) | MB(SQLite 同梱) | GeoNames CSV 依存 |

[posuto]: https://github.com/polm/posuto
[posuto-romaji]: https://github.com/polm/posuto#romaji
[pgeocode]: https://github.com/symerio/pgeocode

## 他言語版

全 SDK で同一の API を提供しています:

[Go](https://github.com/jpzip/go) · [TypeScript](https://github.com/jpzip/js) · [Rust](https://github.com/jpzip/rust) · [Ruby](https://github.com/jpzip/ruby) · [PHP](https://github.com/jpzip/php) · [Swift](https://github.com/jpzip/swift) · [Dart](https://github.com/jpzip/dart)

## 関連リソース

- **Web サイト** — https://jpzip.nadai.dev
- **プロトコル仕様** — [jpzip/spec](https://github.com/jpzip/spec)
- **データ ETL** — [jpzip/data](https://github.com/jpzip/data)
- **MCP サーバー** — [jpzip/mcp](https://github.com/jpzip/mcp) — Claude / ChatGPT / Cursor から jpzip を呼ぶ

## キーワード

日本郵便番号, 郵便番号, KEN_ALL, KEN_ALL_ROME, 住所検索, 住所バリデーション, japanese postal code, japan zipcode, python japanese address, async postal code, fastapi zipcode, httpx japanese address, JIS X 0401, 総務省地方公共団体コード

## ライセンス

[MIT](./LICENSE)
