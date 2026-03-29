"""Best-remote view — engine-chain real connection testing.

Generates dataset/best_remote.txt with engine-verified links.

Absorbs: best/checker.py (best_remote_check)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..config import ALIVE_FILE, BEST_REMOTE_FILE

if TYPE_CHECKING:
    from ..config import Config
    from ..pool import PoolManager

logger = logging.getLogger(__name__)


class BestRemoteView:
    """Engine-chain real test -> best_remote.txt."""

    @staticmethod
    def name() -> str:
        return "best_remote"

    def generate(self, pool: PoolManager, cfg: Config) -> None:
        from engine import TestResult, get_engine_chain, test_with_chain
        from rich.progress import (
            BarColumn,
            MofNCompleteColumn,
            Progress,
            SpinnerColumn,
            TaskProgressColumn,
            TextColumn,
            TimeElapsedColumn,
        )

        try:
            from util import console
        except ImportError:
            from rich.console import Console

            console = Console(highlight=False)

        # Read alive.txt
        if not ALIVE_FILE.exists():
            logger.warning("No alive.txt found, run 'alive' first")
            return

        lines = [
            line.strip()
            for line in ALIVE_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not lines:
            logger.warning("alive.txt is empty")
            return

        batch = lines[: cfg.engine.best_remote_batch]
        chain = get_engine_chain(cfg.engine.test_engine)
        engine_names = [e.name() for e in chain]

        logger.info(
            "Best-remote: testing %d links, engines: %s",
            len(batch),
            engine_names,
        )
        console.print(f"  Engines: [bold]{' -> '.join(engine_names)}[/bold]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("Testing...", total=len(batch))

            def _on_done(r: TestResult) -> None:
                progress.advance(task)

            results = test_with_chain(
                batch,
                chain,
                timeout_ms=cfg.engine.test_timeout_ms,
                concurrency=cfg.engine.test_concurrency,
                test_url=cfg.engine.test_url,
                on_done=_on_done,
            )

        passed = sorted(
            [r for r in results if r.ok], key=lambda r: r.latency_ms
        )[: cfg.engine.best_remote_top]

        BEST_REMOTE_FILE.write_text(
            "\n".join(r.link for r in passed) + "\n" if passed else "",
            encoding="utf-8",
        )

        # Update health latency from engine results
        pool.update_health_from_engine(results)
        pool.save_health()

        logger.info(
            "Best-remote complete: %d/%d passed, top %d saved",
            len(passed),
            len(results),
            len(passed),
        )
        console.print(
            f"  Passed [green bold]{len(passed)}[/green bold] / {len(results)}  |  "
            f"Saved: [bold]{len(passed)}[/bold] to best_remote.txt"
        )
