# Proxy Dataset Crawler -- Design Document

## Overview

The proxy dataset crawler is a multi-stage pipeline that discovers free proxy nodes from GitHub repositories, collects their share links, verifies connectivity, and maintains a structured dataset.

The system addresses a key challenge: **server-side verification results often differ from local network conditions**. A proxy reachable from GitHub Actions (US data center) may be blocked locally, and vice versa. The design mitigates this by:

1. **Server does lenient verification** (TCP/DNS only) to maximize data retention
2. **Raw pool is append-only** -- data is never deleted from the global repository
3. **Failed links become dormant**, not deleted -- they get rechecked periodically
4. **Local verification tool** lets users generate their own best list for their network

## Architecture

```
GitHub Search -> [discover] -> repositories.txt
                     |
               [collect] -> dataset/raw/raw_YYYYMM.txt (append-only)
                     |          + health.json (new entries)
          +----------+----------+
          |                     |
    [alive_check]          [best_remote_check]
    TCP/DNS lenient         Engine chain real test
          |                     |
    dataset/alive.txt      dataset/best_remote.txt
    (<=10000, by latency)  (top 100, UNSTABLE)
          |
    [rank] -> country/*.txt (GeoIP grouping)

    [maintain] -> dormant recheck + repo eval (weekly)

    [local_verify.py] -> user runs locally -> my_best.txt
```

## Data Layers

### 1. Raw Pool (`dataset/raw/`)

- **Purpose**: Global repository of ALL discovered proxy links
- **Policy**: Append-only, never deleted. Deduplicated by `health_key = sha256(protocol:host:port)`
- **Sharding**: By UTC month -- `raw_YYYYMM.txt`. Max 10000 links per file; overflow creates `raw_YYYYMM_2.txt`
- **Update frequency**: Every 6 hours (discover + collect)

### 2. Alive Pool (`dataset/alive.txt`)

- **Purpose**: Links verified reachable via TCP/DNS from the server
- **Policy**: Max 10000 entries, sorted by latency ascending
- **Verification**: TCP `connect()` for TCP protocols, DNS `getaddrinfo()` for UDP protocols
- **Failure handling**: 3 consecutive failures -> link becomes dormant (not deleted)
- **Update frequency**: Every 12 hours

### 3. Best Remote (`dataset/best_remote.txt`)

- **Purpose**: Quick backup of server-tested proxies via real engine chain
- **Policy**: Top 100 by latency from engine-chain test (xray -> singbox -> mihomo -> tcp)
- **IMPORTANT**: Results are UNSTABLE -- they reflect server network conditions, not user's local network
- **Update frequency**: Every 6 hours

### 4. Health Store (`dataset/health.json`)

- **Purpose**: Per-link health tracking for the entire dataset
- **Fields per entry**:
  - `link`, `protocol`, `host`, `port` -- identity
  - `country`, `source_repo` -- metadata
  - `fail_count` -- consecutive failures (0 = healthy)
  - `last_verified`, `last_ok` -- timestamps
  - `latency_ms`, `latency_history` (last 5) -- performance
  - `first_seen` -- discovery date
  - `dormant`, `dormant_since` -- dormant state
- **Pruning**: When exceeding 50000 entries, oldest never-connected dormant entries are removed

### 5. Repo Scores (`dataset/repo_scores.json`)

- **Purpose**: Quality tracking per source repository
- **Fields**: valid_ratio_history, low_quality_streak, blacklisted, contribution counts
- **Blacklisting**: 3 consecutive low-quality evaluations (< 5% valid ratio) -> repo blacklisted (except user-specified repos)

## Pipeline Stages

### Stage 1: Discover (`best/discover.py`)

Searches GitHub for proxy repositories using configurable queries. Maintains repo scores. Outputs `repositories.txt`.

### Stage 2: Collect (`best/collect.py`)

Scans repositories for subscription files, extracts proxy share links, deduplicates, and appends to the raw pool. Creates health entries for new links.

### Stage 3a: Alive Check (`best/checker.py::alive_check`)

TCP/DNS-only verification of all non-dormant links. Updates health entries. Generates `alive.txt`.

### Stage 3b: Best Remote (`best/checker.py::best_remote_check`)

Real engine-chain test on top alive links. Generates `best_remote.txt`. Uses xray/singbox/mihomo binaries with TCP fallback.

### Stage 4: Rank (`best/rank.py`)

Resolves GeoIP for unknown hosts, groups by country, generates `country/*.txt` files.

### Stage 5: Maintain (`best/maintain.py`)

Rechecks dormant links (weekly), evaluates repo quality, prunes oversized health store.

## Scheduling (GitHub Actions)

Cron: `0 0,6,12,18 * * *` (every 6 hours UTC)

| UTC Hour | Tasks |
|----------|-------|
| Every 6h | discover, collect, best-remote, rank |
| 00, 12 | + alive check, + Pipeline 1 (main.py) |
| Sunday 00 | + maintain |

## Local Verification

```bash
cd proxy
python local_verify.py dataset/alive.txt --top 100 --output my_best.txt
python local_verify.py dataset/alive.txt --engine mihomo --timeout 8000
```

This is the recommended way to get accurate results for your network. The server-generated `best_remote.txt` is a quick but unreliable backup.

## Configuration (`best/config.yaml`)

All parameters have sensible defaults. Only override what you need:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `raw_shard_max` | 10000 | Max links per monthly shard |
| `alive_max` | 10000 | Max entries in alive.txt |
| `alive_timeout_s` | 5.0 | TCP/DNS timeout |
| `alive_concurrency` | 64 | Parallel alive checks |
| `best_remote_top` | 100 | Entries in best_remote.txt |
| `best_remote_batch` | 500 | Alive links to engine-test |
| `test_engine` | auto | Engine selection |
| `test_timeout_ms` | 6000 | Engine test timeout |
| `test_concurrency` | 50 | Engine test parallelism |
| `max_consecutive_failures` | 3 | Failures before dormant |
| `dormant_recheck_days` | 7 | Days before rechecking dormant |
| `health_max_entries` | 50000 | Health store prune threshold |

## CLI

```bash
cd proxy
python -m best discover          # Stage 1
python -m best collect           # Stage 2
python -m best alive             # Stage 3a
python -m best best-remote       # Stage 3b
python -m best rank              # Stage 4
python -m best maintain          # Stage 5
python -m best crawl             # Full pipeline
python -m best status            # Show dataset statistics
```

## Key Design Decisions

1. **Server does lenient, local does precise** -- solves the network path mismatch problem
2. **Dormant instead of delete** -- failed links get a second chance on weekly recheck
3. **Monthly sharding** -- natural time dimension, predictable file sizes, easy cleanup
4. **Health key = sha256(protocol:host:port)** -- stable identity across remark rotation
5. **Engine chain fallback** -- xray -> singbox -> mihomo -> tcp ensures maximum coverage
