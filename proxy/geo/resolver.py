"""单 IP 国家码查询。"""

from __future__ import annotations

import functools
import requests

from rich.console import Console

console = Console(highlight=False)


@functools.lru_cache(maxsize=128)
def get_country_code(ip: str = "") -> str:
    url = f"http://ip-api.com/json/{ip}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        return data.get("countryCode", "")
    except Exception as e:
        console.print(f"  [dim]国家码查询失败 {ip}: {e}[/dim]")
        return "XX"