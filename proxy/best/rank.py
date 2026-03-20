"""Stage 4: Rank — sort, classify by country, and output best.txt + country files.

Reads link_health.json, resolves GeoIP for unknown hosts, groups by country,
trims pools, and generates output files.

Usage: python -m best rank
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from rich.panel import Panel
from rich.table import Table

from .config import AVAILABLE_FILE, BEST_FILE, COUNTRY_DIR, Config, load_config
from .geo import resolve_batch
from .state import LinkHealth, StateManager

logger = logging.getLogger(__name__)

try:
    from util import console
except ImportError:
    from rich.console import Console
    console = Console(highlight=False)


def rank(cfg: Config | None = None, state: StateManager | None = None) -> None:
    """Run Stage 4: rank and classify proxies by country."""
    cfg = cfg or load_config()
    state = state or StateManager()
    health = state.load_link_health()

    # Filter to healthy links only
    valid: list[LinkHealth] = [
        entry for entry in health.values()
        if entry.fail_count == 0 and entry.last_ok and entry.link
    ]

    if not valid:
        logger.warning("No valid proxies to rank")
        console.print("[yellow]No valid proxies to rank[/yellow]")
        return

    # Resolve GeoIP for hosts without country
    hosts_needing_geo = [e.host for e in valid if not e.country or e.country == "XX"]
    known_geo = {e.host: e.country for e in valid if e.country and e.country != "XX"}

    if hosts_needing_geo:
        logger.info("Resolving GeoIP for %d hosts", len(hosts_needing_geo))
        geo_results = resolve_batch(hosts_needing_geo, known_geo)
        # Update health entries with resolved countries
        for entry in valid:
            if (not entry.country or entry.country == "XX") and entry.host in geo_results:
                entry.country = geo_results[entry.host]
        # Persist updated countries
        state.save_link_health(health)

    # Group by country
    by_country: dict[str, list[LinkHealth]] = defaultdict(list)
    for entry in valid:
        cc = entry.country or "XX"
        by_country[cc].append(entry)

    # Sort each country by latency
    for cc in by_country:
        by_country[cc].sort(key=lambda e: e.latency_ms or 9999)

    # Merge small countries into OTHER
    small_countries: list[str] = []
    for cc, entries in list(by_country.items()):
        if len(entries) < cfg.min_country_size and cc != "XX":
            small_countries.append(cc)

    if small_countries:
        other = by_country.get("OTHER", [])
        for cc in small_countries:
            other.extend(by_country.pop(cc))
        if "XX" in by_country:
            other.extend(by_country.pop("XX"))
        other.sort(key=lambda e: e.latency_ms or 9999)
        by_country["OTHER"] = other
    elif "XX" in by_country:
        by_country["OTHER"] = by_country.pop("XX")

    # Trim each country to pool_max
    for cc in by_country:
        if len(by_country[cc]) > cfg.country_pool_max:
            by_country[cc] = by_country[cc][: cfg.country_pool_max]

    # Write country files
    COUNTRY_DIR.mkdir(parents=True, exist_ok=True)
    # Clean old country files
    for old_file in COUNTRY_DIR.glob("*.txt"):
        old_file.unlink()

    for cc, entries in sorted(by_country.items()):
        out_file = COUNTRY_DIR / f"{cc}.txt"
        out_file.write_text(
            "\n".join(e.link for e in entries) + "\n",
            encoding="utf-8",
        )

    # Generate best.txt: global top N by latency
    all_valid_sorted = sorted(valid, key=lambda e: e.latency_ms or 9999)
    best = all_valid_sorted[: cfg.top_n]
    BEST_FILE.write_text(
        "\n".join(e.link for e in best) + "\n" if best else "",
        encoding="utf-8",
    )

    # Also regenerate available.txt
    AVAILABLE_FILE.write_text(
        "\n".join(e.link for e in all_valid_sorted) + "\n" if all_valid_sorted else "",
        encoding="utf-8",
    )

    # Summary
    grid = Table.grid(padding=(0, 2))
    grid.add_column(min_width=10)
    grid.add_column(justify="right", min_width=6)
    grid.add_column(style="dim", min_width=12)
    for cc in sorted(by_country.keys()):
        entries = by_country[cc]
        avg_lat = sum(e.latency_ms for e in entries) / len(entries) if entries else 0
        grid.add_row(f"[bold]{cc}[/bold]", str(len(entries)), f"avg {avg_lat:.0f} ms")
    grid.add_row("", "", "")
    grid.add_row("[green bold]best.txt[/green bold]", str(len(best)), f"top {cfg.top_n}")
    grid.add_row("[dim]available.txt[/dim]", str(len(all_valid_sorted)), "total")

    console.print(Panel(grid, title="[bold]Rank Summary[/bold]", border_style="blue", padding=(1, 2)))
    logger.info("Rank complete: %d countries, %d best, %d total", len(by_country), len(best), len(all_valid_sorted))
