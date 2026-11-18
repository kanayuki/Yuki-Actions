"""naive 客户端 config.json（仅含 proxy URL）→ Node[]。"""

from __future__ import annotations

import json
import urllib.parse

from converter._util import console
from converter.models import Node


class NaiveParser:
    ptype = "naive"

    @staticmethod
    def parse_config(text: str, source: str = "") -> list[Node]:
        try:
            config = json.loads(text)
        except json.JSONDecodeError as e:
            console.print(f"  [red]✗ naive JSON 解析失败: {e}[/red]")
            return []

        proxy_url = str(config.get("proxy", ""))
        if not proxy_url:
            console.print("  [red]✗ naive 配置缺少 proxy 字段[/red]")
            return []

        try:
            parsed = urllib.parse.urlparse(proxy_url)
        except Exception as e:
            console.print(f"  [yellow]⚠ naive 节点解析失败: {e}[/yellow]")
            return []
        host = parsed.hostname or ""
        try:
            port = parsed.port or 0
        except ValueError:
            return []
        if not (host and port):
            return []

        return [
            Node(
                protocol="naive",
                host=host,
                port=port,
                username=urllib.parse.unquote(parsed.username or ""),
                password=urllib.parse.unquote(parsed.password or ""),
                tls=True,
                source=source,
                raw_link=proxy_url,
            )
        ]


__all__ = ["NaiveParser"]
