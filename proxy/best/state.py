"""Persistent state management for the proxy dataset crawler.

State files live in proxy/dataset/:
  - health.json       — per-link health tracking
  - repo_scores.json  — per-repo quality metrics
  - raw/*.txt         — monthly sharded raw link pool
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from .config import DATASET_DIR, HEALTH_FILE, RAW_DIR, REPO_SCORES_FILE

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _count_lines(path: Path) -> int:
    """Count non-empty lines in a text file."""
    if not path.exists():
        return 0
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _current_shard() -> Path:
    """Return the shard file path for the current UTC month."""
    month = datetime.now(tz=timezone.utc).strftime("%Y%m")
    return RAW_DIR / f"raw_{month}.txt"


def _overflow_shard(base: Path, seq: int) -> Path:
    """Generate overflow shard name: raw_202603_2.txt, raw_202603_3.txt, ..."""
    stem = base.stem  # raw_202603
    return base.with_name(f"{stem}_{seq}{base.suffix}")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RepoScore(BaseModel):
    source: str = "search"  # "user" | "search"
    stars: int = 0
    last_seen: str = ""
    valid_ratio_history: list[float] = Field(default_factory=list)
    low_quality_streak: int = 0
    blacklisted: bool = False
    total_links_contributed: int = 0
    total_valid_contributed: int = 0


class LinkHealth(BaseModel):
    link: str = ""
    protocol: str = ""
    host: str = ""
    port: int = 0
    country: str = ""
    source_repo: str = ""
    fail_count: int = 0
    last_verified: str = ""
    last_ok: str = ""
    latency_ms: float = 0.0
    latency_history: list[float] = Field(default_factory=list)
    first_seen: str = ""
    dormant: bool = False
    dormant_since: str = ""


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------


class StateManager:
    """Read/write JSON state files and raw pool shards."""

    def __init__(self) -> None:
        DATASET_DIR.mkdir(parents=True, exist_ok=True)
        RAW_DIR.mkdir(parents=True, exist_ok=True)

    # ── helpers ──

    @staticmethod
    def _load_json(path: Path) -> dict | list:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to load %s: %s", path, e)
            return {}

    @staticmethod
    def _save_json(path: Path, data: dict | list) -> None:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── health ──

    def load_health(self) -> dict[str, LinkHealth]:
        raw = self._load_json(HEALTH_FILE)
        if not isinstance(raw, dict):
            return {}
        return {k: LinkHealth.model_validate(v) for k, v in raw.items()}

    def save_health(self, health: dict[str, LinkHealth]) -> None:
        self._save_json(
            HEALTH_FILE, {k: v.model_dump() for k, v in health.items()}
        )

    # ── repo scores ──

    def load_repo_scores(self) -> dict[str, RepoScore]:
        raw = self._load_json(REPO_SCORES_FILE)
        if not isinstance(raw, dict):
            return {}
        return {k: RepoScore.model_validate(v) for k, v in raw.items()}

    def save_repo_scores(self, scores: dict[str, RepoScore]) -> None:
        self._save_json(
            REPO_SCORES_FILE, {k: v.model_dump() for k, v in scores.items()}
        )

    # ── raw pool ──

    def append_to_raw(
        self,
        links: list[str],
        health: dict[str, LinkHealth],
        max_per_shard: int,
    ) -> int:
        """Deduplicate and append new links to the current monthly shard.

        Creates LinkHealth entries for newly added links.
        Returns the number of newly added links.
        """
        from core.parse import health_key, parse_link

        existing_keys = set(health.keys())
        new_items: list[tuple[str, str]] = []  # (health_key, link)

        for link in links:
            hk = health_key(link)
            if not hk or hk in existing_keys:
                continue
            existing_keys.add(hk)
            new_items.append((hk, link))

        if not new_items:
            return 0

        shard = _current_shard()
        current_count = _count_lines(shard)
        overflow_seq = 2
        written = 0

        f = open(shard, "a", encoding="utf-8")
        try:
            for hk, link in new_items:
                if current_count >= max_per_shard:
                    f.close()
                    shard = _overflow_shard(_current_shard(), overflow_seq)
                    overflow_seq += 1
                    f = open(shard, "a", encoding="utf-8")
                    current_count = 0

                f.write(link + "\n")
                current_count += 1
                written += 1

                parsed = parse_link(link)
                health[hk] = LinkHealth(
                    link=link,
                    protocol=parsed.protocol if parsed else "",
                    host=parsed.host if parsed else "",
                    port=parsed.port if parsed else 0,
                    first_seen=_now(),
                )
        finally:
            f.close()

        return written

    def raw_stats(self) -> dict[str, int]:
        """Return {filename: line_count} for all raw shards."""
        stats: dict[str, int] = {}
        for p in sorted(RAW_DIR.glob("raw_*.txt")):
            stats[p.name] = _count_lines(p)
        return stats
