"""GitHub repository crawler source.

Discovers free proxy subscription repos via GitHub API, fetches their
subscription files, and extracts proxy share links.

Absorbs: best/discover.py + best/collect.py
"""

from __future__ import annotations

import base64
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from ..config import REPOSITORIES_FILE
from ..pool import RepoScore, _now
from ._base import SourceResult

if TYPE_CHECKING:
    from ..config import Config
    from ..pool import PoolManager

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


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------


def _headers() -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token := os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {token}"
    return h


def _get(
    url: str, params: dict | None = None, retries: int = 3
) -> dict | list | None:
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=_headers(), params=params, timeout=15)
            if resp.status_code == 403:
                reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
                wait = max(reset - time.time(), 5)
                logger.warning("GitHub rate limited, waiting %.0fs", wait)
                time.sleep(min(wait, 65))
                continue
            if resp.status_code == 404:
                return None
            if not resp.ok:
                logger.debug("GitHub HTTP %d for %s", resp.status_code, url)
                return None
            return resp.json()
        except Exception as e:
            logger.debug("GitHub request error (attempt %d): %s", attempt + 1, e)
            if attempt < retries - 1:
                time.sleep(2**attempt)
    return None


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------


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
# HTTP session
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


# ---------------------------------------------------------------------------
# Repo search
# ---------------------------------------------------------------------------


def _search_repos(queries: list[str], max_repos: int) -> list[dict]:
    """Search GitHub for proxy-related repos, sorted by stars."""
    seen: set[int] = set()
    repos: list[dict] = []

    for query in queries:
        if len(repos) >= max_repos:
            break
        data = _get(
            f"{_API}/search/repositories",
            params={"q": query, "sort": "stars", "order": "desc", "per_page": 30},
        )
        if not data or not isinstance(data, dict):
            continue
        for item in data.get("items", []):
            if item["id"] in seen or len(repos) >= max_repos:
                continue
            if item.get("fork"):
                continue
            seen.add(item["id"])
            repos.append(item)
        time.sleep(1)

    logger.info("GitHub search: %d repos found", len(repos))
    return repos


# ---------------------------------------------------------------------------
# Repo scanning
# ---------------------------------------------------------------------------


def _check_raw_url(url: str, full_name: str) -> tuple[str, str] | None:
    text = _fetch_url(url, timeout=4)
    if not text or len(text) < 10:
        return None
    decoded = _decode_content(text)
    if any(s in decoded for s in _KNOWN_SCHEMES):
        return (url, full_name)
    return None


def _scan_all_repos(repos: list[str]) -> dict[str, list[tuple[str, str]]]:
    """Scan all repos in parallel for subscription files."""
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
# GitHubCrawlerSource
# ---------------------------------------------------------------------------


class GitHubCrawlerSource:
    """Discovers GitHub repos, fetches subscription files, extracts proxy links."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    @staticmethod
    def name() -> str:
        return "github_crawler"

    def collect(self) -> list[SourceResult]:
        """Discover repos -> scan for sub files -> extract links."""
        repos = self._discover()
        return self._collect(repos)

    def _discover(self) -> list[str]:
        """Stage 1: discover repos and update scores."""
        cfg = self._cfg
        # Load scores via a temporary pool — scores are repo-specific state
        from ..pool import PoolManager

        pool = PoolManager()
        scores = pool.load_repo_scores()
        now = _now()

        # User repos (always included)
        user_repos = list(cfg.github_crawler.user_repos)
        for repo in user_repos:
            if repo not in scores:
                scores[repo] = RepoScore(source="user", last_seen=now)
            else:
                scores[repo].source = "user"
                scores[repo].last_seen = now

        # Search GitHub
        queries = cfg.github_crawler.resolve_queries()
        search_results = _search_repos(queries, cfg.github_crawler.max_search_repos)

        search_repos: list[str] = []
        for item in search_results:
            full_name = item["full_name"]
            stars = item.get("stargazers_count", 0)

            if (
                full_name in scores
                and scores[full_name].blacklisted
                and full_name not in user_repos
            ):
                logger.info("Skipping blacklisted repo: %s", full_name)
                continue

            if full_name not in scores:
                scores[full_name] = RepoScore(
                    source="search", stars=stars, last_seen=now
                )
            else:
                scores[full_name].stars = stars
                scores[full_name].last_seen = now
            search_repos.append(full_name)

        # Merge and save
        all_repos = list(dict.fromkeys(user_repos + search_repos))
        pool.save_repo_scores(scores)

        REPOSITORIES_FILE.write_text(
            "\n".join(all_repos) + "\n" if all_repos else "",
            encoding="utf-8",
        )

        logger.info(
            "Discover complete: %d user + %d search = %d repos",
            len(user_repos),
            len(search_repos),
            len(all_repos),
        )
        return all_repos

    def _collect(self, repos: list[str]) -> list[SourceResult]:
        """Stage 2: fetch links from repos, return SourceResult per repo."""
        from core.parse import health_key

        if not repos:
            logger.warning("No repos to collect from")
            return []

        # Discover subscription URLs across all repos
        repo_sub_urls = _scan_all_repos(repos)

        # Fetch and extract links
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

        # Deduplicate within this run, build SourceResults per repo
        results: list[SourceResult] = []
        seen_keys: set[str] = set()

        for repo_name, links in repo_links.items():
            deduped: list[str] = []
            for link in links:
                hk = health_key(link)
                if hk and hk not in seen_keys:
                    seen_keys.add(hk)
                    deduped.append(link)
            if deduped:
                results.append(
                    SourceResult(
                        links=deduped,
                        source_tag=f"github:{repo_name}",
                    )
                )

        total = sum(len(r.links) for r in results)
        logger.info(
            "Collect complete: %d links from %d repos",
            total,
            len(results),
        )
        return results
