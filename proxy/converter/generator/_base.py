"""目标格式生成器协议：所有 generator 必须实现 generate(node) -> dict|str|None。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from converter.models import Node


@runtime_checkable
class Generator(Protocol):
    """目标格式生成器契约。"""

    target: str  # 注册键名：e.g. "clash" / 未来 "v2rayn" / "xray" / "singbox"

    def supported(self, node: Node) -> bool:
        """该 generator 是否能渲染该节点（协议支持 / 字段完备）。"""
        ...

    def generate(self, node: Node) -> dict | str | None:
        """Node → 目标格式（dict / str / None）。失败或不支持时返回 None。"""
        ...


__all__ = ["Generator"]
