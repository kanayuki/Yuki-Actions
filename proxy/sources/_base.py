"""Base types for proxy link sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SourceResult:
    """Output of a single source run.

    Groups discovered links by their origin for per-source tracking.
    """

    links: list[str]
    source_tag: str  # e.g. "github:owner/repo", "subscribe:https://..."
    metadata: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class Source(Protocol):
    """Contract all acquisition sources must implement."""

    @staticmethod
    def name() -> str:
        """Unique identifier (e.g. 'github_crawler', 'subscribe')."""
        ...

    def collect(self) -> list[SourceResult]:
        """Fetch and return proxy links grouped by origin."""
        ...
