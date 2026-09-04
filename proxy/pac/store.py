"""config store：配置原文的内容寻址持久化（随 data 分支持久化）。

目录结构（proxy/config_store/）：
    YYYY-MM/{ptype}_{hash12}.{ext}   按月分组的配置原文，内容寻址，append-only
    manifest.jsonl                    首次出现记录（永久保留，检索/溯源用）
    state.json                        最近活跃状态（每轮重写，窗口合并用）

设计要点：
- 文件名 = 协议类型 + 内容哈希前 12 位 → 同内容只存一份；内容未变时 git 零变更
- 配置固定落在首次出现的月份目录，不跨月复制
- 窗口合并：解析时纳入最近 WINDOW_DAYS 天出现过、但本轮未获取到的配置，
  缓解源临时故障或渐进衰减导致的订阅缩水（活跃配置会随每轮写入"前移"到近期月份）
- 所有写入 best-effort：store 故障只告警，不影响主管线
- 保留策略（CI publish 阶段执行）：工作树仅保留最近 12 个月份目录；
  manifest/state 永久保留，更早的原文可经 git 历史按 manifest 的 hash 找回
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pac.util import console

# parser 类型 → 存储后缀（clash 系为 yaml，其余均为 json）
EXT_MAP = {"clash": "yaml"}
DEFAULT_EXT = "json"

HASH_LEN = 12  # 文件名中保留的哈希前缀长度

WINDOW_DAYS = 7  # 窗口合并天数
STATE_RETAIN_DAYS = 2 * WINDOW_DAYS  # state.json 条目保留天数（窗口的一倍余量）

STORE_DIR = Path(__file__).resolve().parent.parent / "config_store"


# ── 路径 ──────────────────────────────────────────────


def _manifest_path() -> Path:
    return STORE_DIR / "manifest.jsonl"


def _state_path() -> Path:
    return STORE_DIR / "state.json"


def config_path(ptype: str, hash12: str, month: str) -> Path:
    ext = EXT_MAP.get(ptype, DEFAULT_EXT)
    return STORE_DIR / month / f"{ptype}_{hash12}.{ext}"


# ── 写入 ──────────────────────────────────────────────


def save(ptype: str, source: str, text: str, cfg_hash: str) -> tuple[str, bool] | None:
    """写入配置原文（内容寻址）。已存在则跳过。

    Returns:
        (month, is_new)  文件所在月份与是否新写入
        None             写入失败或内容为空（best-effort，不抛异常）
    """
    if not text.strip():
        return None
    hash12 = cfg_hash[:HASH_LEN]
    try:
        month = _find_existing(ptype, hash12)
        is_new = month is None
        if is_new:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            path = config_path(ptype, hash12, month)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            _append_manifest(ptype, source, text, hash12, month)
        return month, is_new
    except Exception as e:
        console.print(f"  [yellow]⚠ store 写入失败: {e}[/yellow]")
        return None


def _find_existing(ptype: str, hash12: str) -> str | None:
    """在全部月份目录中查找已存在的配置文件，返回其月份。"""
    if not STORE_DIR.is_dir():
        return None
    for path in STORE_DIR.glob(f"*/{ptype}_{hash12}.*"):
        return path.parent.name
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
    with open(_manifest_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def mark_seen(records: list[tuple[str, str, str]]) -> None:
    """记录本轮成功获取的配置，重写 state.json。

    records: (cfg_hash 完整值, ptype, month) 列表（month 为 save() 返回的文件位置）。
    超出 STATE_RETAIN_DAYS 的旧条目同时修剪；best-effort。
    """
    if not records:
        return
    today = datetime.now(timezone.utc).date()
    try:
        seen = _load_state()
        for cfg_hash, ptype, month in records:
            seen[cfg_hash[:HASH_LEN]] = {"m": month, "p": ptype, "d": today.isoformat()}
        cutoff = (today - timedelta(days=STATE_RETAIN_DAYS)).isoformat()
        seen = {h: info for h, info in seen.items() if info.get("d", "") >= cutoff}
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seen": seen},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        console.print(f"  [yellow]⚠ state 更新失败: {e}[/yellow]")


# ── 读取 ──────────────────────────────────────────────


def _load_state() -> dict[str, dict]:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("seen", {})
    except Exception:
        return {}


def load_window(exclude: set[str], days: int = WINDOW_DAYS) -> list[tuple[str, str, str]]:
    """加载窗口内（最近 N 天出现过）、且本轮未获取到的存量配置。

    Args:
        exclude: 本轮已获取配置的完整内容哈希集合（内部截断到 HASH_LEN 比较）
        days: 窗口天数

    Returns:
        (ptype, source_label, text) 列表；文件缺失（如未恢复的早期月份）跳过。
    """
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    exclude12 = {h[:HASH_LEN] for h in exclude}
    results: list[tuple[str, str, str]] = []
    try:
        for hash12, info in sorted(_load_state().items()):
            if hash12 in exclude12 or info.get("d", "") < cutoff:
                continue
            path = config_path(info.get("p", ""), hash12, info.get("m", ""))
            if not path.exists():
                continue
            label = f"store:{info.get('m')}/{path.name}"
            results.append((info.get("p", ""), label, path.read_text(encoding="utf-8")))
    except Exception as e:
        console.print(f"  [yellow]⚠ store 窗口加载失败: {e}[/yellow]")
    return results
