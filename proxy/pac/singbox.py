import sys
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import re

from pac.nodes import Node, normalize_protocol
from pac.util import console


def _fix_duplicated_json(text: str) -> str:
    """处理上游配置意外拼接两份 JSON 的情况（取第一份）。"""
    if re.search(r"}\s+{", text):
        console.print("  [yellow]⚠[/yellow] 配置重复，取第一份")
        first = re.split(r"}\s+{", text)[0]
        return first + "}"
    return text


def build_vless_link(proxy: dict, remark: str = "TMP") -> str:
    """生成vless分享链接（singbox outbound 格式）"""
    uuid = proxy["uuid"]
    server = proxy["server"]
    port = proxy["server_port"]

    params = []
    if tls := proxy.get("tls"):
        params.append("security=tls")
        sni = tls.get("server_name", "")
        params.append(f"sni={sni}")
        utls = tls.get("utls", {})
        fingerprint = utls.get("fingerprint", "chrome")
        params.append(f"fp={fingerprint}")
        reality = tls.get("reality", {})
        if reality.get("enabled", False):
            params.append("security=reality")
            params.append(f"pbk={reality.get('public_key', '')}")
            params.append(f"sid={reality.get('short_id', '')}")

    if transport := proxy.get("transport"):
        t_type = transport.get("type", "")
        if t_type:
            params.append(f"type={t_type}")
        if t_type == "ws":
            params.append(f"path={transport.get('path', '/')}")
            headers = transport.get("headers", {})
            if host := headers.get("Host", ""):
                params.append(f"host={host}")
        elif t_type == "grpc":
            params.append(f"serviceName={transport.get('service_name', '')}")

    param_str = f"?{'&'.join(params)}" if params else ""
    url = f"vless://{uuid}@{server}:{port}{param_str}#{remark}"
    return url


def _hysteria1_clash_proxy(proxy: dict) -> dict:
    """singbox hysteria(v1) outbound → mihomo 原生 proxy dict。"""
    tls = proxy.get("tls", {})
    return {
        "type": "hysteria",
        "server": proxy["server"],
        "port": int(proxy["server_port"]),
        "auth-str": proxy.get("auth_str", ""),
        "protocol": proxy.get("network", "udp"),
        "up": proxy.get("up_mbps", 30),
        "down": proxy.get("down_mbps", 30),
        "sni": tls.get("server_name", ""),
        "skip-cert-verify": tls.get("insecure", False),
        "alpn": tls.get("alpn", ["h3"]),
    }


def parse_config(text: str, source: str = "") -> list[Node]:
    """解析 singbox 配置文本 → 节点列表（提取全部代理 outbound）。"""
    try:
        config = json.loads(_fix_duplicated_json(text))
    except json.JSONDecodeError as e:
        console.print(f"  [red]✗ singbox JSON 解析失败: {e}[/red]")
        return []

    nodes: list[Node] = []
    for outbound in config.get("outbounds", []):
        protocol = str(outbound.get("type", "")).lower()
        host = outbound.get("server")
        port = outbound.get("server_port")
        if not host or not port:
            continue

        try:
            if protocol == "vless":
                link = build_vless_link(outbound)
                credential = str(outbound.get("uuid", ""))
                clash_proxy = None
            elif protocol == "hysteria":
                # singbox "hysteria" 是 v1：无 v2rayN 链接，原生映射进 clash 订阅
                link = ""
                credential = str(outbound.get("auth_str", ""))
                clash_proxy = _hysteria1_clash_proxy(outbound)
            else:
                console.print(f"  [dim]singbox 跳过不支持的 outbound 类型: {protocol}[/dim]")
                continue
        except Exception as e:
            console.print(f"  [yellow]⚠ singbox {protocol} 节点解析失败: {e}[/yellow]")
            continue

        nodes.append(
            Node(
                protocol=normalize_protocol(protocol),
                host=str(host),
                port=int(port),
                credential=credential,
                source=source,
                link=link,
                clash_proxy=clash_proxy,
            )
        )
    return nodes
