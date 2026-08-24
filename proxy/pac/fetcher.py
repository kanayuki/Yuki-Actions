"""统一配置下载层：遍历全部 *_config_links.txt，内容哈希全局去重。

互为备用的 URL（指向相同配置）只下载并解析一次；
同一 URL 出现在多个清单中也只下载一次。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pac.util import console, get_config, get_hash

# parser 类型 → URL 清单文件名（与 get_config_urls.py 的 TYPE_MAP 对应）
LINKS_FILES = {
    "xray": "xray_config_links.txt",
    "clash": "clash_config_links.txt",
    "singbox": "singbox_config_links.txt",
    "hysteria2": "hysteria_config_links.txt",  # 沿用历史文件名
    "hysteria1": "hysteria1_config_links.txt",
    "mieru": "mieru_config_links.txt",
    "juicity": "juicity_config_links.txt",
    "naive": "naive_config_links.txt",
    "shadowquic": "shadowquic_config_links.txt",
}


@dataclass
class FetchedConfig:
    ptype: str  # parser 类型（LINKS_FILES 的键）
    source: str  # 来源 URL
    text: str  # 配置原文


def fetch_all(types: list[str] | None = None) -> list[FetchedConfig]:
    """下载全部配置。返回去重后的配置列表。"""
    results: list[FetchedConfig] = []
    seen_url: set[str] = set()
    seen_hash: set[str] = set()
    failed = 0

    for ptype in types or LINKS_FILES:
        path = Path(__file__).parent / LINKS_FILES[ptype]
        if not path.exists():
            continue
        urls = [u.strip() for u in path.read_text(encoding="utf-8").splitlines() if u.strip()]
        for url in urls:
            if url in seen_url:
                continue
            seen_url.add(url)
            console.print(f"[dim]{'=' * 50}[/dim]")
            text = get_config(url)
            if text is None:
                failed += 1
                continue
            cfg_hash = get_hash(text)
            if cfg_hash in seen_hash:
                console.print("  [dim]↻ 重复配置（备用 URL），跳过[/dim]")
                continue
            seen_hash.add(cfg_hash)
            results.append(FetchedConfig(ptype=ptype, source=url, text=text))

    console.print(
        f"  下载 {len(seen_url)} 个 URL，"
        f"失败 [red]{failed}[/red]，去重后 {len(results)} 份配置"
    )
    return results
