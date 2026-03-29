"""Stage 5: Maintain -- dormant recheck, repo quality evaluation, health pruning.

Links that fail max_consecutive_failures times are marked dormant (not deleted).
Dormant links are rechecked after dormant_recheck_days.
Health entries are pruned when exceeding health_max_entries.

Usage: python -m best maintain
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from rich.panel import Panel
from rich.table import Table

from .config import Config, load_config
from .state import LinkHealth, StateManager, _now

logger = logging.getLogger(__name__)

try:
    from util import console
except ImportError:
    from rich.console import Console

    console = Console(highlight=False)


def _recheck_dormant(
    cfg: Config,
    health: dict[str, LinkHealth],
) -> tuple[int, int]:
    """Recheck dormant links that are due for re-verification.

    Returns (rechecked_count, revived_count).
    """
    from core.verify import verify_links

    now_dt = datetime.now(tz=timezone.utc)

    # Find dormant links due for recheck
    due: dict[str, LinkHealth] = {}
    for hk, entry in health.items():
        if not entry.dormant or not entry.link:
            continue
        if not entry.dormant_since:
            due[hk] = entry
            continue
        try:
            ds = datetime.fromisoformat(entry.dormant_since)
            if ds.tzinfo is None:
                ds = ds.replace(tzinfo=timezone.utc)
            age_days = (now_dt - ds).total_seconds() / 86400
            if age_days >= cfg.dormant_recheck_days:
                due[hk] = entry
        except Exception:
            due[hk] = entry

    if not due:
        return 0, 0

    links = [e.link for e in due.values()]
    link_hk = {e.link: hk for hk, e in due.items()}

    logger.info("Rechecking %d dormant links", len(links))
    results = verify_links(
        links, timeout=cfg.alive_timeout_s, concurrency=cfg.alive_concurrency
    )

    now = _now()
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
            entry.latency_history = (entry.latency_history + [r.latency_ms])[
                -5:
            ]
            revived += 1

    return len(results), revived


def _prune_health(
    health: dict[str, LinkHealth], max_entries: int
) -> int:
    """Prune oldest never-connected dormant entries if over max_entries.

    Returns number of pruned entries.
    """
    if len(health) <= max_entries:
        return 0

    # Candidates: dormant entries that never successfully connected
    candidates = [
        (hk, entry)
        for hk, entry in health.items()
        if entry.dormant and not entry.last_ok
    ]
    # Sort by first_seen ascending (oldest first)
    candidates.sort(key=lambda x: x[1].first_seen or "")

    to_remove = len(health) - max_entries
    pruned = 0
    for hk, _ in candidates[:to_remove]:
        health.pop(hk)
        pruned += 1

    return pruned


def maintain(
    cfg: Config | None = None, state: StateManager | None = None
) -> None:
    """Run Stage 5: dormant recheck, repo evaluation, health pruning."""
    cfg = cfg or load_config()
    state = state or StateManager()
    health = state.load_health()
    scores = state.load_repo_scores()

    # 1. Recheck dormant links
    rechecked, revived = _recheck_dormant(cfg, health)

    # 2. Evaluate repo quality
    repo_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "valid": 0}
    )
    for entry in health.values():
        repo = entry.source_repo
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

            if ratio < cfg.repo_min_valid_ratio:
                score.low_quality_streak += 1
            else:
                score.low_quality_streak = 0

            if (
                score.low_quality_streak >= cfg.repo_blacklist_after
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

    state.save_repo_scores(scores)

    # 3. Prune health if over limit
    pruned = _prune_health(health, cfg.health_max_entries)

    state.save_health(health)

    # 4. Count stats
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
    grid.add_row("[dim]Repos tracked[/dim]", str(len(scores)))

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
