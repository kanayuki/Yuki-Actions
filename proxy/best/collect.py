"""Stage 2: Collect -- fetch subscription links from discovered repos.

Reads repositories.txt, fetches subscription files from each repo, extracts
proxy share links, and appends new links to the raw pool (monthly shards).

Usage: python -m best collect
"""

from __future__ import annotations

import base64
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from .config import REPOSITORIES_FILE, Config, load_config
from .state import StateManager

logger = logging.getLogger(__name__)

_API = "https://api.github.com"
_RAW = "https://raw.githubusercontent.com"

_KNOWN_SCHEMES = (
    "vmess://",
    "vless://",
    "ss://",
    "trojan://",
    "hysteria://",
    "hysteria2://",
    "tuic://",
    "anytls://",
    "mieru://",
)

_B64_RE = re.compile(r"^[A-Za-z0-9+/=\r\n]+$")

_SUB_NAME_RE = re.compile(
    r"(subscribe|subscrib|sub|nodes?|vmess|vless|proxy|proxies|clash|links?|free|v2ray|base64|ss)",
    re.IGNORECASE,
)
_SUB_EXTS = {".txt", ".yaml", ".yml", ""}

_COMMON_RAW_PATHS = [
    "sub",
    "sub.txt",
    "subscribe",
    "subscribe.txt",
    "node",
    "node.txt",
    "nodes",
    "nodes.txt",
    "base64",
    "base64.txt",
    "v2ray",
    "v2ray.txt",
    "vmess",
    "vmess.txt",
    "vless.txt",
    "proxy",
    "proxy.txt",
    "proxies.txt",
    "clash.yaml",
    "clash.txt",
    "share/all.txt",
    "sub/sub",
    "sub/sub.txt",
    "sub/base64",
    "merge/merge.txt",
    "subscription/v2ray",
]


def _headers() -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token := os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {token}"
    return h


def _decode_content(text: str) -> str:
    """Attempt base64 decode if content looks like pure base64."""
    compact = text.replace("\n", "").replace("\r", "")
    if _B64_RE.match(compact) and len(compact) > 20:
        try:
            decoded = base64.b64decode(compact + "==").decode("utf-8")
            if any(s in decoded for s in _KNOWN_SCHEMES):
                return decoded
        except Exception:
            pass
    return text


def _extract_links(text: str) -> list[str]:
    """Extract proxy share links from raw text."""
    text = _decode_content(text)
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and any(line.strip().startswith(s) for s in _KNOWN_SCHEMES)
    ]


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        from requests.adapters import HTTPAdapter

        _session = requests.Session()
        _session.verify = False
        _session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0"
        )
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
        _session.mount("https://", adapter)
        _session.mount("http://", adapter)
    return _session


def _fetch_url(url: str, timeout: float = 8) -> str | None:
    try:
        resp = _get_session().get(url, timeout=timeout)
        if resp.ok:
            return resp.text
    except Exception as e:
        logger.debug("Fetch failed %s: %s", url, e)
    return None


def _check_raw_url(url: str, full_name: str) -> tuple[str, str] | None:
    """Check a single raw URL for proxy links."""
    text = _fetch_url(url, timeout=4)
    if not text or len(text) < 10:
        return None
    decoded = _decode_content(text)
    if any(s in decoded for s in _KNOWN_SCHEMES):
        return (url, full_name)
    return None


def _scan_all_repos(repos: list[str]) -> dict[str, list[tuple[str, str]]]:
    """Scan ALL repos in parallel for subscription files.

    Probes common raw URLs directly -- tries main branch, then master.
    """
    tasks: list[tuple[str, str]] = []
    for repo_name in repos:
        parts = repo_name.split("/", 1)
        if len(parts) != 2:
            continue
        owner, name = parts
        for path in _COMMON_RAW_PATHS:
            tasks.append((f"{_RAW}/{owner}/{name}/main/{path}", repo_name))

    results: dict[str, list[tuple[str, str]]] = {r: [] for r in repos}

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {
            pool.submit(_check_raw_url, url, rn): (url, rn) for url, rn in tasks
        }
        for f in as_completed(futures):
            r = f.result()
            if r:
                url, full_name = r
                results[full_name].append(r)
                logger.info("  Found: %s", url)

    # Retry empty repos with master branch
    empty_repos = [r for r in repos if not results.get(r)]
    if empty_repos:
        retry_tasks: list[tuple[str, str]] = []
        for repo_name in empty_repos:
            parts = repo_name.split("/", 1)
            if len(parts) != 2:
                continue
            owner, name = parts
            for path in _COMMON_RAW_PATHS:
                retry_tasks.append(
                    (f"{_RAW}/{owner}/{name}/master/{path}", repo_name)
                )

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = {
                pool.submit(_check_raw_url, url, rn): (url, rn)
                for url, rn in retry_tasks
            }
            for f in as_completed(futures):
                r = f.result()
                if r:
                    url, full_name = r
                    results[full_name].append(r)
                    logger.info("  Found (master): %s", url)

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect(
    cfg: Config | None = None, state: StateManager | None = None
) -> list[str]:
    """Run Stage 2: fetch links from repos and append to raw pool.

    Returns list of all collected share links (deduplicated within this run).
    """
    from core.parse import health_key

    cfg = cfg or load_config()
    state = state or StateManager()
    health = state.load_health()

    # Load repos
    repos: list[str] = []
    if REPOSITORIES_FILE.exists():
        repos = [
            line.strip()
            for line in REPOSITORIES_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and "/" in line
        ]
    if not repos:
        logger.warning("No repos in %s, run 'discover' first", REPOSITORIES_FILE)
        return []

    # Discover subscription URLs across all repos in parallel
    repo_sub_urls = _scan_all_repos(repos)

    # Fetch and extract links from discovered URLs
    repo_links: dict[str, list[str]] = {}

    fetch_tasks: list[tuple[str, str]] = []
    for repo_name, url_pairs in repo_sub_urls.items():
        for url, _ in url_pairs:
            fetch_tasks.append((url, repo_name))

    def _fetch_and_extract(url: str) -> tuple[str, list[str]]:
        text = _fetch_url(url, timeout=8)
        if text:
            return url, _extract_links(text)
        return url, []

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_fetch_and_extract, url): (url, rn)
            for url, rn in fetch_tasks
        }
        for f in as_completed(futures):
            url, rn = futures[f]
            _, links = f.result()
            if links:
                repo_links.setdefault(rn, []).extend(links)
                logger.info("  %s -> %d links", url, len(links))

    # Flatten and deduplicate within this run
    all_links: list[str] = []
    seen_keys: set[str] = set()
    link_to_repo: dict[str, str] = {}

    for repo_name, links in repo_links.items():
        for link in links:
            hk = health_key(link)
            if hk and hk not in seen_keys:
                seen_keys.add(hk)
                all_links.append(link)
                link_to_repo[link] = repo_name

    # Append to raw pool (dedup against health, create health entries)
    new_count = state.append_to_raw(all_links, health, cfg.raw_shard_max)

    # Set source_repo for newly created entries
    for link, repo_name in link_to_repo.items():
        hk = health_key(link)
        if hk and hk in health and not health[hk].source_repo:
            health[hk].source_repo = repo_name

    state.save_health(health)

    logger.info(
        "Collect complete: %d links from %d repos, %d new added to raw pool",
        len(all_links),
        len(repos),
        new_count,
    )
    return all_links
