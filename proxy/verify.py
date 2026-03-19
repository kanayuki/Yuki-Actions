"""Proxy share link parser and real-connection verifier.

Supports: vmess, vless, ss, trojan, hysteria/hysteria2, tuic, anytls, mieru
TCP-based protocols: full TCP connect + latency measurement
UDP-based protocols (hysteria/hysteria2, tuic): DNS resolution check
"""

import asyncio
import base64
import json
import logging
import socket
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console(highlight=False)

# Protocols that use UDP transport — TCP connect won't work
UDP_PROTOCOLS = {"hysteria", "hysteria2", "tuic"}


@dataclass
class ParsedProxy:
    protocol: str
    host: str
    port: int
    raw_link: str


@dataclass
class VerifyResult:
    link: str
    valid: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _strip_remark(link: str) -> str:
    idx = link.find("#")
    return link[:idx] if idx != -1 else link


def _b64decode_flexible(s: str) -> bytes:
    s = s.replace("-", "+").replace("_", "/")
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.b64decode(s)


def _parse_vmess(link: str) -> Optional[ParsedProxy]:
    b64 = _strip_remark(link)[8:]
    try:
        cfg = json.loads(_b64decode_flexible(b64).decode("utf-8"))
    except Exception as e:
        logger.debug("vmess parse error: %s", e)
        return None
    host = cfg.get("add", "").strip()
    try:
        port = int(cfg.get("port", 0))
    except (ValueError, TypeError):
        return None
    if not host or not port:
        return None
    return ParsedProxy(protocol="vmess", host=host, port=port, raw_link=link)


def _parse_url(scheme: str, link: str) -> Optional[ParsedProxy]:
    try:
        parsed = urllib.parse.urlparse(_strip_remark(link))
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            return None
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        return ParsedProxy(protocol=scheme, host=host, port=port, raw_link=link)
    except Exception as e:
        logger.debug("%s parse error: %s", scheme, e)
        return None


def _parse_mieru(link: str) -> Optional[ParsedProxy]:
    b64 = _strip_remark(link)[8:]
    try:
        decoded = _b64decode_flexible(b64).decode("utf-8")
    except Exception:
        return None
    at_idx = decoded.find("@")
    if at_idx == -1:
        return None
    host_part = decoded[at_idx + 1 :]
    host = host_part.split("?")[0].strip()
    port: Optional[int] = None
    if "?" in host_part:
        params = urllib.parse.parse_qs(host_part.split("?", 1)[1])
        ports = params.get("port", [])
        if ports:
            try:
                port = int(ports[0])
            except ValueError:
                pass
    if not host or port is None:
        return None
    return ParsedProxy(protocol="mieru", host=host, port=port, raw_link=link)


_PARSERS = {
    "vmess": _parse_vmess,
    "vless": lambda l: _parse_url("vless", l),
    "ss": lambda l: _parse_url("ss", l),
    "trojan": lambda l: _parse_url("trojan", l),
    "hysteria": lambda l: _parse_url("hysteria", l),
    "hysteria2": lambda l: _parse_url("hysteria2", l),
    "tuic": lambda l: _parse_url("tuic", l),
    "anytls": lambda l: _parse_url("anytls", l),
    "mieru": _parse_mieru,
}


def parse_link(link: str) -> Optional[ParsedProxy]:
    """Parse a proxy share link into a ParsedProxy. Returns None on failure."""
    link = link.strip()
    if not link or "://" not in link:
        return None
    scheme = link.split("://", 1)[0].lower()
    parser = _PARSERS.get(scheme)
    if parser is None:
        logger.debug("unsupported scheme: %s", scheme)
        return None
    try:
        return parser(link)
    except Exception as e:
        logger.debug("parse_link error (%s): %s", scheme, e)
        return None


# ---------------------------------------------------------------------------
# Connectivity checks
# ---------------------------------------------------------------------------


async def _tcp_check(host: str, port: int, timeout: float) -> float:
    start = time.monotonic()
    _, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port),
        timeout=timeout,
    )
    latency_ms = (time.monotonic() - start) * 1000.0
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return latency_ms


async def _dns_check(host: str, port: int, timeout: float) -> float:
    loop = asyncio.get_event_loop()
    start = time.monotonic()
    await asyncio.wait_for(
        loop.run_in_executor(None, socket.getaddrinfo, host, port, 0, socket.SOCK_DGRAM),
        timeout=timeout,
    )
    return (time.monotonic() - start) * 1000.0


async def _verify_proxy(proxy: ParsedProxy, timeout: float) -> VerifyResult:
    try:
        if proxy.protocol in UDP_PROTOCOLS:
            latency = await _dns_check(proxy.host, proxy.port, timeout)
        else:
            latency = await _tcp_check(proxy.host, proxy.port, timeout)
        return VerifyResult(link=proxy.raw_link, valid=True, latency_ms=round(latency, 1))
    except asyncio.TimeoutError:
        return VerifyResult(link=proxy.raw_link, valid=False, error="timeout")
    except OSError as e:
        return VerifyResult(link=proxy.raw_link, valid=False, error=str(e))
    except Exception as e:
        return VerifyResult(link=proxy.raw_link, valid=False, error=str(e))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def verify_links_async(
    links: list[str],
    timeout: float = 5.0,
    concurrency: int = 64,
    _on_done: Optional[Callable[[VerifyResult], None]] = None,
) -> list[VerifyResult]:
    """Verify share links concurrently. Unparseable links are marked invalid."""
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(link: str) -> VerifyResult:
        async with sem:
            proxy = parse_link(link)
            result = (
                VerifyResult(link=link, valid=False, error="parse_failed")
                if proxy is None
                else await _verify_proxy(proxy, timeout)
            )
            if _on_done is not None:
                _on_done(result)
            return result

    return await asyncio.gather(*[_bounded(link) for link in links])


def verify_links(
    links: list[str],
    timeout: float = 5.0,
    concurrency: int = 64,
) -> list[VerifyResult]:
    """Synchronous entry point with rich progress bar."""
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
        task = progress.add_task("验证连接…", total=len(links))
        return asyncio.run(
            verify_links_async(
                links,
                timeout=timeout,
                concurrency=concurrency,
                _on_done=lambda _: progress.advance(task),
            )
        )


def filter_valid_links(
    links: list[str],
    timeout: float = 5.0,
    concurrency: int = 64,
) -> tuple[list[str], list[VerifyResult]]:
    """Verify links and return (valid_links, all_results)."""
    results = verify_links(links, timeout=timeout, concurrency=concurrency)
    valid = [r.link for r in results if r.valid]
    return valid, results


# ---------------------------------------------------------------------------
# CLI / standalone usage
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import sys
    from pathlib import Path

    target = Path("share_links.txt") if len(sys.argv) < 2 else Path(sys.argv[1])
    if not target.exists():
        console.print(f"[red]File not found:[/red] {target}")
        sys.exit(1)

    raw_links = [l.strip() for l in target.read_text(encoding="utf-8").splitlines() if l.strip()]
    console.print(f"\n验证 [bold]{len(raw_links)}[/bold] 条链接…\n")

    results = verify_links(raw_links, timeout=5.0, concurrency=64)

    valid_results = sorted(
        [r for r in results if r.valid],
        key=lambda r: r.latency_ms or float("inf"),
    )
    failed_results = [r for r in results if not r.valid]

    # Results table
    table = Table(title="验证结果", show_lines=False, header_style="bold")
    table.add_column("延迟", style="cyan", justify="right", width=10)
    table.add_column("协议", style="blue", width=10)
    table.add_column("地址", width=26)
    table.add_column("链接", no_wrap=True, overflow="ellipsis", max_width=60)

    for r in valid_results:
        proxy = parse_link(r.link)
        host_port = f"{proxy.host}:{proxy.port}" if proxy else "-"
        proto = proxy.protocol if proxy else "-"
        table.add_row(f"{r.latency_ms:.1f} ms", proto, host_port, r.link)

    for r in failed_results:
        proxy = parse_link(r.link)
        host_port = f"{proxy.host}:{proxy.port}" if proxy else "-"
        proto = proxy.protocol if proxy else "-"
        table.add_row(
            "[red]-[/red]",
            f"[dim]{proto}[/dim]",
            f"[dim]{host_port}[/dim]",
            f"[red]✗[/red] [dim]{r.error}[/dim]",
        )

    console.print()
    console.print(table)
    console.print(
        f"\n[green]有效[/green] [bold]{len(valid_results)}[/bold] / {len(raw_links)}   "
        f"[red]失败[/red] [bold]{len(failed_results)}[/bold]"
    )
