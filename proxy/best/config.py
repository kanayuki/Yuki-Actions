"""Unified configuration for the best proxy pipeline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


_DEFAULT_QUERIES: list[str] = [
    "v2ray free nodes subscribe",
    "free vmess vless subscription stars:>50",
    "clash free proxy nodes stars:>20",
    "v2ray free subscribe pushed:>{recent_7d}",
]


class Config(BaseModel):
    # ── repos ──
    user_repos: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=lambda: list(_DEFAULT_QUERIES))
    max_search_repos: int = 20

    # ── verify ──
    test_engine: str = "auto"
    test_timeout_ms: int = 6000
    test_concurrency: int = 50
    test_url: str = "http://www.gstatic.com/generate_204"
    batch_size: int = 500

    # ── health ──
    max_consecutive_failures: int = 3
    health_recheck_interval_min: int = 60

    # ── repo quality ──
    repo_min_valid_ratio: float = 0.05
    repo_blacklist_after: int = 3

    # ── output ──
    top_n: int = 100
    country_pool_max: int = 100
    min_country_size: int = 10

    # ── binary paths (empty = auto-detect) ──
    xray_bin: str = ""
    singbox_bin: str = ""
    mihomo_bin: str = ""

    def resolve_queries(self) -> list[str]:
        """Replace template variables in search queries."""
        recent_7d = (datetime.now(tz=timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        return [q.replace("{recent_7d}", recent_7d) for q in self.search_queries]


# ── Paths ──

BEST_DIR = Path(__file__).resolve().parent          # proxy/best/
PROXY_DIR = BEST_DIR.parent                         # proxy/
DATA_DIR = BEST_DIR / "data"
COUNTRY_DIR = PROXY_DIR / "country"
LOGS_DIR = PROXY_DIR / "logs"

REPOSITORIES_FILE = PROXY_DIR / "repositories.txt"
COLLECTIONS_FILE = PROXY_DIR / "collections.txt"
AVAILABLE_FILE = PROXY_DIR / "available.txt"
BEST_FILE = PROXY_DIR / "best.txt"

CONFIG_FILE = BEST_DIR / "config.yaml"


def load_config(path: Path | None = None) -> Config:
    """Load config from YAML file, falling back to defaults."""
    p = path or CONFIG_FILE
    if p.exists():
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return Config(**data)
    return Config()
