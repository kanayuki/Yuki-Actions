"""TCP/DNS fallback engine — no real proxy test, just port reachability."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Callable

from . import TestEngine, TestResult

logger = logging.getLogger(__name__)

_UDP_PROTOCOLS = {"hysteria", "hysteria2", "tuic"}
_ALL_PROTOCOLS = {
    "vmess", "vless", "ss", "trojan",
    "hysteria", "hysteria2", "tuic",
    "anytls", "mieru",
}


def _parse_host_port(link: str) -> tuple[str, int, str] | None:
    """Quick parse: return (host, port, protocol) or None."""
    from core.parse import parse_link
    proxy = parse_link(link)
    if proxy is None:
        return None
    return proxy.host, proxy.port, proxy.protocol


class TcpEngine(TestEngine):
    @classmethod
    def name(cls) -> str:
        return "tcp"

    @classmethod
    def supported_protocols(cls) -> set[str]:
        return _ALL_PROTOCOLS

    @classmethod
    def is_available(cls) -> bool:
        return True  # always available

    def test_batch(
        self,
        links: list[str],
        *,
        timeout_ms: int = 6000,
        concurrency: int = 64,
        test_url: str = "",
        on_done: Callable[[TestResult], None] | None = None,
    ) -> list[TestResult]:
        timeout_s = timeout_ms / 1000.0

        async def _check_one(link: str, sem: asyncio.Semaphore) -> TestResult:
            async with sem:
                parsed = _parse_host_port(link)
                if parsed is None:
                    r = TestResult(link=link, ok=False, error="parse_failed")
                    if on_done:
                        on_done(r)
                    return r

                host, port, proto = parsed
                try:
                    start = time.monotonic()
                    if proto in _UDP_PROTOCOLS:
                        loop = asyncio.get_event_loop()
                        await asyncio.wait_for(
                            loop.run_in_executor(
                                None,
                                socket.getaddrinfo,
                                host, port, 0, socket.SOCK_DGRAM,
                            ),
                            timeout=timeout_s,
                        )
                    else:
                        _, writer = await asyncio.wait_for(
                            asyncio.open_connection(host, port),
                            timeout=timeout_s,
                        )
                        writer.close()
                        try:
                            await writer.wait_closed()
                        except Exception:
                            pass
                    latency = (time.monotonic() - start) * 1000.0
                    r = TestResult(link=link, ok=True, latency_ms=round(latency, 1))
                except asyncio.TimeoutError:
                    r = TestResult(link=link, ok=False, error="timeout")
                except Exception as e:
                    r = TestResult(link=link, ok=False, error=str(e))

                if on_done:
                    on_done(r)
                return r

        async def _run() -> list[TestResult]:
            sem = asyncio.Semaphore(concurrency)
            return await asyncio.gather(*[_check_one(l, sem) for l in links])

        return asyncio.run(_run())
