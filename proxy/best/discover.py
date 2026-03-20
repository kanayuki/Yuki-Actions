"""Stage 1: Discover — search GitHub for free proxy subscription repos.

Merges user-specified repos with auto-discovered repos. Updates repo_scores.json.

Usage: python -m best discover
"""

from __future__ import annotations

import logging
import os
import re
import time

import requests

from .config import REPOSITORIES_FILE, Config, load_config
from .state import RepoScore, StateManager, _now

logger = logging.getLogger(__name__)

_API = "https://api.github.com"


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token := os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {token}"
    return h


def _get(url: str, params: dict | None = None, retries: int = 3) -> dict | list | None:
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
            # Skip forks and inactive repos
            if item.get("fork"):
                continue
            seen.add(item["id"])
            repos.append(item)
        time.sleep(1)

    logger.info("GitHub search: %d repos found", len(repos))
    return repos


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover(cfg: Config | None = None, state: StateManager | None = None) -> list[str]:
    """Run Stage 1: discover repos and update scores.

    Returns list of ``owner/repo`` strings.
    """
    cfg = cfg or load_config()
    state = state or StateManager()
    scores = state.load_repo_scores()
    now = _now()

    # 1. User repos (always included)
    user_repos = list(cfg.user_repos)
    for repo in user_repos:
        if repo not in scores:
            scores[repo] = RepoScore(source="user", last_seen=now)
        else:
            scores[repo].source = "user"
            scores[repo].last_seen = now

    # 2. Search GitHub
    queries = cfg.resolve_queries()
    search_results = _search_repos(queries, cfg.max_search_repos)

    search_repos: list[str] = []
    for item in search_results:
        full_name = item["full_name"]
        stars = item.get("stargazers_count", 0)

        # Skip blacklisted (unless user-specified)
        if full_name in scores and scores[full_name].blacklisted and full_name not in user_repos:
            logger.info("Skipping blacklisted repo: %s", full_name)
            continue

        if full_name not in scores:
            scores[full_name] = RepoScore(source="search", stars=stars, last_seen=now)
        else:
            scores[full_name].stars = stars
            scores[full_name].last_seen = now
        search_repos.append(full_name)

    # 3. Merge
    all_repos = list(dict.fromkeys(user_repos + search_repos))

    # 4. Save
    state.save_repo_scores(scores)

    REPOSITORIES_FILE.write_text(
        "\n".join(all_repos) + "\n" if all_repos else "",
        encoding="utf-8",
    )

    logger.info(
        "Discover complete: %d user + %d search = %d repos",
        len(user_repos), len(search_repos), len(all_repos),
    )
    return all_repos
