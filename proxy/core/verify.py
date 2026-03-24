"""TCP/DNS-only proxy connectivity verification — no binary engine required.

Tests TCP protocols via asyncio.open_connection(host, port).
Tests UDP protocols (hysteria, tuic) via socket.getaddrinfo with SOCK_DGRAM.

Public API
----------
verify_links(links, timeout=5.0, concurrency=64) -> list[VerifyResult]
    Synchronous batch verify with Rich progress bar.

filter_valid_links(links, **kw) -> tuple[list[str], list[VerifyResult]]
    Returns (sorted_valid_links, all_results).
"""

from __future__ import annotations

import asyncio
import socket
import time
from typing import Callable

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from .models import VerifyResult
from .parse import parse_link

_UDP_PROTOCOLS = {"hysteria", "hysteria2", "tuic"}


async def _verify_one(
    link: str,
    sem: asyncio.Semaphore,
    timeout_s: float,
    on_done: Callable[[VerifyResult], None] | None,
) -> VerifyResult:
    async with sem:
        parsed = parse_link(link)
        if parsed is None:
            r = VerifyResult(link=link, valid=False, error="parse_failed")
            if on_done:
                on_done(r)
            return r
        try:
            start = time.monotonic()
            if parsed.protocol in _UDP_PROTOCOLS:
                loop = asyncio.get_event_loop()
                await asyncio.wait_for(
                    loop.run_in_executor(
                        None, socket.getaddrinfo, parsed.host, parsed.port, 0, socket.SOCK_DGRAM
                    ),
                    timeout=timeout_s,
                )
            else:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(parsed.host, parsed.port),
                    timeout=timeout_s,
                )
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
            latency = (time.monotonic() - start) * 1000.0
            r = VerifyResult(link=link, valid=True, latency_ms=round(latency, 1))
        except asyncio.TimeoutError:
            r = VerifyResult(link=link, valid=False, error="timeout")
        except Exception as e:
            r = VerifyResult(link=link, valid=False, error=str(e))
        if on_done:
            on_done(r)
        return r


async def _verify_batch_async(
    links: list[str],
    timeout_s: float,
    concurrency: int,
    on_done: Callable[[VerifyResult], None] | None,
) -> list[VerifyResult]:
    sem = asyncio.Semaphore(concurrency)
    return list(await asyncio.gather(*[_verify_one(l, sem, timeout_s, on_done) for l in links]))


def verify_links(
    links: list[str],
    *,
    timeout: float = 5.0,
    concurrency: int = 64,
) -> list[VerifyResult]:
    """Synchronous TCP/DNS batch verification with a Rich progress bar."""
    try:
        from util import console
    except ImportError:
        from rich.console import Console
        console = Console(highlight=False)

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

        def _on_done(r: VerifyResult) -> None:
            progress.advance(task)

        return asyncio.run(_verify_batch_async(links, timeout, concurrency, _on_done))


def filter_valid_links(
    links: list[str],
    *,
    timeout: float = 5.0,
    concurrency: int = 64,
) -> tuple[list[str], list[VerifyResult]]:
    """Verify and return (sorted_valid_links, all_results)."""
    results = verify_links(links, timeout=timeout, concurrency=concurrency)
    valid = sorted(
        [r.link for r in results if r.valid],
        key=lambda lnk: next((r.latency_ms for r in results if r.link == lnk), float("inf")),
    )
    return valid, results
