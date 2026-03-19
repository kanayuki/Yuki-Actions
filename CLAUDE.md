# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the project

All scripts must be run from the **`proxy/`** directory (it is the working directory assumed by all imports and relative file paths):

```bash
cd proxy
pip install requests pyyaml
python main.py
```

Run individual modules standalone for debugging:

```bash
cd proxy
python xray.py        # fetch & print xray share links
python clash.py       # fetch & print clash share links
python verify.py share_links.txt   # verify connectivity of a links file
python merge/merge.py              # fetch subscriptions, verify, save filtered links
```

The GitHub Actions workflow (`proxy-script.yml`) runs `python proxy/main.py` from the repo root and commits `share_links.txt`, `share_link_keys.txt`, `proxy/backup/`, and `proxy/merge/`. It fires at UTC 00:00 and 12:00.

## Architecture

### Two-pipeline design

**Pipeline 1 — Config → Share links** (`gen_share_links.py` → `share_links.txt`)

Each proxy-type module (`xray.py`, `clash.py`, `hysteria.py`, `singbox.py`, `mieru.py`) fetches raw config JSON/YAML from URLs listed in a corresponding `proxy/*_config_links.txt` file, parses it, and emits `(key, share_link)` tuples. The `@load_all_config(file)` decorator in `util.py` handles fetching all URLs and iterating the decorated function over each config.

`gen_share_links.py` calls `get_all_links()` from every module, deduplicates via SHA-256 key (stored in `share_link_keys.txt`), and appends only new links to `share_links.txt`.

**Pipeline 2 — Subscription merge + verify** (`merge/merge.py` → `merge/merge_share_links_filter.txt`)

Reads subscription URLs from `proxy/merge/subscribe_links.txt`, fetches links (decoding base64 if needed), merges with the existing cached `merge_share_links_filter.txt`, deduplicates, then runs `verify.filter_valid_links()` to TCP-connect each proxy and discard dead ones. Output is sorted by latency.

### Key conventions

**Deduplication key** — every `gen_*_share_link()` function returns `(key, url)`. The key is `sha256(url_without_remark)` for most protocols, or `sha256(protocol:addr:port:uuid)` for vmess. Keys persist in `share_link_keys.txt` to avoid re-adding known links across runs.

**`util.py` shared helpers** — `get_config(url)` fetches a remote config with SSL verification disabled; `gen_remark(address, postfix)` calls `ip-api.com` (cached via `lru_cache`) to get country code and builds a remark string like `CN_20260319_xray`; `get_hash(s)` returns SHA-256 hex.

**`verify.py` connectivity logic** — TCP-based protocols (vless, vmess, ss, trojan, anytls, mieru) use `asyncio.open_connection`; UDP-based protocols (hysteria, hysteria2, tuic) use DNS resolution only. Concurrency is semaphore-limited (default 64). Entry points: `verify_links()` (sync) and `verify_links_async()` (async).

**Import paths** — all `proxy/*.py` modules import each other with bare names (e.g. `from util import ...`) — this only works when the CWD or `sys.path` includes `proxy/`. `merge/merge.py` inserts `Path(__file__).parent.parent` into `sys.path` to reach `verify.py`.

### Config URL files

| File | Fed to |
|---|---|
| `proxy/xray_config_links.txt` | `xray.py` |
| `proxy/clash_config_links.txt` | `clash.py` |
| `proxy/hysteria_config_links.txt` | `hysteria.py` |
| `proxy/singbox_config_links.txt` | `singbox.py` |
| `proxy/merge/subscribe_links.txt` | `merge/merge.py` (base64 subscriptions) |

Adding a new config source = append its URL to the relevant `.txt` file. Adding a new protocol = add a `gen_*_share_link(config) -> tuple[key, url]` function and register it in the module's `protocol_map`.
