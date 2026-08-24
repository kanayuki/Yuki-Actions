import sys
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from pac.nodes import Node
from pac.util import console


def _mihomo_proxy(outbound: dict) -> dict:
    """shadowquic client.yaml 的 outbound → mihomo 原生 shadowquic proxy dict。"""
    address: str = outbound["addr"]
    index = address.rfind(":")
    if index == -1:
        raise ValueError(f"Invalid addr: {address}")

    proxy: dict = {
        "type": "shadowquic",
        "server": address[:index],
        "port": int(address[index + 1 :]),
        "username": outbound.get("username", ""),
        "password": outbound.get("password", ""),
        "congestion-controller": outbound.get("congestion-control", "cubic"),
    }
    if outbound.get("server-name"):
        proxy["sni"] = outbound["server-name"]
    if outbound.get("alpn"):
        proxy["alpn"] = outbound["alpn"]
    if "zero-rtt" in outbound:
        proxy["zero-rtt"] = outbound["zero-rtt"]
    return proxy


def parse_config(text: str, source: str = "") -> list[Node]:
    """解析 shadowquic 客户端配置（client.yaml）→ 节点列表。

    mihomo 原生支持 shadowquic（type: shadowquic）；
    v2rayN 不支持该协议，节点仅进 clash 订阅。
    """
    try:
        config = yaml.safe_load(text)
    except yaml.YAMLError as e:
        console.print(f"  [red]✗ shadowquic YAML 解析失败: {e}[/red]")
        return []

    outbound = (config or {}).get("outbound", {})
    if not outbound.get("addr"):
        console.print("  [red]✗ shadowquic 配置缺少 outbound.addr[/red]")
        return []

    try:
        clash_proxy = _mihomo_proxy(outbound)
    except Exception as e:
        console.print(f"  [yellow]⚠ shadowquic 节点解析失败: {e}[/yellow]")
        return []

    address = outbound["addr"]
    index = address.rfind(":")
    return [
        Node(
            protocol="shadowquic",
            host=address[:index],
            port=int(address[index + 1 :]),
            credential=f"{outbound.get('username', '')}:{outbound.get('password', '')}",
            source=source,
            link="",
            clash_proxy=clash_proxy,
        )
    ]
