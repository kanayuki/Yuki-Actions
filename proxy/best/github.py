"""Discover free v2ray subscription URLs from GitHub.

Strategies (in order):
1. Code search — files that literally contain vmess:// or vless:// (requires token)
2. Repo search — popular repos, then use Contents API to find actual subscription files
"""

import logging
import os
import re
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_API = "https://api.github.com"
_RAW = "https://raw.githubusercontent.com"

# Patterns for filenames that are likely subscription/node lists
_SUB_NAME_RE = re.compile(
    r"(subscribe|subscrib|sub|nodes?|vmess|vless|proxy|proxies|clash|links?|free|v2ray)",
    re.IGNORECASE,
)
_SUB_EXT = {".txt", ".yaml", ".yml", ""}  # extensionless files like "sub", "Base64"

_REPO_QUERIES = [
    "v2ray free nodes subscribe",
    "free vmess vless subscription stars:>10",
    "clash free proxy nodes stars:>5",
]


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token := os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {token}"
    return h


def _has_token() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN"))


def _get(url: str, params: Optional[dict] = None, retries: int = 3) -> Optional[dict | list]:
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
# Strategy 1: Code search
# ---------------------------------------------------------------------------


def _search_code_urls(max_per_query: int = 30) -> list[str]:
    """Search for .txt files that literally contain vmess:// or vless://."""
    if not _has_token():
        logger.info("No GITHUB_TOKEN — skipping code search")
        return []

    raw_urls: list[str] = []
    for query in ["vmess:// extension:txt", "vless:// extension:txt", "ss:// extension:txt"]:
        data = _get(
            f"{_API}/search/code",
            params={"q": query, "per_page": min(max_per_query, 30)},
        )
        if not data or not isinstance(data, dict):
            continue
        for item in data.get("items", []):
            html = item.get("html_url", "")
            # https://github.com/owner/repo/blob/branch/path → raw URL
            raw = html.replace("https://github.com/", f"{_RAW}/").replace("/blob/", "/")
            if raw and raw not in raw_urls:
                raw_urls.append(raw)
        time.sleep(2)  # code search is rate-limited harder

    logger.info("Code search: %d candidate files", len(raw_urls))
    return raw_urls


# ---------------------------------------------------------------------------
# Strategy 2: Repo search + Contents API
# ---------------------------------------------------------------------------


def _is_sub_file(name: str) -> bool:
    """True if the filename looks like a subscription/node list."""
    stem, ext = os.path.splitext(name)
    if ext.lower() not in _SUB_EXT:
        return False
    return bool(_SUB_NAME_RE.search(stem or name))


def _repo_sub_urls(owner: str, repo: str, branch: str) -> list[str]:
    """List root-level files via Contents API, return raw URLs of subscription candidates."""
    data = _get(f"{_API}/repos/{owner}/{repo}/contents/")
    if not data or not isinstance(data, list):
        return []
    urls = []
    for item in data:
        if item.get("type") == "file" and _is_sub_file(item["name"]):
            dl = item.get("download_url")
            if dl:
                urls.append(dl)
    return urls


def _search_repos(max_repos: int = 20) -> list[dict]:
    seen: set[int] = set()
    repos: list[dict] = []
    for query in _REPO_QUERIES:
        if len(repos) >= max_repos:
            break
        data = _get(
            f"{_API}/search/repositories",
            params={"q": query, "sort": "stars", "order": "desc", "per_page": 30},
        )
        if not data or not isinstance(data, dict):
            continue
        for item in data.get("items", []):
            if item["id"] not in seen and len(repos) < max_repos:
                seen.add(item["id"])
                repos.append(item)
        time.sleep(1)
    logger.info("Repo search: %d repos", len(repos))
    return repos


def _repo_strategy_urls(repos: list[dict]) -> list[str]:
    urls: list[str] = []
    for repo in repos:
        owner = repo["owner"]["login"]
        name = repo["name"]
        branch = repo.get("default_branch", "main")
        found = _repo_sub_urls(owner, name, branch)
        if found:
            logger.debug("%s/%s: %d subscription files", owner, name, len(found))
        urls.extend(found)
        time.sleep(0.3)  # be polite to Contents API
    return urls


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_subscription_urls(max_urls: int = 150) -> list[str]:
    """Return raw URLs that likely contain v2ray subscription content."""
    urls: list[str] = []

    # Strategy 1: code search (direct, highest quality)
    urls.extend(_search_code_urls(max_per_query=30))

    # Strategy 2: popular repos → actual files via Contents API
    repos = _search_repos(max_repos=20)
    urls.extend(_repo_strategy_urls(repos))

    # Deduplicate, preserve order
    seen: set[str] = set()
    result: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)

    return result[:max_urls]
