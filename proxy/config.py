"""Unified configuration for all proxy pipelines (except PAC)."""

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

PROXY_DIR = Path(__file__).resolve().parent  # proxy/
DATASET_DIR = PROXY_DIR / "dataset"
RAW_DIR = DATASET_DIR / "raw"
ALIVE_FILE = DATASET_DIR / "alive.txt"
BEST_REMOTE_FILE = DATASET_DIR / "best_remote.txt"
HEALTH_FILE = DATASET_DIR / "health.json"
REPO_SCORES_FILE = DATASET_DIR / "repo_scores.json"
REPOSITORIES_FILE = PROXY_DIR / "repositories.txt"
COUNTRY_DIR = PROXY_DIR / "country"
MERGE_FILE = PROXY_DIR / "merge" / "merge.txt"
LOGS_DIR = PROXY_DIR / "logs"
CONFIG_FILE = PROXY_DIR / "config.yaml"


# ── Config sections ──


class GitHubCrawlerConfig(BaseModel):
    """Settings for the GitHub repository crawler source."""

    enabled: bool = True
    user_repos: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_QUERIES)
    )
    max_search_repos: int = 20

    def resolve_queries(self) -> list[str]:
        """Replace template variables in search queries."""
        recent_7d = (
            datetime.now(tz=timezone.utc) - timedelta(days=7)
        ).strftime("%Y-%m-%d")
        return [q.replace("{recent_7d}", recent_7d) for q in self.search_queries]


class SubscribeConfig(BaseModel):
    """Settings for the subscription URL source."""

    enabled: bool = True
    subscribe_file: str = "merge/subscribe_links.txt"


class PoolConfig(BaseModel):
    """Settings for the global proxy pool."""

    raw_shard_max: int = 10000
    health_max_entries: int = 50000


class VerifyConfig(BaseModel):
    """Settings for TCP/DNS alive verification."""

    alive_timeout_s: float = 5.0
    alive_concurrency: int = 64
    alive_max: int = 10000
    max_consecutive_failures: int = 3
    dormant_recheck_days: int = 7


class EngineConfig(BaseModel):
    """Settings for engine-chain real connection testing."""

    test_engine: str = "auto"
    test_timeout_ms: int = 6000
    test_concurrency: int = 50
    test_url: str = "http://www.gstatic.com/generate_204"
    best_remote_top: int = 100
    best_remote_batch: int = 500


class OutputConfig(BaseModel):
    """Settings for output views (country, merge, etc.)."""

    country_pool_max: int = 100
    min_country_size: int = 10


class RepoQualityConfig(BaseModel):
    """Settings for repository quality evaluation."""

    repo_min_valid_ratio: float = 0.05
    repo_blacklist_after: int = 3


class Config(BaseModel):
    """Unified configuration for all proxy pipelines."""

    github_crawler: GitHubCrawlerConfig = Field(
        default_factory=GitHubCrawlerConfig
    )
    subscribe: SubscribeConfig = Field(default_factory=SubscribeConfig)
    pool: PoolConfig = Field(default_factory=PoolConfig)
    verify: VerifyConfig = Field(default_factory=VerifyConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    repo_quality: RepoQualityConfig = Field(default_factory=RepoQualityConfig)

    # Binary paths (empty = auto-detect)
    xray_bin: str = ""
    singbox_bin: str = ""
    mihomo_bin: str = ""


# ── Flat-to-nested migration mapping ──

_FLAT_TO_NESTED: dict[str, tuple[str, str]] = {
    "user_repos": ("github_crawler", "user_repos"),
    "search_queries": ("github_crawler", "search_queries"),
    "max_search_repos": ("github_crawler", "max_search_repos"),
    "raw_shard_max": ("pool", "raw_shard_max"),
    "health_max_entries": ("pool", "health_max_entries"),
    "alive_timeout_s": ("verify", "alive_timeout_s"),
    "alive_concurrency": ("verify", "alive_concurrency"),
    "alive_max": ("verify", "alive_max"),
    "max_consecutive_failures": ("verify", "max_consecutive_failures"),
    "dormant_recheck_days": ("verify", "dormant_recheck_days"),
    "test_engine": ("engine", "test_engine"),
    "test_timeout_ms": ("engine", "test_timeout_ms"),
    "test_concurrency": ("engine", "test_concurrency"),
    "test_url": ("engine", "test_url"),
    "best_remote_top": ("engine", "best_remote_top"),
    "best_remote_batch": ("engine", "best_remote_batch"),
    "country_pool_max": ("output", "country_pool_max"),
    "min_country_size": ("output", "min_country_size"),
    "repo_min_valid_ratio": ("repo_quality", "repo_min_valid_ratio"),
    "repo_blacklist_after": ("repo_quality", "repo_blacklist_after"),
}


def _migrate_flat_config(data: dict) -> dict:
    """Convert flat (old best/config.yaml) format to nested format."""
    # If already nested (has any section key), return as-is
    section_keys = {
        "github_crawler",
        "subscribe",
        "pool",
        "verify",
        "engine",
        "output",
        "repo_quality",
    }
    if any(k in data for k in section_keys):
        return data

    nested: dict = {}
    for key, value in data.items():
        if key in _FLAT_TO_NESTED:
            section, field = _FLAT_TO_NESTED[key]
            nested.setdefault(section, {})[field] = value
        elif key in ("xray_bin", "singbox_bin", "mihomo_bin"):
            nested[key] = value
        else:
            logger.warning("Unknown config key: %s (ignored)", key)
    return nested


def load_config(path: Path | None = None) -> Config:
    """Load config from YAML file, falling back to defaults.

    Supports both the old flat format (best/config.yaml) and the new
    nested format. Flat keys are automatically migrated.
    """
    p = path or CONFIG_FILE
    if not p.exists():
        return Config()
    try:
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        data = _migrate_flat_config(data)
        return Config.model_validate(data)
    except Exception as e:
        logger.warning("Failed to load config from %s: %s -- using defaults", p, e)
        return Config()
