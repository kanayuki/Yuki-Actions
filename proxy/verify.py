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
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

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
    """Remove #remark fragment from share link."""
    idx = link.find("#")
    return link[:idx] if idx != -1 else link


def _b64decode_flexible(s: str) -> bytes:
    """Decode base64 with automatic padding, accepting both standard and URL-safe."""
    s = s.replace("-", "+").replace("_", "/")
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.b64decode(s)


def _parse_vmess(link: str) -> Optional[ParsedProxy]:
    """vmess://base64(json)"""
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
    """Generic URL-based parser for vless/ss/trojan/hysteria2/tuic/anytls."""
    try:
        parsed = urllib.parse.urlparse(_strip_remark(link))
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            return None
        # strip IPv6 brackets that urlparse may leave in hostname
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        return ParsedProxy(protocol=scheme, host=host, port=port, raw_link=link)
    except Exception as e:
        logger.debug("%s parse error: %s", scheme, e)
        return None


def _parse_mieru(link: str) -> Optional[ParsedProxy]:
    """mieru://base64(name:password@host?params) — extract host, use first port param."""
    b64 = _strip_remark(link)[8:]
    try:
        decoded = _b64decode_flexible(b64).decode("utf-8")
    except Exception:
        return None
    # decoded: "name:password@host?port=PORT&protocol=TCP..."
    at_idx = decoded.find("@")
    if at_idx == -1:
        return None
    host_part = decoded[at_idx + 1 :]
    host = host_part.split("?")[0].strip()
    # extract first port= param
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
    """Open a TCP connection and return latency in ms. Raises on failure."""
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
    """DNS resolution check for UDP-based protocols. Returns resolution latency in ms."""
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
        return VerifyResult(
            link=proxy.raw_link,
            valid=True,
            latency_ms=round(latency, 1),
        )
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
) -> list[VerifyResult]:
    """Verify share links concurrently. Unparseable links are marked invalid."""
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(link: str) -> VerifyResult:
        async with sem:
            proxy = parse_link(link)
            if proxy is None:
                return VerifyResult(link=link, valid=False, error="parse_failed")
            return await _verify_proxy(proxy, timeout)

    return await asyncio.gather(*[_bounded(link) for link in links])


def verify_links(
    links: list[str],
    timeout: float = 5.0,
    concurrency: int = 64,
) -> list[VerifyResult]:
    """Synchronous entry point — runs the async verifier in a new event loop."""
    return asyncio.run(verify_links_async(links, timeout=timeout, concurrency=concurrency))


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

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    target = Path("share_links.txt") if len(sys.argv) < 2 else Path(sys.argv[1])
    if not target.exists():
        print(f"File not found: {target}")
        sys.exit(1)

    raw_links = [l.strip() for l in target.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"Verifying {len(raw_links)} links…")

    valid_links, results = filter_valid_links(raw_links, timeout=5.0, concurrency=64)

    failed = [r for r in results if not r.valid]
    print(f"\nValid:  {len(valid_links)}/{len(raw_links)}")
    print(f"Failed: {len(failed)}")

    if valid_links:
        print("\n--- Valid links (sorted by latency) ---")
        valid_results = sorted(
            [r for r in results if r.valid],
            key=lambda r: r.latency_ms or float("inf"),
        )
        for r in valid_results:
            print(f"  {r.latency_ms:>7.1f} ms  {r.link[:80]}")
