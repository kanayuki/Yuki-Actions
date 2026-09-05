import sys
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from urllib.parse import quote

from pac.nodes import Node
from pac.util import console


def build_hysteria2_link(config: dict, remark: str = "TMP") -> str:
    """生成hysteria2分享链接（hysteria2 客户端 config.json 格式）

    hysteria2://dongtaiwang.com@195.154.33.70:42259/?sni=www.bing.com&insecure=1#remark
    """
    protocol = "hysteria2"

    address: str = config.get("server", "")
    index = address.rfind(":")
    if index == -1:
        raise ValueError(f"Invalid address: {address}")

    server = address[:index]
    port = address[index + 1 :].split(",")[0]

    auth = config.get("auth", "")

    sni = ""
    insecure = "1"
    if tls := config.get("tls"):
        sni = tls.get("sni", "")
        insecure = "1" if tls.get("insecure", True) else "0"

    url = f"{protocol}://{quote(str(auth), safe='')}@{server}:{port}/?sni={sni}&insecure={insecure}#{remark}"
    return url


def parse_config(text: str, source: str = "") -> list[Node]:
    """解析 hysteria2 客户端配置 → 节点列表。"""
    try:
        config = json.loads(text)
    except json.JSONDecodeError as e:
        console.print(f"  [red]✗ hysteria2 JSON 解析失败: {e}[/red]")
        return []

    address: str = config.get("server", "")
    index = address.rfind(":")
    if index == -1:
        console.print(f"  [red]✗ 无效的 server 地址: {address}[/red]")
        return []
    host = address[:index].strip("[]")  # IPv6 形如 [::1]:port，去掉方括号
    port = int(address[index + 1 :].split(",")[0])

    try:
        link = build_hysteria2_link(config)
    except Exception as e:
        console.print(f"  [yellow]⚠ hysteria2 节点解析失败: {e}[/yellow]")
        return []

    return [
        Node(
            protocol="hysteria2",
            host=host,
            port=port,
            credential=str(config.get("auth", "")),
            source=source,
            link=link,
        )
    ]
