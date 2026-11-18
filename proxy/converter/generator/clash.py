"""Node → Clash / mihomo proxy dict 生成器。

直接消费富 IR，无需重新解析分享链接。覆盖 mihomo 支持的全部 11 种协议。
"""

from __future__ import annotations

from converter.generator._base import Generator
from converter.models import Node

# mihomo 支持的协议（与 pac/nodes.py CLASH_PROTOCOLS 对齐）
_SUPPORTED = {
    "vmess", "vless", "ss", "trojan",
    "hysteria1", "hysteria2",
    "tuic", "anytls",
    "mieru", "shadowquic", "juicity", "naive",
}


class ClashGenerator:
    target = "clash"

    def supported(self, node: Node) -> bool:
        return node.protocol in _SUPPORTED and bool(node.host) and node.port > 0

    def generate(self, node: Node) -> dict | None:
        if not self.supported(node):
            return None
        builder = _BUILDERS.get(node.protocol)
        if builder is None:
            return None
        return builder(node)


# ── builders ──────────────────────────────────────────────


def _name(node: Node) -> str:
    return node.name or f"{node.host}:{node.port}"


def _gen_vmess(node: Node) -> dict:
    p: dict = {
        "name": _name(node),
        "type": "vmess",
        "server": node.host,
        "port": node.port,
        "uuid": node.uuid,
        "alterId": node.alter_id,
        "cipher": node.cipher or "auto",
    }
    _fill_transport(p, node)
    _fill_tls(p, node)
    return p


def _gen_vless(node: Node) -> dict:
    p = {
        "name": _name(node),
        "type": "vless",
        "server": node.host,
        "port": node.port,
        "uuid": node.uuid,
    }
    if node.flow:
        p["flow"] = node.flow
    _fill_transport(p, node)
    _fill_tls(p, node)
    return p


def _gen_ss(node: Node) -> dict:
    p = {
        "name": _name(node),
        "type": "ss",
        "server": node.host,
        "port": node.port,
        "cipher": node.cipher,
        "password": node.password,
    }
    _fill_transport(p, node)
    _fill_tls(p, node)
    return p


def _gen_trojan(node: Node) -> dict:
    p = {
        "name": _name(node),
        "type": "trojan",
        "server": node.host,
        "port": node.port,
        "password": node.password,
    }
    if node.sni:
        p["sni"] = node.sni
    if node.skip_cert_verify:
        p["skip-cert-verify"] = True
    if node.alpn:
        p["alpn"] = list(node.alpn)
    _fill_transport(p, node)
    if node.tls and "tls" not in p:
        p["tls"] = True
    return p


def _gen_hysteria2(node: Node) -> dict:
    server = f"[{node.host}]" if ":" in node.host and not node.host.startswith("[") else node.host
    p = {
        "name": _name(node),
        "type": "hysteria2",
        "server": server,
        "port": node.port,
        "password": node.password,
    }
    if node.sni:
        p["sni"] = node.sni
    if node.skip_cert_verify:
        p["skip-cert-verify"] = True
    if node.obfs:
        p["obfs"] = node.obfs
        p["obfs-password"] = node.obfs_password
    if node.hop_interval:
        p["hop-interval"] = node.hop_interval
    return p


def _gen_hysteria1(node: Node) -> dict:
    p = {
        "name": _name(node),
        "type": "hysteria",
        "server": node.host,
        "port": node.port,
        "auth-str": node.auth_str,
        "protocol": node.hy1_protocol,
        "up": node.up_mbps,
        "down": node.down_mbps,
    }
    if node.sni:
        p["sni"] = node.sni
    if node.skip_cert_verify:
        p["skip-cert-verify"] = True
    if node.alpn:
        p["alpn"] = list(node.alpn)
    return p


def _gen_tuic(node: Node) -> dict:
    alpn = node.alpn or ["h3"]
    p = {
        "name": _name(node),
        "type": "tuic",
        "server": node.host,
        "port": node.port,
        "uuid": node.uuid,
        "password": node.password,
        "congestion-controller": node.congestion_controller,
        "alpn": alpn,
    }
    if node.sni:
        p["sni"] = node.sni
    if node.skip_cert_verify:
        p["skip-cert-verify"] = True
    return p


def _gen_anytls(node: Node) -> dict:
    p = {
        "name": _name(node),
        "type": "anytls",
        "server": node.host,
        "port": node.port,
        "password": node.password,
    }
    if node.fingerprint:
        p["client-fingerprint"] = node.fingerprint
    if node.alpn:
        p["alpn"] = list(node.alpn)
    if node.skip_cert_verify:
        p["skip-cert-verify"] = True
    return p


def _gen_mieru(node: Node) -> dict:
    mtrans = str(node.extra_params.get("mieru_transport", "TCP")).upper()
    p = {
        "name": _name(node),
        "type": "mieru",
        "server": node.host,
        "username": node.username,
        "password": node.password,
        "transport": mtrans,
        "multiplexing": node.multiplexing or "MULTIPLEXING_LOW",
    }
    if node.port_range:
        p["port-range"] = node.port_range
    else:
        p["port"] = node.port
    return p


def _gen_shadowquic(node: Node) -> dict:
    p = {
        "name": _name(node),
        "type": "shadowquic",
        "server": node.host,
        "port": node.port,
        "username": node.username,
        "password": node.password,
        "congestion-controller": node.congestion_controller,
        "tls": True,
    }
    if node.sni:
        p["sni"] = node.sni
    if node.alpn:
        p["alpn"] = list(node.alpn)
    if node.zero_rtt:
        p["zero-rtt"] = True
    return p


def _gen_juicity(node: Node) -> dict:
    p = {
        "name": _name(node),
        "type": "juicity",
        "server": node.host,
        "port": node.port,
        "uuid": node.uuid,
        "password": node.password,
        "congestion-controller": node.congestion_controller,
    }
    if node.sni:
        p["sni"] = node.sni
    if node.skip_cert_verify:
        p["skip-cert-verify"] = True
    return p


def _gen_naive(node: Node) -> dict:
    p = {
        "name": _name(node),
        "type": "naive",
        "server": node.host,
        "port": node.port,
        "username": node.username,
        "password": node.password,
    }
    if node.sni:
        p["sni"] = node.sni
    if node.skip_cert_verify:
        p["skip-cert-verify"] = True
    return p


_BUILDERS = {
    "vmess": _gen_vmess,
    "vless": _gen_vless,
    "ss": _gen_ss,
    "trojan": _gen_trojan,
    "hysteria2": _gen_hysteria2,
    "hysteria1": _gen_hysteria1,
    "tuic": _gen_tuic,
    "anytls": _gen_anytls,
    "mieru": _gen_mieru,
    "shadowquic": _gen_shadowquic,
    "juicity": _gen_juicity,
    "naive": _gen_naive,
}


# ── 共用填充 ──────────────────────────────────────────────


def _fill_transport(p: dict, node: Node) -> None:
    """transport-specific 字段：network / ws-opts / grpc-opts / h2-opts。"""
    if node.transport in ("ws", "grpc", "http", "splithttp", "xhttp", "httpupgrade"):
        p["network"] = node.transport

    if node.transport == "ws":
        opts: dict = {"path": node.path or "/"}
        if node.host_headers:
            opts["headers"] = {"Host": node.host_headers[0]}
        p["ws-opts"] = opts
    elif node.transport == "grpc":
        p["grpc-opts"] = {"grpc-service-name": node.service_name}
    elif node.transport == "http":
        opts = {"path": node.path or "/"}
        if node.host_headers:
            opts["host"] = list(node.host_headers)
        p["h2-opts"] = opts


def _fill_tls(p: dict, node: Node) -> None:
    """TLS / Reality / fingerprint / alpn 填充。"""
    if node.reality:
        ro = {
            "public-key": node.reality_public_key,
            "short-id": node.reality_short_id,
        }
        p["reality-opts"] = ro
        p["tls"] = True
    elif node.tls:
        p["tls"] = True

    if node.tls or node.reality:
        if node.sni and "servername" not in p and "sni" not in p:
            p["servername"] = node.sni
        if node.fingerprint:
            p["client-fingerprint"] = node.fingerprint
        if node.alpn and "alpn" not in p:
            p["alpn"] = list(node.alpn)
        if node.skip_cert_verify:
            p["skip-cert-verify"] = True


__all__ = ["ClashGenerator"]
