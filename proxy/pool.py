"""Global proxy pool manager — single source of truth for all proxy data.

Manages:
  - Raw pool shards (append-only monthly files in dataset/raw/)
  - Health store (per-link tracking in dataset/health.json)
  - Repo scores (per-repo quality in dataset/repo_scores.json)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from .config import DATASET_DIR, HEALTH_FILE, RAW_DIR, REPO_SCORES_FILE

if TYPE_CHECKING:
    from .sources._base import SourceResult

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _current_shard() -> Path:
    month = datetime.now(tz=timezone.utc).strftime("%Y%m")
    return RAW_DIR / f"raw_{month}.txt"


def _overflow_shard(base: Path, seq: int) -> Path:
    return base.with_name(f"{base.stem}_{seq}{base.suffix}")


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
    source_repo: str = ""  # Legacy field, kept for backwards compat
    source_tag: str = ""  # New: "github:owner/repo" | "subscribe:url"
    fail_count: int = 0
    last_verified: str = ""
    last_ok: str = ""
    latency_ms: float = 0.0
    latency_history: list[float] = Field(default_factory=list)
    first_seen: str = ""
    dormant: bool = False
    dormant_since: str = ""

    @property
    def effective_source(self) -> str:
        """Return source_tag if set, otherwise fall back to source_repo."""
        return self.source_tag or self.source_repo


# ---------------------------------------------------------------------------
# PoolManager
# ---------------------------------------------------------------------------


class PoolManager:
    """Central state manager for the global proxy pool."""

    def __init__(self) -> None:
        DATASET_DIR.mkdir(parents=True, exist_ok=True)
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        self._health: dict[str, LinkHealth] | None = None
        self._health_dirty: bool = False

    # ── JSON helpers ──

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

    # ── Health store (lazy-loaded, cached) ──

    def load_health(self) -> dict[str, LinkHealth]:
        if self._health is None:
            raw = self._load_json(HEALTH_FILE)
            if not isinstance(raw, dict):
                self._health = {}
            else:
                self._health = {
                    k: LinkHealth.model_validate(v) for k, v in raw.items()
                }
            self._health_dirty = False
        return self._health

    def save_health(self) -> None:
        if self._health is None:
            return
        self._save_json(
            HEALTH_FILE,
            {k: v.model_dump(exclude_defaults=False) for k, v in self._health.items()},
        )
        self._health_dirty = False

    @property
    def health(self) -> dict[str, LinkHealth]:
        return self.load_health()

    # ── Repo scores ──

    def load_repo_scores(self) -> dict[str, RepoScore]:
        raw = self._load_json(REPO_SCORES_FILE)
        if not isinstance(raw, dict):
            return {}
        return {k: RepoScore.model_validate(v) for k, v in raw.items()}

    def save_repo_scores(self, scores: dict[str, RepoScore]) -> None:
        self._save_json(
            REPO_SCORES_FILE,
            {k: v.model_dump() for k, v in scores.items()},
        )

    # ── Ingest (used by sources) ──

    def ingest(self, results: list[SourceResult], max_per_shard: int) -> int:
        """Deduplicate and append links from source results into the raw pool.

        Creates LinkHealth entries for new links. Returns count of newly added links.
        """
        from core.parse import health_key, parse_link

        health = self.load_health()
        existing_keys = set(health.keys())
        new_items: list[tuple[str, str, str]] = []  # (hk, link, source_tag)

        for result in results:
            for link in result.links:
                hk = health_key(link)
                if not hk or hk in existing_keys:
                    continue
                existing_keys.add(hk)
                new_items.append((hk, link, result.source_tag))

        if not new_items:
            return 0

        shard = _current_shard()
        current_count = _count_lines(shard)
        overflow_seq = 2
        written = 0

        f = open(shard, "a", encoding="utf-8")
        try:
            for hk, link, source_tag in new_items:
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
                    source_tag=source_tag,
                    first_seen=_now(),
                )
        finally:
            f.close()

        self._health_dirty = True
        return written

    # ── Query (used by views) ──

    def active_links(self) -> list[LinkHealth]:
        """Non-dormant, zero-fail links with last_ok set."""
        return [
            h
            for h in self.health.values()
            if not h.dormant and h.fail_count == 0 and h.last_ok and h.link
        ]

    def all_non_dormant(self) -> list[LinkHealth]:
        """All non-dormant links with a link field."""
        return [
            h for h in self.health.values() if not h.dormant and h.link
        ]

    def dormant_due_for_recheck(self, days: int) -> list[LinkHealth]:
        """Dormant links past the recheck threshold."""
        now_dt = datetime.now(tz=timezone.utc)
        due: list[LinkHealth] = []
        for entry in self.health.values():
            if not entry.dormant or not entry.link:
                continue
            if not entry.dormant_since:
                due.append(entry)
                continue
            try:
                ds = datetime.fromisoformat(entry.dormant_since)
                if ds.tzinfo is None:
                    ds = ds.replace(tzinfo=timezone.utc)
                age_days = (now_dt - ds).total_seconds() / 86400
                if age_days >= days:
                    due.append(entry)
            except Exception:
                due.append(entry)
        return due

    # ── Health updates ──

    def update_health_from_verify(
        self,
        results: list,
        max_failures: int,
        *,
        link_hk_map: dict[str, str] | None = None,
    ) -> int:
        """Update health entries from VerifyResult list.

        If link_hk_map is provided, use it for link -> health_key lookup.
        Otherwise, compute health_key from each link.
        Returns count of valid results.
        """
        from core.parse import health_key

        health = self.load_health()
        now = _now()
        ok_count = 0

        for r in results:
            if link_hk_map:
                hk = link_hk_map.get(r.link)
            else:
                hk = health_key(r.link)
            if not hk or hk not in health:
                continue

            entry = health[hk]
            entry.last_verified = now

            if r.valid:
                entry.fail_count = 0
                entry.last_ok = now
                entry.latency_ms = r.latency_ms
                entry.latency_history = (
                    entry.latency_history + [r.latency_ms]
                )[-5:]
                entry.dormant = False
                ok_count += 1
            else:
                entry.fail_count += 1
                if entry.fail_count >= max_failures:
                    entry.dormant = True
                    entry.dormant_since = now

        self._health_dirty = True
        return ok_count

    def update_health_from_engine(self, results: list) -> None:
        """Update health latency from engine TestResult list."""
        from core.parse import health_key

        health = self.load_health()
        for r in results:
            if not r.ok:
                continue
            hk = health_key(r.link)
            if hk and hk in health:
                health[hk].latency_ms = r.latency_ms
                health[hk].latency_history = (
                    health[hk].latency_history + [r.latency_ms]
                )[-5:]
        self._health_dirty = True

    def prune(self, max_entries: int) -> int:
        """Prune oldest never-connected dormant entries if over max_entries."""
        health = self.load_health()
        if len(health) <= max_entries:
            return 0

        candidates = [
            (hk, entry)
            for hk, entry in health.items()
            if entry.dormant and not entry.last_ok
        ]
        candidates.sort(key=lambda x: x[1].first_seen or "")

        to_remove = len(health) - max_entries
        pruned = 0
        for hk, _ in candidates[:to_remove]:
            health.pop(hk)
            pruned += 1

        if pruned:
            self._health_dirty = True
        return pruned

    # ── Stats ──

    def raw_stats(self) -> dict[str, int]:
        stats: dict[str, int] = {}
        for p in sorted(RAW_DIR.glob("raw_*.txt")):
            stats[p.name] = _count_lines(p)
        return stats
