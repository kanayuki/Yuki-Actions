"""hysteria2 客户端 config.json → Node[]。"""

from __future__ import annotations

import json

from converter._util import console
from converter.models import Node


class Hysteria2Parser:
    ptype = "hysteria2"

    @staticmethod
    def parse_config(text: str, source: str = "") -> list[Node]:
        try:
            config = json.loads(text)
        except json.JSONDecodeError as e:
            console.print(f"  [red]✗ hysteria2 JSON 解析失败: {e}[/red]")
            return []

        address = str(config.get("server", ""))
        host, port = _split_address(address)
        if not host or not port:
            console.print(f"  [red]✗ 无效的 server 地址: {address}[/red]")
            return []

        tls = config.get("tls") or {}
        sni = str(tls.get("sni", ""))
        insecure = bool(tls.get("insecure", False))

        obfs_cfg = config.get("obfs") or {}
        if not isinstance(obfs_cfg, dict):
            obfs_cfg = {}

        node = Node(
            protocol="hysteria2",
            host=host,
            port=port,
            password=str(config.get("auth", "")),
            tls=True,
            sni=sni,
            skip_cert_verify=insecure,
            obfs=str(obfs_cfg.get("type", "")),
            obfs_password=str(obfs_cfg.get("password", "")),
            source=source,
        )
        return [node]


def _split_address(address: str) -> tuple[str, int]:
    """hysteria2 客户端 config 中的 server 形如 'host:port' 或 '[ipv6]:port'，支持多端口取第一个。"""
    index = address.rfind(":")
    if index == -1:
        return "", 0
    host = address[:index].strip("[]")
    port_str = address[index + 1:].split(",")[0].strip()
    try:
        return host, int(port_str)
    except ValueError:
        return "", 0


__all__ = ["Hysteria2Parser"]
