"""converter 模块的统一中间表示（IR）。

Node 是描述一个代理节点的富 dataclass，涵盖 protocol / credentials / transport /
security / TLS / reality / mux / 协议特有字段等所有语义。生成器只需按 `protocol`
分支读取字段，无需重新猜测语义；解析器按上游格式填齐字段，无需关心最终输出。

设计目标（与 subconverter-ng 对齐）：
- 一份 IR 完整描述一个代理节点，避免 link ↔ dict 的有损往返
- 字段命名贴近 mihomo/clash 与 v2rayN / xray / sing-box 主流客户端的 schema
- 预留 future-proof 字段（flow / host_headers / cipher_2022 / ech / mux / extra_params），
  减少 Phase 3 引入 v2rayN / xray / sing-box 生成器时的 dataclass 破坏性变更
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field


# ── 协议归一化 ──────────────────────────────────────────────
# 上游配置中的协议名 → 统一协议名（小写）
PROTOCOL_ALIASES: dict[str, str] = {
    "shadowsocks": "ss",
    "hysteria": "hysteria1",  # clash/singbox 的 type "hysteria" 是 v1
    "hy2": "hysteria2",
}


def normalize_protocol(name: str) -> str:
    """将任意大小写 / 别名的协议名归一化到 IR 的统一命名。"""
    return PROTOCOL_ALIASES.get(name.lower(), name.lower())


def _b64decode(s: str) -> bytes:
    """解码 urlsafe base64（容忍缺失 padding）。"""
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)


@dataclass
class Node:
    """一个代理节点的完整描述。

    字段按主题分组（Identity / Credentials / Transport / TLS / Reality / Flow&Mux /
    协议特有 / Chained / Metadata）。所有字段都有默认值，parsers 按需填充；生成器按
    `protocol` 分支读取必填项。

    `extra_params: dict` 是无法建模字段的兜底透传通道，生成器按需读取。
    `schema_version: int` 标记当前 IR 版本（占位，未来加迁移逻辑时启用）。
    """

    # ── Identity ──
    name: str = ""
    protocol: str = ""
    host: str = ""
    port: int = 0

    # ── Credentials ──
    uuid: str = ""            # vmess / vless / tuic / juicity
    password: str = ""        # ss / trojan / tuic / juicity / anytls / hysteria2 / naive
    alter_id: int = 0         # vmess
    cipher: str = ""          # vmess (scy) / ss (method)
    cipher_2022: bool = False # ss-2022 系列标识
    auth_str: str = ""        # hysteria1
    username: str = ""        # mieru / shadowquic / naive

    # ── Transport ──
    transport: str = "tcp"    # tcp / ws / grpc / http / httpupgrade / splithttp / xhttp
    path: str = ""            # ws / grpc / h2 / xhttp / splithttp / httpupgrade
    host_headers: list[str] = field(default_factory=list)  # ws Host / h2 host[]
    service_name: str = ""    # grpc serviceName
    transport_mode: str = ""  # xhttp / splithttp 模式
    header_type: str = ""     # vmess tcp headerType (http)

    # ── TLS ──
    tls: bool = False
    sni: str = ""
    alpn: list[str] = field(default_factory=list)
    fingerprint: str = ""
    skip_cert_verify: bool = False
    ech: bool = False
    ech_config: str = ""

    # ── Reality ──
    reality: bool = False
    reality_public_key: str = ""
    reality_short_id: str = ""

    # ── Flow / Mux ──
    flow: str = ""            # vless xtls-rprx-vision
    mux: dict = field(default_factory=dict)  # xray / sing-box multiplex (free-form)

    # ── Hysteria2 ──
    obfs: str = ""
    obfs_password: str = ""
    hop_interval: str = ""

    # ── TUIC / Juicity ──
    congestion_controller: str = "bbr"

    # ── Mieru ──
    multiplexing: str = "MULTIPLEXING_LOW"
    port_range: str = ""

    # ── Hysteria1 ──
    hy1_protocol: str = "udp"
    up_mbps: str = "30 Mbps"
    down_mbps: str = "30 Mbps"

    # ── ShadowQUIC ──
    zero_rtt: bool = False

    # ── Chained / Misc ──
    dialer_proxy: str = ""
    extra_params: dict = field(default_factory=dict)

    # ── Compatibility / Metadata ──
    raw_link: str = ""        # 来源若是分享链接，保存原始字符串
    source: str = ""          # URL 或 store label
    schema_version: int = 1


__all__ = [
    "Node",
    "PROTOCOL_ALIASES",
    "normalize_protocol",
    "_b64decode",
]
