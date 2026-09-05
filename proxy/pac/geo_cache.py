"""国家码持久缓存 + ip-api.com 批量解析。

ip-api.com 免费版限流：逐条查询 45 次/分钟，batch 接口 15 次/分钟
（单次最多 100 个）。这里：
- geo_cache.json 持久缓存 host → 国家码（host 归属基本不变，跨运行命中）
- 域名先经本地 DNS 解析为 IP 再查询（ip-api batch 接口不接受域名）
- 仅有新 host 时才调用 batch 接口，单轮通常 0~1 次请求
"""

from __future__ import annotations

import ipaddress
import json
import socket
from pathlib import Path

import requests

from pac.util import console

CACHE_FILE = Path(__file__).parent.parent / "geo_cache.json"

_BATCH_URL = "http://ip-api.com/batch?fields=status,countryCode,query"
_BATCH_SIZE = 100


def load_cache() -> dict[str, str]:
    if CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            console.print(f"  [yellow]⚠ geo 缓存损坏，重建: {e}[/yellow]")
            return {}
        # 丢弃历史失败的 XX 条目，本轮重试（失败很少，代价可忽略）
        return {h: c for h, c in cache.items() if c != "XX"}
    return {}


def save_cache(cache: dict[str, str]) -> None:
    """原子写入缓存文件。"""
    tmp = CACHE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CACHE_FILE)


def _resolve_to_ip(host: str) -> str:
    """host → 可查询的 IP：去括号的 IPv6 直接用，域名做 DNS 解析。失败返回空串。"""
    h = host.strip()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    try:
        ipaddress.ip_address(h)
        return h
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(h, None)
        return infos[0][4][0]
    except OSError:
        return ""


def resolve(hosts: list[str]) -> dict[str, str]:
    """批量解析 host → 国家码（两字码，失败为 XX）。命中缓存的不再请求。"""
    cache = load_cache()
    unknown = sorted({h for h in hosts if h and h not in cache})

    if unknown:
        # host → IP（域名 DNS 解析 / 括号 IPv6 归一化）
        ip_of = {h: _resolve_to_ip(h) for h in unknown}
        ips = sorted({ip for ip in ip_of.values() if ip})

        ip_country: dict[str, str] = {}
        for i in range(0, len(ips), _BATCH_SIZE):
            batch = ips[i : i + _BATCH_SIZE]
            try:
                resp = requests.post(_BATCH_URL, json=batch, timeout=30)
                resp.raise_for_status()
                for item in resp.json():
                    ip = item.get("query", "")
                    if item.get("status") == "success":
                        ip_country[ip] = item.get("countryCode", "XX")
                    else:
                        ip_country[ip] = "XX"
            except Exception as e:
                console.print(f"  [yellow]⚠ geo batch 查询失败: {e}[/yellow]")
                for ip in batch:
                    ip_country[ip] = "XX"

        for h in unknown:
            ip = ip_of[h]
            cache[h] = ip_country.get(ip, "XX") if ip else "XX"

        save_cache(cache)
        resolved = sum(1 for h in unknown if cache[h] != "XX")
        console.print(
            f"  geo: 新解析 [bold]{len(unknown)}[/bold] 个 host"
            f"（成功 {resolved}），缓存共 {len(cache)} 条"
        )
    else:
        console.print(f"  geo: 全部命中缓存（{len(cache)} 条）")

    return {h: cache.get(h, "XX") for h in hosts}
