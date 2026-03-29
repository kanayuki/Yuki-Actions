"""Subscription URL source.

Fetches proxy share links from V2Ray/Clash subscription URLs listed
in a config file (one URL per line).

Absorbs: merge/merge.py (fetch logic)
"""

from __future__ import annotations

import base64
import logging
import re
from typing import TYPE_CHECKING

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from ..config import PROXY_DIR
from ._base import SourceResult

if TYPE_CHECKING:
    from ..config import Config

logger = logging.getLogger(__name__)

_KNOWN_SCHEMES = (
    "vmess://",
    "vless://",
    "ss://",
    "trojan://",
    "hysteria://",
    "hysteria2://",
    "tuic://",
    "anytls://",
    "mieru://",
)


def _fetch_and_extract(url: str) -> list[str]:
    """Fetch a subscription URL and extract share links."""
    try:
        resp = requests.get(url, timeout=15, verify=False)
        resp.raise_for_status()
        text = resp.text.strip()

        # Attempt base64 decode
        if re.match(r"^[a-zA-Z0-9+/=\n]+$", text):
            try:
                text = base64.b64decode(text).decode("utf-8")
            except Exception:
                pass

        links = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
            and any(line.strip().startswith(s) for s in _KNOWN_SCHEMES)
        ]
        logger.info("  %s -> %d links", url, len(links))
        return links
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return []


class SubscribeSource:
    """Fetches proxy links from subscription URLs."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    @staticmethod
    def name() -> str:
        return "subscribe"

    def collect(self) -> list[SourceResult]:
        """Read subscribe file, fetch each URL, extract links."""
        sub_file = PROXY_DIR / self._cfg.subscribe.subscribe_file
        if not sub_file.exists():
            logger.warning("Subscribe file not found: %s", sub_file)
            return []

        urls = [
            line.strip()
            for line in sub_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]

        if not urls:
            logger.info("No subscription URLs configured")
            return []

        results: list[SourceResult] = []
        for url in urls:
            links = _fetch_and_extract(url)
            if links:
                results.append(
                    SourceResult(
                        links=links,
                        source_tag=f"subscribe:{url}",
                    )
                )

        total = sum(len(r.links) for r in results)
        logger.info(
            "Subscribe complete: %d links from %d URLs", total, len(results)
        )
        return results
