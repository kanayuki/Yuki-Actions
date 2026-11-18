# proxy/new_pac/ 模块设计方案

> **现状更新（2026-11）**：本方案中"扫描本地目录（`F:\Download\Chrome150_*` 等）提取 bat"的做法已**废弃**。
> 当前 `scan` 由 `source.py` 从 web 源获取：`alvin9999.com/高内核版` 页面 → 抓取"云盘"下载链接（云盘1/2/3 互为后备，
> 首选即最新版）→ 下载 `.7z` 到 `new_pac/cache/`（同名同大小命中缓存，`.part` 断点续传，直连优先/代理后备）
> → `py7zr` 仅解压 `ip_Update/ip_*.bat` 到 `cache/extracted/` → 复用本方案的 bat 扫描逻辑生成 `urls.yaml`。
> 另：`main.py` 无参数时默认执行 `all`；新增 `pull.py` 用于测试任意订阅 URL（格式自动识别 +
> 跟随一层 clash proxy-providers）。稳定性约定：除致命因素外，单个不稳定环节失败不得中断整条流程。

## Context

`proxy/converter/` 已完成 Phase 1 (富 IR Node + 9 个 parser + Clash generator + compat 桥)，但尚未与 `proxy/pac/` 形成实际的依赖关系。`proxy/pac/` 当前是唯一的 PAC 管线入口（`python -m proxy pac`），仍走 thin IR（`pac.nodes.Node`）和自维护的 9 个 `*_config_links.txt` 散文件，存在下列痛点：

1. **URL 来源硬编码散文件**：`pac/get_config_urls.py` 写死了 9 个 `*_config_links.txt` 路径，新增 ptype 需改多处；丢失了 URL 与 `.bat` 来源的追溯关系。
2. **文本哈希不稳定**：HTTP 下载的 json/yaml 因缩进/换行/键序差异产生不同 sha256，导致"同配置不同格式"被当作两份，store 重复落盘。
3. **协议逻辑重复**：每个 `pac/*.py` 解析器与 `core/parse.py` 重复维护，converter 暂未被复用。

本轮目标：**建立 `proxy/new_pac/` 模块**，以 `proxy/converter/` 为唯一 IR 与解析/渲染引擎，独立完成"URL 提取 → 下载 → 规范化 → 渲染"全流程；不动 `proxy/pac/` 任何文件。后续 Phase 再把 `pac/` 迁到依赖 `new_pac/`，最终把 `pac/` 拆掉。

用户明确要求：
- 与 `pac/` **保持独立**（不 import 任何 `pac.*` 模块）。
- URL 提取 → **单一结构化 YAML**（含 bat 文件路径追溯）。
- 下载到 `new_pac/config_store/`，**按月分组**（`YYYY-MM/`）。
- 下载的配置做**深度规范化**后再存储与哈希（消除文本格式差异）。
- 通过 converter 汇总 clash/mihomo 支持的节点 → 渲染 `new_pac/subscribe/clash.yaml`。
- 入口 `new_pac/main.py`。
- 日志到 `new_pac/logs/`，**30 日循环保存**。
- 必要时用 **Rich** 美化输出。

用户已确认的关键决策：
- **URL 下载策略**：下载全部 URL（含主备），由内容哈希去重合并。
- **节点命名策略**：沿用旧 pac 的 GeoIP 命名（`country_date_postfix`），通过 `proxy/geo/resolver.py` 的 `get_country_code` 实现（**不** import `pac.util`，仅 import 共享 `geo` 子模块）。

## 目标 & 非目标

**目标（本轮）**
- 新建 `proxy/new_pac/` 完整骨架。
- `scan.py`：扫 `F:\Download\Chrome150_AllNew_2026.7.15\{Xray|clash.meta|singbox|hysteria2|hysteria|mieru|juicity|naiveproxy|shadowquic}\ip_Update\ip_*.bat`（GBK），抽 HTTPS URL，写入 `new_pac/urls.yaml`（结构化、含 bat 路径追溯）。
- `fetch.py`：读 `urls.yaml` → 下载全部 URL（主备全下）→ 规范化 → 落盘 `config_store/YYYY-MM/`。
- `normalize.py`：parse raw config → canonical dump → sha256(canonical) → 用 canonical 再喂 converter parser。
- `pool.py`：基于 `converter.Node` 身份键（`protocol:host:port:credential`）去重 + GeoIP 命名。
- `render.py`：节点池 → `converter.generate(node, "clash")` → `subscribe/clash.yaml`（空池保护）。
- `logger.py`：`TimedRotatingFileHandler(when="midnight", interval=1, backupCount=30)` + RichHandler 双写。
- `main.py`：CLI 入口，子命令 `scan` / `fetch` / `render` / `all`，支持 `--types`、`--log-level`、`--from-store`。

**非目标（后续 Phase）**
- 不改 `proxy/pac/` 任何文件。
- 不动 `proxy/__main__.py` 子命令。
- 不引入 `state.json` 窗口合并（新模块第一版简化）。
- 不新增 converter ptype（沿用现有 9 个）。
- 不改 CI / publish 流程。

## 目录结构

```
proxy/new_pac/
├── __init__.py                       # 空，仅标记包
├── main.py                           # CLI 入口（4 子命令）
├── config.py                         # 路径常量 + Pydantic 模型（UrlsFile / SourceGroup）
├── logger.py                         # TimedRotatingFileHandler 30 日 + RichHandler
├── scan.py                           # 扫 ip_*.bat → urls.yaml
├── fetch.py                          # 下载 + 规范化 + 落盘
├── normalize.py                      # 深度规范化（parse → canonical dump → sha256）
├── store.py                          # 内容寻址 + 按月分组存储
├── pool.py                           # 节点池（身份键去重 + GeoIP 命名）
├── render.py                         # 节点池 → clash.yaml
├── urls.yaml                         # 扫描产物（git 跟踪，含 bat 路径追溯）
├── config_store/                     # 配置文件原文（git 忽略）
│   ├── YYYY-MM/{ptype}_{hash12}.{ext}
│   ├── manifest.jsonl                # 首次出现记录
│   └── state.json                    # 最近活跃窗口（占位，本轮不消费）
├── subscribe/                        # 渲染产物（git 忽略）
│   └── clash.yaml
└── logs/                             # 运行日志（git 忽略）
    └── new_pac.log
```

`.gitignore` 追加：
```
proxy/new_pac/config_store/
proxy/new_pac/subscribe/
proxy/new_pac/logs/
proxy/new_pac/__pycache__/
```

## 数据流全景

```
   F:\Download\Chrome150_AllNew_2026.7.15
   ├── Xray/ip_Update/ip_*.bat          ┐
   ├── clash.meta/ip_Update/ip_*.bat    │
   ├── singbox/ip_Update/ip_*.bat       ├─→ scan.py (GBK + 正则)
   ├── hysteria2/ip_Update/ip_*.bat     │    → new_pac/urls.yaml
   ├── hysteria/ip_Update/ip_*.bat      │       (含 bat 路径 + 主备标记)
   ├── mieru/ip_Update/ip_*.bat         │
   ├── juicity/ip_Update/ip_*.bat       │
   ├── naiveproxy/ip_Update/ip_*.bat    │
   └── shadowquic/ip_Update/ip_*.bat    ┘
                  │
                  ▼
   ┌──────────────────────────────────────────────────┐
   │  fetch.py                                        │
   │  - 读 urls.yaml → (ptype, url, role)[]          │
   │  - requests.get(url) 全下（含主备）              │
   │  - normalize(text, ptype):                       │
   │      parse → canonical dump → sha256             │
   │  - store.save(canonical, hash) → config_store/   │
   │  - 累计 FetchedConfig(ptype, source, nodes, ...) │
   └──────────────────────────────────────────────────┘
                  │
       ┌──────────┴──────────┐
       ▼                     ▼
   config_store/YYYY-MM/    FetchedConfig[].nodes
   clash_abc.yaml           （converter.Node 列表）
   xray_xyz.json
   manifest.jsonl                    │
                                     ▼
                         ┌──────────────────────┐
                         │  pool.py             │
                         │  - identity_key 去重 │
                         │  - GeoIP 命名        │
                         │  - clash_supported() │
                         └──────────────────────┘
                                     │
                                     ▼
                         ┌──────────────────────┐
                         │  render.py           │
                         │  - generate(node,    │
                         │      "clash")        │
                         │  - proxies+groups+   │
                         │    rules → yaml.dump │
                         └──────────────────────┘
                                     │
                                     ▼
                         new_pac/subscribe/clash.yaml
```

## 核心模块设计

### `config.py` — 路径与配置

```python
"""new_pac 路径常量与 Pydantic 配置。"""

from __future__ import annotations
from pathlib import Path
from pydantic import BaseModel, Field

NEW_PAC_DIR = Path(__file__).resolve().parent
PROXY_DIR = NEW_PAC_DIR.parent
URLS_FILE = NEW_PAC_DIR / "urls.yaml"
CONFIG_STORE_DIR = NEW_PAC_DIR / "config_store"
LOGS_DIR = NEW_PAC_DIR / "logs"
SUBSCRIBE_DIR = NEW_PAC_DIR / "subscribe"
OUTPUT_CLASH = SUBSCRIBE_DIR / "clash.yaml"
LOG_FILE = LOGS_DIR / "new_pac.log"

# bat 目录 → converter ptype
SOURCE_DIR_MAP: dict[str, str] = {
    "Xray": "xray",
    "clash.meta": "clash",
    "singbox": "singbox",
    "hysteria2": "hysteria2",
    "hysteria": "hysteria1",
    "mieru": "mieru",
    "juicity": "juicity",
    "naiveproxy": "naive",
    "shadowquic": "shadowquic",
}

DEFAULT_SOURCE_ROOT = Path(r"F:\Download\Chrome150_AllNew_2026.7.15")


class UrlEntry(BaseModel):
    """单条 URL（带角色标记）。"""
    url: str
    role: str = "primary"  # primary | backup
    bat_file: str


class BatGroup(BaseModel):
    """单个 .bat 文件的 URL 组。"""
    bat_file: str
    urls: list[UrlEntry]


class SourceGroup(BaseModel):
    """单个 ptype 的所有 bat 组。"""
    ptype: str
    source_dir: str
    bat_files: list[str] = Field(default_factory=list)  # 仅作总览索引
    groups: list[BatGroup] = Field(default_factory=list)


class UrlsFile(BaseModel):
    version: int = 1
    sources: list[SourceGroup] = Field(default_factory=list)
```

### `logger.py` — 30 日轮转

```python
"""new_pac 日志：TimedRotatingFileHandler 30 日循环 + RichHandler。"""
import logging
from logging.handlers import TimedRotatingFileHandler
from rich.logging import RichHandler
from .config import LOG_FILE, LOGS_DIR

LOGGER_NAME = "new_pac"
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s  %(message)s"
BACKUP_COUNT = 30


def setup_logger(level: int = logging.INFO) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    for h in list(logger.handlers):
        logger.removeHandler(h)

    fh = TimedRotatingFileHandler(
        LOG_FILE, when="midnight", interval=1,
        backupCount=BACKUP_COUNT, encoding="utf-8",
    )
    fh.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(fh)

    ch = RichHandler(rich_tracebacks=True, show_path=False, markup=True)
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
```

### `scan.py` — bat → urls.yaml

```python
"""扫描 ip_*.bat（GBK）→ urls.yaml（含 bat 路径 + 主备标记）。"""
import re
from pathlib import Path
from rich.table import Table
from .config import (
    DEFAULT_SOURCE_ROOT, SOURCE_DIR_MAP, URLS_FILE,
    BatGroup, SourceGroup, UrlsFile, UrlEntry,
)
from .logger import get_logger

URL_PATTERN = re.compile(r"https://\S+")
BAT_GLOB = "ip_*.bat"


def extract_urls_from_bat(bat_path: Path) -> list[UrlEntry]:
    """从 .bat 文件按出现顺序抽取 URL：第 1 条=primary，其余=backup。"""
    text = bat_path.read_text(encoding="gbk", errors="ignore")
    raw = URL_PATTERN.findall(text)
    entries: list[UrlEntry] = []
    for i, u in enumerate(raw):
        entries.append(UrlEntry(
            url=u,
            role="primary" if i == 0 else "backup",
            bat_file=str(bat_path),
        ))
    return entries


def scan_source(source_root: Path, dir_name: str, ptype: str) -> SourceGroup:
    ip_dir = source_root / dir_name / "ip_Update"
    cfg = SourceGroup(ptype=ptype, source_dir=str(ip_dir))
    if not ip_dir.is_dir():
        get_logger().warning("源目录不存在: %s", ip_dir)
        return cfg
    for bat in sorted(ip_dir.glob(BAT_GLOB)):
        urls = extract_urls_from_bat(bat)
        if urls:
            cfg.bat_files.append(str(bat))
            cfg.groups.append(BatGroup(bat_file=str(bat), urls=urls))
    return cfg


def scan_all(source_root: Path = DEFAULT_SOURCE_ROOT) -> UrlsFile:
    log = get_logger()
    if not source_root.is_dir():
        log.error("source_root 不存在: %s", source_root)
        raise SystemExit(1)
    file = UrlsFile()
    for dir_name, ptype in SOURCE_DIR_MAP.items():
        cfg = scan_source(source_root, dir_name, ptype)
        file.sources.append(cfg)
        log.info("[%s] bat=%d groups=%d urls=%d",
                 ptype, len(cfg.bat_files), len(cfg.groups),
                 sum(len(g.urls) for g in cfg.groups))
    return file


def write_urls_yaml(file: UrlsFile, path: Path = URLS_FILE) -> None:
    import yaml
    path.write_text(
        yaml.safe_dump(
            file.model_dump(),
            allow_unicode=True, sort_keys=False,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )
    get_logger().info("写入 urls.yaml: %s", path)


def render_summary(file: UrlsFile) -> None:
    """Rich 表格汇总：协议 / bat / URL 数。"""
    table = Table(title="URL 提取汇总", header_style="bold cyan")
    table.add_column("协议", style="bold", width=10)
    table.add_column("bat 数", justify="right")
    table.add_column("URL 组", justify="right")
    table.add_column("URL 总数", justify="right")
    for src in file.sources:
        url_total = sum(len(g.urls) for g in src.groups)
        table.add_row(src.ptype, str(len(src.bat_files)),
                      str(len(src.groups)), str(url_total))
    console = get_logger().handlers[1].console  # RichHandler console
    console.print(table)


def run(source_root: Path = DEFAULT_SOURCE_ROOT, write: bool = True) -> UrlsFile:
    file = scan_all(source_root)
    render_summary(file)
    if write:
        write_urls_yaml(file)
    return file
```

### `store.py` — 内容寻址 + 按月分组

```python
"""new_pac 配置存储：内容寻址、按月分组、append-only。

与 pac/store.py 区别：
- 存储文本是规范化后内容（normalize.py 产物），哈希更稳定。
- EXT_MAP 扩展：clash/shadowquic → yaml，其余 → json。
- 第一版不消费 state.json 窗口合并（接口预留）。
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from .config import CONFIG_STORE_DIR
from .logger import get_logger

EXT_MAP: dict[str, str] = {"clash": "yaml", "shadowquic": "yaml"}
DEFAULT_EXT = "json"
HASH_LEN = 12


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def config_path(ptype: str, hash12: str, month: str) -> Path:
    ext = EXT_MAP.get(ptype, DEFAULT_EXT)
    return CONFIG_STORE_DIR / month / f"{ptype}_{hash12}.{ext}"


def save(ptype: str, source: str, text: str, cfg_hash: str) -> tuple[str, bool] | None:
    """写入规范化配置。已存在则跳过。best-effort。"""
    if not text.strip():
        return None
    log = get_logger()
    hash12 = cfg_hash[:HASH_LEN]
    try:
        existing = _find_existing(ptype, hash12)
        if existing:
            return existing, False
        month = _month()
        path = config_path(ptype, hash12, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        _append_manifest(ptype, source, text, hash12, month)
        return month, True
    except Exception as e:
        log.warning("store 写入失败: %s", e)
        return None


def _find_existing(ptype: str, hash12: str) -> str | None:
    if not CONFIG_STORE_DIR.is_dir():
        return None
    for p in CONFIG_STORE_DIR.glob(f"*/{ptype}_{hash12}.*"):
        return p.parent.name
    return None


def _append_manifest(ptype: str, source: str, text: str, hash12: str, month: str) -> None:
    entry = {
        "hash": hash12,
        "ptype": ptype,
        "source": source,
        "first_seen": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "size": len(text.encode("utf-8")),
        "month": month,
    }
    manifest = CONFIG_STORE_DIR / "manifest.jsonl"
    with open(manifest, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
```

### `normalize.py` — 深度规范化（核心）

```python
"""配置文件深度规范化：parse + canonical dump + sha256。

策略：
- raw text → Python 对象（json.loads / yaml.safe_load）
- 对象 → 规范化文本
  * json: json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
  * yaml: yaml.safe_dump(obj, allow_unicode=True, default_flow_style=False, sort_keys=False)
- 哈希: sha256(canonical)  ← 用于去重与文件名
- 解析: 用 canonical 文本喂 converter.parse_config() → Node[]
  （避免 raw 文本与 parser 期望差异）

parser 失败不抛：normalize() 返回 nodes=[]，仍落盘（让 store 可被后续 --from-store 重读）。
"""
import hashlib
import json
from typing import Any
import yaml
from converter.parser import parse_config
from converter.models import Node
from .logger import get_logger

JSON_PTYPES = {"xray", "singbox", "hysteria2", "hysteria1", "mieru", "juicity", "naive"}
YAML_PTYPES = {"clash", "shadowquic"}


def _parse_raw(text: str, ptype: str) -> Any:
    if ptype in JSON_PTYPES:
        return json.loads(text)
    if ptype in YAML_PTYPES:
        return yaml.safe_load(text)
    raise ValueError(f"unknown ptype: {ptype}")


def _canonical_dump(obj: Any, ptype: str) -> str:
    if ptype in JSON_PTYPES:
        return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    if ptype in YAML_PTYPES:
        return yaml.safe_dump(obj, allow_unicode=True, default_flow_style=False, sort_keys=False)
    raise ValueError(f"unknown ptype: {ptype}")


def normalize(text: str, ptype: str) -> tuple[str, str, list[Node]]:
    """Returns: (canonical_text, sha256_hex, nodes)."""
    log = get_logger()
    obj = _parse_raw(text, ptype)
    canonical = _canonical_dump(obj, ptype)
    cfg_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    try:
        nodes = parse_config(canonical, ptype=ptype, source=ptype)
    except Exception as e:
        log.warning("[%s] parser 失败: %s", ptype, e)
        nodes = []
    return canonical, cfg_hash, nodes
```

### `fetch.py` — 下载 + 规范化串联

```python
"""下载 urls.yaml 全部 URL（含主备），规范化后写盘。

数据流：
    urls.yaml → (ptype, url, role, bat_file)[] → 全部下载
    → normalize(text, ptype) → store.save(canonical, hash)
    → 累计 FetchedConfig(ptype, source, nodes, hash, month, is_new)
"""
from __future__ import annotations
import urllib3
from dataclasses import dataclass
from pathlib import Path
import requests
from rich.progress import (
    BarColumn, MofNCompleteColumn, Progress,
    SpinnerColumn, TextColumn, TimeElapsedColumn,
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
    ptype: str
    source: str
    role: str
    bat_file: str
    nodes: list[Node]
    hash: str
    month: str
    is_new: bool


def _download(url: str) -> str | None:
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
    import yaml
    if not path.exists():
        raise SystemExit(
            f"urls.yaml 不存在: {path}（先运行 scan）"
        )
    return UrlsFile(**yaml.safe_load(path.read_text(encoding="utf-8")))


def fetch_all(types: list[str] | None = None) -> list[FetchedConfig]:
    """下载 urls.yaml 全部 URL（主备全下），规范化后写盘。"""
    log = get_logger()
    file = _load_urls()

    # 展平全部 URL（含主备）
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
        BarColumn(), MofNCompleteColumn(), TimeElapsedColumn(),
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
            results.append(FetchedConfig(
                ptype=ptype, source=url, role=role, bat_file=bat_file,
                nodes=nodes, hash=cfg_hash, month=month, is_new=is_new,
            ))
            progress.advance(task)

    log.info(
        "下载完成: %d 成功 / %d 失败 / %d 内容重复, 共 %d 节点",
        len(results), failed, duplicate,
        sum(len(r.nodes) for r in results),
    )
    return results
```

### `pool.py` — 节点池（身份键去重 + GeoIP 命名）

```python
"""new_pac 节点池：converter.Node 身份键去重 + GeoIP 命名。

身份键：protocol:host:port:credential
  - uuid（vmess/vless/tuic/juicity）
  - password（ss/trojan/hysteria2/anytls/naive）
  - auth_str（hysteria1）
  - username:password（mieru/shadowquic）
  - 空串兜底

命名格式：<country>_<YYYYMMDD>_<ptype>_<host>_<port>  ← 沿用旧 pac 风格
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Iterable
from converter.models import Node
from geo.resolver import get_country_code  # 共享子模块，非 pac
from .logger import get_logger

CLASH_PROTOCOLS = {
    "vmess", "vless", "ss", "trojan",
    "hysteria1", "hysteria2",
    "tuic", "anytls",
    "mieru", "shadowquic", "juicity", "naive",
}


def identity_key(node: Node) -> str:
    credential = (
        node.uuid
        or node.password
        or node.auth_str
        or f"{node.username}:{node.password}"
    )
    return f"{node.protocol}:{node.host}:{node.port}:{credential}"


class NodePool:
    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}

    def add(self, node: Node) -> bool:
        key = identity_key(node)
        if key in self._nodes:
            return False
        self._nodes[key] = node
        return True

    def extend(self, nodes: Iterable[Node]) -> int:
        return sum(self.add(n) for n in nodes)

    def all(self) -> list[Node]:
        return list(self._nodes.values())

    def clash_supported(self) -> list[Node]:
        return [n for n in self._all_sorted() if n.protocol in CLASH_PROTOCOLS]

    def __len__(self) -> int:
        return len(self._nodes)

    def _all_sorted(self) -> list[Node]:
        return sorted(self._nodes.values(), key=identity_key)

    def finalize_names(self) -> None:
        """GeoIP 命名：<country>_<date>_<ptype>_<host>_<port>。

        重名时追加 _2/_3/... 后缀。
        """
        log = get_logger()
        date = datetime.now(timezone.utc).strftime("%Y%m%d")
        used: set[str] = set()
        for node in self._all_sorted():
            country = get_country_code(node.host) or "XX"
            base = f"{country}_{date}_{node.protocol}_{node.host}_{node.port}"
            name = base
            i = 2
            while name in used:
                name = f"{base}_{i}"
                i += 1
            used.add(name)
            node.name = name
        log.debug("GeoIP 命名完成: %d 个", len(used))

    def stats_by_protocol(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for n in self._all_sorted():
            counts[n.protocol] = counts.get(n.protocol, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
```

### `render.py` — 节点池 → clash.yaml

```python
"""new_pac 渲染：converter.Node → subscribe/clash.yaml。

策略：
  - 过滤 mihomo 支持的协议（pool.clash_supported）
  - converter.generate(node, "clash") → proxy dict
  - 附带 PROXY(select) / AUTO(url-test) 分组 + GEOIP 分流规则
  - 空池保护：节点池为空时不覆盖已有 clash.yaml（exit 1）
"""
import sys
from pathlib import Path
import yaml
from rich.table import Table
from converter import generate
from .config import OUTPUT_CLASH, SUBSCRIBE_DIR
from .logger import get_logger

_TEST_URL = "http://www.gstatic.com/generate_204"
_BASE_RULES = [
    "GEOIP,LAN,DIRECT,no-resolve",
    "GEOIP,CN,DIRECT",
    "MATCH,PROXY",
]


def render(pool, out_path: Path = OUTPUT_CLASH) -> tuple[int, int, Path]:
    log = get_logger()
    clash_nodes = pool.clash_supported()
    proxies: list[dict] = []
    skipped = 0
    for node in clash_nodes:
        proxy = generate(node, target="clash")
        if proxy is None:
            skipped += 1
            continue
        proxies.append(proxy)

    if not proxies:
        log.warning("可用节点为 0，跳过写入（保护 %s）", out_path.name)
        return 0, skipped, out_path

    SUBSCRIBE_DIR.mkdir(parents=True, exist_ok=True)
    names = [p["name"] for p in proxies]
    config = {
        "proxies": proxies,
        "proxy-groups": [
            {"name": "PROXY", "type": "select",
             "proxies": ["AUTO", "DIRECT", *names]},
            {"name": "AUTO", "type": "url-test",
             "url": _TEST_URL, "interval": 300, "tolerance": 50,
             "proxies": names},
        ],
        "rules": _BASE_RULES,
    }
    out_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False, width=4096),
        encoding="utf-8",
    )
    log.info("Clash 订阅: %d 节点 → %s", len(proxies), out_path)
    if skipped:
        log.info("  跳过 %d 个（mihomo 不支持或 generate 失败）", skipped)
    return len(proxies), skipped, out_path


def print_stats(pool) -> None:
    """Rich 表格：各协议节点数。"""
    table = Table(
        title=f"节点池统计 [[bold]{len(pool)}[/bold]]",
        header_style="bold cyan",
    )
    table.add_column("协议", style="bold")
    table.add_column("节点数", justify="right")
    for proto, count in pool.stats_by_protocol().items():
        table.add_row(proto, str(count))
    get_logger().handlers[1].console.print(table)
```

### `main.py` — CLI 入口

```python
"""new_pac CLI 入口。

子命令：
    scan        扫描 ip_*.bat → urls.yaml
    fetch       下载 urls.yaml → 规范化 → config_store/
    render      读 fetch 结果或 store → clash.yaml
    all         scan → fetch → render 串联
"""
import argparse
import logging
from pathlib import Path
from rich.rule import Rule
from .config import DEFAULT_SOURCE_ROOT, CONFIG_STORE_DIR
from .logger import get_logger, setup_logger
from .pool import NodePool
from .render import print_stats, render
from .scan import run as run_scan
from .fetch import fetch_all
from .normalize import normalize


def _cmd_scan(args) -> None:
    get_logger().info(Rule("[bold cyan]Scan ip_*.bat[/bold cyan]"))
    root = Path(args.source_root) if args.source_root else DEFAULT_SOURCE_ROOT
    run_scan(root, write=True)


def _cmd_fetch(args) -> None:
    get_logger().info(Rule("[bold cyan]Fetch configs[/bold cyan]"))
    results = fetch_all(types=args.types)
    get_logger().info(
        "Fetched %d 份配置, 节点数 %d",
        len(results), sum(len(r.nodes) for r in results),
    )


def _cmd_render(args) -> None:
    get_logger().info(Rule("[bold cyan]Render clash.yaml[/bold cyan]"))
    pool = NodePool()
    if args.from_store:
        n = 0
        for path in CONFIG_STORE_DIR.glob("*/*.*"):
            if path.suffix not in (".yaml", ".json"):
                continue
            ptype = path.name.split("_", 1)[0]
            try:
                _, _, nodes = normalize(path.read_text(encoding="utf-8"), ptype)
            except Exception:
                continue
            pool.extend(nodes)
            n += 1
        get_logger().info("从 store 读出 %d 份配置, 共 %d 节点", n, len(pool))
    else:
        results = fetch_all(types=args.types)
        for r in results:
            pool.extend(r.nodes)

    if len(pool) == 0:
        get_logger().error("节点池为空，跳过渲染（保护 clash.yaml）")
        raise SystemExit(1)

    pool.finalize_names()
    print_stats(pool)
    n, skipped, path = render(pool)
    get_logger().info("渲染完成: %d 节点 → %s", n, path)


def _cmd_all(args) -> None:
    _cmd_scan(args)
    _cmd_fetch(args)
    _cmd_render(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="new_pac",
        description="new_pac: 独立 PAC 管线，基于 converter",
    )
    parser.add_argument("--source-root", default=None,
                        help="bat 根目录（默认 F:\\Download\\Chrome150_AllNew_2026.7.15）")
    parser.add_argument("--types", nargs="+", default=None,
                        help="限定 ptype（如 xray clash singbox）")
    parser.add_argument("--from-store", action="store_true",
                        help="render 时从 config_store 全部月份重读")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scan", help="扫描 bat → urls.yaml")
    sub.add_parser("fetch", help="下载+规范化+落盘")
    sub.add_parser("render", help="节点池 → clash.yaml")
    sub.add_parser("all", help="scan + fetch + render 一把梭")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logger(level=getattr(logging, args.log_level))
    log = get_logger()
    try:
        {"scan": _cmd_scan, "fetch": _cmd_fetch,
         "render": _cmd_render, "all": _cmd_all}[args.command](args)
    except Exception as e:
        log.exception("执行失败: %s", e)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
```

## 关键文件路径（修改/新建）

| 文件 | 状态 | 作用 |
|---|---|---|
| `proxy/new_pac/__init__.py` | **新建** | 包标记（空） |
| `proxy/new_pac/config.py` | **新建** | 路径 + Pydantic 配置 |
| `proxy/new_pac/logger.py` | **新建** | 30 日轮转 + RichHandler |
| `proxy/new_pac/scan.py` | **新建** | bat → urls.yaml |
| `proxy/new_pac/store.py` | **新建** | 内容寻址存储 |
| `proxy/new_pac/normalize.py` | **新建** | 深度规范化（核心） |
| `proxy/new_pac/fetch.py` | **新建** | 下载 + 规范化串联 |
| `proxy/new_pac/pool.py` | **新建** | 节点池 + GeoIP 命名 |
| `proxy/new_pac/render.py` | **新建** | clash.yaml 渲染 |
| `proxy/new_pac/main.py` | **新建** | CLI 入口 |
| `proxy/new_pac/urls.yaml` | **运行时生成** | URL 扫描产物（git 跟踪） |
| `proxy/new_pac/config_store/` | **运行时生成** | 配置原文（git 忽略） |
| `proxy/new_pac/subscribe/clash.yaml` | **运行时生成** | 渲染产物（git 忽略） |
| `proxy/new_pac/logs/new_pac.log` | **运行时生成** | 运行日志（git 忽略） |
| `.gitignore` | **追加 4 行** | 忽略 `new_pac/` 运行时产物 |

**绝对不动**：所有 `proxy/pac/*`、`proxy/__main__.py`、`proxy/converter/*`。

## 复用的现有模块

- `converter.parser.parse_config` —— normalize.py 用规范化文本喂入
- `converter.models.Node` —— pool.py / normalize.py 唯一 IR
- `converter.generator.generate` —— render.py 渲染 clash proxy dict
- `geo.resolver.get_country_code` —— pool.py GeoIP 命名
- `rich.console.Console` / `rich.logging.RichHandler` / `rich.progress.Progress` / `rich.table.Table` / `rich.rule.Rule` —— UI 美化

## 边界情况处理

| 场景 | 处理 |
|---|---|
| `F:\Download\...` 不存在 | `scan_all` → `SystemExit(1)`，日志记录 |
| bat GBK 解码失败 | `errors="ignore"` 跳过坏字符 |
| 某协议无 bat 文件 | 写 `urls.yaml` 时保留空 group（不报错） |
| HTTP 下载失败/超时 | log warning + failed 计数 + 继续下一个 |
| raw 文本非合法 JSON/YAML | normalize 抛 ValueError，外层 catch 跳过 |
| parser 在 canonical 上失败 | normalize 返回 `nodes=[]`，仍落盘 |
| 内容哈希重复（主备 URL 同源） | `seen_hash` 命中跳过，不重复写盘 |
| 节点池为空 | render 跳过写盘 + `SystemExit(1)`，保护已有 clash.yaml |
| 节点名冲突（同 host:port 多协议） | 追加 `_2`/`_3` 后缀 |
| 重复运行 main | logger `removeHandler` 清空再装 + `propagate=False` |
| urls.yaml 缺失（首次跑 fetch） | `fetch_all` → SystemExit 提示先跑 scan |
| GeoIP 网络失败 | `get_country_code` 返回 `XX`，命名仍可用 |
| `urls.yaml` 已存在 | scan 直接覆盖（来源稳定，git diff 小） |
| `config_store` 跨月存量 | `_find_existing` 跨月份目录扫描命中则跳过 |

## 关键决策与理由

| 决策点 | 选择 | 理由 |
|---|---|---|
| URL 存储格式 | 单一 `urls.yaml`（含 bat 路径追溯） | 旧 9 个散文件难维护；结构化 yaml 保留追溯 |
| URL 下载策略 | **全部 URL（含主备）** | 用户确认；内容哈希去重自动合并重复 |
| 内容去重粒度 | 规范化后 sha256 | 消除 json/yaml 缩进/键序差异；同配置 100% 命中 |
| 规范化参数 | json: sort_keys+紧凑；yaml: safe_dump 默认 | json 强制键序稳定；yaml 块序天然稳定 |
| 命名策略 | **GeoIP 命名**（country_date_ptype_host_port） | 用户确认；沿用旧 pac 风格，CI 可容忍 ip-api 失败 |
| 日志 handler | `TimedRotatingFileHandler` + `RichHandler` | 30 日轮转 + 控制台富化 |
| 与 `__main__.py` 关系 | **不注册** | 独立运行 `python -m proxy.new_pac.main` |
| `state.json` 窗口合并 | 第一版不实现 | 简化第一版；接口预留 |
| 空池保护 | 节点池=0 → exit 1 不写盘 | 保护已有 clash.yaml |
| 与 `pac/` 边界 | **零 import pac.*** | 用户明确要求；GeoIP 走 `geo.resolver` 共享子模块 |

## 验证方式（端到端）

### 1. 离线烟测（无网络）

```bash
cd d:\Code\Python\Yuki-Actions
python -m proxy.new_pac.main scan --source-root "F:\Download\Chrome150_AllNew_2026.7.15"
```

预期：
- 生成 `proxy/new_pac/urls.yaml`
- Rich 表格显示 9 个协议 + bat/URL 计数
- 日志写入 `proxy/new_pac/logs/new_pac.log.*`

### 2. 下载烟测（部分网络）

```bash
python -m proxy.new_pac.main fetch --types hysteria2 clash --log-level INFO
```

预期：
- Rich 进度条展示下载进度
- 命中数 + 失败数 + 重复数汇总
- `proxy/new_pac/config_store/2026-09/` 出现 `hysteria2_*.json` / `clash_*.yaml`
- `manifest.jsonl` 追加新记录

### 3. 渲染烟测

```bash
python -m proxy.new_pac.main render
```

预期：
- GeoIP 命名（控制台无明显错误）
- `proxy/new_pac/subscribe/clash.yaml` 写入，含 proxies + groups + rules
- 节点数为 0 → exit 1 不写盘

### 4. 全流程一键

```bash
python -m proxy.new_pac.main all
```

预期：串联 scan → fetch → render 全部成功（或各阶段友好降级）。

### 5. 独立验证（与 pac 对比）

```bash
# 旧管线（不动，作为对照）
python -m proxy pac

# 新管线
python -m proxy.new_pac.main all
```

预期：两套 clash.yaml 节点集**功能等价**（允许 name 命名风格不同）。

### 6. 日志轮转验证

```bash
# 模拟 31 天前的日志
touch -d "31 days ago" proxy/new_pac/logs/new_pac.log.20260812
python -m proxy.new_pac.main scan
# 期望：.20260812 被 TimedRotatingFileHandler 自动清理（保留最近 30 个）
```

### 7. `.gitignore` 验证

```bash
git check-ignore proxy/new_pac/config_store/2026-09/clash_abc.yaml
git check-ignore proxy/new_pac/subscribe/clash.yaml
git check-ignore proxy/new_pac/logs/new_pac.log

# urls.yaml 应被跟踪
git check-ignore proxy/new_pac/urls.yaml  # 期望：无输出（未被忽略）
```

## 推荐实现顺序（4 步）

1. **Step 1（基础设施）**：`config.py` + `logger.py` + `__init__.py` + `.gitignore` 追加
2. **Step 2（URL 提取）**：`scan.py` + 跑 `scan` 生成 `urls.yaml`，立刻验证 bat 解析
3. **Step 3（下载 + 规范化）**：`store.py` + `normalize.py` + `fetch.py`，跑 `fetch` 验证 `config_store` 落盘
4. **Step 4（渲染 + CLI 串联）**：`pool.py` + `render.py` + `main.py`，跑 `all` 端到端验证

每步独立可跑，CI 友好。
