"""Discover free v2ray subscription URLs from GitHub.

Uses two strategies:
1. Code search — files containing vmess:// or vless:// directly
2. Repo search — popular v2ray/free-proxy repos, then probes common filenames
"""

import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_API = "https://api.github.com"
_RAW = "https://raw.githubusercontent.com"

# Common subscription/node filenames in free-proxy repos
_NODE_FILES = [
    "subscribe.txt",
    "sub.txt",
    "nodes.txt",
    "v2ray.txt",
    "vmess.txt",
    "vless.txt",
    "links.txt",
    "proxy.txt",
    "free.txt",
    "clash.yaml",
    "clash.yml",
    "Base64",
    "sub",
    "subscribe",
]

_REPO_QUERIES = [
    "v2ray free nodes subscribe",
    "free vmess vless subscription",
    "clash free proxy nodes",
]


def _headers() -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token := os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {token}"
    return h


def _has_token() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN"))


def _get(url: str, params: Optional[dict] = None, retries: int = 3) -> Optional[dict]:
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=_headers(), params=params, timeout=15)
            if resp.status_code == 403:
                reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
                wait = max(reset - time.time(), 5)
                logger.warning("GitHub rate limited, waiting %.0fs", wait)
                time.sleep(min(wait, 65))
                continue
            if not resp.ok:
                logger.debug("GitHub %d for %s", resp.status_code, url)
                return None
            return resp.json()
        except Exception as e:
            logger.debug("GitHub request error (attempt %d): %s", attempt + 1, e)
            if attempt < retries - 1:
                time.sleep(2**attempt)
    return None


def _search_repos(max_repos: int = 30) -> list[dict]:
    seen: set[int] = set()
    repos: list[dict] = []
    for query in _REPO_QUERIES:
        if len(repos) >= max_repos:
            break
        data = _get(
            f"{_API}/search/repositories",
            params={"q": query, "sort": "stars", "order": "desc", "per_page": 30},
        )
        if not data:
            continue
        for item in data.get("items", []):
            if item["id"] not in seen and len(repos) < max_repos:
                seen.add(item["id"])
                repos.append(item)
        time.sleep(1)  # avoid hitting secondary rate limits
    logger.info("Repo search found %d repos", len(repos))
    return repos


def _repo_raw_urls(repos: list[dict]) -> list[str]:
    urls: list[str] = []
    for repo in repos:
        owner = repo["owner"]["login"]
        name = repo["name"]
        branch = repo.get("default_branch", "main")
        for filename in _NODE_FILES:
            urls.append(f"{_RAW}/{owner}/{name}/{branch}/{filename}")
    return urls


def _search_code_urls(max_per_query: int = 30) -> list[str]:
    """Search GitHub code for .txt files containing proxy links (requires token)."""
    if not _has_token():
        logger.info("No GITHUB_TOKEN — skipping code search")
        return []

    raw_urls: list[str] = []
    for query in ["vmess:// extension:txt", "vless:// extension:txt"]:
        data = _get(
            f"{_API}/search/code",
            params={"q": query, "per_page": min(max_per_query, 30)},
        )
        if not data:
            continue
        for item in data.get("items", []):
            html = item.get("html_url", "")
            # https://github.com/owner/repo/blob/branch/path → raw URL
            raw = html.replace("https://github.com/", f"{_RAW}/").replace("/blob/", "/")
            if raw:
                raw_urls.append(raw)
        time.sleep(2)  # code search has stricter rate limits

    logger.info("Code search found %d files", len(raw_urls))
    return raw_urls


def get_subscription_urls(max_urls: int = 120) -> list[str]:
    """Return raw GitHub URLs that likely contain v2ray subscription links."""
    # Code search first (most direct — only with token)
    urls = _search_code_urls(max_per_query=30)

    # Repo search + probe common filenames
    repos = _search_repos(max_repos=25)
    urls.extend(_repo_raw_urls(repos))

    # Deduplicate, preserve order
    seen: set[str] = set()
    result: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)

    return result[:max_urls]
