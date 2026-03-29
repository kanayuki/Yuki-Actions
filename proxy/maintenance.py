"""Maintenance tasks — dormant recheck, repo quality evaluation, health pruning.

Absorbs: best/maintain.py
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.table import Table

from .pool import LinkHealth

if TYPE_CHECKING:
    from .config import Config
    from .pool import PoolManager

logger = logging.getLogger(__name__)


def _recheck_dormant(pool: PoolManager, cfg: Config) -> tuple[int, int]:
    """Recheck dormant links due for re-verification.

    Returns (rechecked_count, revived_count).
    """
    from core.parse import health_key
    from core.verify import verify_links

    due = pool.dormant_due_for_recheck(cfg.verify.dormant_recheck_days)
    if not due:
        return 0, 0

    links = [e.link for e in due]
    link_hk: dict[str, str] = {}
    for e in due:
        hk = health_key(e.link)
        if hk:
            link_hk[e.link] = hk

    logger.info("Rechecking %d dormant links", len(links))
    results = verify_links(
        links,
        timeout=cfg.verify.alive_timeout_s,
        concurrency=cfg.verify.alive_concurrency,
    )

    from .pool import _now

    now = _now()
    health = pool.health
    revived = 0

    for r in results:
        hk = link_hk.get(r.link)
        if not hk or hk not in health:
            continue
        entry = health[hk]
        entry.last_verified = now

        if r.valid:
            entry.dormant = False
            entry.dormant_since = ""
            entry.fail_count = 0
            entry.last_ok = now
            entry.latency_ms = r.latency_ms
            entry.latency_history = (entry.latency_history + [r.latency_ms])[-5:]
            revived += 1

    return len(results), revived


def _evaluate_repos(pool: PoolManager, cfg: Config) -> int:
    """Evaluate repository quality and blacklist low-quality repos.

    Returns count of newly blacklisted repos.
    """
    health = pool.health
    scores = pool.load_repo_scores()

    repo_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "valid": 0}
    )
    for entry in health.values():
        source = entry.effective_source
        # Extract repo name from source_tag if github-sourced
        repo = ""
        if source.startswith("github:"):
            repo = source.removeprefix("github:")
        elif source and ":" not in source:
            repo = source  # Legacy source_repo field
        if repo:
            repo_stats[repo]["total"] += 1
            if entry.fail_count == 0 and entry.last_ok and not entry.dormant:
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
            if len(score.valid_ratio_history) > 10:
                score.valid_ratio_history = score.valid_ratio_history[-10:]

            if ratio < cfg.repo_quality.repo_min_valid_ratio:
                score.low_quality_streak += 1
            else:
                score.low_quality_streak = 0

            if (
                score.low_quality_streak >= cfg.repo_quality.repo_blacklist_after
                and score.source != "user"
                and not score.blacklisted
            ):
                score.blacklisted = True
                blacklisted_count += 1
                logger.warning(
                    "Blacklisted repo: %s (streak=%d)",
                    repo_name,
                    score.low_quality_streak,
                )

    pool.save_repo_scores(scores)
    return blacklisted_count


def maintain(pool: PoolManager, cfg: Config) -> None:
    """Run all maintenance tasks: dormant recheck, repo eval, prune."""
    try:
        from util import console
    except ImportError:
        from rich.console import Console

        console = Console(highlight=False)

    health = pool.health

    # 1. Recheck dormant links
    rechecked, revived = _recheck_dormant(pool, cfg)

    # 2. Evaluate repo quality
    blacklisted_count = _evaluate_repos(pool, cfg)

    # 3. Prune health if over limit
    pruned = pool.prune(cfg.pool.health_max_entries)

    pool.save_health()

    # 4. Stats
    dormant_count = sum(1 for e in health.values() if e.dormant)
    active_count = sum(
        1 for e in health.values() if not e.dormant and e.fail_count == 0
    )
    failing_count = sum(
        1 for e in health.values() if not e.dormant and e.fail_count > 0
    )

    # Summary
    grid = Table.grid(padding=(0, 2))
    grid.add_column(min_width=28)
    grid.add_column(justify="right", min_width=6)
    grid.add_row("[green]Dormant rechecked[/green]", str(rechecked))
    grid.add_row("[green bold]Revived[/green bold]", str(revived))
    grid.add_row("[dim]Pruned (never connected)[/dim]", str(pruned))
    grid.add_row("[red]Repos blacklisted[/red]", str(blacklisted_count))
    grid.add_row("", "")
    grid.add_row("[bold]Total links[/bold]", str(len(health)))
    grid.add_row("[green]  Active[/green]", str(active_count))
    grid.add_row("[yellow]  Failing[/yellow]", str(failing_count))
    grid.add_row("[dim]  Dormant[/dim]", str(dormant_count))

    console.print(
        Panel(
            grid,
            title="[bold]Maintenance Summary[/bold]",
            border_style="yellow",
            padding=(1, 2),
        )
    )
    logger.info(
        "Maintain: rechecked %d dormant (%d revived), pruned %d, "
        "blacklisted %d repos, %d links total",
        rechecked,
        revived,
        pruned,
        blacklisted_count,
        len(health),
    )
