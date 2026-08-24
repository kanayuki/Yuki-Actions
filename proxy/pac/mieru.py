import sys
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import base64
import json

from pac.nodes import Node
from pac.util import console


def build_mieru_link(profile: dict, remark: str = "TMP") -> str:
    """生成Mieru分享链接（mieru 客户端 profile 格式）

    mieru://base64(user:password@ip?port=..&protocol=..&profile=..)
    """
    user = profile["user"]
    name = user["name"]
    password = user["password"]
    server = profile["servers"][0]

    ipAddress = server["ipAddress"]
    portBindings = server["portBindings"]

    params = []
    for portBinding in portBindings:
        port = portBinding["port"]
        protocol = portBinding["protocol"]
        params.append(f"port={port}&protocol={protocol}")

    params.append(f"profile={remark}")
    params_str = "&".join(params)

    link = f"{name}:{password}@{ipAddress}?{params_str}"
    encoded_link = base64.b64encode(link.encode("utf-8")).decode("utf-8")
    return f"mieru://{encoded_link}"


def _mihomo_proxy(profile: dict) -> dict:
    """mieru profile → mihomo 原生 mieru proxy dict（取第一个端口绑定）。"""
    user = profile["user"]
    server = profile["servers"][0]
    binding = server["portBindings"][0]

    proxy: dict = {
        "type": "mieru",
        "server": server["ipAddress"],
        "username": user["name"],
        "password": user["password"],
        "transport": binding.get("protocol", "TCP"),
        "multiplexing": "MULTIPLEXING_LOW",
    }
    port = str(binding.get("port", ""))
    if "-" in port:
        proxy["port-range"] = port
    else:
        proxy["port"] = int(port)
    return proxy


def parse_config(text: str, source: str = "") -> list[Node]:
    """解析 mieru 客户端配置 → 节点列表（全部 profiles）。"""
    try:
        config = json.loads(text)
    except json.JSONDecodeError as e:
        console.print(f"  [red]✗ mieru JSON 解析失败: {e}[/red]")
        return []

    nodes: list[Node] = []
    for profile in config.get("profiles", []):
        try:
            user = profile["user"]
            server = profile["servers"][0]
            binding = server["portBindings"][0]
            port = int(str(binding["port"]).split("-")[0])

            link = build_mieru_link(profile)
            clash_proxy = _mihomo_proxy(profile)
            credential = f"{user['name']}:{user['password']}"
        except Exception as e:
            console.print(f"  [yellow]⚠ mieru 节点解析失败: {e}[/yellow]")
            continue

        nodes.append(
            Node(
                protocol="mieru",
                host=str(server["ipAddress"]),
                port=port,
                credential=credential,
                source=source,
                link=link,
                clash_proxy=clash_proxy,
            )
        )
    return nodes
