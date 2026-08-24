import sys
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from urllib.parse import quote, urlparse

from pac.nodes import Node
from pac.util import console


def build_naive_link(proxy_url: str, remark: str = "TMP") -> str:
    """生成naive分享链接（naive 客户端 config.json 的 proxy 字段格式）

    naive+https://user:password@server:port#remark
    """
    parsed = urlparse(proxy_url)
    if not parsed.hostname or not parsed.port:
        raise ValueError(f"Invalid proxy url: {proxy_url}")

    userinfo = ""
    if parsed.username:
        userinfo = f"{quote(parsed.username, safe='')}:{quote(parsed.password or '', safe='')}@"

    return f"naive+https://{userinfo}{parsed.hostname}:{parsed.port}#{remark}"


def parse_config(text: str, source: str = "") -> list[Node]:
    """解析 naive 客户端配置 → 节点列表。"""
    try:
        config = json.loads(text)
    except json.JSONDecodeError as e:
        console.print(f"  [red]✗ naive JSON 解析失败: {e}[/red]")
        return []

    proxy_url = config.get("proxy", "")
    if not proxy_url:
        console.print("  [red]✗ naive 配置缺少 proxy 字段[/red]")
        return []

    try:
        link = build_naive_link(proxy_url)
        parsed = urlparse(proxy_url)
    except Exception as e:
        console.print(f"  [yellow]⚠ naive 节点解析失败: {e}[/yellow]")
        return []

    return [
        Node(
            protocol="naive",
            host=parsed.hostname or "",
            port=parsed.port or 0,
            credential=f"{parsed.username or ''}:{parsed.password or ''}",
            source=source,
            link=link,
        )
    ]
