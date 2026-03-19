# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the project

All scripts must be run from the **`proxy/`** directory (it is the working directory assumed by all imports and relative file paths):

```bash
cd proxy
pip install requests pyyaml rich
python main.py
```

Run individual modules standalone for debugging:

```bash
cd proxy
python xray.py                     # fetch & print xray share links
python clash.py                    # fetch & print clash share links
python verify.py share_links.txt   # verify connectivity with rich progress + results table
python merge/merge.py              # fetch subscriptions, verify, save filtered links
```

The GitHub Actions workflow (`proxy-script.yml`) runs `python proxy/main.py` from the repo root and commits `share_links.txt`, `share_link_keys.txt`, `proxy/share_link_health.json`, and `proxy/merge/`. It fires at UTC 00:00 and 12:00.

## Architecture

### Two-pipeline design

**Pipeline 1 — Config → Share links** (`gen_share_links.py` → `share_links.txt`)

Each proxy-type module (`xray.py`, `clash.py`, `hysteria.py`, `singbox.py`, `mieru.py`) fetches raw config JSON/YAML from URLs listed in a corresponding `proxy/*_config_links.txt` file, parses it, and emits `(key, share_link)` tuples. The `@load_all_config(file)` decorator in `util.py` handles fetching all URLs and calling the decorated function per config.

`gen_share_links.py` merges all new links with `share_links.txt`, deduplicates by `health_key = sha256(protocol:host:port)` (stable across daily remark rotation), **verifies real connectivity on every run**, and applies a **3-consecutive-failure rule** before removing a link. State persists in `proxy/share_link_health.json`. Output is sorted by latency; pending-removal links (fail count 1–2) are appended after valid ones.

**Pipeline 2 — Subscription merge + verify** (`merge/merge.py` → `merge/merge_share_links_filter.txt`)

Reads subscription URLs from `proxy/merge/subscribe_links.txt`, fetches links (decoding base64 if needed), merges with the existing `merge_share_links_filter.txt`, deduplicates, then verifies and discards dead ones. Output sorted by latency. No failure-count grace period — one failure = removed.

### Key conventions

**Health key** — identity for the 3-failure rule is `sha256(protocol:host:port)` derived via `parse_link()`, stable across vmess base64 remark rotation and daily remark string changes. Stored in `proxy/share_link_health.json` as `{health_key: consecutive_fail_count}`.

**Protocol key vs health key** — `gen_*_share_link()` returns a protocol-level dedup key (`sha256(url)` or `sha256(protocol:addr:port:uuid)` for vmess) used only in `share_link_keys.txt`. The health key is a separate, connectivity-focused identity.

**`util.py` shared exports** — `console` (shared `rich.Console` instance, imported by all modules), `get_config(url)` (fetches remote config, SSL disabled, correct User-Agent), `gen_remark(address, postfix)` (calls ip-api.com, cached), `get_hash(s)` (SHA-256 hex).

**`verify.py` connectivity logic** — TCP-based protocols (vless, vmess, ss, trojan, anytls, mieru) use `asyncio.open_connection`; UDP-based (hysteria, hysteria2, tuic) use DNS resolution. `verify_links_async()` accepts an `_on_done` callback for the rich progress bar in the sync `verify_links()` wrapper. Concurrency semaphore-limited (default 64).

**Import paths** — all `proxy/*.py` modules import each other by bare name; requires CWD or `sys.path` to include `proxy/`. `merge/merge.py` inserts `Path(__file__).parent.parent` into `sys.path` to reach `verify.py` and `util.py`.

**Output** — all user-facing output uses the shared `console` from `util.py` (rich, no highlight). `verify_links()` shows an animated progress bar. `gen_share_links.update()` and `merge.main()` print `Rule` section headers and a summary `Panel`.

### Config URL files

| File | Fed to |
|---|---|
| `proxy/xray_config_links.txt` | `xray.py` |
| `proxy/clash_config_links.txt` | `clash.py` |
| `proxy/hysteria_config_links.txt` | `hysteria.py` |
| `proxy/singbox_config_links.txt` | `singbox.py` |
| `proxy/merge/subscribe_links.txt` | `merge/merge.py` (base64 subscriptions) |

Adding a new config source = append its URL to the relevant `.txt` file. Adding a new protocol = add a `gen_*_share_link(config) -> tuple[key, url]` function and register it in the module's `protocol_map`, then add the scheme to `verify.py`'s `_PARSERS`.
