"""Stage 3: Verify — batch test proxy links for real connectivity.

Pulls links from verify_queue (priority 1 = new, 2 = recheck), tests via
the engine chain (xray → singbox → mihomo → tcp), and updates link_health.json.

Usage: python -m best verify [--all]
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from .config import AVAILABLE_FILE, Config, load_config
from ..engine import TestResult, get_engine_chain, test_with_chain
from .state import LinkHealth, QueueItem, StateManager, _now

logger = logging.getLogger(__name__)

# Reuse the shared console from proxy/util.py
try:
    from util import console
except ImportError:
    from rich.console import Console
    console = Console(highlight=False)


def _health_key_from_link(link: str) -> str:
    from verify import parse_link

    proxy = parse_link(link)
    if proxy is None:
        return hashlib.sha256(link.encode()).hexdigest()
    return hashlib.sha256(f"{proxy.protocol}:{proxy.host}:{proxy.port}".encode()).hexdigest()


def _parse_link_info(link: str) -> tuple[str, str, int]:
    """Return (protocol, host, port) from a share link."""
    from verify import parse_link

    proxy = parse_link(link)
    if proxy:
        return proxy.protocol, proxy.host, proxy.port
    return "", "", 0


def _stale_health_items(
    health: dict[str, LinkHealth],
    recheck_min: int,
) -> list[tuple[str, LinkHealth]]:
    """Find health entries due for re-verification."""
    now = datetime.now(tz=timezone.utc)
    stale: list[tuple[str, LinkHealth]] = []
    for hk, entry in health.items():
        if not entry.last_verified:
            stale.append((hk, entry))
            continue
        try:
            last = datetime.fromisoformat(entry.last_verified)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age_min = (now - last).total_seconds() / 60
            if age_min >= recheck_min:
                stale.append((hk, entry))
        except Exception:
            stale.append((hk, entry))
    return stale


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def verify_batch(
    cfg: Config | None = None,
    state: StateManager | None = None,
    *,
    process_all: bool = False,
) -> int:
    """Run Stage 3: verify a batch of links.

    Returns the number of links tested.
    """
    cfg = cfg or load_config()
    state = state or StateManager()
    health = state.load_link_health()
    queue = state.load_queue()

    # Also add stale health entries as recheck items
    stale = _stale_health_items(health, cfg.health_recheck_interval_min)
    queued_keys = {item.health_key for item in queue}
    for hk, entry in stale:
        if hk not in queued_keys:
            queue.append(
                QueueItem(link=entry.link, health_key=hk, source_repo=entry.source_repo, priority=2)
            )

    # Sort: priority 1 first, then 2
    queue.sort(key=lambda x: x.priority)

    if not queue:
        logger.info("Verify: nothing to test")
        return 0

    # Pick batch
    batch_size = len(queue) if process_all else min(cfg.batch_size, len(queue))
    batch = queue[:batch_size]
    remaining_queue = queue[batch_size:]

    links = [item.link for item in batch]
    link_to_item = {item.link: item for item in batch}

    # Engine chain
    chain = get_engine_chain(cfg.test_engine)
    engine_names = [e.name() for e in chain]
    logger.info("Verify batch: %d links, engines: %s", len(links), engine_names)

    console.print(f"  Engines: [bold]{' → '.join(engine_names)}[/bold]")

    # Run with progress bar
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
        task = progress.add_task("Verifying…", total=len(links))

        def _on_done(r: TestResult) -> None:
            progress.advance(task)

        results = test_with_chain(
            links,
            chain,
            timeout_ms=cfg.test_timeout_ms,
            concurrency=cfg.test_concurrency,
            test_url=cfg.test_url,
            on_done=_on_done,
        )

    # Update health
    now = _now()
    ok_count = 0
    for r in results:
        item = link_to_item.get(r.link)
        hk = item.health_key if item else hashlib.sha256(r.link.encode()).hexdigest()
        proto, host, port = _parse_link_info(r.link)

        if hk not in health:
            health[hk] = LinkHealth(
                link=r.link,
                protocol=proto,
                host=host,
                port=port,
                source_repo=item.source_repo if item else "",
                first_seen=now,
            )
        entry = health[hk]
        entry.link = r.link  # keep fresh link text
        entry.last_verified = now

        if r.ok:
            entry.fail_count = 0
            entry.last_ok = now
            entry.latency_ms = r.latency_ms
            # Rolling latency history (last 5)
            entry.latency_history.append(r.latency_ms)
            if len(entry.latency_history) > 5:
                entry.latency_history = entry.latency_history[-5:]
            ok_count += 1
        else:
            entry.fail_count += 1

    state.save_link_health(health)
    state.save_queue(remaining_queue)

    # Regenerate available.txt
    available = [
        entry.link
        for entry in sorted(health.values(), key=lambda e: e.latency_ms or 9999)
        if entry.fail_count == 0 and entry.last_ok
    ]
    AVAILABLE_FILE.write_text(
        "\n".join(available) + "\n" if available else "",
        encoding="utf-8",
    )

    logger.info("Verify complete: %d/%d passed, %d available total", ok_count, len(results), len(available))
    console.print(
        f"  Passed [green bold]{ok_count}[/green bold] / {len(results)}  |  "
        f"Total available: [bold]{len(available)}[/bold]"
    )
    return len(results)
