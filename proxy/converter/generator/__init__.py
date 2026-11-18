"""目标格式生成器注册表：generate(node, target) -> dict | str | None。

新目标支持：实现 `Generator` 协议（target + supported + generate），然后在此注册。
本轮支持：clash（mihomo proxy dict）。未来 v2rayN / xray / singbox 在 Phase 3 接入。
"""

from __future__ import annotations

from converter.generator._base import Generator
from converter.generator.clash import ClashGenerator
from converter.models import Node

GENERATORS: dict[str, Generator] = {
    "clash": ClashGenerator(),
}


def generate(node: Node, target: str = "clash") -> dict | str | None:
    """按 target 渲染 Node。未知 target 抛 ValueError。"""
    g = GENERATORS.get(target)
    if g is None:
        msg = f"Unknown target: {target!r} (available: {', '.join(GENERATORS)})"
        raise ValueError(msg)
    if not g.supported(node):
        return None
    try:
        return g.generate(node)
    except Exception:
        return None


def available_targets() -> list[str]:
    """返回已注册的 target 列表。"""
    return list(GENERATORS.keys())


__all__ = ["Generator", "GENERATORS", "generate", "available_targets"]
