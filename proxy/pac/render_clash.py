"""Clash Verge 订阅渲染器：节点池 → mihomo 原生配置 YAML。

产物（proxy/subscribe/clash.yaml）：
- 优先使用 parser 提供的 mihomo 原生 proxy dict（hysteria1/mieru/shadowquic 等
  clash-only 协议）
- 否则经 core.parse.link_to_clash 由分享链接转换
- 附带 PROXY(select) / AUTO(url-test) 分组与基础分流规则
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from pac.nodes import Node, NodePool
from pac.util import console

if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.parse import link_to_clash  # noqa: E402

_OUTPUT_DIR = Path(__file__).parent.parent / "subscribe"

_TEST_URL = "http://www.gstatic.com/generate_204"


def _proxy_dict(node: Node) -> dict | None:
    """取节点的 mihomo proxy dict：原生优先，链接转换兜底。"""
    if node.clash_proxy is not None:
        return {**node.clash_proxy, "name": node.name}
    if node.link:
        converted = link_to_clash(node.link, node.name)
        if converted is not None:
            return converted
    return None


def render(pool: NodePool) -> tuple[int, Path]:
    """生成 Clash Verge 订阅。返回 (节点数, yaml 文件路径)。"""
    proxies: list[dict] = []
    skipped = 0
    for node in pool.all():
        if not node.clash_ok:
            continue
        proxy = _proxy_dict(node)
        if proxy is None:
            skipped += 1
            continue
        proxies.append(proxy)

    if not proxies:
        console.print("  [yellow]⚠ Clash 订阅：0 个可用节点，跳过写入（保护现有文件）[/yellow]")
        return 0, _OUTPUT_DIR / "clash.yaml"

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = _OUTPUT_DIR / "clash.yaml"

    names = [p["name"] for p in proxies]
    config = {
        "proxies": proxies,
        "proxy-groups": [
            {"name": "PROXY", "type": "select", "proxies": ["AUTO", "DIRECT", *names]},
            {
                "name": "AUTO",
                "type": "url-test",
                "url": _TEST_URL,
                "interval": 300,
                "tolerance": 50,
                "proxies": names,
            },
        ],
        "rules": [
            "GEOIP,LAN,DIRECT,no-resolve",
            "GEOIP,CN,DIRECT",
            "MATCH,PROXY",
        ],
    }
    with open(out, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False, width=4096)

    console.print(
        f"  Clash 订阅：[bold]{len(proxies)}[/bold] 个节点"
        + (f"（[yellow]{skipped}[/yellow] 个转换失败跳过）" if skipped else "")
        + f" → {out.name}"
    )
    return len(proxies), out
