"""新旧 IR 桥：pac.nodes.Node (thin) ↔ converter.Node (rich)。

迁移策略（先并行、后切换）：
- `from_pac_node`：本轮已实现。优先用 pac.Node.clash_proxy 反向解析成富 IR，
  其次回退到 raw_link 经 share_link 解析；再其次只填 protocol/host/port/credential。
- `to_pac_node`：Phase 2 任务。本轮留 NotImplementedError 占位。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from converter.models import Node, _b64decode, normalize_protocol
from converter.parser.share_link import parse_share_link

if TYPE_CHECKING:
    from pac.nodes import Node as PacNode


def from_pac_node(old: "PacNode") -> Node:
    """pac.nodes.Node (thin) → converter.Node (rich)。

    升级策略（按优先级）：
    1. clash_proxy 非空 → 经 ClashParser 反解析（字段最完整）
    2. raw_link 非空 → 经 parse_share_link（vmess/vless/ss/trojan/hy2/tuic/anytls）
    3. 仅 protocol/host/port/credential 兜底
    """
    # 策略 1：clash_proxy 直通
    if old.clash_proxy:
        node = _from_clash_proxy(old)
        if node is not None:
            node.source = old.source or node.source
            return node

    # 策略 2：分享链接解析
    if old.link:
        node = parse_share_link(old.link, source=old.source)
        if node is not None:
            if old.name:
                node.name = old.name
            return node

    # 策略 3：兜底
    return _from_scratch(old)


def to_pac_node(new: Node) -> "PacNode":
    """converter.Node → pac.nodes.Node。Phase 2 任务，本轮占位。

    计划实现：
    - name / source / raw_link 直接透传
    - link: 经 share_link.build 重建（或 Phase 2 抽 build_share_link 模块）
    - clash_proxy: 经 generator.generate(node, "clash") 重建
    - credential: 经 Node.key 派生
    """
    raise NotImplementedError("to_pac_node 待 Phase 2 实现")


# ── 内部 helpers ──────────────────────────────────────────────


def _from_clash_proxy(old: "PacNode") -> Node | None:
    """把 mihomo proxy dict 序列化进 YAML 文本再走 ClashParser 解析，拿到完整富 IR。"""
    try:
        import yaml
    except ImportError:
        return None
    try:
        text = yaml.safe_dump({"proxies": [old.clash_proxy]}, allow_unicode=True, sort_keys=False)
        from converter.parser.clash import ClashParser
        nodes = ClashParser.parse_config(text, source=old.source)
    except Exception:
        return None
    if not nodes:
        return None
    node = nodes[0]
    if old.name:
        node.name = old.name
    return node


def _from_scratch(old: "PacNode") -> Node:
    """仅靠 protocol/host/port 兜底（最差情形）。

    注：pac.Node.credential 字段在富 IR 中没有直接对应位置（已拆解为 uuid / password /
    username / auth_str 等具体字段），scratch 路径无法判定属于哪类，故丢弃。健康的 thin→rich
    路径必须走 clash_proxy 或 link 两条策略之一。
    """
    return Node(
        name=old.name or "",
        protocol=normalize_protocol(old.protocol),
        host=old.host,
        port=old.port,
        source=old.source,
    )


__all__ = ["from_pac_node", "to_pac_node"]
