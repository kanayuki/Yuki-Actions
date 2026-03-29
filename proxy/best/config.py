"""Unified configuration for the proxy dataset crawler."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DEFAULT_QUERIES: list[str] = [
    "v2ray free nodes subscribe",
    "free vmess vless subscription stars:>50",
    "clash free proxy nodes stars:>20",
    "v2ray free subscribe pushed:>{recent_7d}",
]

# ── Paths ──

BEST_DIR = Path(__file__).resolve().parent  # proxy/best/
PROXY_DIR = BEST_DIR.parent  # proxy/
DATASET_DIR = PROXY_DIR / "dataset"
RAW_DIR = DATASET_DIR / "raw"
ALIVE_FILE = DATASET_DIR / "alive.txt"
BEST_REMOTE_FILE = DATASET_DIR / "best_remote.txt"
HEALTH_FILE = DATASET_DIR / "health.json"
REPO_SCORES_FILE = DATASET_DIR / "repo_scores.json"
REPOSITORIES_FILE = PROXY_DIR / "repositories.txt"
COUNTRY_DIR = PROXY_DIR / "country"
LOGS_DIR = PROXY_DIR / "logs"
CONFIG_FILE = BEST_DIR / "config.yaml"


class Config(BaseModel):
    """All tuneable parameters for the proxy dataset crawler.

    Parameters not present in config.yaml fall back to defaults here.
    """

    # ── Repository discovery ──
    user_repos: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=lambda: list(_DEFAULT_QUERIES))
    max_search_repos: int = 20

    # ── Raw pool (global repository) ──
    raw_shard_max: int = 10000  # max links per monthly shard

    # ── Alive verification (lenient TCP/DNS) ──
    alive_max: int = 10000  # max entries in alive.txt
    alive_timeout_s: float = 5.0  # TCP/DNS timeout
    alive_concurrency: int = 64  # parallel connections

    # ── Best-remote (engine-chain real test) ──
    best_remote_top: int = 100  # entries in best_remote.txt
    best_remote_batch: int = 500  # how many alive links to test
    test_engine: str = "auto"  # auto | xray | singbox | mihomo | tcp
    test_timeout_ms: int = 6000  # engine test timeout
    test_concurrency: int = 50  # engine test parallelism
    test_url: str = "http://www.gstatic.com/generate_204"

    # ── Health management ──
    max_consecutive_failures: int = 3  # failures before dormant
    dormant_recheck_days: int = 7  # days before rechecking dormant
    health_max_entries: int = 50000  # prune threshold

    # ── Repository quality ──
    repo_min_valid_ratio: float = 0.05
    repo_blacklist_after: int = 3

    # ── Output ──
    country_pool_max: int = 100
    min_country_size: int = 10

    # ── Binary paths (empty = auto-detect) ──
    xray_bin: str = ""
    singbox_bin: str = ""
    mihomo_bin: str = ""

    def resolve_queries(self) -> list[str]:
        """Replace template variables in search queries."""
        recent_7d = (datetime.now(tz=timezone.utc) - timedelta(days=7)).strftime(
            "%Y-%m-%d"
        )
        return [q.replace("{recent_7d}", recent_7d) for q in self.search_queries]


def load_config(path: Path | None = None) -> Config:
    """Load config from YAML file, falling back to defaults."""
    p = path or CONFIG_FILE
    if not p.exists():
        return Config()
    try:
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return Config.model_validate(data)
    except Exception as e:
        logger.warning("Failed to load config from %s: %s — using defaults", p, e)
        return Config()
