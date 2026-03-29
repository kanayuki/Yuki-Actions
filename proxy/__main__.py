"""Unified CLI entry point for the proxy pipeline.

Usage:
    cd proxy
    python -m proxy collect                    # All sources -> pool
    python -m proxy collect --source github_crawler
    python -m proxy collect --source subscribe

    python -m proxy verify alive               # TCP/DNS -> alive.txt
    python -m proxy verify best-remote         # Engine chain -> best_remote.txt

    python -m proxy output country             # GeoIP -> country/*.txt
    python -m proxy output merge               # Pool -> merge.txt

    python -m proxy maintain                   # Dormant recheck + repo eval + prune
    python -m proxy run                        # Full pipeline
    python -m proxy status                     # Show dataset state
    python -m proxy pac                        # PAC pipeline (independent)
"""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# Ensure proxy/ is in sys.path so bare imports like
# ``from core.parse import ...`` and ``from util import console`` work.
_PROXY_DIR = Path(__file__).resolve().parent
if str(_PROXY_DIR) not in sys.path:
    sys.path.insert(0, str(_PROXY_DIR))

from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from .config import LOGS_DIR, Config, load_config
from .pool import PoolManager

try:
    from util import console
except ImportError:
    from rich.console import Console

    console = Console(highlight=False)


def _setup_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(
        LOGS_DIR / "proxy.log",
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s  %(message)s")
    )
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _cmd_collect(cfg: Config, args: argparse.Namespace) -> None:
    from .sources import get_all_sources, get_source_by_name

    pool = PoolManager()

    if args.source:
        console.print(
            Rule(f"[bold cyan]Collect: {args.source}[/bold cyan]")
        )
        source = get_source_by_name(args.source, cfg)
        results = source.collect()
    else:
        console.print(Rule("[bold cyan]Collect: all sources[/bold cyan]"))
        sources = get_all_sources(cfg)
        results = []
        for src in sources:
            console.print(f"  [dim]Source: {src.name()}[/dim]")
            results.extend(src.collect())

    new = pool.ingest(results, cfg.pool.raw_shard_max)
    pool.save_health()
    console.print(
        f"  Ingested [bold]{new}[/bold] new links "
        f"({sum(len(r.links) for r in results)} total collected)"
    )


def _cmd_verify(cfg: Config, args: argparse.Namespace) -> None:
    from .views import get_view_by_name

    pool = PoolManager()
    # Map "best-remote" CLI arg to "best_remote" view name
    view_name = args.type.replace("-", "_")
    view = get_view_by_name(view_name)
    console.print(
        Rule(f"[bold cyan]Verify: {args.type}[/bold cyan]")
    )
    view.generate(pool, cfg)


def _cmd_output(cfg: Config, args: argparse.Namespace) -> None:
    from .views import get_view_by_name

    pool = PoolManager()
    view = get_view_by_name(args.type)
    console.print(
        Rule(f"[bold cyan]Output: {args.type}[/bold cyan]")
    )
    view.generate(pool, cfg)


def _cmd_maintain(cfg: Config) -> None:
    from .maintenance import maintain

    console.print(Rule("[bold cyan]Maintenance[/bold cyan]"))
    pool = PoolManager()
    maintain(pool, cfg)


def _cmd_run(cfg: Config) -> None:
    """Full pipeline: collect -> verify alive -> verify best-remote -> output."""
    ns = argparse.Namespace

    _cmd_collect(cfg, ns(source=None))

    console.print(Rule("[bold cyan]Verify: alive[/bold cyan]"))
    from .views.alive import AliveView

    pool = PoolManager()
    AliveView().generate(pool, cfg)

    console.print(Rule("[bold cyan]Verify: best-remote[/bold cyan]"))
    from .views.best_remote import BestRemoteView

    BestRemoteView().generate(pool, cfg)

    console.print(Rule("[bold cyan]Output: country[/bold cyan]"))
    from .views.country import CountryView

    CountryView().generate(pool, cfg)

    console.print(Rule("[bold cyan]Output: merge[/bold cyan]"))
    from .views.merge import MergeView

    MergeView().generate(pool, cfg)


def _cmd_status(cfg: Config) -> None:
    from .config import (
        ALIVE_FILE,
        BEST_REMOTE_FILE,
        COUNTRY_DIR,
        REPOSITORIES_FILE,
    )

    pool = PoolManager()
    health = pool.health
    scores = pool.load_repo_scores()
    raw = pool.raw_stats()

    def _count(p: Path) -> int:
        if not p.exists():
            return 0
        return len(
            [
                line
                for line in p.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        )

    grid = Table.grid(padding=(0, 2))
    grid.add_column(min_width=28)
    grid.add_column(justify="right", min_width=8)

    # Raw pool
    grid.add_row("[bold]Raw Pool[/bold]", "")
    total_raw = 0
    for name, count in raw.items():
        grid.add_row(f"  {name}", str(count))
        total_raw += count
    if not raw:
        grid.add_row("  [dim](empty)[/dim]", "")
    else:
        grid.add_row("  [bold]total[/bold]", str(total_raw))

    grid.add_row("", "")

    # Output files
    grid.add_row("[bold]Output[/bold]", "")
    grid.add_row("  repositories.txt", str(_count(REPOSITORIES_FILE)))
    grid.add_row("  alive.txt", str(_count(ALIVE_FILE)))
    grid.add_row("  best_remote.txt", str(_count(BEST_REMOTE_FILE)))

    grid.add_row("", "")

    # Health breakdown
    active = sum(
        1
        for e in health.values()
        if not e.dormant and e.fail_count == 0 and e.last_ok
    )
    failing = sum(
        1 for e in health.values() if not e.dormant and e.fail_count > 0
    )
    dormant = sum(1 for e in health.values() if e.dormant)
    untested = sum(
        1 for e in health.values() if not e.dormant and not e.last_verified
    )

    grid.add_row("[bold]Health[/bold]", str(len(health)))
    grid.add_row("[green]  Active[/green]", str(active))
    grid.add_row("[yellow]  Failing[/yellow]", str(failing))
    grid.add_row("[dim]  Dormant[/dim]", str(dormant))
    grid.add_row("[dim]  Untested[/dim]", str(untested))

    grid.add_row("", "")

    # Repos
    blacklisted = sum(1 for s in scores.values() if s.blacklisted)
    grid.add_row("[bold]Repos[/bold]", str(len(scores)))
    grid.add_row("[red]  Blacklisted[/red]", str(blacklisted))

    # Country files
    if COUNTRY_DIR.exists():
        country_files = sorted(COUNTRY_DIR.glob("*.txt"))
        if country_files:
            grid.add_row("", "")
            grid.add_row("[bold]Countries[/bold]", "")
            for f in country_files:
                grid.add_row(f"  {f.stem}", str(_count(f)))

    console.print(
        Panel(
            grid,
            title="[bold]Dataset Status[/bold]",
            border_style="cyan",
            padding=(1, 2),
        )
    )


def _cmd_pac(cfg: Config) -> None:
    """Run the PAC pipeline (independent, delegates to pac/gen_share_links.py)."""
    console.print(Rule("[bold cyan]PAC Pipeline[/bold cyan]"))
    try:
        from pac import gen_share_links

        gen_share_links.main()
    except Exception as e:
        console.print(f"[red]PAC pipeline failed: {e}[/red]")
        raise


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="proxy",
        description="Unified proxy pipeline: collect, verify, output, maintain",
    )
    parser.add_argument(
        "--config", type=Path, default=None, help="Path to config.yaml"
    )

    sub = parser.add_subparsers(dest="command")

    # collect
    p_collect = sub.add_parser("collect", help="Run sources -> ingest into pool")
    p_collect.add_argument(
        "--source",
        type=str,
        default=None,
        help="Run specific source only (e.g. github_crawler, subscribe)",
    )

    # verify
    p_verify = sub.add_parser("verify", help="Run verification views")
    p_verify.add_argument(
        "type",
        choices=["alive", "best-remote"],
        help="Verification type",
    )

    # output
    p_output = sub.add_parser("output", help="Generate output views")
    p_output.add_argument(
        "type",
        choices=["country", "merge"],
        help="Output type",
    )

    # maintain
    sub.add_parser("maintain", help="Dormant recheck + repo eval + prune")

    # run
    sub.add_parser("run", help="Full pipeline (collect -> verify -> output)")

    # status
    sub.add_parser("status", help="Show dataset state")

    # pac
    sub.add_parser("pac", help="Run PAC pipeline (independent)")

    args = parser.parse_args()

    _setup_logging()
    cfg = load_config(args.config)

    commands = {
        "collect": lambda: _cmd_collect(cfg, args),
        "verify": lambda: _cmd_verify(cfg, args),
        "output": lambda: _cmd_output(cfg, args),
        "maintain": lambda: _cmd_maintain(cfg),
        "run": lambda: _cmd_run(cfg),
        "status": lambda: _cmd_status(cfg),
        "pac": lambda: _cmd_pac(cfg),
    }

    if not args.command:
        parser.print_help()
        return

    commands[args.command]()


if __name__ == "__main__":
    main()
