"""new_pac 节点池：converter.Node 身份键去重 + GeoIP 命名。

身份键：protocol:host:port:credential
  - uuid（vmess/vless/tuic/juicity）
  - password（ss/trojan/hysteria2/anytls/naive）
  - auth_str（hysteria1）
  - username:password（mieru/shadowquic）
  - 空串兜底

命名格式：<country>_<YYYYMMDD>_<ptype>_<host>_<port>
  沿用旧 pac 风格，通过 geo.resolver.get_country_code 查询国家码。
  查询失败时回退 "XX"。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from converter.models import Node
from geo.resolver import get_country_code

from .logger import get_logger

# mihomo/clash 原生支持的协议（与 converter.generator.clash._SUPPORTED 对齐）
CLASH_PROTOCOLS = {
    "vmess",
    "vless",
    "ss",
    "trojan",
    "hysteria1",
    "hysteria2",
    "tuic",
    "anytls",
    "mieru",
    "shadowquic",
    # "juicity",
    # "naive",
}


def identity_key(node: Node) -> str:
    """生成稳定身份键：protocol:host:port:credential。"""
    credential = (
        node.uuid
        or node.password
        or node.auth_str
        or f"{node.username}:{node.password}"
    )
    return f"{node.protocol}:{node.host}:{node.port}:{credential}"


class NodePool:
    """节点池：身份键去重 + 命名。"""

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}

    def add(self, node: Node) -> bool:
        """加入节点。重复键返回 False。"""
        key = identity_key(node)
        if key in self._nodes:
            return False
        self._nodes[key] = node
        return True

    def extend(self, nodes: Iterable[Node]) -> int:
        """批量加入。返回新增数。"""
        return sum(self.add(n) for n in nodes)

    def all(self) -> list[Node]:
        return list(self._nodes.values())

    def clash_supported(self) -> list[Node]:
        """过滤出 mihomo/clash 支持的节点。"""
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
            base = (
                f"{country}_{date}_{node.protocol}_{node.host}_{node.port}"
            )
            name = base
            i = 2
            while name in used:
                name = f"{base}_{i}"
                i += 1
            used.add(name)
            node.name = name
        log.debug("GeoIP 命名完成: %d 个", len(used))

    def stats_by_protocol(self) -> dict[str, int]:
        """按协议统计节点数（按数量降序）。"""
        counts: dict[str, int] = {}
        for n in self._all_sorted():
            counts[n.protocol] = counts.get(n.protocol, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


__all__ = [
    "CLASH_PROTOCOLS",
    "identity_key",
    "NodePool",
]
