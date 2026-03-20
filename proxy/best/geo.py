"""GeoIP batch resolver with persistent cache.

Uses ip-api.com/batch (free, up to 100 per request, 15 req/min).
Falls back to single-query ip-api.com/json/{ip} (45/min).
"""

from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

_BATCH_URL = "http://ip-api.com/batch"
_SINGLE_URL = "http://ip-api.com/json/{}"
_BATCH_SIZE = 100


def resolve_batch(hosts: list[str], known: dict[str, str] | None = None) -> dict[str, str]:
    """Resolve country codes for a list of hosts.

    *known* is a ``{host: country_code}`` cache — already-resolved hosts are
    skipped.  Returns ``{host: country_code}`` for all *hosts* (merged with
    *known*).
    """
    known = dict(known or {})
    result: dict[str, str] = {}
    to_resolve: list[str] = []

    for h in hosts:
        if h in known and known[h] and known[h] != "XX":
            result[h] = known[h]
        else:
            to_resolve.append(h)

    if not to_resolve:
        return result

    to_resolve = list(dict.fromkeys(to_resolve))  # deduplicate, preserve order

    # Batch API
    for i in range(0, len(to_resolve), _BATCH_SIZE):
        chunk = to_resolve[i : i + _BATCH_SIZE]
        try:
            resp = requests.post(
                _BATCH_URL,
                json=[{"query": h, "fields": "query,countryCode,status"} for h in chunk],
                timeout=15,
            )
            if resp.ok:
                for item in resp.json():
                    host = item.get("query", "")
                    cc = item.get("countryCode", "XX") if item.get("status") == "success" else "XX"
                    result[host] = cc
            else:
                logger.warning("ip-api batch HTTP %d, falling back to single", resp.status_code)
                for h in chunk:
                    result[h] = _single_query(h)
        except Exception as e:
            logger.warning("ip-api batch error: %s, falling back to single", e)
            for h in chunk:
                result[h] = _single_query(h)

        if i + _BATCH_SIZE < len(to_resolve):
            time.sleep(4)  # rate limit: ~15 req/min for batch

    # Fill missing
    for h in to_resolve:
        if h not in result:
            result[h] = "XX"

    return result


def _single_query(host: str) -> str:
    try:
        resp = requests.get(_SINGLE_URL.format(host), timeout=10)
        if resp.ok:
            data = resp.json()
            if data.get("status") == "success":
                return data.get("countryCode", "XX")
    except Exception:
        pass
    return "XX"
