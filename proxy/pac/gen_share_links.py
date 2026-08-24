"""PAC 管线编排器：下载 → 解析 → 节点池 → 渲染双客户端订阅。

流程：
1. fetcher.fetch_all()   统一下载全部 *_config_links.txt，URL/内容哈希双重去重
2. 各协议 parser.parse_config() → Node → NodePool（身份键跨源去重）
3. geo_cache 批量解析国家码 → NodePool.finalize() 命名节点
4. render_v2rayn / render_clash 生成订阅产物（proxy/subscribe/）
5. save_links() 兼容旧的 share_links.txt 输出

空结果保护：节点池为空时直接报错退出（exit 1），不覆盖任何已有订阅文件。
"""

import sys
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.rule import Rule
from rich.table import Table

from pac import clash, hysteria, hysteria1, juicity, mieru, naive, shadowquic, singbox, xray
from pac import render_clash, render_v2rayn
from pac.fetcher import fetch_all
from pac.geo_cache import resolve as resolve_geo
from pac.nodes import NodePool
from pac.util import console, save_links

# parser 类型 → 模块（各模块暴露 parse_config(text, source) -> list[Node]）
PARSERS = {
    "xray": xray,
    "clash": clash,
    "singbox": singbox,
    "hysteria2": hysteria,
    "hysteria1": hysteria1,
    "mieru": mieru,
    "juicity": juicity,
    "naive": naive,
    "shadowquic": shadowquic,
}


def build_pool() -> NodePool:
    """下载全部配置并解析进节点池。"""
    console.print(Rule("[bold cyan]获取代理配置[/bold cyan]"))
    configs = fetch_all()

    pool = NodePool()
    for cfg in configs:
        parser = PARSERS.get(cfg.ptype)
        if parser is None:
            console.print(f"  [yellow]⚠ 未知配置类型: {cfg.ptype}[/yellow]")
            continue
        console.print(f"[dim]{'=' * 50}[/dim]")
        console.print(f"[dim]{cfg.source}[/dim]")
        nodes = parser.parse_config(cfg.text, source=cfg.source)
        added = sum(pool.add(n) for n in nodes)
        console.print(
            f"  {cfg.ptype}: 解析 [bold]{len(nodes)}[/bold] 个节点，新增 {added}"
        )
    return pool


def print_stats(pool: NodePool) -> None:
    table = Table(title="节点池统计", header_style="bold cyan")
    table.add_column("协议", style="bold")
    table.add_column("节点数", justify="right")
    for proto, count in pool.stats_by_protocol().items():
        table.add_row(proto, str(count))
    console.print(table)


def main() -> None:
    pool = build_pool()
    print_stats(pool)

    if len(pool) == 0:
        console.print("[red]✗ 节点池为空，跳过渲染以保护现有订阅文件[/red]")
        raise SystemExit(1)

    # 国家码解析 + 节点命名
    console.print(Rule("[bold cyan]GeoIP 与命名[/bold cyan]"))
    country_of = resolve_geo([n.host for n in pool.all()])
    pool.finalize(country_of)

    # 渲染双客户端订阅
    console.print(Rule("[bold cyan]渲染订阅[/bold cyan]"))
    render_v2rayn.render(pool)
    render_clash.render(pool)

    # 兼容旧产物：share_links.txt
    save_links([n.link for n in pool.all() if n.link], label="all")


if __name__ == "__main__":
    main()
