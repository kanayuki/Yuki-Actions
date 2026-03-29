"""CLI entry point for the proxy dataset crawler.

Usage:
    cd proxy
    python -m best discover          # Stage 1: find repos
    python -m best collect           # Stage 2: fetch links -> raw pool
    python -m best alive             # Stage 3a: TCP/DNS verify -> alive.txt
    python -m best best-remote       # Stage 3b: engine test -> best_remote.txt
    python -m best rank              # Stage 4: GeoIP -> country/
    python -m best maintain          # Stage 5: dormant recheck + repo eval
    python -m best crawl             # Full pipeline
    python -m best status            # Show dataset state
"""

from __future__ import annotations

import argparse
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from .config import LOGS_DIR, Config, load_config

try:
    from util import console
except ImportError:
    from rich.console import Console

    console = Console(highlight=False)


def _setup_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(
        LOGS_DIR / "best.log",
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


def _cmd_discover(cfg: Config) -> None:
    from .discover import discover
    from .state import StateManager

    console.print(Rule("[bold cyan]Stage 1: Discover[/bold cyan]"))
    repos = discover(cfg, StateManager())
    console.print(f"  Found [bold]{len(repos)}[/bold] repos -> repositories.txt")


def _cmd_collect(cfg: Config) -> None:
    from .collect import collect
    from .state import StateManager

    console.print(Rule("[bold cyan]Stage 2: Collect[/bold cyan]"))
    links = collect(cfg, StateManager())
    console.print(
        f"  Collected [bold]{len(links)}[/bold] links -> raw pool"
    )


def _cmd_alive(cfg: Config) -> None:
    from .checker import alive_check
    from .state import StateManager

    console.print(Rule("[bold cyan]Stage 3a: Alive Check (TCP/DNS)[/bold cyan]"))
    n = alive_check(cfg, StateManager())
    if n == 0:
        console.print("  [dim]No links to verify[/dim]")


def _cmd_best_remote(cfg: Config) -> None:
    from .checker import best_remote_check
    from .state import StateManager

    console.print(
        Rule("[bold cyan]Stage 3b: Best Remote (engine chain)[/bold cyan]")
    )
    n = best_remote_check(cfg, StateManager())
    if n == 0:
        console.print("  [dim]No results[/dim]")


def _cmd_rank(cfg: Config) -> None:
    from .rank import rank
    from .state import StateManager

    console.print(Rule("[bold cyan]Stage 4: Rank[/bold cyan]"))
    rank(cfg, StateManager())


def _cmd_maintain(cfg: Config) -> None:
    from .maintain import maintain
    from .state import StateManager

    console.print(Rule("[bold cyan]Stage 5: Maintain[/bold cyan]"))
    maintain(cfg, StateManager())


def _cmd_crawl(cfg: Config) -> None:
    """Full pipeline: discover -> collect -> alive -> best-remote -> rank."""
    _cmd_discover(cfg)
    _cmd_collect(cfg)
    _cmd_alive(cfg)
    _cmd_best_remote(cfg)
    _cmd_rank(cfg)


def _cmd_status(cfg: Config) -> None:
    """Show current dataset state."""
    from .config import (
        ALIVE_FILE,
        BEST_REMOTE_FILE,
        COUNTRY_DIR,
        REPOSITORIES_FILE,
    )
    from .state import StateManager

    state = StateManager()
    health = state.load_health()
    scores = state.load_repo_scores()
    raw = state.raw_stats()

    def _count_lines(p: Path) -> int:
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
    grid.add_row("  repositories.txt", str(_count_lines(REPOSITORIES_FILE)))
    grid.add_row("  alive.txt", str(_count_lines(ALIVE_FILE)))
    grid.add_row("  best_remote.txt", str(_count_lines(BEST_REMOTE_FILE)))

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
                grid.add_row(f"  {f.stem}", str(_count_lines(f)))

    console.print(
        Panel(
            grid,
            title="[bold]Dataset Status[/bold]",
            border_style="cyan",
            padding=(1, 2),
        )
    )


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="best",
        description="Proxy dataset crawler: discover, collect, verify, rank",
    )
    parser.add_argument(
        "--config", type=Path, default=None, help="Path to config.yaml"
    )

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("discover", help="Stage 1: search GitHub for repos")
    sub.add_parser("collect", help="Stage 2: fetch links -> raw pool")
    sub.add_parser("alive", help="Stage 3a: TCP/DNS alive check")
    sub.add_parser("best-remote", help="Stage 3b: engine-chain real test")
    sub.add_parser("rank", help="Stage 4: GeoIP classify -> country/")
    sub.add_parser("maintain", help="Stage 5: dormant recheck + repo eval")
    sub.add_parser("crawl", help="Full pipeline (all stages)")
    sub.add_parser("status", help="Show dataset state")

    args = parser.parse_args()

    _setup_logging()

    cfg = load_config(args.config)

    commands: dict[str, object] = {
        "discover": lambda: _cmd_discover(cfg),
        "collect": lambda: _cmd_collect(cfg),
        "alive": lambda: _cmd_alive(cfg),
        "best-remote": lambda: _cmd_best_remote(cfg),
        "rank": lambda: _cmd_rank(cfg),
        "maintain": lambda: _cmd_maintain(cfg),
        "crawl": lambda: _cmd_crawl(cfg),
        "status": lambda: _cmd_status(cfg),
    }

    if not args.command:
        parser.print_help()
        return

    commands[args.command]()


if __name__ == "__main__":
    main()
