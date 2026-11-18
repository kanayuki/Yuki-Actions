"""new_pac 渲染：converter.Node → subscribe/clash.yaml（mihomo 原生配置）。

策略：
  - 过滤 mihomo 支持的协议（pool.clash_supported）
  - converter.generate(node, "clash") → proxy dict
  - 附带 PROXY(select) / AUTO(url-test) 分组 + GEOIP 分流规则
  - 空池保护：节点池为空时不覆盖已有 clash.yaml（exit 1）
"""

from __future__ import annotations

from pathlib import Path

import yaml
from rich.table import Table

from converter import generate

from .config import OUTPUT_CLASH, SUBSCRIBE_DIR
from .logger import get_logger
from .pool import NodePool

_TEST_URL = "http://www.gstatic.com/generate_204"
_BASE_RULES = [
    "GEOIP,LAN,DIRECT,no-resolve",
    "GEOIP,CN,DIRECT",
    "MATCH,PROXY",
]


def render(
    pool: NodePool, out_path: Path = OUTPUT_CLASH
) -> tuple[int, int, Path]:
    """渲染 clash.yaml。

    Args:
        pool: 已 finalize_names 的节点池
        out_path: 输出路径

    Returns:
        (proxies_count, skipped, path)
    """
    log = get_logger()
    clash_nodes = pool.clash_supported()

    proxies: list[dict] = []
    skipped = 0
    for node in clash_nodes:
        proxy = generate(node, target="clash")
        if proxy is None:
            skipped += 1
            continue
        proxies.append(proxy)

    if not proxies:
        log.warning("可用节点为 0，跳过写入（保护 %s）", out_path.name)
        return 0, skipped, out_path

    SUBSCRIBE_DIR.mkdir(parents=True, exist_ok=True)
    names = [p["name"] for p in proxies]
    config = {
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "PROXY",
                "type": "select",
                "proxies": ["AUTO", "DIRECT", *names],
            },
            {
                "name": "AUTO",
                "type": "url-test",
                "url": _TEST_URL,
                "interval": 300,
                "tolerance": 50,
                "proxies": names,
            },
        ],
        "rules": _BASE_RULES,
    }
    out_path.write_text(
        yaml.safe_dump(
            config, allow_unicode=True, sort_keys=False, width=4096
        ),
        encoding="utf-8",
    )
    log.info("Clash 订阅: %d 节点 → %s", len(proxies), out_path)
    if skipped:
        log.info("  跳过 %d 个（mihomo 不支持或 generate 失败）", skipped)
    return len(proxies), skipped, out_path


def print_stats(pool: NodePool) -> None:
    """Rich 表格输出各协议节点数。"""
    table = Table(
        title=f"节点池统计 [[bold]{len(pool)}[/bold]]",
        header_style="bold cyan",
    )
    table.add_column("协议", style="bold")
    table.add_column("节点数", justify="right")
    for proto, count in pool.stats_by_protocol().items():
        table.add_row(proto, str(count))
    get_logger().handlers[1].console.print(table)


__all__ = ["render", "print_stats"]
