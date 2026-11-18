"""juicity 客户端 config.json → Node[]。"""

from __future__ import annotations

import json

from converter._util import console
from converter.models import Node


class JuicityParser:
    ptype = "juicity"

    @staticmethod
    def parse_config(text: str, source: str = "") -> list[Node]:
        try:
            config = json.loads(text)
        except json.JSONDecodeError as e:
            console.print(f"  [red]✗ juicity JSON 解析失败: {e}[/red]")
            return []

        address = str(config.get("server", ""))
        host, port = _split_address(address)
        if not host or not port:
            console.print(f"  [red]✗ 无效的 server 地址: {address}[/red]")
            return []

        return [
            Node(
                protocol="juicity",
                host=host,
                port=port,
                uuid=str(config.get("uuid", "")),
                password=str(config.get("password", "")),
                tls=True,
                sni=str(config.get("sni", "")),
                skip_cert_verify=bool(config.get("allow_insecure", False)),
                congestion_controller=str(config.get("congestion_control", "cubic")),
                source=source,
            )
        ]


def _split_address(address: str) -> tuple[str, int]:
    index = address.rfind(":")
    if index == -1:
        return "", 0
    host = address[:index].strip("[]")
    try:
        return host, int(address[index + 1:])
    except ValueError:
        return "", 0


__all__ = ["JuicityParser"]
