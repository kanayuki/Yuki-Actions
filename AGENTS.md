# AGENTS.md

Guidance for coding agents working in this repository.

## Running the project

Dependencies are managed by **uv** (`pyproject.toml` + `uv.lock`).

Run from the **project root** (`Yuki-Actions/`):

```bash
uv sync                                        # Install dependencies (creates .venv)

uv run python -m proxy run                     # Full pipeline
uv run python -m proxy status                  # Show dataset statistics
uv run python -m proxy collect                 # All sources -> pool
uv run python -m proxy collect --source github_crawler
uv run python -m proxy collect --source subscribe
uv run python -m proxy verify alive            # TCP/DNS -> alive.txt
uv run python -m proxy verify best-remote      # Engine chain -> best_remote.txt
uv run python -m proxy output country          # GeoIP -> country/*.txt
uv run python -m proxy output merge            # Pool -> merge.txt
uv run python -m proxy maintain                # Dormant recheck + repo eval + prune
uv run python -m proxy pac                     # PAC pipeline (independent, legacy)

uv run python -m proxy.new_pac.main            # new_pac pipeline (default = all)
uv run python -m proxy.new_pac.main scan       # web source -> archive -> cache -> urls.yaml
uv run python -m proxy.new_pac.main pull <url> # test a single subscription URL

cd proxy && uv run python local_verify.py dataset/alive.txt   # Local verification
```

The GitHub Actions workflow (`proxy.yml`) runs every 3 hours (UTC 00/03/06/.../21). It has three jobs: the main pipeline, the independent PAC pipeline, and a unified `publish` job that pushes all outputs to the orphan `data` branch exactly once. State persists on the orphan `data` branch.

## Architecture

### Unified pipeline (`proxy/`)

Plugin-based architecture with a **global proxy pool** as the single source of truth.

```
         SOURCES (plugins)                    VIEWS (output)
    ┌─────────────────────┐              ┌──────────────────┐
    │  GitHubCrawlerSource│──┐           │  AliveView       │──→ alive.txt
    │  SubscribeSource    │──┤  ┌──────┐ │  BestRemoteView  │──→ best_remote.txt
    │  (future...)        │──┼──│ POOL │→│  CountryView     │──→ country/*.txt
    └─────────────────────┘  │  └──────┘ │  MergeView       │──→ merge.txt
                             │           └──────────────────┘
    ┌─────────────────────┐  │
    │  PAC / new_pac      │  │  ┌──────────────┐
    └─────────────────────┘  └──│ MAINTENANCE  │ dormant recheck / repo eval / prune
                                └──────────────┘
```

**Data layers** in `proxy/dataset/`:

| Layer | File | Max | Update | Description |
|-------|------|-----|--------|-------------|
| Raw pool | `dataset/raw/raw_YYYYMM.txt` | 10000/file | Every 6h | Append-only, monthly shards |
| Alive | `dataset/alive.txt` | 10000 | Every 12h | TCP/DNS verified (lenient) |
| Best remote | `dataset/best_remote.txt` | 100 | Every 6h | Engine-chain tested |
| Health | `dataset/health.json` | 50000 | Per verify | Per-link health tracking |
| Repo scores | `dataset/repo_scores.json` | — | Per maintain | Repository quality metrics |

**Key design**: Server does lenient TCP/DNS verification to maximize data retention. Failed links become **dormant** (not deleted) and are rechecked weekly. Users run `local_verify.py` to get accurate results for their own network.

### Source plugins (`proxy/sources/`)

Each source implements the `Source` protocol (`_base.py`): `name() -> str` and `collect() -> list[SourceResult]`.

- `github_crawler.py` — discovers GitHub repos via API, fetches subscription files, extracts links
- `subscribe.py` — fetches links from subscription URLs listed in `merge/subscribe_links.txt`

To add a new source: implement `Source` in a new file, register in `sources/__init__.py`.

### View plugins (`proxy/views/`)

Each view implements the `View` protocol (`_base.py`): `name() -> str` and `generate(pool, cfg) -> None`.

- `alive.py` — TCP/DNS verification -> `alive.txt`
- `best_remote.py` — engine-chain test -> `best_remote.txt`
- `country.py` — GeoIP classification -> `country/*.txt`
- `merge.py` — active pool links -> `merge/merge.txt`

To add a new view: implement `View` in a new file, register in `views/__init__.py`.

### Core modules (`proxy/core/`)

Shared library, unchanged:

- `parse.py` — protocol parsers (vmess, vless, ss, trojan, hysteria2, tuic, etc.), converters to clash/xray/singbox formats
- `verify.py` — TCP/DNS-only async verification with Rich progress
- `geo.py` — GeoIP batch resolver via ip-api.com
- `models.py` — `ParsedProxy`, `VerifyResult` dataclasses
- `binary.py` — xray/singbox/mihomo binary management (auto-download from GitHub Releases)

### Engine modules (`proxy/engine/`)

Real proxy connectivity testing via engine chain (xray -> singbox -> mihomo -> tcp fallback).

### Pool manager (`proxy/pool.py`)

Central state: health.json, repo_scores.json, raw pool shards. Provides `ingest()` for sources and query methods (`active_links()`, `all_non_dormant()`, etc.) for views.

### Converter module (`proxy/converter/`)

Rich IR + parsing/rendering engine, shared by PAC pipelines:

- `models.py` — rich IR `Node` (transport/TLS/reality/mux fully modelled)
- `parser/` — 9 source-format parsers (`parse_config(text, ptype, source) -> list[Node]`) + `share_link.py` (`parse_share_link`)
- `generator/` — Node → target format (`clash` supported)
- `compat.py` — bridge to legacy thin IR

### PAC module (`proxy/pac/`) — legacy

**Independent, not part of the unified pipeline.** Run via `python -m proxy pac`. Thin-IR based, being superseded by `new_pac/` (see `proxy/docs/new-pac-module-design.md`).

### new_pac module (`proxy/new_pac/`)

**Next-generation PAC pipeline**, built on `converter/`. Run via `python -m proxy.new_pac.main` (default command = `all` = scan → fetch → render).

Data flow:

```
alvin9999.com 高内核版页面 → 抓取"云盘"下载链接（云盘1/2/3 互为后备）
  → 下载 .7z 到 cache/（同名同大小命中缓存；.part 断点续传；直连优先/代理后备）
  → py7zr 仅解压 ip_Update/ip_*.bat → cache/extracted/
  → scan.py: bat（GBK）→ urls.yaml（结构化，含 bat 路径追溯 + 主备标记）
  → fetch.py: 下载全部 URL → normalize.py 规范化（canonical dump + sha256）→ config_store/YYYY-MM/
  → pool.py: 身份键 protocol:host:port:credential 去重 + GeoIP 命名
  → render.py: converter 生成 clash 节点 → subscribe/clash.yaml（空池保护）
```

Key files:

- `source.py` — web 源（页面抓包/下载/解压）；稳定优先，任一环节失败回退缓存，scan 失败沿用现有 urls.yaml
- `pull.py` — 拉取任意订阅 URL 测试（格式自动识别：分享链接/base64/clash/singbox/xray，跟随一层 clash proxy-providers）
- `urls.yaml` — URL 清单（git 跟踪）；`cache/`、`config_store/`、`subscribe/`、`logs/` 为运行时产物（git 忽略）

稳定性约定：除致命因素（如 urls.yaml 不存在且源不可达、渲染空池退出保护）外，单个不稳定环节的失败不得导致整条流程失败。

### Key conventions

**Health key** — `sha256(protocol:host:port)`, stable identity for deduplication and health tracking.

**Source tag** — `"github:owner/repo"` or `"subscribe:https://..."`, tracks link origin in health store.

**Import paths** — new code uses relative package imports (`from .config import ...`). Legacy bare imports (`from core.parse import ...`) still work via sys.path setup in `__main__.py`.

**Output** — all user-facing output uses `console` from `util.py` (Rich, no highlight).

**Config** — `proxy/config.yaml` (nested Pydantic model). Backwards-compatible with old flat format.

### Config

| File | Purpose |
|---|---|
| `proxy/config.yaml` | Unified pipeline config (sources, pool, verify, engine, output) |
| `proxy/merge/subscribe_links.txt` | Subscription URLs for SubscribeSource |
| `proxy/pac/*_config_links.txt` | Config URLs for legacy PAC pipeline |
| `proxy/new_pac/urls.yaml` | URL manifest for new_pac (generated by scan, git-tracked) |

### Design documentation

- `proxy/docs/dataset_design.md` — dataset crawler design
- `proxy/docs/proxy-converter-design.md` — converter (rich IR) design
- `proxy/docs/new-pac-module-design.md` — new_pac pipeline design
