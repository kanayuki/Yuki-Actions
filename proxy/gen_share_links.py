import json
from pathlib import Path

from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

import clash
import hysteria
import mieru
import singbox
import xray
from util import console, get_hash
from verify import parse_link, verify_links

path = Path(".")
keyfile = path / "share_link_keys.txt"
link_file = path / "share_links.txt"
health_file = path / "proxy" / "share_link_health.json"


def _health_key(link: str) -> str:
    """Stable identity across remark/date changes: sha256(protocol:host:port)."""
    proxy = parse_link(link)
    if proxy:
        return get_hash(f"{proxy.protocol}:{proxy.host}:{proxy.port}")
    return get_hash(link.split("#")[0])


def _load_health() -> dict[str, int]:
    if health_file.exists():
        try:
            return json.loads(health_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_health(health: dict[str, int]) -> None:
    health_file.write_text(json.dumps(health, indent=2), encoding="utf-8")


def get_all_links() -> dict[str, str]:
    links = []
    links.extend(xray.get_all_links())
    links.extend(clash.get_all_links())
    links.extend(hysteria.get_all_links())
    links.extend(mieru.get_all_links())
    links.extend(singbox.get_all_links())
    return {k: link for k, link in links}


def update() -> None:
    # ── 获取配置 ──────────────────────────────────────────
    console.print(Rule("[bold cyan]获取代理配置[/bold cyan]"))
    new_link_dict = get_all_links()
    console.print(f"  配置源链接：[bold]{len(new_link_dict)}[/bold] 条")

    existing_links = (
        [l for l in link_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        if link_file.exists()
        else []
    )
    console.print(f"  现有链接：  [bold]{len(existing_links)}[/bold] 条")

    # 合并去重：以 health_key(protocol:host:port) 为单位，新链接覆盖旧（刷新 remark）
    merged: dict[str, str] = {}
    for link in existing_links:
        merged[_health_key(link)] = link
    for url in new_link_dict.values():
        merged[_health_key(url)] = url

    all_links = list(merged.values())
    console.print(f"  合并去重后：[bold]{len(all_links)}[/bold] 条")

    # ── 全量验证 ───────────────────────────────────────────
    console.print(Rule("[bold cyan]全量验证[/bold cyan]"))
    results = verify_links(all_links, timeout=5.0, concurrency=64)
    result_map = {r.link: r for r in results}

    # 更新连续失败计数
    health = _load_health()
    kept_valid = []
    kept_pending: list[str] = []
    removed_count = 0

    for result in results:
        hk = _health_key(result.link)
        if result.valid:
            health[hk] = 0
            kept_valid.append(result)
        else:
            count = health.get(hk, 0) + 1
            health[hk] = count
            if count < 3:
                kept_pending.append(result.link)
            else:
                removed_count += 1
                health.pop(hk, None)

    kept_valid.sort(key=lambda r: r.latency_ms or float("inf"))
    kept_all = [r.link for r in kept_valid] + kept_pending

    # 覆写 share_links.txt：有效（按延迟）在前，待观察在后
    with open(link_file, "w", encoding="utf-8") as f:
        for r in kept_valid:
            f.write(r.link + "\n")
        for link in kept_pending:
            f.write(link + "\n")

    # 同步重写 keyfile
    new_url_to_key = {url: k for k, url in new_link_dict.items()}
    surviving_keys = [new_url_to_key.get(link, _health_key(link)) for link in kept_all]
    with open(keyfile, "w", encoding="utf-8") as f:
        f.write("\n".join(surviving_keys) + "\n")

    _save_health(health)

    # ── 摘要 ──────────────────────────────────────────────
    grid = Table.grid(padding=(0, 2))
    grid.add_column(min_width=16)
    grid.add_column(justify="right", min_width=4)
    grid.add_column(style="dim")
    grid.add_row("[green]✓  有效[/green]",      str(len(kept_valid)),  "条")
    grid.add_row("[yellow]⏳ 等待确认[/yellow]", str(len(kept_pending)), "条  (失败未满3次，暂保留)")
    grid.add_row("[red]✗  移除[/red]",           str(removed_count),    "条  (连续失败≥3次)")
    grid.add_row("[bold]   共保留[/bold]",        str(len(kept_all)),    "条")

    console.print(Panel(grid, title="[bold]验证结果[/bold]", border_style="blue", padding=(1, 2)))


def main() -> None:
    update()


if __name__ == "__main__":
    main()
