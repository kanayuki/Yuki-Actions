"""统一节点池：PAC 管线的中间表示（IR）。

所有协议的配置解析为 Node 后进入 NodePool：
- 按 type:server:port:credential 身份键跨源去重（互为备用的 URL 自动合并）
- finalize() 时批量解析国家码、命名节点并写入链接备注
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

from pac.util import console

# ── 协议支持矩阵 ──────────────────────────────────────────────
# v2rayN（含 sing-box 内核）订阅中可用的协议
V2RAYN_PROTOCOLS = {
    "vmess",
    "vless",
    "ss",
    "trojan",
    "hysteria2",
    "tuic",
    "anytls",
    "juicity",
    "naive",
}

# Clash Verge（mihomo 内核）订阅中可用的协议
CLASH_PROTOCOLS = {
    "vmess",
    "vless",
    "ss",
    "trojan",
    "hysteria2",
    "tuic",
    "anytls",
    "mieru",
    "hysteria1",
    "shadowquic",
}

# 各来源配置中的协议名 → 统一协议名
PROTOCOL_ALIASES = {
    "shadowsocks": "ss",
    "hysteria": "hysteria1",  # clash/singbox 的 type "hysteria" 是 v1
    "hy2": "hysteria2",
}


def normalize_protocol(name: str) -> str:
    return PROTOCOL_ALIASES.get(name.lower(), name.lower())


def _b64decode(s: str) -> bytes:
    """解码 urlsafe base64（容忍缺失 padding）。"""
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)


@dataclass
class Node:
    """单个代理节点。

    link       分享链接（v2rayN 订阅产物；clash-only 协议为空串）
    clash_proxy mihomo 原生 proxy dict（无则渲染时经 link_to_clash 转换）
    """

    protocol: str
    host: str
    port: int
    credential: str
    source: str = ""
    link: str = ""
    clash_proxy: dict | None = None
    name: str = ""

    @property
    def key(self) -> str:
        return f"{self.protocol}:{self.host}:{self.port}:{self.credential}"

    @property
    def v2rayn_ok(self) -> bool:
        return self.protocol in V2RAYN_PROTOCOLS and bool(self.link)

    @property
    def clash_ok(self) -> bool:
        return self.protocol in CLASH_PROTOCOLS


class NodePool:
    """节点池：身份键去重 + 命名。"""

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}

    def add(self, node: Node) -> bool:
        """加入节点。同身份键时合并信息（clash_proxy 与 link 互补），返回是否新增。"""
        old = self._nodes.get(node.key)
        if old is None:
            self._nodes[node.key] = node
            return True
        # 保留信息更全的一份
        if node.clash_proxy and not old.clash_proxy:
            node.link = node.link or old.link
            self._nodes[node.key] = node
        else:
            old.link = old.link or node.link
        return False

    def all(self) -> list[Node]:
        return list(self._nodes.values())

    def __len__(self) -> int:
        return len(self._nodes)

    # ── 命名 ──────────────────────────────────────────────

    def finalize(self, country_of: dict[str, str]) -> None:
        """批量命名节点（国家_日期_协议），并把名字写进链接备注与 clash proxy。"""
        used: set[str] = set()
        date = datetime.now().strftime("%Y%m%d")
        for node in sorted(self._nodes.values(), key=lambda n: n.key):
            country = country_of.get(node.host, "XX")
            base = f"{country}_{date}_{node.protocol}"
            name = base
            i = 2
            while name in used:
                name = f"{base}_{i}"
                i += 1
            used.add(name)
            node.name = name
            if node.link:
                node.link = set_link_remark(node.link, name)
            if node.clash_proxy is not None:
                node.clash_proxy = {**node.clash_proxy, "name": node.name}

    def stats_by_protocol(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for node in self._nodes.values():
            counts[node.protocol] = counts.get(node.protocol, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def set_link_remark(link: str, name: str) -> str:
    """把节点名写入分享链接备注（#片段 / vmess 的 ps 字段 / mieru 的 profile 参数）。"""
    if link.startswith("vmess://"):
        try:
            payload = json.loads(_b64decode(link[len("vmess://") :]))
            payload["ps"] = name
            raw = json.dumps(payload, ensure_ascii=False).encode()
            return "vmess://" + base64.urlsafe_b64encode(raw).decode()
        except Exception:
            return link
    if link.startswith("mieru://"):
        try:
            inner = base64.b64decode(link[len("mieru://") :]).decode()
            inner = re.sub(r"profile=[^&]*", f"profile={name}", inner)
            return "mieru://" + base64.b64encode(inner.encode()).decode()
        except Exception:
            return link
    # URL 型链接：替换 # 片段
    if "#" in link:
        link = link.rsplit("#", 1)[0]
    return f"{link}#{quote(name, safe='')}"


def brief_url(url: str, width: int = 50) -> str:
    """日志用的短 URL。"""
    return url if len(url) <= width else url[: width - 3] + "..."
