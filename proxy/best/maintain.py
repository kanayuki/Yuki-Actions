"""Stage 5: Maintain — cleanup dead links and evaluate repo quality.

Removes links that failed max_consecutive_failures times, evaluates repo
quality, and blacklists consistently bad repos.

Usage: python -m best maintain
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from rich.panel import Panel
from rich.table import Table

from .config import Config, load_config
from .state import StateManager, _now

logger = logging.getLogger(__name__)

try:
    from util import console
except ImportError:
    from rich.console import Console
    console = Console(highlight=False)


def maintain(cfg: Config | None = None, state: StateManager | None = None) -> None:
    """Run Stage 5: cleanup and evaluate."""
    cfg = cfg or load_config()
    state = state or StateManager()
    health = state.load_link_health()
    scores = state.load_repo_scores()

    # ── 1. Remove dead links ──
    dead_keys: list[str] = []
    stale_keys: list[str] = []
    now = datetime.now(tz=timezone.utc)

    for hk, entry in list(health.items()):
        # Consecutive failure removal
        if entry.fail_count >= cfg.max_consecutive_failures:
            dead_keys.append(hk)
            continue
        # Stale removal: not verified in 7 days
        if entry.last_verified:
            try:
                last = datetime.fromisoformat(entry.last_verified)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                age_days = (now - last).total_seconds() / 86400
                if age_days > 7:
                    stale_keys.append(hk)
            except Exception:
                pass

    for hk in dead_keys + stale_keys:
        health.pop(hk, None)

    state.save_link_health(health)

    # ── 2. Evaluate repo quality ──
    # Count valid/total per repo
    repo_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "valid": 0})
    for entry in health.values():
        repo = entry.source_repo
        if repo:
            repo_stats[repo]["total"] += 1
            if entry.fail_count == 0 and entry.last_ok:
                repo_stats[repo]["valid"] += 1

    blacklisted_count = 0
    for repo_name, score in scores.items():
        stats = repo_stats.get(repo_name, {"total": 0, "valid": 0})
        total = stats["total"]
        valid = stats["valid"]

        score.total_links_contributed = total
        score.total_valid_contributed = valid

        if total > 0:
            ratio = valid / total
            score.valid_ratio_history.append(round(ratio, 3))
            # Keep last 10 entries
            if len(score.valid_ratio_history) > 10:
                score.valid_ratio_history = score.valid_ratio_history[-10:]

            if ratio < cfg.repo_min_valid_ratio:
                score.low_quality_streak += 1
            else:
                score.low_quality_streak = 0

            # Blacklist check (skip user repos)
            if (
                score.low_quality_streak >= cfg.repo_blacklist_after
                and score.source != "user"
                and not score.blacklisted
            ):
                score.blacklisted = True
                blacklisted_count += 1
                logger.warning("Blacklisted repo: %s (streak=%d)", repo_name, score.low_quality_streak)

    state.save_repo_scores(scores)

    # ── 3. Country pool trimming ──
    # This is handled by rank stage, but we can also trim here
    # for entries exceeding pool_max that haven't been ranked yet

    # ── Summary ──
    grid = Table.grid(padding=(0, 2))
    grid.add_column(min_width=24)
    grid.add_column(justify="right", min_width=6)
    grid.add_row("[red]Dead links removed[/red]", str(len(dead_keys)))
    grid.add_row("[yellow]Stale links removed[/yellow]", str(len(stale_keys)))
    grid.add_row("[dim]Remaining links[/dim]", str(len(health)))
    grid.add_row("[red]Repos blacklisted[/red]", str(blacklisted_count))
    grid.add_row("[dim]Total repos tracked[/dim]", str(len(scores)))

    console.print(Panel(grid, title="[bold]Maintenance Summary[/bold]", border_style="yellow", padding=(1, 2)))
    logger.info(
        "Maintain: removed %d dead + %d stale, blacklisted %d repos, %d links remaining",
        len(dead_keys), len(stale_keys), blacklisted_count, len(health),
    )
