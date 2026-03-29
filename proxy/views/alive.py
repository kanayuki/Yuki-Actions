"""Alive view — TCP/DNS verification of non-dormant links.

Generates dataset/alive.txt with verified, latency-sorted links.

Absorbs: best/checker.py (alive_check)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..config import ALIVE_FILE

if TYPE_CHECKING:
    from ..config import Config
    from ..pool import PoolManager

logger = logging.getLogger(__name__)


class AliveView:
    """Lenient TCP/DNS verification -> alive.txt."""

    @staticmethod
    def name() -> str:
        return "alive"

    def generate(self, pool: PoolManager, cfg: Config) -> None:
        from core.parse import health_key
        from core.verify import verify_links

        try:
            from util import console
        except ImportError:
            from rich.console import Console

            console = Console(highlight=False)

        # Filter candidates: non-dormant with a link
        candidates = pool.all_non_dormant()
        if not candidates:
            logger.info("Alive check: no candidates")
            return

        links = [h.link for h in candidates]
        logger.info("Alive check: testing %d links (TCP/DNS)", len(links))

        results = verify_links(
            links,
            timeout=cfg.verify.alive_timeout_s,
            concurrency=cfg.verify.alive_concurrency,
        )

        # Build link -> health_key mapping
        link_hk: dict[str, str] = {}
        for h in candidates:
            hk = health_key(h.link)
            if hk:
                link_hk[h.link] = hk

        ok_count = pool.update_health_from_verify(
            results,
            cfg.verify.max_consecutive_failures,
            link_hk_map=link_hk,
        )
        pool.save_health()

        # Generate alive.txt
        alive = sorted(
            pool.active_links(),
            key=lambda h: h.latency_ms or 9999,
        )[: cfg.verify.alive_max]

        ALIVE_FILE.write_text(
            "\n".join(h.link for h in alive) + "\n" if alive else "",
            encoding="utf-8",
        )

        logger.info(
            "Alive check complete: %d/%d passed, %d in alive.txt",
            ok_count,
            len(results),
            len(alive),
        )
        console.print(
            f"  Passed [green bold]{ok_count}[/green bold] / {len(results)}  |  "
            f"Alive: [bold]{len(alive)}[/bold]"
        )
