"""扫描 ip_*.bat（GBK 编码）→ urls.yaml（含 bat 路径 + 主备标记）。

数据流：
    source.prepare() 解压出的 <root>/{Xray|clash.meta|...}/ip_Update/ip_*.bat
      ↓ regex 抽 HTTPS URL（按出现顺序）
    UrlsFile (Pydantic)
      ↓ yaml.safe_dump
    proxy/new_pac/urls.yaml（git 跟踪）

URL 角色约定：同一 bat 内出现的第 1 个 URL = primary，其余 = backup。
"""

from __future__ import annotations

import re
from pathlib import Path

from rich.table import Table

from .config import (
    SOURCE_DIR_MAP,
    URLS_FILE,
    BatGroup,
    SourceGroup,
    UrlsFile,
    UrlEntry,
)
from .logger import get_logger

URL_PATTERN = re.compile(r"https://\S+")
BAT_GLOB = "ip_*.bat"


def extract_urls_from_bat(bat_path: Path) -> list[UrlEntry]:
    """从 .bat 文件（GBK）按出现顺序抽取 URL。

    第 1 条 = primary，其余 = backup。
    """
    text = bat_path.read_text(encoding="gbk", errors="ignore")
    raw = URL_PATTERN.findall(text)
    entries: list[UrlEntry] = []
    for i, u in enumerate(raw):
        entries.append(
            UrlEntry(
                url=u,
                role="primary" if i == 0 else "backup",
                bat_file=str(bat_path),
            )
        )
    return entries


def scan_source(source_root: Path, dir_name: str, ptype: str) -> SourceGroup:
    """扫描单个 ptype 对应的 bat 目录。"""
    ip_dir = source_root / dir_name / "ip_Update"
    cfg = SourceGroup(ptype=ptype, source_dir=str(ip_dir))

    if not ip_dir.is_dir():
        get_logger().warning("源目录不存在，跳过: %s", ip_dir)
        return cfg

    for bat in sorted(ip_dir.glob(BAT_GLOB)):
        urls = extract_urls_from_bat(bat)
        if urls:
            cfg.bat_files.append(str(bat))
            cfg.groups.append(BatGroup(bat_file=str(bat), urls=urls))
    return cfg


def scan_all(source_root: Path) -> UrlsFile:
    """扫描全部 9 个协议类型，返回 UrlsFile。"""
    log = get_logger()
    if not source_root.is_dir():
        log.error("source_root 不存在: %s", source_root)
        raise SystemExit(1)

    file = UrlsFile()
    for dir_name, ptype in SOURCE_DIR_MAP.items():
        cfg = scan_source(source_root, dir_name, ptype)
        file.sources.append(cfg)
        log.info(
            "[%s] bat=%d groups=%d urls=%d",
            ptype,
            len(cfg.bat_files),
            len(cfg.groups),
            sum(len(g.urls) for g in cfg.groups),
        )
    return file


def write_urls_yaml(file: UrlsFile, path: Path = URLS_FILE) -> None:
    """将 UrlsFile 序列化为 yaml（结构稳定、git diff 友好）。"""
    import yaml

    path.write_text(
        yaml.safe_dump(
            file.model_dump(),
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )
    get_logger().info("写入 urls.yaml: %s", path)


def render_summary(file: UrlsFile) -> None:
    """Rich 表格汇总。"""
    table = Table(title="URL 提取汇总", header_style="bold cyan")
    table.add_column("协议", style="bold", width=10)
    table.add_column("bat 数", justify="right")
    table.add_column("URL 组", justify="right")
    table.add_column("URL 总数", justify="right")

    for src in file.sources:
        url_total = sum(len(g.urls) for g in src.groups)
        table.add_row(
            src.ptype,
            str(len(src.bat_files)),
            str(len(src.groups)),
            str(url_total),
        )

    # 复用 RichHandler 的 console（保证 markup 一致）
    console = get_logger().handlers[1].console
    console.print(table)


def run(source_root: Path, write: bool = True) -> UrlsFile:
    """CLI `scan` 子命令入口：扫描 → 汇总 → 可选写盘。"""
    file = scan_all(source_root)
    render_summary(file)
    if write:
        write_urls_yaml(file)
    return file


__all__ = [
    "extract_urls_from_bat",
    "scan_source",
    "scan_all",
    "write_urls_yaml",
    "render_summary",
    "run",
]
