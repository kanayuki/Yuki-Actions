import sys
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json

from pac.nodes import Node
from pac.util import console


def _mihomo_proxy(config: dict) -> dict:
    """hysteria v1 客户端 config.json → mihomo 原生 hysteria proxy dict。"""
    address: str = config["server"]
    index = address.rfind(":")
    if index == -1:
        raise ValueError(f"Invalid server: {address}")

    alpn = config.get("alpn", "h3")
    proxy: dict = {
        "type": "hysteria",
        "server": address[:index],
        "port": int(address[index + 1 :]),
        "auth-str": config.get("auth_str", ""),
        "protocol": config.get("protocol", "udp"),
        "up": config.get("up_mbps", 30),
        "down": config.get("down_mbps", 30),
    }
    if config.get("server_name"):
        proxy["sni"] = config["server_name"]
    if "insecure" in config:
        proxy["skip-cert-verify"] = bool(config["insecure"])
    if alpn:
        proxy["alpn"] = [alpn]
    return proxy


def parse_config(text: str, source: str = "") -> list[Node]:
    """解析 hysteria v1 客户端配置 → 节点列表。

    mihomo 原生支持 hysteria v1（type: hysteria）；
    v2rayN 不支持该协议，节点仅进 clash 订阅。
    """
    try:
        config = json.loads(text)
    except json.JSONDecodeError as e:
        console.print(f"  [red]✗ hysteria1 JSON 解析失败: {e}[/red]")
        return []

    if not config.get("server"):
        console.print("  [red]✗ hysteria1 配置缺少 server 字段[/red]")
        return []

    try:
        clash_proxy = _mihomo_proxy(config)
    except Exception as e:
        console.print(f"  [yellow]⚠ hysteria1 节点解析失败: {e}[/yellow]")
        return []

    address = config["server"]
    index = address.rfind(":")
    host = address[:index].strip("[]")  # IPv6 形如 [::1]:port，去掉方括号
    if isinstance(clash_proxy, dict):
        clash_proxy["server"] = host  # mihomo 期望裸地址
    return [
        Node(
            protocol="hysteria1",
            host=host,
            port=int(address[index + 1 :]),
            credential=str(config.get("auth_str", "")),
            source=source,
            link="",
            clash_proxy=clash_proxy,
        )
    ]
