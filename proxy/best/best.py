"""Search GitHub for free v2ray subscriptions, verify, keep top N by latency.

Usage:
    python proxy/best/best.py           # default top 100
    python proxy/best/best.py --top 50  # keep top 50
"""

import argparse
import base64
import logging
import re
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent   # proxy/best/
PROXY_DIR = BASE_DIR.parent                  # proxy/

# Allow importing from proxy/
if str(PROXY_DIR) not in sys.path:
    sys.path.insert(0, str(PROXY_DIR))
# Allow importing github.py from the same directory
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import requests
import urllib3
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from util import console
from verify import filter_valid_links
import github  # proxy/best/github.py

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TOP_N = 100
TIMEOUT = 5.0
CONCURRENCY = 64
OUTPUT_FILE = PROXY_DIR / "best.txt"
LOGS_DIR = PROXY_DIR / "logs"

_KNOWN_SCHEMES = (
    "vmess://", "vless://", "ss://", "trojan://",
    "hysteria://", "hysteria2://", "tuic://", "anytls://", "mieru://",
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging setup
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
# Fetch & decode
# ---------------------------------------------------------------------------

_B64_RE = re.compile(r"^[a-zA-Z0-9+/=\n\r\t ]+$")


def _fetch_links(url: str) -> list[str]:
    """Download a URL, base64-decode if needed, return proxy share links."""
    try:
        resp = requests.get(url, timeout=10, verify=False)
        if not resp.ok:
            return []
        text = resp.text.strip()
    except Exception as e:
        logger.debug("Fetch failed %s: %s", url, e)
        return []

    # Try base64 decode when content looks like pure base64
    if _B64_RE.match(text.replace("\n", "").replace("\r", "")):
        try:
            decoded = base64.b64decode(text + "==").decode("utf-8")
            if any(decoded.startswith(s) or f"\n{s}" in decoded for s in _KNOWN_SCHEMES):
                text = decoded
        except Exception:
            pass

    links = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and any(line.strip().startswith(s) for s in _KNOWN_SCHEMES)
    ]
    return links


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(top_n: int = TOP_N) -> None:
    _setup_logging()
    logger.info("=== best.py started, top_n=%d ===", top_n)

    # 1. Discover subscription URLs from GitHub
    console.print(Rule("[bold cyan]搜索 GitHub 订阅源[/bold cyan]"))
    sub_urls = github.get_subscription_urls()
    console.print(f"  找到 [bold]{len(sub_urls)}[/bold] 个候选来源")
    logger.info("Candidate URLs: %d", len(sub_urls))

    # 2. Fetch and decode links from each URL
    console.print(Rule("[bold cyan]获取节点链接[/bold cyan]"))
    all_links: list[str] = []
    for url in sub_urls:
        links = _fetch_links(url)
        if links:
            console.print(f"  [dim]{url}[/dim]  →  [bold]{len(links)}[/bold] 条")
            logger.info("Fetched %d links from %s", len(links), url)
            all_links.extend(links)

    all_links = list(dict.fromkeys(all_links))  # deduplicate, preserve order
    console.print(f"\n  合计 [bold]{len(all_links)}[/bold] 条（去重后）")
    logger.info("Unique links total: %d", len(all_links))

    if not all_links:
        console.print("[red]未找到任何节点链接[/red]")
        logger.warning("No links found, exiting")
        return

    # 3. Verify connectivity
    console.print(Rule("[bold cyan]验证连通性[/bold cyan]"))
    valid_links, results = filter_valid_links(all_links, timeout=TIMEOUT, concurrency=CONCURRENCY)
    logger.info("Valid: %d / %d", len(valid_links), len(all_links))

    # 4. Sort by latency, take top N
    best = sorted(
        [r for r in results if r.valid],
        key=lambda r: r.latency_ms or float("inf"),
    )[:top_n]

    # 5. Save
    OUTPUT_FILE.write_text(
        "".join(r.link + "\n" for r in best),
        encoding="utf-8",
    )
    logger.info("Saved %d links to %s", len(best), OUTPUT_FILE)

    # 6. Summary
    failed_count = len(all_links) - len(valid_links)
    grid = Table.grid(padding=(0, 2))
    grid.add_column(min_width=16)
    grid.add_column(justify="right", min_width=4)
    grid.add_column(style="dim")
    grid.add_row("[green]✓  有效[/green]",       str(len(valid_links)), "条")
    grid.add_row("[red]✗  失败/超时[/red]",       str(failed_count),     "条")
    grid.add_row("[bold]   精选 top N[/bold]",    str(len(best)),        f"条  →  {OUTPUT_FILE.name}")
    console.print(
        Panel(grid, title=f"[bold]Best 节点 (top {top_n})[/bold]", border_style="blue", padding=(1, 2))
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search GitHub for best free v2ray nodes")
    parser.add_argument("--top", type=int, default=TOP_N, metavar="N", help=f"保留最佳节点数 (默认 {TOP_N})")
    args = parser.parse_args()
    main(top_n=args.top)
