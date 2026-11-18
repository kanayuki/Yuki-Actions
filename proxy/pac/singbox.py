import sys
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json

from pac.nodes import Node, normalize_protocol
from pac.util import console


def _find_json_seams(text: str) -> list[tuple[int, int]]:
    """定位可能的多文档接缝（字符串字面量免疫）。"""
    seams: list[tuple[int, int]] = []
    in_str = False
    esc = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            i += 1
            continue
        if ch in "}]":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "{[":
                seams.append((i, j))
        i += 1
    return seams


def _extract_first_json(text: str) -> str:
    """文本意外拼接了多份 JSON（或尾随垃圾）时，截取第一份完整文档。"""
    text = text.strip().lstrip("\ufeff")
    decoder = json.JSONDecoder()
    try:
        end = decoder.raw_decode(text)[1]
    except json.JSONDecodeError:
        pass
    else:
        if end < len(text):
            return text[:end].rstrip()
        return text
    for _close_idx, open_idx in _find_json_seams(text):
        prefix = text[:open_idx].rstrip()
        for candidate in (prefix, prefix + "}", prefix + "]"):
            try:
                json.loads(candidate)
            except json.JSONDecodeError:
                continue
            return candidate
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
        "up": proxy.get("up_mbps", "30"),
        "down": proxy.get("down_mbps", "30"),
        "sni": tls.get("server_name", ""),
        "skip-cert-verify": tls.get("insecure", False),
        "alpn": tls.get("alpn", ["h3"]),
    }


def parse_config(text: str, source: str = "") -> list[Node]:
    """解析 singbox 配置文本 → 节点列表（提取全部代理 outbound）。"""
    fixed = _extract_first_json(text)
    if fixed != text:
        console.print("  [yellow]⚠[/yellow] 配置重复/尾随垃圾，取第一份")
    try:
        config = json.loads(fixed)
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
