"""clash / mihomo proxies 配置 → Node[]。"""

from __future__ import annotations

import yaml

from converter._util import console
from converter.models import Node, normalize_protocol


class ClashParser:
    ptype = "clash"

    @staticmethod
    def parse_config(text: str, source: str = "") -> list[Node]:
        try:
            config = yaml.safe_load(text)
        except yaml.YAMLError as e:
            console.print(f"  [red]✗ clash YAML 解析失败: {e}[/red]")
            return []
        if not config or "proxies" not in config:
            console.print("  [yellow]⚠[/yellow] 无 proxies 字段")
            return []

        nodes: list[Node] = []
        for proxy in config["proxies"]:
            node = _proxy_to_node(proxy, source)
            if node is not None:
                nodes.append(node)
        return nodes


def _credential(proxy: dict) -> str:
    """mihomo proxy dict → 身份凭据。"""
    for field in ("uuid", "password", "auth-str", "auth"):
        if field in proxy:
            return str(proxy[field])
    return ""


def _proxy_to_node(proxy: dict, source: str) -> Node | None:
    """mihomo proxy dict → Node。覆盖 CLASH_PROTOCOLS 全部 12 种。"""
    protocol = normalize_protocol(str(proxy.get("type", "")))
    try:
        port = int(proxy.get("port", 0))
    except (TypeError, ValueError):
        return None
    host = str(proxy.get("server", "")).strip()
    if not (host and port):
        return None

    # clash dict 不在 mihomo 协议层有"credential"统一字段；用 _credential() 仅在 health key 派生时需要
    node = Node(
        protocol=protocol,
        host=host,
        port=port,
        source=source,
    )

    if protocol in ("vmess", "vless"):
        node.uuid = str(proxy.get("uuid", ""))
        if protocol == "vmess":
            node.alter_id = int(proxy.get("alterId") or 0)
            node.cipher = str(proxy.get("cipher") or "auto")

    elif protocol == "ss":
        node.cipher = str(proxy.get("cipher", "")).lower()
        node.cipher_2022 = node.cipher.startswith("2022-")
        node.password = str(proxy.get("password", ""))

    elif protocol in ("trojan", "hysteria2", "anytls"):
        node.password = str(proxy.get("password", ""))

    elif protocol in ("tuic", "juicity"):
        node.uuid = str(proxy.get("uuid", ""))
        node.password = str(proxy.get("password", ""))
        node.congestion_controller = str(proxy.get("congestion-controller") or "bbr")

    elif protocol == "hysteria1":
        node.auth_str = str(proxy.get("auth-str") or proxy.get("auth_str") or "")
        node.hy1_protocol = str(proxy.get("protocol") or "udp")
        node.up_mbps = str(proxy.get("up") or "30")
        node.down_mbps = str(proxy.get("down") or "30")

    elif protocol == "mieru":
        node.username = str(proxy.get("username", ""))
        node.password = str(proxy.get("password", ""))
        node.multiplexing = str(proxy.get("multiplexing") or "MULTIPLEXING_LOW")
        if "port-range" in proxy:
            node.port_range = str(proxy["port-range"])
        # mieru transport
        mtrans = str(proxy.get("transport", "")).upper()
        if mtrans in ("TCP", "UDP"):
            node.transport = "tcp"
            node.extra_params["mieru_transport"] = mtrans

    elif protocol == "shadowquic":
        node.username = str(proxy.get("username", ""))
        node.password = str(proxy.get("password", ""))
        node.congestion_controller = str(proxy.get("congestion-controller") or "cubic")
        if "zero-rtt" in proxy:
            node.zero_rtt = bool(proxy["zero-rtt"])

    elif protocol == "naive":
        node.username = str(proxy.get("username", ""))
        node.password = str(proxy.get("password", ""))

    # 公共：transport / TLS / reality / flow
    _apply_transport(node, proxy)
    _apply_tls(node, proxy)
    return node


def _apply_transport(node: Node, proxy: dict) -> None:
    """transport / 传输选项。"""
    net = str(proxy.get("network", "tcp"))
    if net in ("ws", "grpc", "http", "splithttp", "xhttp", "httpupgrade"):
        node.transport = net

    if net == "ws":
        opts = proxy.get("ws-opts") or {}
        node.path = str(opts.get("path") or "/")
        host = (opts.get("headers") or {}).get("Host")
        if host:
            node.host_headers = [str(host)]
    elif net == "grpc":
        opts = proxy.get("grpc-opts") or {}
        node.service_name = str(opts.get("grpc-service-name") or "")
    elif net == "http":
        opts = proxy.get("h2-opts") or {}
        node.path = str(opts.get("path") or "/")
        hosts = opts.get("host") or []
        if hosts:
            node.host_headers = [str(h) for h in hosts]


def _apply_tls(node: Node, proxy: dict) -> None:
    """TLS / Reality / fingerprint / alpn 等。"""
    if proxy.get("reality-opts"):
        node.reality = True
        ro = proxy["reality-opts"]
        node.reality_public_key = str(ro.get("public-key") or ro.get("publicKey") or "")
        node.reality_short_id = str(ro.get("short-id") or ro.get("shortId") or "")

    sni = proxy.get("servername") or proxy.get("sni")
    if sni:
        node.sni = str(sni)

    if proxy.get("tls") or node.reality:
        node.tls = True

    fp = proxy.get("client-fingerprint") or proxy.get("fingerprint")
    if fp:
        node.fingerprint = str(fp)

    alpn = proxy.get("alpn")
    if isinstance(alpn, list):
        node.alpn = [str(a) for a in alpn]
    elif isinstance(alpn, str) and alpn:
        node.alpn = [a for a in alpn.split(",") if a]

    if proxy.get("skip-cert-verify"):
        node.skip_cert_verify = True

    if proxy.get("flow"):
        node.flow = str(proxy["flow"])


__all__ = ["ClashParser"]
