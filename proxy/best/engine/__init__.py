"""Test engine abstraction for proxy connectivity verification.

Priority chain: xray → singbox → mihomo → tcp
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    link: str
    ok: bool
    latency_ms: float = 0.0
    error: str = ""


class TestEngine(ABC):
    """Abstract base class for proxy test engines."""

    @classmethod
    @abstractmethod
    def name(cls) -> str: ...

    @classmethod
    @abstractmethod
    def supported_protocols(cls) -> set[str]: ...

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """Check if the engine binary is available."""

    @abstractmethod
    def test_batch(
        self,
        links: list[str],
        *,
        timeout_ms: int = 6000,
        concurrency: int = 50,
        test_url: str = "http://www.gstatic.com/generate_204",
        on_done: Callable[[TestResult], None] | None = None,
    ) -> list[TestResult]:
        """Test a batch of proxy links. Returns one TestResult per link."""


def _get_protocol(link: str) -> str:
    if "://" not in link:
        return ""
    return link.split("://", 1)[0].lower()


def get_engine_chain(preferred: str = "auto") -> list[TestEngine]:
    """Return available engines in priority order.

    If *preferred* is not ``"auto"``, only that engine (+ tcp fallback) is returned.
    """
    from .mihomo import MihomoEngine
    from .singbox import SingboxEngine
    from .tcp import TcpEngine
    from .xray import XrayEngine

    all_engines: list[type[TestEngine]] = [XrayEngine, SingboxEngine, MihomoEngine, TcpEngine]

    if preferred != "auto":
        name_map = {cls.name(): cls for cls in all_engines}
        if preferred in name_map and name_map[preferred].is_available():
            chain: list[TestEngine] = [name_map[preferred]()]
            if preferred != "tcp":
                chain.append(TcpEngine())
            return chain
        logger.warning("Engine '%s' not available, falling back to auto", preferred)

    chain = []
    for cls in all_engines:
        if cls.is_available():
            chain.append(cls())
            logger.info("Engine available: %s", cls.name())
    if not chain:
        chain.append(all_engines[-1]())  # TcpEngine always works
    return chain


def test_with_chain(
    links: list[str],
    chain: list[TestEngine],
    *,
    timeout_ms: int = 6000,
    concurrency: int = 50,
    test_url: str = "http://www.gstatic.com/generate_204",
    on_done: Callable[[TestResult], None] | None = None,
) -> list[TestResult]:
    """Test links using the engine chain with protocol-based fallback.

    Each engine handles the protocols it supports; unsupported links fall
    through to the next engine in the chain.
    """
    results: list[TestResult] = []
    remaining = list(links)

    for engine in chain:
        if not remaining:
            break
        supported = engine.supported_protocols()
        batch = [l for l in remaining if _get_protocol(l) in supported]
        rest = [l for l in remaining if _get_protocol(l) not in supported]

        if batch:
            logger.info(
                "Testing %d links with %s (protocols: %s)",
                len(batch),
                engine.name(),
                ", ".join(sorted({_get_protocol(l) for l in batch})),
            )
            batch_results = engine.test_batch(
                batch,
                timeout_ms=timeout_ms,
                concurrency=concurrency,
                test_url=test_url,
                on_done=on_done,
            )
            results.extend(batch_results)
        remaining = rest

    # Any leftovers that no engine handled → mark failed
    for link in remaining:
        r = TestResult(link=link, ok=False, error="unsupported_protocol")
        results.append(r)
        if on_done:
            on_done(r)

    return results
