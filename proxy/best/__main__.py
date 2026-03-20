"""CLI entry point for the best proxy pipeline.

Usage:
    cd proxy
    python -m best discover          # Stage 1
    python -m best collect           # Stage 2
    python -m best verify            # Stage 3 (one batch)
    python -m best verify --all      # Stage 3 (all queued)
    python -m best rank              # Stage 4
    python -m best maintain          # Stage 5
    python -m best run               # Full pipeline
    python -m best run --top 200     # Override top_n
    python -m best status            # Show current state
"""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from .config import BEST_DIR, LOGS_DIR, Config, load_config

# Ensure proxy/ is in sys.path for bare imports (verify, util, converter)
_PROXY_DIR = BEST_DIR.parent
if str(_PROXY_DIR) not in sys.path:
    sys.path.insert(0, str(_PROXY_DIR))
if str(BEST_DIR) not in sys.path:
    sys.path.insert(0, str(BEST_DIR))


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
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s  %(message)s"))
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
    console.print(f"  Found [bold]{len(repos)}[/bold] repos → repositories.txt")


def _cmd_collect(cfg: Config) -> None:
    from .collect import collect
    from .state import StateManager

    console.print(Rule("[bold cyan]Stage 2: Collect[/bold cyan]"))
    links = collect(cfg, StateManager())
    console.print(f"  Collected [bold]{len(links)}[/bold] links → collections.txt")


def _cmd_verify(cfg: Config, *, process_all: bool = False) -> None:
    from .state import StateManager
    from .checker import verify_batch

    console.print(Rule("[bold cyan]Stage 3: Verify[/bold cyan]"))
    n = verify_batch(cfg, StateManager(), process_all=process_all)
    if n == 0:
        console.print("  [dim]Nothing to verify[/dim]")


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


def _cmd_run(cfg: Config) -> None:
    """Full pipeline: all stages in order."""
    _cmd_discover(cfg)
    _cmd_collect(cfg)
    _cmd_verify(cfg, process_all=True)
    _cmd_rank(cfg)
    _cmd_maintain(cfg)


def _cmd_status(cfg: Config) -> None:
    """Show current pipeline state."""
    from .config import AVAILABLE_FILE, BEST_FILE, COLLECTIONS_FILE, COUNTRY_DIR, REPOSITORIES_FILE
    from .state import StateManager

    state = StateManager()
    health = state.load_link_health()
    scores = state.load_repo_scores()
    queue = state.load_queue()

    # File line counts
    def _count_lines(p: Path) -> int:
        if not p.exists():
            return 0
        return len([l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()])

    # Engine availability (check without downloading)
    from .engine.binary import find_binary

    engine_names = []
    for name, cfg_path in [("xray", cfg.xray_bin), ("sing-box", cfg.singbox_bin), ("mihomo", cfg.mihomo_bin)]:
        if find_binary(name, cfg_path):
            engine_names.append(name)
    engine_names.append("tcp")  # always available

    grid = Table.grid(padding=(0, 2))
    grid.add_column(min_width=28)
    grid.add_column(justify="right", min_width=8)
    grid.add_row("[bold]Engines[/bold]", " → ".join(engine_names))
    grid.add_row("", "")
    grid.add_row("repositories.txt", str(_count_lines(REPOSITORIES_FILE)))
    grid.add_row("collections.txt", str(_count_lines(COLLECTIONS_FILE)))
    grid.add_row("available.txt", str(_count_lines(AVAILABLE_FILE)))
    grid.add_row("best.txt", str(_count_lines(BEST_FILE)))
    grid.add_row("", "")
    grid.add_row("Health entries", str(len(health)))
    valid_count = sum(1 for e in health.values() if e.fail_count == 0 and e.last_ok)
    grid.add_row("  valid (fail=0)", str(valid_count))
    failing = sum(1 for e in health.values() if e.fail_count > 0)
    grid.add_row("  failing", str(failing))
    grid.add_row("Verify queue", str(len(queue)))
    grid.add_row("", "")
    grid.add_row("Repos tracked", str(len(scores)))
    blacklisted = sum(1 for s in scores.values() if s.blacklisted)
    grid.add_row("  blacklisted", str(blacklisted))

    # Country breakdown
    if COUNTRY_DIR.exists():
        grid.add_row("", "")
        grid.add_row("[bold]Country files[/bold]", "")
        for f in sorted(COUNTRY_DIR.glob("*.txt")):
            n = _count_lines(f)
            grid.add_row(f"  {f.stem}", str(n))

    console.print(Panel(grid, title="[bold]Pipeline Status[/bold]", border_style="cyan", padding=(1, 2)))


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="best",
        description="Free proxy collector, verifier, and ranker",
    )
    parser.add_argument(
        "--config", type=Path, default=None, help="Path to config.yaml"
    )
    parser.add_argument(
        "--top", type=int, default=None, help="Override top_n"
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("discover", help="Stage 1: search GitHub for repos")
    sub.add_parser("collect", help="Stage 2: fetch links from repos")

    verify_p = sub.add_parser("verify", help="Stage 3: verify proxy connectivity")
    verify_p.add_argument("--all", action="store_true", dest="verify_all", help="Process all, not just one batch")

    sub.add_parser("rank", help="Stage 4: rank and classify by country")
    sub.add_parser("maintain", help="Stage 5: cleanup and repo evaluation")
    sub.add_parser("run", help="Full pipeline (all stages)")
    sub.add_parser("status", help="Show current pipeline state")

    args = parser.parse_args()

    _setup_logging()

    cfg = load_config(args.config)
    if args.top is not None:
        cfg.top_n = args.top

    commands = {
        "discover": lambda: _cmd_discover(cfg),
        "collect": lambda: _cmd_collect(cfg),
        "verify": lambda: _cmd_verify(cfg, process_all=getattr(args, "verify_all", False)),
        "rank": lambda: _cmd_rank(cfg),
        "maintain": lambda: _cmd_maintain(cfg),
        "run": lambda: _cmd_run(cfg),
        "status": lambda: _cmd_status(cfg),
    }

    if not args.command:
        parser.print_help()
        return

    commands[args.command]()


if __name__ == "__main__":
    main()
