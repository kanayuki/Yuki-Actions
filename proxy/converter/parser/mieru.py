"""mieru client profile (json) → Node[]（取全部 profiles）。"""

from __future__ import annotations

import json

from converter._util import console
from converter.models import Node


class MieruParser:
    ptype = "mieru"

    @staticmethod
    def parse_config(text: str, source: str = "") -> list[Node]:
        try:
            config = json.loads(text)
        except json.JSONDecodeError as e:
            console.print(f"  [red]✗ mieru JSON 解析失败: {e}[/red]")
            return []

        nodes: list[Node] = []
        for profile in config.get("profiles", []):
            node = _profile_to_node(profile, source)
            if node is not None:
                nodes.append(node)
        return nodes


def _profile_to_node(profile: dict, source: str) -> Node | None:
    try:
        user = profile["user"]
        server = profile["servers"][0]
        binding = server["portBindings"][0]
        port_val = str(binding.get("port", ""))
        if "-" in port_val:
            port = int(port_val.split("-")[0])
            port_range = port_val
        else:
            port = int(port_val)
            port_range = ""
    except (KeyError, IndexError, TypeError, ValueError) as e:
        console.print(f"  [yellow]⚠ mieru 节点解析失败: {e}[/yellow]")
        return None

    # 传输协议（mieru 用 TCP / UDP，区别于 IR 的"network transport"概念）
    mieru_transport = str(binding.get("protocol", "TCP")).upper()
    if mieru_transport not in ("TCP", "UDP"):
        mieru_transport = "TCP"

    return Node(
        protocol="mieru",
        host=str(server.get("ipAddress", "")),
        port=port,
        username=str(user.get("name", "")),
        password=str(user.get("password", "")),
        multiplexing=str(profile.get("multiplexing", {}).get("level", "MULTIPLEXING_LOW"))
        if isinstance(profile.get("multiplexing"), dict)
        else "MULTIPLEXING_LOW",
        port_range=port_range,
        source=source,
        extra_params={"mieru_transport": mieru_transport},
    )


__all__ = ["MieruParser"]
