"""Stage 3: Verify -- alive check (TCP/DNS) and best-remote check (engine chain).

alive_check:       Lenient TCP/DNS verification of all non-dormant links.
                   Generates dataset/alive.txt.
best_remote_check: Real connection test via engine chain on top alive links.
                   Generates dataset/best_remote.txt (unstable backup).

Usage:
    python -m best alive
    python -m best best-remote
"""

from __future__ import annotations

import logging

from .config import ALIVE_FILE, BEST_REMOTE_FILE, Config, load_config
from .state import StateManager, _now

logger = logging.getLogger(__name__)

try:
    from util import console
except ImportError:
    from rich.console import Console

    console = Console(highlight=False)


def alive_check(
    cfg: Config | None = None, state: StateManager | None = None
) -> int:
    """Lenient TCP/DNS verification of all non-dormant links.

    Updates health entries and generates alive.txt.
    Returns the number of links tested.
    """
    from core.parse import health_key
    from core.verify import verify_links

    cfg = cfg or load_config()
    state = state or StateManager()
    health = state.load_health()

    # Filter candidates: non-dormant with a link
    candidates = {
        hk: h for hk, h in health.items() if not h.dormant and h.link
    }
    if not candidates:
        logger.info("Alive check: no candidates")
        return 0

    links = [h.link for h in candidates.values()]
    logger.info("Alive check: testing %d links (TCP/DNS)", len(links))

    results = verify_links(
        links, timeout=cfg.alive_timeout_s, concurrency=cfg.alive_concurrency
    )

    # Build link -> health_key mapping for result processing
    link_hk: dict[str, str] = {}
    for hk, h in candidates.items():
        link_hk[h.link] = hk

    now = _now()
    ok_count = 0

    for r in results:
        hk = link_hk.get(r.link)
        if not hk or hk not in health:
            continue

        entry = health[hk]
        entry.last_verified = now

        if r.valid:
            entry.fail_count = 0
            entry.last_ok = now
            entry.latency_ms = r.latency_ms
            entry.latency_history = (entry.latency_history + [r.latency_ms])[
                -5:
            ]
            entry.dormant = False
            ok_count += 1
        else:
            entry.fail_count += 1
            if entry.fail_count >= cfg.max_consecutive_failures:
                entry.dormant = True
                entry.dormant_since = now

    state.save_health(health)

    # Generate alive.txt
    alive = sorted(
        [
            h
            for h in health.values()
            if not h.dormant and h.fail_count == 0 and h.last_ok
        ],
        key=lambda h: h.latency_ms or 9999,
    )[: cfg.alive_max]

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
    return len(results)


def best_remote_check(
    cfg: Config | None = None, state: StateManager | None = None
) -> int:
    """Real engine-chain test on top alive links.

    Generates best_remote.txt (unstable server-side backup).
    Returns the number of links that passed.
    """
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

    cfg = cfg or load_config()
    state = state or StateManager()

    # Read alive.txt
    if not ALIVE_FILE.exists():
        logger.warning("No alive.txt found, run 'alive' first")
        return 0

    lines = [
        line.strip()
        for line in ALIVE_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not lines:
        logger.warning("alive.txt is empty")
        return 0

    batch = lines[: cfg.best_remote_batch]
    chain = get_engine_chain(cfg.test_engine)
    engine_names = [e.name() for e in chain]

    logger.info(
        "Best-remote: testing %d links, engines: %s", len(batch), engine_names
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
            timeout_ms=cfg.test_timeout_ms,
            concurrency=cfg.test_concurrency,
            test_url=cfg.test_url,
            on_done=_on_done,
        )

    passed = sorted(
        [r for r in results if r.ok], key=lambda r: r.latency_ms
    )[: cfg.best_remote_top]

    BEST_REMOTE_FILE.write_text(
        "\n".join(r.link for r in passed) + "\n" if passed else "",
        encoding="utf-8",
    )

    # Optionally update health latency from engine results
    health = state.load_health()
    from core.parse import health_key

    updated = False
    for r in results:
        if r.ok:
            hk = health_key(r.link)
            if hk and hk in health:
                health[hk].latency_ms = r.latency_ms
                health[hk].latency_history = (
                    health[hk].latency_history + [r.latency_ms]
                )[-5:]
                updated = True
    if updated:
        state.save_health(health)

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
    return len(passed)
