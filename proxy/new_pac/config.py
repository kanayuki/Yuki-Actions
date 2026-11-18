"""new_pac 路径常量与 Pydantic 配置。

URL 清单文件 urls.yaml 的结构（git 跟踪）：
    version: int
    sources:
      - ptype: str             # converter ptype（Xray→xray, naiveproxy→naive 等）
        source_dir: str        # bat 所在 ip_Update 目录
        bat_files: [str]       # 仅作总览索引
        groups:
          - bat_file: str
            urls:
              - url: str
                role: primary|backup  # 第一个出现的 url 为 primary
                bat_file: str
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

# ── 路径常量 ──────────────────────────────────────────────
NEW_PAC_DIR = Path(__file__).resolve().parent
PROXY_DIR = NEW_PAC_DIR.parent
URLS_FILE = NEW_PAC_DIR / "urls.yaml"
CONFIG_STORE_DIR = NEW_PAC_DIR / "config_store"
LOGS_DIR = NEW_PAC_DIR / "logs"
SUBSCRIBE_DIR = NEW_PAC_DIR / "subscribe"
OUTPUT_CLASH = SUBSCRIBE_DIR / "clash.yaml"
LOG_FILE = LOGS_DIR / "new_pac.log"

# ── bat 目录 → converter ptype 映射 ───────────────────────
# 注意：clash.meta → clash，naiveproxy → naive，hysteria → hysteria1
# （converter 内部已将 "hysteria" alias 为 "hysteria1"）
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

DEFAULT_SOURCE_ROOT = Path(r"F:\Download\Chrome153_AllNew_2026.9.12")


# ── Pydantic 模型 ──────────────────────────────────────────


class UrlEntry(BaseModel):
    """单条 URL（带角色标记 + 来源追溯）。"""

    url: str
    role: str = "primary"  # primary | backup
    bat_file: str


class BatGroup(BaseModel):
    """单个 .bat 文件的 URL 组。"""

    bat_file: str
    urls: list[UrlEntry] = Field(default_factory=list)


class SourceGroup(BaseModel):
    """单个 ptype 的所有 bat 组。"""

    ptype: str
    source_dir: str
    bat_files: list[str] = Field(default_factory=list)  # 总览索引
    groups: list[BatGroup] = Field(default_factory=list)


class UrlsFile(BaseModel):
    """urls.yaml 顶层模型。"""

    version: int = 1
    sources: list[SourceGroup] = Field(default_factory=list)


__all__ = [
    "NEW_PAC_DIR",
    "PROXY_DIR",
    "URLS_FILE",
    "CONFIG_STORE_DIR",
    "LOGS_DIR",
    "SUBSCRIBE_DIR",
    "OUTPUT_CLASH",
    "LOG_FILE",
    "SOURCE_DIR_MAP",
    "DEFAULT_SOURCE_ROOT",
    "UrlEntry",
    "BatGroup",
    "SourceGroup",
    "UrlsFile",
]
