import sys
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from urllib.parse import quote

from pac.nodes import Node
from pac.util import console


def build_juicity_link(config: dict, remark: str = "TMP") -> str:
    """生成juicity分享链接（juicity 客户端 config.json 格式）

    juicity://uuid:password@server:port?sni=..&allow_insecure=..&congestion_control=..#remark
    """
    address: str = config["server"]
    index = address.rfind(":")
    if index == -1:
        raise ValueError(f"Invalid server: {address}")
    server = address[:index]
    port = address[index + 1 :]

    uuid = config["uuid"]
    password = quote(str(config["password"]), safe="")

    params = []
    if config.get("sni"):
        params.append(f"sni={config['sni']}")
    if config.get("allow_insecure"):
        params.append("allow_insecure=1")
    if config.get("congestion_control"):
        params.append(f"congestion_control={config['congestion_control']}")
    param_str = f"?{'&'.join(params)}" if params else ""

    return f"juicity://{uuid}:{password}@{server}:{port}{param_str}#{remark}"


def parse_config(text: str, source: str = "") -> list[Node]:
    """解析 juicity 客户端配置 → 节点列表。"""
    try:
        config = json.loads(text)
    except json.JSONDecodeError as e:
        console.print(f"  [red]✗ juicity JSON 解析失败: {e}[/red]")
        return []

    address: str = config.get("server", "")
    index = address.rfind(":")
    if index == -1:
        console.print(f"  [red]✗ 无效的 server 地址: {address}[/red]")
        return []
    host = address[:index]
    port = int(address[index + 1 :])

    try:
        link = build_juicity_link(config)
    except Exception as e:
        console.print(f"  [yellow]⚠ juicity 节点解析失败: {e}[/yellow]")
        return []

    return [
        Node(
            protocol="juicity",
            host=host,
            port=port,
            credential=f"{config.get('uuid', '')}:{config.get('password', '')}",
            source=source,
            link=link,
        )
    ]
