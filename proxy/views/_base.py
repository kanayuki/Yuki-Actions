"""Base types for output views."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from proxy.config import Config
    from proxy.pool import PoolManager


@runtime_checkable
class View(Protocol):
    """Contract all output views must implement."""

    @staticmethod
    def name() -> str:
        """Unique identifier (e.g. 'alive', 'country', 'merge')."""
        ...

    def generate(self, pool: PoolManager, cfg: Config) -> None:
        """Read from the global pool and write output files."""
        ...
