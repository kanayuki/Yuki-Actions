"""Core proxy data models shared across all pipelines."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass
class ParsedProxy:
    """Protocol-level representation of a proxy share link."""

    protocol: str
    host: str
    port: int
    raw_link: str

    @property
    def health_key(self) -> str:
        """Stable identity across remark/date rotation: sha256(protocol:host:port)."""
        return hashlib.sha256(f"{self.protocol}:{self.host}:{self.port}".encode()).hexdigest()


@dataclass
class VerifyResult:
    """Result of a TCP/DNS connectivity check."""

    link: str
    valid: bool
    latency_ms: float = 0.0
    error: str = ""
