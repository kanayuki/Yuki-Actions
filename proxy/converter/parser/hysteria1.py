"""hysteria v1 客户端 config.json → Node[]。

mihomo 原生支持 hysteria v1（type: hysteria）；v2rayN 不支持，节点仅进 clash 订阅。
"""

from __future__ import annotations

import json

from converter._util import console
from converter.models import Node


class Hysteria1Parser:
    ptype = "hysteria1"

    @staticmethod
    def parse_config(text: str, source: str = "") -> list[Node]:
        try:
            config = json.loads(text)
        except json.JSONDecodeError as e:
            console.print(f"  [red]✗ hysteria1 JSON 解析失败: {e}[/red]")
            return []

        address = str(config.get("server", ""))
        host, port = _split_address(address)
        if not host or not port:
            console.print("  [red]✗ hysteria1 配置缺少 server 字段[/red]")
            return []

        alpn = config.get("alpn", "h3")
        node = Node(
            protocol="hysteria1",
            host=host,
            port=port,
            auth_str=str(config.get("auth_str", "")),
            hy1_protocol=str(config.get("protocol", "udp")),
            up_mbps=str(config.get("up_mbps", "30")),
            down_mbps=str(config.get("down_mbps", "30")),
            sni=str(config.get("server_name", "")),
            alpn=[str(alpn)] if alpn else [],
            skip_cert_verify=bool(config.get("insecure", False)),
            source=source,
        )
        return [node]



def _split_address(address: str) -> tuple[str, int]:
    index = address.rfind(":")
    if index == -1:
        return "", 0
    host = address[:index].strip("[]")
    try:
        return host, int(address[index + 1:])
    except ValueError:
        return "", 0


__all__ = ["Hysteria1Parser"]
