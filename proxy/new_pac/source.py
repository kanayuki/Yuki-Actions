"""web 源：alvin9999 高内核版页面 → 云盘压缩包 → cache 解压 → bat 根目录。

数据流：
    PAGE_URL → 抓取含"云盘"的下载链接（云盘1/2/3 互为后备，第一个 = 最新版）
    → stream 下载 .7z → cache/（同名同大小跳过；.part 临时文件防半包）
    → py7zr 仅解压 ip_Update/ip_*.bat → cache/extracted/
    → 返回 bat 根目录（<root>/{Xray|clash.meta|...}/ip_Update/ip_*.bat）

稳定优先：页面/下载/解压任一环节失败仅告警并回退缓存旧包，
全部失败返回 None，由 scan 沿用现有 urls.yaml（不致命）。
"""

from __future__ import annotations

import re
import shutil
import urllib3
from pathlib import Path
from re import Pattern

import requests
from py7zr import SevenZipFile
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TransferSpeedColumn,
)

from .config import CACHE_DIR
from .logger import get_logger

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PAGE_URL = "https://alvin9999.com/%e9%ab%98%e5%86%85%e6%a0%b8%e7%89%88/"
EXTRACT_DIR = CACHE_DIR / "extracted"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    )
}
# 双会话互为后备：页面主机直连被 RST（需代理），下载主机走代理易慢速窒息（直连快）
# 页面抓取 = 代理优先；压缩包下载 = 直连优先。CI 无代理时两者等价于直连。
PROXY_SESSION = requests.Session()  # trust_env=True，走系统/环境代理
DIRECT_SESSION = requests.Session()  # 绕过系统/环境代理，直连
DIRECT_SESSION.trust_env = False
SESSIONS_PROXY_FIRST = (PROXY_SESSION, DIRECT_SESSION)
SESSIONS_DIRECT_FIRST = (DIRECT_SESSION, PROXY_SESSION)

PAGE_RETRIES = 2
DL_RETRIES = 3
LINK_PATTERN = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S)
BAT_IN_ARCHIVE: Pattern[str] = re.compile(r"(^|/)ip_Update/ip_[^/]*\.bat$")


def _get_page() -> str | None:
    """抓取高内核版页面 HTML（代理优先，直连后备）。失败返回 None。"""
    log = get_logger()
    for attempt in range(PAGE_RETRIES):
        for sess in SESSIONS_PROXY_FIRST:
            try:
                resp = sess.get(PAGE_URL, headers=HEADERS, verify=False, timeout=20)
                if resp.status_code == 200 and resp.text.strip():
                    return resp.text
                log.warning("页面状态码异常: %d", resp.status_code)
            except Exception as e:
                log.warning(
                    "页面抓取异常(%d/%d): %s", attempt + 1, PAGE_RETRIES, e
                )
    return None


def find_cloud_links(html: str) -> list[str]:
    """按出现顺序提取文本含"云盘"的下载链接（云盘1/2/3 × 各版本）。"""
    links: list[str] = []
    for m in LINK_PATTERN.finditer(html):
        text = re.sub(r"<[^>]+>", "", m.group(2))
        if "云盘" in text and m.group(1).startswith("http"):
            links.append(m.group(1))
    return links


def _download(url: str, dest: Path) -> Path | None:
    """下载压缩包到 cache/。同名同大小直接命中缓存；.part 断点续传。

    服务端支持 Accept-Ranges 时，中断后从已下载字节处续传。
    失败返回 None。
    """
    log = get_logger()
    for attempt in range(DL_RETRIES):
        for sess in SESSIONS_DIRECT_FIRST:
            try:
                # 缓存命中：远端 Content-Length 与本地文件大小一致
                head = sess.head(
                    url, headers=HEADERS, verify=False, timeout=15,
                    allow_redirects=True,
                )
                clen = int(head.headers.get("Content-Length") or 0)
                if (
                    head.status_code == 200
                    and clen
                    and dest.exists()
                    and dest.stat().st_size == clen
                ):
                    log.info("缓存命中: %s (%.0f MB)", dest.name, clen / 1048576)
                    return dest

                tmp = dest.with_suffix(".part")
                done = tmp.stat().st_size if tmp.exists() else 0
                headers = dict(HEADERS)
                if done:
                    headers["Range"] = f"bytes={done}-"
                    log.info("断点续传: %s 从 %.0f MB 处", dest.name, done / 1048576)

                with sess.get(
                    url, headers=headers, stream=True, verify=False,
                    timeout=(15, 120),
                ) as resp:
                    resp.raise_for_status()
                    resumed = resp.status_code == 206
                    if not resumed:
                        done = 0  # 服务端不支持 Range，从头下
                    total = done + int(resp.headers.get("Content-Length") or 0)
                    with Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(),
                        DownloadColumn(),
                        TransferSpeedColumn(),
                        TimeElapsedColumn(),
                        transient=True,
                    ) as progress:
                        task = progress.add_task(
                            f"下载 {dest.name}", total=total or None
                        )
                        progress.advance(task, done)
                        with open(tmp, "ab" if resumed else "wb") as f:
                            for chunk in resp.iter_content(chunk_size=1 << 20):
                                f.write(chunk)
                                progress.advance(task, len(chunk))
                if total and tmp.stat().st_size != total:
                    raise IOError(f"大小校验失败: {tmp.stat().st_size} != {total}")
                tmp.replace(dest)
                log.info(
                    "下载完成: %s (%.0f MB)",
                    dest.name,
                    dest.stat().st_size / 1048576,
                )
                return dest
            except Exception as e:
                tag = "代理" if sess is PROXY_SESSION else "直连"
                log.warning(
                    "下载异常(%d/%d, %s): %s — %s",
                    attempt + 1,
                    DL_RETRIES,
                    tag,
                    url,
                    e,
                )
    return None


def extract_bats(archive: Path) -> Path | None:
    """仅解压 ip_Update/ip_*.bat，返回 bat 根目录。失败返回 None。"""
    log = get_logger()
    try:
        with SevenZipFile(archive) as z:
            targets = [
                fi.filename
                for fi in z.list()
                if fi.filename and BAT_IN_ARCHIVE.search(fi.filename)
            ]
            if not targets:
                log.warning("压缩包内无 ip_Update/ip_*.bat: %s", archive.name)
                return None

            # 全量重建解压目录，避免上游删除的协议目录残留旧 bat
            if EXTRACT_DIR.exists():
                shutil.rmtree(EXTRACT_DIR)
            z.extract(path=EXTRACT_DIR, targets=targets)
    except Exception as e:
        log.warning("解压失败: %s — %s", archive.name, e)
        return None

    # bat 路径形如 [root...]/<proto>/ip_Update/ip_N.bat → root = 上三级
    first = EXTRACT_DIR / targets[0]
    root = first.parent.parent.parent
    if not any((root / d).is_dir() for d in ("Xray", "clash.meta", "singbox")):
        log.warning("解压目录结构异常（未找到协议目录）: %s", root)
        return None
    log.info("解压完成: %d 个 bat → %s", len(targets), root)
    return root


def _latest_cached_archive() -> Path | None:
    """回退：cache 中最近修改的 .7z（页面/下载全挂时解旧包）。"""
    archives = sorted(
        CACHE_DIR.glob("*.7z"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if archives:
        get_logger().warning("回退使用缓存压缩包: %s", archives[0].name)
    return archives[0] if archives else None


def prepare() -> Path | None:
    """完整流程：页面 → 链接 → 下载 → 解压，返回 bat 根目录。

    任一环节失败依次回退：旧缓存包 → None（scan 沿用现有 urls.yaml）。
    """
    log = get_logger()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    archive: Path | None = None
    links = []
    html = _get_page()
    if html is None:
        log.error("页面抓取失败（已重试 %d 次）", PAGE_RETRIES)
    else:
        links = find_cloud_links(html)
        if not links:
            log.error("页面中未找到云盘下载链接")
        else:
            log.info("云盘链接 %d 条, 首选: %s", len(links), links[0])
            for url in links:
                dest = CACHE_DIR / url.rsplit("/", 1)[-1]
                archive = _download(url, dest)
                if archive is not None:
                    break
                log.warning("切换下一镜像...")

    if archive is None:
        archive = _latest_cached_archive()
    if archive is None:
        log.error("无可用压缩包（下载与缓存均失败）")
        return None

    return extract_bats(archive)


__all__ = [
    "PAGE_URL",
    "EXTRACT_DIR",
    "find_cloud_links",
    "extract_bats",
    "prepare",
]
