import sys
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import base64
import json
from urllib.parse import quote

import yaml

from pac.nodes import Node, normalize_protocol
from pac.util import console


def build_vless_link(config: dict, remark: str = "TMP") -> str:
    """生成vless分享链接（clash proxy 格式）"""
    protocol = config["type"]
    server = config["server"]
    port = config["port"]
    uuid = config["uuid"]

    # query paramaters of shared link
    query = f"flow={config.get('flow', '')}"

    # 传输协议 (network)type: ws / tcp
    network = config.get("network", "tcp")
    query += f"&type={network}"

    if network == "ws":
        ws_opts = config.get("ws-opts", {})
        host = ws_opts.get("headers", {}).get("Host", "")
        path = ws_opts.get("path", "/")
        query += f"&host={host}&path={path}"

    elif network == "grpc":
        grpc_opts = config.get("grpc-opts", {})
        serviceName = grpc_opts.get("grpc-service-name", "")
        query += f"&serviceName={serviceName}"

    # 传输层安全:  tls reality
    if config.get("reality-opts"):
        query += "&security=reality"
        public_key = config["reality-opts"].get("public-key", "")
        short_id = config["reality-opts"].get("short-id", "")
        query += f"&pbk={public_key}&sid={short_id}"
    elif config.get("tls"):
        query += "&security=tls"

    servername = config.get("servername", "")
    fingerprint = config.get("client-fingerprint", "")
    query += f"&sni={servername}&fp={fingerprint}"

    # 如果 server 是 IPv6 地址，则需要加上中括号
    server = f"[{server}]" if ":" in server else server
    url = f"{protocol}://{uuid}@{server}:{port}?{query}#{remark}"
    return url


def build_vmess_link(config: dict, remark: str = "TMP") -> str:
    """生成vmess分享链接（clash proxy 格式）"""
    vmess_dict = {
        "v": "2",
        "ps": remark,
        "add": config["server"],
        "port": config["port"],
        "id": config["uuid"],
        "aid": config.get("alterId", 0),
        "scy": config.get("cipher", "auto"),
        "net": config.get("network", "tcp"),
        "type": "none",
    }

    if config.get("network") == "ws":
        ws_opts = config.get("ws-opts", {})
        vmess_dict["host"] = ws_opts.get("headers", {}).get("Host", "")
        vmess_dict["path"] = ws_opts.get("path", "/")

    elif config.get("network") == "httpupgrade":
        hu_opts = config.get("httpupgrade-opts", {})
        vmess_dict["host"] = hu_opts.get("host", "")
        vmess_dict["path"] = hu_opts.get("path", "/")

    if config.get("tls"):
        vmess_dict.update(
            {
                "tls": "tls",
                "sni": config.get("servername", ""),
                "alpn": "",
                "fp": "chrome",
            }
        )

    text = json.dumps(vmess_dict)
    id = base64.urlsafe_b64encode(text.encode()).decode()
    return f"vmess://{id}"


def build_shadowsocks_link(config: dict, remark: str = "TMP") -> str:
    """生成shadowsocks分享链接（clash proxy 格式）"""
    # ss://base64(method:password)@server:port#remark
    text = f"{config['cipher']}:{config['password']}"
    userinfo = base64.urlsafe_b64encode(text.encode()).decode()
    url = f"ss://{userinfo}@{config['server']}:{config['port']}#{remark}"
    return url


def build_trojan_link(config: dict, remark: str = "TMP") -> str:
    """生成trojan分享链接（clash proxy 格式）"""
    # trojan://password@server:port?sni=xx&type=ws#remark
    password = quote(str(config["password"]), safe="")
    server = config["server"]
    port = config["port"]

    params = []
    if config.get("sni"):
        params.append(f"sni={config['sni']}")
    if config.get("skip-cert-verify"):
        params.append("allowInsecure=1")

    network = config.get("network")
    if network:
        params.append(f"type={network}")
        if network == "ws":
            ws_opts = config.get("ws-opts", {})
            host = ws_opts.get("headers", {}).get("Host", "")
            path = ws_opts.get("path", "/")
            params.append(f"host={host}&path={path}")
        elif network == "grpc":
            grpc_opts = config.get("grpc-opts", {})
            params.append(f"serviceName={grpc_opts.get('grpc-service-name', '')}")

    param_str = f"?{'&'.join(params)}" if params else ""
    url = f"trojan://{password}@{server}:{port}{param_str}#{remark}"
    return url


def build_tuic_link(config: dict, remark: str = "TMP") -> str:
    """生成tuic分享链接（clash proxy 格式）"""
    # TUIC 分享链接格式: tuic://uuid:password@server:port?参数#备注
    uuid = config["uuid"]
    password = quote(str(config["password"]), safe="")
    server = config["server"]
    port = config["port"]

    params = []
    if config.get("sni"):
        params.append(f"sni={config['sni']}")
    if alpn := config.get("alpn"):
        params.append(f"alpn={','.join(alpn)}")
    if config.get("skip-cert-verify"):
        params.append(f"allowInsecure={1 if config['skip-cert-verify'] else 0}")
    if config.get("congestion-controller"):
        params.append(f"congestion_control={config['congestion-controller']}")

    param_str = f"?{'&'.join(params)}" if params else ""
    server = f"[{server}]" if ":" in server else server
    return f"tuic://{uuid}:{password}@{server}:{port}{param_str}#{remark}"


def build_hysteria2_link(config: dict, remark: str = "TMP") -> str:
    """生成hysteria2分享链接（clash proxy 格式）"""
    auth = config.get("password") or config.get("auth") or config.get("auth-str", "")
    auth_str = quote(str(auth), safe="")
    server = config["server"]
    port = config["port"]

    params = []
    if config.get("sni"):
        params.append(f"sni={config['sni']}")
    if config.get("skip-cert-verify"):
        params.append(f"allowInsecure={1 if config['skip-cert-verify'] else 0}")

    param_str = f"?{'&'.join(params)}" if params else ""
    server = f"[{server}]" if ":" in server else server
    return f"hysteria2://{auth_str}@{server}:{port}{param_str}#{remark}"


def build_anytls_link(config: dict, remark: str = "TMP") -> str:
    """生成anytls分享链接（clash proxy 格式）"""
    server = config["server"]
    port = config["port"]
    password = quote(str(config["password"]), safe="")

    params = []
    if fp := config.get("client-fingerprint"):
        params.append(f"fp={fp}")
    if alpn := config.get("alpn"):
        params.append(f"alpn={','.join(alpn)}")
    if cv := config.get("skip-cert-verify"):
        params.append(f"allowInsecure={1 if cv else 0}")

    param_str = f"?{'&'.join(params)}" if params else ""
    server = f"[{server}]" if ":" in server else server
    return f"anytls://{password}@{server}:{port}{param_str}#{remark}"


# clash/mihomo type → 分享链接 builder（hysteria v1 无 v2rayN 链接，仅原生 clash_proxy）
protocol_map = {
    "vless": build_vless_link,
    "vmess": build_vmess_link,
    "ss": build_shadowsocks_link,
    "shadowsocks": build_shadowsocks_link,
    "trojan": build_trojan_link,
    "hysteria2": build_hysteria2_link,
    "tuic": build_tuic_link,
    "anytls": build_anytls_link,
}


def _credential(proxy: dict) -> str:
    """clash proxy 的身份凭据（用于去重键）。"""
    for field in ("uuid", "password", "auth-str", "auth"):
        if field in proxy:
            return str(proxy[field])
    return ""


def parse_config(text: str, source: str = "") -> list[Node]:
    """解析 clash 配置文本 → 节点列表（提取全部 proxies，原生 dict 直通 clash 订阅）。"""
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
        protocol = str(proxy.get("type", "")).lower()
        # clash 原生 proxy dict 直通 mihomo 订阅，避免转换损失
        link = ""
        builder = protocol_map.get(protocol)
        if builder is not None:
            try:
                link = builder(proxy)
            except Exception as e:
                console.print(f"  [yellow]⚠ clash {protocol} 链接构建失败: {e}[/yellow]")
        try:
            port = int(proxy.get("port", 0))
        except (TypeError, ValueError):
            continue
        nodes.append(
            Node(
                protocol=normalize_protocol(protocol),
                host=str(proxy.get("server", "")),
                port=port,
                credential=_credential(proxy),
                source=source,
                link=link,
                clash_proxy=dict(proxy),
            )
        )
    return nodes
