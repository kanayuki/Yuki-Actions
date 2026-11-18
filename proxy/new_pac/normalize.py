"""配置文件深度规范化：parse + canonical dump + sha256。

为什么需要规范化？
- HTTP 下载的 json/yaml 可能含不同缩进 / 换行 / 键序，原始文本 sha256 不稳定。
- 规范化后 sha256(canonical) 跨源同配置 100% 命中。

策略：
1. raw text → Python 对象（json.loads / yaml.safe_load）
2. 对象 → 规范化文本
   - json: json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
   - yaml: yaml.safe_dump(obj, allow_unicode=True, default_flow_style=False, sort_keys=False)
3. sha256(canonical) 用于去重与文件名
4. 用 canonical 文本喂 converter.parse_config() → Node[]
   （确保 parser 收到的是稳定输入）

parser 失败不抛：normalize() 返回 nodes=[]，仍落盘（让 store 可被 --from-store 重读）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import yaml
from converter._util import extract_first_json
from converter.models import Node
from converter.parser import parse_config

from .logger import get_logger

JSON_PTYPES = {
    "xray",
    "singbox",
    "hysteria2",
    "hysteria1",
    "mieru",
    "juicity",
    "naive",
}
YAML_PTYPES = {"clash", "shadowquic"}


def _parse_raw(text: str, ptype: str) -> Any:
    """raw text → Python 对象。失败抛 ValueError。"""
    if ptype in JSON_PTYPES:
        return json.loads(extract_first_json(text))
    if ptype in YAML_PTYPES:
        return yaml.safe_load(text)
    raise ValueError(f"unknown ptype: {ptype}")


def _canonical_dump(obj: Any, ptype: str) -> str:
    """Python 对象 → 规范化文本。"""
    if ptype in JSON_PTYPES:
        return json.dumps(
            obj,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            indent=2,
        )
    if ptype in YAML_PTYPES:
        return yaml.safe_dump(
            obj,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
    raise ValueError(f"unknown ptype: {ptype}")


def normalize(text: str, ptype: str) -> tuple[str, str, list[Node]]:
    """对一份原始配置做深度规范化。

    Args:
        text: 原始配置文本（HTTP 下载或磁盘读出）
        ptype: 协议类型

    Returns:
        (canonical_text, sha256_hex, nodes)
        - canonical_text: 规范化后文本（用于写盘 + 哈希）
        - sha256_hex:     canonical_text 的 sha256（用于去重）
        - nodes:          解析出的 Node 列表（失败时为 []）

    Raises:
        ValueError: 解析失败（text 不是合法 json/yaml）
    """
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


__all__ = ["normalize", "JSON_PTYPES", "YAML_PTYPES"]
