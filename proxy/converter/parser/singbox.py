"""sing-box outbounds 配置 → Node[]。"""

from __future__ import annotations

import json

from converter._util import console, extract_first_json
from converter.models import Node, normalize_protocol


class SingboxParser:
    ptype = "singbox"

    @staticmethod
    def parse_config(text: str, source: str = "") -> list[Node]:
        fixed = extract_first_json(text)
        if fixed != text:
            console.print("  [yellow]⚠[/yellow] 配置重复/尾随垃圾，取第一份")
        try:
            config = json.loads(fixed)
        except json.JSONDecodeError as e:
            console.print(f"  [red]✗ singbox JSON 解析失败: {e}[/red]")
            return []

        nodes: list[Node] = []
        for outbound in config.get("outbounds", []):
            node = _outbound_to_node(outbound, source)
            if node is not None:
                nodes.append(node)
        return nodes


def _outbound_to_node(outbound: dict, source: str) -> Node | None:
    """sing-box outbound dict → Node。本轮覆盖 vless / hysteria (v1) 两种。"""
    protocol = normalize_protocol(str(outbound.get("type", "")))
    host = outbound.get("server")
    port = outbound.get("server_port")
    if not host or not port:
        return None
    try:
        port = int(port)
    except (TypeError, ValueError):
        return None

    if protocol == "vless":
        node = Node(
            protocol="vless",
            host=str(host),
            port=port,
            uuid=str(outbound.get("uuid", "")),
            source=source,
        )
    elif protocol == "hysteria1":
        # singbox "hysteria" 是 v1：无 v2rayN 链接，仅映射进 clash 订阅
        node = Node(
            protocol="hysteria1",
            host=str(host),
            port=port,
            auth_str=str(outbound.get("auth_str", "")),
            hy1_protocol=str(outbound.get("network", "udp")),
            up_mbps=str(outbound.get("up_mbps", "30")),
            down_mbps=str(outbound.get("down_mbps", "30")),
            source=source,
        )
    else:
        console.print(f"  [dim]singbox 跳过不支持的 outbound 类型: {protocol}[/dim]")
        return None

    # 公共：TLS / transport / flow
    _apply_tls(node, outbound)
    _apply_transport(node, outbound)
    if outbound.get("flow"):
        node.flow = str(outbound["flow"])
    return node


def _apply_tls(node: Node, outbound: dict) -> None:
    tls = outbound.get("tls")
    if not tls or not isinstance(tls, dict):
        return
    if not tls.get("enabled", True):
        return
    node.tls = True
    sni = str(tls.get("server_name") or "").strip()
    if sni:
        node.sni = sni
    alpn = tls.get("alpn")
    if isinstance(alpn, list):
        node.alpn = [str(a) for a in alpn]
    if "insecure" in tls:
        node.skip_cert_verify = bool(tls["insecure"])
    utls = tls.get("utls") or {}
    if isinstance(utls, dict) and utls.get("fingerprint"):
        node.fingerprint = str(utls["fingerprint"])
    reality = tls.get("reality") or {}
    if isinstance(reality, dict) and reality.get("enabled"):
        node.reality = True
        node.reality_public_key = str(reality.get("public_key", ""))
        node.reality_short_id = str(reality.get("short_id", ""))


def _apply_transport(node: Node, outbound: dict) -> None:
    transport = outbound.get("transport")
    if not transport or not isinstance(transport, dict):
        return
    t_type = str(transport.get("type", ""))
    if t_type in ("ws", "grpc", "http", "splithttp", "xhttp", "httpupgrade"):
        node.transport = t_type
    if t_type == "ws":
        node.path = str(transport.get("path") or "/")
        host = (transport.get("headers") or {}).get("Host")
        if host:
            node.host_headers = [str(host)]
    elif t_type == "grpc":
        node.service_name = str(transport.get("service_name") or "")
    elif t_type == "http":
        node.path = str(transport.get("path") or "/")
        hosts = transport.get("host") or []
        if hosts:
            node.host_headers = [str(h) for h in hosts]
    elif t_type in ("splithttp", "xhttp"):
        node.path = str(transport.get("path") or "/")
        host = transport.get("host")
        if host:
            node.host_headers = [str(host)]
        if transport.get("mode"):
            node.transport_mode = str(transport["mode"])


__all__ = ["SingboxParser"]
