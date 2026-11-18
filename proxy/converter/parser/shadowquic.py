"""shadowquic client.yaml (outbound) → Node[]。

mihomo 原生支持 shadowquic（type: shadowquic）；v2rayN 不支持，节点仅进 clash 订阅。
"""

from __future__ import annotations

import yaml

from converter._util import console
from converter.models import Node


class ShadowquicParser:
    ptype = "shadowquic"

    @staticmethod
    def parse_config(text: str, source: str = "") -> list[Node]:
        try:
            config = yaml.safe_load(text)
        except yaml.YAMLError as e:
            console.print(f"  [red]✗ shadowquic YAML 解析失败: {e}[/red]")
            return []

        outbound = (config or {}).get("outbound", {})
        if not outbound.get("addr"):
            console.print("  [red]✗ shadowquic 配置缺少 outbound.addr[/red]")
            return []

        address = str(outbound["addr"])
        index = address.rfind(":")
        if index == -1:
            console.print(f"  [red]✗ 无效的 addr: {address}[/red]")
            return []
        host = address[:index]
        try:
            port = int(address[index + 1:])
        except ValueError:
            return []

        node = Node(
            protocol="shadowquic",
            host=host,
            port=port,
            username=str(outbound.get("username", "")),
            password=str(outbound.get("password", "")),
            tls=True,
            sni=str(outbound.get("server-name", "")),
            congestion_controller=str(outbound.get("congestion-control", "cubic")),
            zero_rtt=bool(outbound.get("zero-rtt", False)),
            source=source,
        )
        alpn = outbound.get("alpn")
        if alpn:
            node.alpn = [str(a) for a in alpn]
        return [node]


__all__ = ["ShadowquicParser"]
