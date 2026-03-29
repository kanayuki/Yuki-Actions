"""Merge view — generates merge output from the global pool.

Writes active, latency-sorted links to merge/merge.txt.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..config import MERGE_FILE

if TYPE_CHECKING:
    from ..config import Config
    from ..pool import PoolManager

logger = logging.getLogger(__name__)


class MergeView:
    """Active pool links -> merge/merge.txt."""

    @staticmethod
    def name() -> str:
        return "merge"

    def generate(self, pool: PoolManager, cfg: Config) -> None:
        try:
            from util import console
        except ImportError:
            from rich.console import Console

            console = Console(highlight=False)

        active = pool.active_links()
        active.sort(key=lambda h: h.latency_ms or 9999)

        MERGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        MERGE_FILE.write_text(
            "\n".join(h.link for h in active) + "\n" if active else "",
            encoding="utf-8",
        )

        logger.info("Merge output: %d links -> %s", len(active), MERGE_FILE.name)
        console.print(
            f"  Merge: [bold]{len(active)}[/bold] links -> {MERGE_FILE.name}"
        )
