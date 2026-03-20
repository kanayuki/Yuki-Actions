"""Persistent state management for the best proxy pipeline.

All state is stored as JSON files in proxy/best/data/.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from .config import DATA_DIR

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


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


class QueueItem(BaseModel):
    link: str
    health_key: str
    source_repo: str = ""
    enqueued_at: str = Field(default_factory=_now)
    priority: int = 1  # 1=new, 2=recheck


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------


class StateManager:
    """Read/write JSON state files in DATA_DIR."""

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # -- helpers --

    def _path(self, name: str) -> Path:
        return self.data_dir / name

    def _load_json(self, name: str) -> dict | list:
        p = self._path(name)
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to load %s: %s", p, e)
            return {}

    def _save_json(self, name: str, data: dict | list) -> None:
        p = self._path(name)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # -- repo scores --

    def load_repo_scores(self) -> dict[str, RepoScore]:
        raw = self._load_json("repo_scores.json")
        if not isinstance(raw, dict):
            return {}
        return {k: RepoScore.model_validate(v) for k, v in raw.items()}

    def save_repo_scores(self, scores: dict[str, RepoScore]) -> None:
        self._save_json(
            "repo_scores.json",
            {k: v.model_dump() for k, v in scores.items()},
        )

    # -- link health --

    def load_link_health(self) -> dict[str, LinkHealth]:
        raw = self._load_json("link_health.json")
        if not isinstance(raw, dict):
            return {}
        return {k: LinkHealth.model_validate(v) for k, v in raw.items()}

    def save_link_health(self, health: dict[str, LinkHealth]) -> None:
        self._save_json(
            "link_health.json",
            {k: v.model_dump() for k, v in health.items()},
        )

    # -- verify queue --

    def load_queue(self) -> list[QueueItem]:
        raw = self._load_json("verify_queue.json")
        if isinstance(raw, dict):
            items = raw.get("queue", [])
        elif isinstance(raw, list):
            items = raw
        else:
            return []
        return [QueueItem.model_validate(item) for item in items]

    def save_queue(self, queue: list[QueueItem]) -> None:
        self._save_json(
            "verify_queue.json",
            {"queue": [item.model_dump() for item in queue]},
        )
