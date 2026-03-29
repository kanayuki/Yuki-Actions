"""Source plugin registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._base import Source, SourceResult

if TYPE_CHECKING:
    from proxy.config import Config

__all__ = ["Source", "SourceResult", "get_all_sources", "get_source_by_name"]


def get_all_sources(cfg: Config) -> list[Source]:
    """Instantiate all enabled sources from config."""
    from .github_crawler import GitHubCrawlerSource
    from .subscribe import SubscribeSource

    sources: list[Source] = []
    if cfg.github_crawler.enabled:
        sources.append(GitHubCrawlerSource(cfg))
    if cfg.subscribe.enabled:
        sources.append(SubscribeSource(cfg))
    return sources


def get_source_by_name(name: str, cfg: Config) -> Source:
    """Instantiate a specific source by name."""
    from .github_crawler import GitHubCrawlerSource
    from .subscribe import SubscribeSource

    registry: dict[str, type] = {
        GitHubCrawlerSource.name(): GitHubCrawlerSource,
        SubscribeSource.name(): SubscribeSource,
    }
    if name not in registry:
        msg = f"Unknown source: {name!r} (available: {', '.join(registry)})"
        raise ValueError(msg)
    return registry[name](cfg)
