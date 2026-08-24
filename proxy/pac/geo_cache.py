"""国家码持久缓存 + ip-api.com 批量解析。

ip-api.com 免费版限流：逐条查询 45 次/分钟，batch 接口 15 次/分钟
（单次最多 100 个）。这里：
- geo_cache.json 持久缓存 host → 国家码（host 归属基本不变，跨运行命中）
- 仅有新 host 时才调用 batch 接口，单轮通常 0~1 次请求
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

from pac.util import console

CACHE_FILE = Path(__file__).parent.parent / "geo_cache.json"

_BATCH_URL = "http://ip-api.com/batch?fields=status,countryCode,query"
_BATCH_SIZE = 100


def load_cache() -> dict[str, str]:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            console.print(f"  [yellow]⚠ geo 缓存损坏，重建: {e}[/yellow]")
    return {}


def save_cache(cache: dict[str, str]) -> None:
    """原子写入缓存文件。"""
    tmp = CACHE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CACHE_FILE)


def resolve(hosts: list[str]) -> dict[str, str]:
    """批量解析 host → 国家码（两字码，失败为 XX）。命中缓存的不再请求。"""
    cache = load_cache()
    unknown = sorted({h for h in hosts if h and h not in cache})

    for i in range(0, len(unknown), _BATCH_SIZE):
        batch = unknown[i : i + _BATCH_SIZE]
        try:
            resp = requests.post(_BATCH_URL, json=batch, timeout=30)
            resp.raise_for_status()
            for item in resp.json():
                host = item.get("query", "")
                if item.get("status") == "success":
                    cache[host] = item.get("countryCode", "XX")
                else:
                    # 失败也写入 XX，避免反复重查
                    cache[host] = "XX"
        except Exception as e:
            console.print(f"  [yellow]⚠ geo batch 查询失败: {e}[/yellow]")
            for h in batch:
                cache[h] = "XX"

    if unknown:
        save_cache(cache)
        console.print(f"  geo: 新解析 [bold]{len(unknown)}[/bold] 个 host，缓存共 {len(cache)} 条")
    else:
        console.print(f"  geo: 全部命中缓存（{len(cache)} 条）")

    return {h: cache.get(h, "XX") for h in hosts}
