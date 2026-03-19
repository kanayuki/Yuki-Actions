"""Search GitHub for free v2ray subscriptions, tiered verification, keep top N.

Two-tier verification:
  Tier 1 — TCP port check (fast, ~5 s timeout, 64 concurrent)
            Eliminates nodes with closed/firewalled ports.
  Tier 2 — mihomo real HTTP test (Linux/Actions only)
            Routes actual HTTP through each proxy via mihomo's REST API.
            Only nodes that actually forward traffic pass this stage.

Tier 2 runs automatically on Linux (GitHub Actions). Falls back to Tier 1
latencies on Windows/macOS for local development.

Usage:
    python proxy/best/best.py           # top 100
    python proxy/best/best.py --top 50
"""

import argparse
import base64
import logging
import re
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent  # proxy/best/
PROXY_DIR = BASE_DIR.parent                 # proxy/

if str(PROXY_DIR) not in sys.path:
    sys.path.insert(0, str(PROXY_DIR))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import requests
import urllib3
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.rule import Rule
from rich.table import Table

from util import console
from verify import verify_links, VerifyResult
import converter
import github
import mihomo as mihomo_mod

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TOP_N = 100
TIER1_TIMEOUT = 5.0
TIER1_CONCURRENCY = 64
TIER2_TIMEOUT_MS = 6000
TIER2_CONCURRENCY = 50
OUTPUT_FILE = PROXY_DIR / "best.txt"
LOGS_DIR = PROXY_DIR / "logs"

_KNOWN_SCHEMES = (
    "vmess://", "vless://", "ss://", "trojan://",
    "hysteria://", "hysteria2://", "tuic://", "anytls://", "mieru://",
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


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
# Fetch & decode subscriptions
# ---------------------------------------------------------------------------

_B64_RE = re.compile(r"^[A-Za-z0-9+/=\r\n]+$")


def _fetch_links(url: str) -> list[str]:
    """Fetch a URL, base64-decode if needed, return proxy share links."""
    try:
        resp = requests.get(url, timeout=12, verify=False)
        if not resp.ok:
            return []
        text = resp.text.strip()
    except Exception as e:
        logger.debug("Fetch failed %s: %s", url, e)
        return []

    # Attempt base64 decode when content looks like pure base64
    compact = text.replace("\n", "").replace("\r", "")
    if _B64_RE.match(compact) and len(compact) > 20:
        try:
            decoded = base64.b64decode(compact + "==").decode("utf-8")
            if any(s in decoded for s in _KNOWN_SCHEMES):
                text = decoded
        except Exception:
            pass

    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and any(line.strip().startswith(s) for s in _KNOWN_SCHEMES)
    ]


# ---------------------------------------------------------------------------
# Tier 1: TCP port check
# ---------------------------------------------------------------------------


def _tier1(links: list[str]) -> list[VerifyResult]:
    """TCP port reachability check. Returns all results (valid + invalid)."""
    console.print(Rule("[bold cyan]Tier 1 — TCP 端口检测[/bold cyan]"))
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("TCP 检测…", total=len(links))
        from verify import verify_links_async
        import asyncio
        results = asyncio.run(
            verify_links_async(
                links,
                timeout=TIER1_TIMEOUT,
                concurrency=TIER1_CONCURRENCY,
                _on_done=lambda _: progress.advance(task),
            )
        )
    valid = [r for r in results if r.valid]
    logger.info("Tier 1: %d/%d passed", len(valid), len(links))
    console.print(f"  通过 [green bold]{len(valid)}[/green bold] / {len(links)} 条")
    return results


# ---------------------------------------------------------------------------
# Tier 2: mihomo real HTTP test
# ---------------------------------------------------------------------------


def _tier2(
    tier1_results: list[VerifyResult],
) -> tuple[list[tuple[str, int]], list[str]]:
    """
    Convert Tier 1 survivors to Clash format, run mihomo, test real HTTP.

    Returns:
        tested:   [(link, latency_ms)] for nodes that passed Tier 2
        fallback: links that Tier 1 passed but aren't Clash-convertible (anytls, mieru…)
                  these carry Tier 1 latencies
    """
    console.print(Rule("[bold cyan]Tier 2 — mihomo 真实流量检测[/bold cyan]"))

    if not mihomo_mod.is_supported():
        console.print("  [yellow]mihomo 仅支持 Linux，跳过 Tier 2，使用 Tier 1 延迟[/yellow]")
        logger.info("Tier 2 skipped: platform not supported")
        return [], [r.link for r in tier1_results if r.valid]

    valid_t1 = [r for r in tier1_results if r.valid]
    if not valid_t1:
        return [], []

    # Build name → link mapping, convert to Clash proxy dicts
    name_to_link: dict[str, str] = {}
    clash_proxies: list[dict] = []
    fallback_with_lat: list[tuple[str, float]] = []  # (link, tier1_latency_ms)

    for i, r in enumerate(valid_t1):
        name = f"p{i}"
        proxy = converter.link_to_clash(r.link, name)
        if proxy:
            clash_proxies.append(proxy)
            name_to_link[name] = r.link
        else:
            # Protocol not supported by Clash (anytls, mieru…) — keep via Tier 1 latency
            fallback_with_lat.append((r.link, r.latency_ms or 9999.0))

    console.print(
        f"  Clash 可转换: [bold]{len(clash_proxies)}[/bold]  "
        f"回退 (Tier 1): [dim]{len(fallback_with_lat)}[/dim]"
    )
    logger.info("Tier 2: %d to test via mihomo, %d fallback", len(clash_proxies), len(fallback_with_lat))

    if not clash_proxies:
        return [], [lnk for lnk, _ in fallback_with_lat]

    # Download mihomo binary if needed
    if not mihomo_mod.ensure_binary():
        console.print("  [red]mihomo 下载失败，跳过 Tier 2[/red]")
        return [], [r.link for r in valid_t1]

    # Run mihomo and test all proxies
    latency_map: dict[str, Optional[int]] = {}
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("mihomo 检测…", total=len(clash_proxies))

        def _on_done(name: str, lat) -> None:
            progress.advance(task)

        try:
            with mihomo_mod.MihomoRunner(clash_proxies) as runner:
                latency_map = runner.test_all(
                    timeout_ms=TIER2_TIMEOUT_MS,
                    concurrency=TIER2_CONCURRENCY,
                    on_done=_on_done,
                )
        except Exception as e:
            logger.error("mihomo run failed: %s", e)
            console.print(f"  [red]mihomo 运行失败: {e}[/red]")
            return [], [r.link for r in valid_t1]

    tested: list[tuple[str, int]] = []
    for name, lat in latency_map.items():
        if lat is not None:
            tested.append((name_to_link[name], lat))

    passed_count = len(tested)
    failed_count = len(clash_proxies) - passed_count
    logger.info("Tier 2: %d passed, %d failed", passed_count, failed_count)
    console.print(
        f"  通过 [green bold]{passed_count}[/green bold]  "
        f"失败/超时 [red]{failed_count}[/red]"
    )

    # Fallback links get Tier 1 latency (treated as Tier 2 result at end of list)
    # We'll sort them by latency and append after Tier 2 results
    fallback_links = [lnk for lnk, _ in sorted(fallback_with_lat, key=lambda x: x[1])]
    return tested, fallback_links


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(top_n: int = TOP_N) -> None:
    _setup_logging()
    logger.info("=== best.py started, top_n=%d ===", top_n)

    # ── 1. Discovery ──────────────────────────────────────────────────────
    console.print(Rule("[bold cyan]搜索 GitHub 订阅源[/bold cyan]"))
    sub_urls = github.get_subscription_urls()
    console.print(f"  找到 [bold]{len(sub_urls)}[/bold] 个候选来源")
    logger.info("Candidate subscription URLs: %d", len(sub_urls))

    # ── 2. Fetch links ────────────────────────────────────────────────────
    console.print(Rule("[bold cyan]获取节点链接[/bold cyan]"))
    all_links: list[str] = []
    for url in sub_urls:
        links = _fetch_links(url)
        if links:
            console.print(f"  [dim]{url}[/dim]  →  [bold]{len(links)}[/bold] 条")
            logger.info("  %d links from %s", len(links), url)
            all_links.extend(links)

    all_links = list(dict.fromkeys(all_links))
    console.print(f"\n  合计 [bold]{len(all_links)}[/bold] 条（去重后）")
    logger.info("Unique links: %d", len(all_links))

    if not all_links:
        console.print("[red]未找到任何节点链接[/red]")
        logger.warning("No links found, exiting")
        return

    # ── 3. Tier 1: TCP check ──────────────────────────────────────────────
    tier1_results = _tier1(all_links)
    valid_t1 = [r for r in tier1_results if r.valid]

    if not valid_t1:
        console.print("[red]Tier 1 全部失败，无可用节点[/red]")
        logger.warning("Tier 1: no survivors")
        return

    # ── 4. Tier 2: mihomo real proxy test ─────────────────────────────────
    tested, fallback_links = _tier2(tier1_results)

    # ── 5. Rank and pick top N ────────────────────────────────────────────
    # Tier 2: sort by real latency
    tested_sorted = sorted(tested, key=lambda x: x[1])

    if tested_sorted:
        # Blend Tier 2 tested + fallback (fallback appended after Tier 2 results)
        ordered_links = [lnk for lnk, _ in tested_sorted] + fallback_links
        source_label = "Tier 2 (mihomo)"
    else:
        # No Tier 2 — use Tier 1 latencies
        ordered_links = [
            r.link
            for r in sorted(valid_t1, key=lambda r: r.latency_ms or 9999.0)
        ]
        source_label = "Tier 1 (TCP)"

    best_links = ordered_links[:top_n]

    # ── 6. Save ───────────────────────────────────────────────────────────
    OUTPUT_FILE.write_text("".join(lnk + "\n" for lnk in best_links), encoding="utf-8")
    logger.info("Saved %d links to %s", len(best_links), OUTPUT_FILE)

    # ── 7. Summary ────────────────────────────────────────────────────────
    t2_pass = len(tested_sorted)
    t1_pass = len(valid_t1)
    grid = Table.grid(padding=(0, 2))
    grid.add_column(min_width=22)
    grid.add_column(justify="right", min_width=5)
    grid.add_column(style="dim")
    grid.add_row("[dim]发现链接[/dim]",                    str(len(all_links)),   "条")
    grid.add_row("[green]✓  Tier 1 (TCP 可达)[/green]",   str(t1_pass),          "条")
    if mihomo_mod.is_supported():
        grid.add_row("[green]✓  Tier 2 (真实流量)[/green]", str(t2_pass),         "条")
    grid.add_row(f"[bold]   精选 top {top_n} ({source_label})[/bold]", str(len(best_links)), f"条  →  {OUTPUT_FILE.name}")
    console.print(
        Panel(grid, title="[bold]Best 节点汇总[/bold]", border_style="blue", padding=(1, 2))
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=TOP_N, metavar="N")
    args = parser.parse_args()
    main(top_n=args.top)
