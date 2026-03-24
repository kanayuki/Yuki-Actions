import re
import sys
import requests
import base64
from pathlib import Path

from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

BASE_DIR = Path(__file__).resolve().parent

# Allow importing from proxy/ (parent directory)
_PROXY_DIR = BASE_DIR.parent
if str(_PROXY_DIR) not in sys.path:
    sys.path.insert(0, str(_PROXY_DIR))

from util import console  # noqa: E402
from core.verify import filter_valid_links  # noqa: E402


def fetch_v2ray_links(sub_url: str) -> list[str]:
    """Fetch share links from a subscription URL (plain-text or base64)."""
    try:
        resp = requests.get(sub_url, timeout=15)
        resp.raise_for_status()
        text = resp.text.strip()
        if re.match(r"^[a-zA-Z0-9+/=\n]+$", text):
            try:
                text = base64.b64decode(text).decode("utf-8")
            except Exception:
                pass
        links = [line.strip() for line in text.splitlines() if line.strip()]
        console.print(f"  [dim]{sub_url}[/dim]  →  [bold]{len(links)}[/bold] 条")
        return links
    except Exception as e:
        console.print(f"  [red]✗[/red] [dim]{sub_url}[/dim]  {e}")
        return []


def main() -> None:
    subscribe_file = BASE_DIR / "subscribe_links.txt"
    if not subscribe_file.exists():
        subscribe_file.touch()

    merge_file = BASE_DIR / "merge_share_links_filter.txt"
    if not merge_file.exists():
        merge_file.touch()

    # ── 获取订阅 ──────────────────────────────────────────
    console.print(Rule("[bold cyan]合并订阅链接[/bold cyan]"))

    sub_urls = [
        l.strip()
        for l in subscribe_file.read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.startswith("#")
    ]

    v2ray_links: list[str] = []
    for url in sub_urls:
        v2ray_links.extend(fetch_v2ray_links(url))

    existing = [
        l for l in merge_file.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    all_links = list(dict.fromkeys(v2ray_links + existing))
    console.print(f"  合并去重后：[bold]{len(all_links)}[/bold] 条")

    # ── 验证连通性 ─────────────────────────────────────────
    console.print(Rule("[bold cyan]验证连通性[/bold cyan]"))
    valid_links, results = filter_valid_links(all_links, timeout=5.0, concurrency=64)

    failed_count = len(all_links) - len(valid_links)

    # 保存（按延迟排序）
    valid_results = sorted(
        [r for r in results if r.valid],
        key=lambda r: r.latency_ms or float("inf"),
    )
    with open(merge_file, "w", encoding="utf-8") as f:
        for r in valid_results:
            f.write(r.link + "\n")

    # ── 摘要 ──────────────────────────────────────────────
    grid = Table.grid(padding=(0, 2))
    grid.add_column(min_width=14)
    grid.add_column(justify="right", min_width=4)
    grid.add_column(style="dim")
    grid.add_row("[green]✓  有效[/green]",    str(len(valid_links)), "条")
    grid.add_row("[red]✗  失败/超时[/red]",   str(failed_count),     "条")
    grid.add_row("[bold]   已保存[/bold]",     str(len(valid_links)), f"条  →  {merge_file.name}")

    console.print(Panel(grid, title="[bold]验证结果[/bold]", border_style="blue", padding=(1, 2)))


if __name__ == "__main__":
    main()
