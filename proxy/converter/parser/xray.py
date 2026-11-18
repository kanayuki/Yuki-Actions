"""xray outbound 配置 → Node[]。"""

from __future__ import annotations

import json

from converter._util import console
from converter.models import Node, normalize_protocol


class XrayParser:
    ptype = "xray"

    @staticmethod
    def parse_config(text: str, source: str = "") -> list[Node]:
        try:
            config = json.loads(text)
        except json.JSONDecodeError as e:
            console.print(f"  [red]✗ xray JSON 解析失败: {e}[/red]")
            return []

        nodes: list[Node] = []
        for outbound in config.get("outbounds", []):
            node = _outbound_to_node(outbound, source)
            if node is not None:
                nodes.append(node)
        return nodes


def _outbound_to_node(outbound: dict, source: str) -> Node | None:
    """xray outbound dict → 内部 Node。仅处理 vless / vmess / shadowsocks 三种。"""
    protocol = str(outbound.get("protocol", "")).lower()
    settings = outbound.get("settings", {})
    stream = outbound.get("streamSettings", {})

    if protocol == "vless":
        vnext = settings.get("vnext") or []
        if not vnext:
            return None
        v = vnext[0]
        user = (v.get("users") or [{}])[0]
        try:
            host = str(v.get("address", ""))
            port = int(v.get("port", 0))
        except (TypeError, ValueError):
            return None
        if not (host and port):
            return None
        node = Node(
            protocol="vless",
            host=host,
            port=port,
            uuid=str(user.get("id", "")),
            source=source,
        )

    elif protocol == "vmess":
        vnext = settings.get("vnext") or []
        if not vnext:
            return None
        v = vnext[0]
        user = (v.get("users") or [{}])[0]
        try:
            host = str(v.get("address", ""))
            port = int(v.get("port", 0))
        except (TypeError, ValueError):
            return None
        if not (host and port):
            return None
        node = Node(
            protocol="vmess",
            host=host,
            port=port,
            uuid=str(user.get("id", "")),
            alter_id=int(user.get("alterId") or 0),
            cipher=str(user.get("security") or "auto"),
            source=source,
        )

    elif protocol == "shadowsocks":
        servers = settings.get("servers") or []
        if not servers:
            return None
        s = servers[0]
        try:
            host = str(s.get("address", ""))
            port = int(s.get("port", 0))
        except (TypeError, ValueError):
            return None
        if not (host and port):
            return None
        cipher = str(s.get("method", ""))
        node = Node(
            protocol="ss",
            host=host,
            port=port,
            cipher=cipher.lower(),
            password=str(s.get("password", "")),
            cipher_2022=cipher.lower().startswith("2022-"),
            source=source,
        )

    else:
        return None

    # 公共：流层（transport / TLS / reality / flow）
    _apply_stream(node, stream)
    return node


def _apply_stream(node: Node, stream: dict) -> None:
    """把 xray streamSettings 投影到 IR 字段。"""
    net = str(stream.get("network", "tcp"))
    if net in ("ws", "grpc", "http", "splithttp", "xhttp", "httpupgrade"):
        node.transport = net

    sec = str(stream.get("security", ""))
    if sec == "tls":
        node.tls = True
        tls = stream.get("tlsSettings") or {}
        sni = str(tls.get("serverName") or "").strip()
        if sni:
            node.sni = sni
        fp = str(tls.get("fingerprint") or "").strip()
        if fp:
            node.fingerprint = fp
        alpn = tls.get("alpn") or []
        if alpn:
            node.alpn = [str(a) for a in alpn]
        if "allowInsecure" in tls:
            node.skip_cert_verify = bool(tls["allowInsecure"])
    elif sec == "reality":
        node.reality = True
        rs = stream.get("realitySettings") or {}
        node.reality_public_key = str(rs.get("publicKey", ""))
        node.reality_short_id = str(rs.get("shortId", ""))
        sni = str(rs.get("serverName") or "").strip()
        if sni:
            node.sni = sni
        fp = str(rs.get("fingerprint") or "").strip()
        if fp:
            node.fingerprint = fp

    # transport-specific
    if net == "ws":
        ws = stream.get("wsSettings") or {}
        node.path = str(ws.get("path") or "/")
        host = (ws.get("headers") or {}).get("Host")
        if host:
            node.host_headers = [str(host)]
    elif net == "grpc":
        grpc = stream.get("grpcSettings") or {}
        node.service_name = str(grpc.get("serviceName") or "")
    elif net == "http":
        h2 = stream.get("httpSettings") or {}
        node.path = str(h2.get("path") or "/")
        hosts = h2.get("host") or []
        if hosts:
            node.host_headers = [str(h) for h in hosts]
    elif net in ("splithttp", "xhttp"):
        s = stream.get(f"{net}Settings") or {}
        node.path = str(s.get("path") or "/")
        host = s.get("host")
        if host:
            node.host_headers = [str(host)]
        if s.get("mode"):
            node.transport_mode = str(s["mode"])
    elif net == "httpupgrade":
        s = stream.get("httpupgradeSettings") or {}
        node.path = str(s.get("path") or "")
        host = s.get("host")
        if host:
            node.host_headers = [str(host)]


__all__ = ["XrayParser"]
