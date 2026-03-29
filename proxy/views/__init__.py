"""View plugin registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._base import View

if TYPE_CHECKING:
    from proxy.config import Config
    from proxy.pool import PoolManager

__all__ = ["View", "get_all_views", "get_view_by_name"]


def get_all_views(cfg: Config) -> list[View]:
    """Instantiate all available views."""
    from .alive import AliveView
    from .best_remote import BestRemoteView
    from .country import CountryView
    from .merge import MergeView

    return [AliveView(), BestRemoteView(), CountryView(), MergeView()]


def get_view_by_name(name: str) -> View:
    """Instantiate a specific view by name."""
    from .alive import AliveView
    from .best_remote import BestRemoteView
    from .country import CountryView
    from .merge import MergeView

    registry: dict[str, type] = {
        AliveView.name(): AliveView,
        BestRemoteView.name(): BestRemoteView,
        CountryView.name(): CountryView,
        MergeView.name(): MergeView,
    }
    if name not in registry:
        msg = f"Unknown view: {name!r} (available: {', '.join(registry)})"
        raise ValueError(msg)
    return registry[name]()
