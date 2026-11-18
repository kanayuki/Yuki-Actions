"""下载 urls.yaml 全部 URL（含主备），规范化后写盘。

数据流：
    urls.yaml → (ptype, url, role, bat_file)[] → 全部下载
    → normalize(text, ptype) → (canonical, hash, nodes)
    → store.save(canonical, hash) → config_store/YYYY-MM/
    → 累计 FetchedConfig 列表（含 nodes，供后续 render 使用）
"""

from __future__ import annotations

import urllib3
from dataclasses import dataclass
from pathlib import Path

import requests
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from converter.models import Node

from .config import URLS_FILE, UrlsFile
from .logger import get_logger
from .normalize import normalize
from .store import save as store_save

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    )
}
TIMEOUT = 15


@dataclass
class FetchedConfig:
    """单次成功获取 + 规范化的配置（含已解析 Node）。"""

    ptype: str
    source: str
    role: str
    bat_file: str
    nodes: list[Node]
    hash: str
    month: str
    is_new: bool


def _download(url: str) -> str | None:
    """下载单个 URL，返回文本。失败返回 None。"""
    log = get_logger()
    try:
        resp = requests.get(url, headers=HEADERS, verify=False, timeout=TIMEOUT)
        if resp.status_code == 200 and resp.text.strip():
            return resp.text
        log.warning("下载失败: %s [%d]", url, resp.status_code)
    except Exception as e:
        log.warning("下载异常: %s — %s", url, e)
    return None


def _load_urls(path: Path = URLS_FILE) -> UrlsFile:
    """加载 urls.yaml。文件不存在则 SystemExit。"""
    import yaml

    if not path.exists():
        raise SystemExit(
            f"urls.yaml 不存在: {path}（先运行 scan）"
        )
    return UrlsFile(**yaml.safe_load(path.read_text(encoding="utf-8")))


def fetch_all(types: list[str] | None = None) -> list[FetchedConfig]:
    """下载 urls.yaml 全部 URL（主备全下），规范化后写盘。

    Args:
        types: 限定 ptype 列表（None=全部）

    Returns:
        FetchedConfig 列表（已去重 + 已落盘）
    """
    log = get_logger()
    file = _load_urls()

    # 展平全部 URL（含主备），跳过不匹配的 ptype
    jobs: list[tuple[str, str, str, str]] = []  # (ptype, url, role, bat_file)
    for src in file.sources:
        if types and src.ptype not in types:
            continue
        for g in src.groups:
            for e in g.urls:
                jobs.append((src.ptype, e.url, e.role, e.bat_file))

    results: list[FetchedConfig] = []
    seen_hash: set[str] = set()
    failed = 0
    duplicate = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        transient=True,
    ) as progress:
        task = progress.add_task("下载", total=len(jobs))
        for ptype, url, role, bat_file in jobs:
            log.debug("[%s/%s] 下载 %s", ptype, role, url)
            text = _download(url)
            if text is None:
                failed += 1
                progress.advance(task)
                continue
            try:
                canonical, cfg_hash, nodes = normalize(text, ptype)
            except Exception as e:
                log.warning("[%s] 规范化失败: %s — %s", ptype, url, e)
                failed += 1
                progress.advance(task)
                continue
            if cfg_hash in seen_hash:
                duplicate += 1
                progress.advance(task)
                continue
            seen_hash.add(cfg_hash)
            saved = store_save(ptype, url, canonical, cfg_hash)
            if saved is None:
                failed += 1
                progress.advance(task)
                continue
            month, is_new = saved
            results.append(
                FetchedConfig(
                    ptype=ptype,
                    source=url,
                    role=role,
                    bat_file=bat_file,
                    nodes=nodes,
                    hash=cfg_hash,
                    month=month,
                    is_new=is_new,
                )
            )
            progress.advance(task)

    log.info(
        "下载完成: %d 成功 / %d 失败 / %d 内容重复, 共 %d 节点",
        len(results),
        failed,
        duplicate,
        sum(len(r.nodes) for r in results),
    )
    return results


__all__ = ["FetchedConfig", "fetch_all", "_download", "_load_urls"]
