"""源格式解析器协议：所有 parser 必须实现 `parse_config(text, source) -> list[Node]`。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from converter.models import Node


@runtime_checkable
class Parser(Protocol):
    """源格式解析器契约。"""

    ptype: str  # 注册键名：与 pac/fetcher.LINKS_FILES 的键对齐 (xray/clash/singbox/...)

    def parse_config(self, text: str, source: str = "") -> list[Node]:
        """解析一份源配置文本，返回 Node 列表（可能 0 个）。失败时返回空列表。"""
        ...


__all__ = ["Parser"]
