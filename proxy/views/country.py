"""Country view — GeoIP classification into per-country files.

Generates country/*.txt with latency-sorted links per country.

Absorbs: best/rank.py
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.table import Table

from ..config import COUNTRY_DIR
from ..pool import LinkHealth

if TYPE_CHECKING:
    from ..config import Config
    from ..pool import PoolManager

logger = logging.getLogger(__name__)


class CountryView:
    """GeoIP classify -> country/*.txt."""

    @staticmethod
    def name() -> str:
        return "country"

    def generate(self, pool: PoolManager, cfg: Config) -> None:
        from core.geo import resolve_batch

        try:
            from util import console
        except ImportError:
            from rich.console import Console

            console = Console(highlight=False)

        valid = pool.active_links()
        if not valid:
            logger.warning("No valid proxies to rank")
            console.print("[yellow]No valid proxies to rank[/yellow]")
            return

        # Resolve GeoIP for hosts without country
        hosts_needing_geo = [
            e.host for e in valid if not e.country or e.country == "XX"
        ]
        known_geo = {
            e.host: e.country
            for e in valid
            if e.country and e.country != "XX"
        }

        if hosts_needing_geo:
            logger.info("Resolving GeoIP for %d hosts", len(hosts_needing_geo))
            geo_results = resolve_batch(hosts_needing_geo, known_geo)
            health = pool.health
            for entry in health.values():
                if (
                    not entry.country or entry.country == "XX"
                ) and entry.host in geo_results:
                    entry.country = geo_results[entry.host]
            pool.save_health()
            # Refresh valid list with updated countries
            valid = pool.active_links()

        # Group by country
        by_country: dict[str, list[LinkHealth]] = defaultdict(list)
        for entry in valid:
            cc = entry.country or "XX"
            by_country[cc].append(entry)

        # Sort each country by latency
        for cc in by_country:
            by_country[cc].sort(key=lambda e: e.latency_ms or 9999)

        # Merge small countries into OTHER
        small_countries = [
            cc
            for cc, entries in by_country.items()
            if len(entries) < cfg.output.min_country_size
            and cc not in ("XX", "OTHER")
        ]
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
            if len(by_country[cc]) > cfg.output.country_pool_max:
                by_country[cc] = by_country[cc][: cfg.output.country_pool_max]

        # Write country files
        COUNTRY_DIR.mkdir(parents=True, exist_ok=True)
        for old_file in COUNTRY_DIR.glob("*.txt"):
            old_file.unlink()

        for cc, entries in sorted(by_country.items()):
            out_file = COUNTRY_DIR / f"{cc}.txt"
            out_file.write_text(
                "\n".join(e.link for e in entries) + "\n",
                encoding="utf-8",
            )

        # Summary
        grid = Table.grid(padding=(0, 2))
        grid.add_column(min_width=10)
        grid.add_column(justify="right", min_width=6)
        grid.add_column(style="dim", min_width=12)
        for cc in sorted(by_country.keys()):
            entries = by_country[cc]
            avg_lat = (
                sum(e.latency_ms for e in entries) / len(entries)
                if entries
                else 0
            )
            grid.add_row(
                f"[bold]{cc}[/bold]",
                str(len(entries)),
                f"avg {avg_lat:.0f} ms",
            )

        console.print(
            Panel(
                grid,
                title="[bold]Rank Summary[/bold]",
                border_style="blue",
                padding=(1, 2),
            )
        )
        logger.info(
            "Rank complete: %d countries, %d total valid",
            len(by_country),
            len(valid),
        )
