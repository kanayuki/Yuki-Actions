"""new_pac 配置文件存储：内容寻址 + 按月分组 + append-only。

与 pac/store.py 区别：
- 存储文本是 normalize.py 规范化后的内容（哈希更稳定）。
- EXT_MAP 扩展：clash/shadowquic → yaml，其余 → json。
- 第一版不消费 state.json 窗口合并（接口预留）。

目录布局：
    config_store/
      YYYY-MM/{ptype}_{hash12}.{ext}    # 配置原文（content-addressed）
      manifest.jsonl                     # 首次出现记录（永久）
      state.json                         # 最近活跃窗口（本轮不消费）
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import CONFIG_STORE_DIR
from .logger import get_logger

# parser ptype → 文件后缀
EXT_MAP: dict[str, str] = {"clash": "yaml", "shadowquic": "yaml"}
DEFAULT_EXT = "json"
HASH_LEN = 12  # 文件名保留的哈希前缀


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def config_path(ptype: str, hash12: str, month: str) -> Path:
    """构造规范化配置落盘路径。"""
    ext = EXT_MAP.get(ptype, DEFAULT_EXT)
    return CONFIG_STORE_DIR / month / f"{ptype}_{hash12}.{ext}"


def save(ptype: str, source: str, text: str, cfg_hash: str) -> tuple[str, bool] | None:
    """写入规范化后的配置原文（内容寻址）。已存在（同 hash12）则跳过。

    Args:
        ptype: 协议类型
        source: 来源 URL（仅用于 manifest）
        text: 规范化后的文本
        cfg_hash: 完整 sha256 hex

    Returns:
        (month, is_new) 落盘月份与是否新写入
        None            text 为空或写入失败（best-effort）
    """
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
    """跨月份目录查找已存在的同 hash12 文件，返回其月份。"""
    if not CONFIG_STORE_DIR.is_dir():
        return None
    for p in CONFIG_STORE_DIR.glob(f"*/{ptype}_{hash12}.*"):
        return p.parent.name
    return None


def _append_manifest(
    ptype: str, source: str, text: str, hash12: str, month: str
) -> None:
    """追加 manifest 记录（永久保留，用于检索/溯源）。"""
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


__all__ = [
    "EXT_MAP",
    "DEFAULT_EXT",
    "HASH_LEN",
    "config_path",
    "save",
]
