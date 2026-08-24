import sys
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import base64
import json

from pac.nodes import Node, normalize_protocol
from pac.util import console

postfix = "xray"


def build_vless_link(config: dict, remark: str = "TMP") -> str:
    """生成vless分享链接（xray outbound 格式）"""
    protocol = config["protocol"]
    settings = config["settings"]
    vnext = settings["vnext"][0]

    address = vnext["address"]
    port = vnext["port"]
    user = vnext["users"][0]
    user_id = user["id"]

    encryption = f"encryption={user['encryption']}"
    flow = f"flow={user.get('flow', '')}"
    # query paramaters of shared link
    query = f"{encryption}&{flow}"

    # streamSettings
    streamSettings = config["streamSettings"]

    # 传输协议 type: ws / tcp
    network = streamSettings["network"]
    query += f"&type={network}"

    if network == "ws":
        wsSettings = streamSettings["wsSettings"]
        path = wsSettings["path"]
        host = wsSettings["headers"]["Host"]
        query += f"&host={host}&path={path}"

    elif network == "grpc":
        grpcSettings = streamSettings["grpcSettings"]
        serviceName = grpcSettings["serviceName"]
        query += f"&serviceName={serviceName}"

    elif network == "splithttp":
        splithttpSettings = streamSettings["splithttpSettings"]
        path = splithttpSettings["path"]
        host = splithttpSettings["host"]
        query += f"&host={host}&path={path}"

    elif network == "xhttp":
        xhttpSettings = streamSettings["xhttpSettings"]
        path = xhttpSettings.get("path", "/")
        host = xhttpSettings.get("host", "")
        query += f"&host={host}&path={path}"

    # 传输层安全:  security : tls reality
    security = streamSettings.get("security", "")
    if security:
        query += f"&security={security}"

    if security == "reality":
        realitySettings = streamSettings["realitySettings"]
        serverName = realitySettings["serverName"]
        fingerprint = realitySettings["fingerprint"]
        publicKey = realitySettings["publicKey"]
        shortId = realitySettings["shortId"]
        query += f"&sni={serverName}&fp={fingerprint}&pbk={publicKey}&sid={shortId}"

    elif security == "tls":
        tlsSettings = streamSettings["tlsSettings"]
        serverName = tlsSettings["serverName"]
        fingerprint = tlsSettings.get("fingerprint", "chrome")
        query += f"&sni={serverName}&fp={fingerprint}"

    address = f"[{address}]" if ":" in address and not address.startswith("[") else address
    url = f"{protocol}://{user_id}@{address}:{port}?{query}#{remark}"
    return url


def build_vmess_link(config: dict, remark: str = "TMP") -> str:
    """生成vmess分享链接（xray outbound 格式）"""
    protocol = config["protocol"]
    settings = config["settings"]
    vnext = settings["vnext"][0]
    address = vnext["address"]
    port = vnext["port"]
    user = vnext["users"][0]
    streamSettings = config["streamSettings"]

    vmess_dict = {
        "v": "2",
        "ps": remark,
        "add": address,
        "port": port,
        "id": user["id"],
        "aid": user["alterId"],
        "scy": user["security"],
        "net": streamSettings["network"],
        "type": "none",
    }

    if streamSettings["network"] == "ws":
        ws_info = {
            "net": "ws",
            "host": streamSettings["wsSettings"]["headers"].get("Host", ""),
            "path": streamSettings["wsSettings"]["path"],
        }
        vmess_dict.update(ws_info)

    elif streamSettings["network"] == "httpupgrade":
        httpupgrade_info = {
            "http": "",
            "host": streamSettings["httpupgradeSettings"]["host"],
            "path": streamSettings["httpupgradeSettings"]["path"],
        }
        vmess_dict.update(httpupgrade_info)

    if streamSettings.get("security") == "tls":
        tls_info = {
            "tls": "tls",
            "sni": streamSettings.get("tlsSettings")["serverName"],
            "alpn": "",
            "fp": "chrome",
        }
        vmess_dict.update(tls_info)

    text = json.dumps(vmess_dict)
    id = base64.urlsafe_b64encode(text.encode()).decode()

    url = f"{protocol}://{id}"
    return url


def build_shadowsocks_link(config: dict, remark: str = "TMP") -> str:
    """生成shadowsocks分享链接（xray outbound 格式）"""
    protocol = "ss"
    settings = config["settings"]
    server = settings["servers"][0]

    address = server["address"]
    port = server["port"]
    method = server["method"]
    password = server["password"]

    text = f"{method}:{password}"
    id = base64.urlsafe_b64encode(text.encode()).decode()
    url = f"{protocol}://{id}@{address}:{port}#{remark}"
    return url


protocol_map = {
    "vless": build_vless_link,
    "vmess": build_vmess_link,
    "shadowsocks": build_shadowsocks_link,
}


def _identity(outbound: dict) -> tuple[str, int, str] | None:
    """从 xray outbound 提取 (host, port, credential)。"""
    settings = outbound.get("settings", {})
    if "vnext" in settings:
        vnext = settings["vnext"][0]
        user = vnext["users"][0]
        return vnext["address"], int(vnext["port"]), str(user.get("id", ""))
    if "servers" in settings:
        server = settings["servers"][0]
        return server["address"], int(server["port"]), str(server.get("password", ""))
    return None


def parse_config(text: str, source: str = "") -> list[Node]:
    """解析 xray 配置文本 → 节点列表（提取全部代理 outbound）。"""
    try:
        config = json.loads(text)
    except json.JSONDecodeError as e:
        console.print(f"  [red]✗ xray JSON 解析失败: {e}[/red]")
        return []

    nodes: list[Node] = []
    for outbound in config.get("outbounds", []):
        protocol = outbound.get("protocol", "")
        builder = protocol_map.get(protocol)
        if builder is None:
            continue
        try:
            identity = _identity(outbound)
            if identity is None:
                continue
            host, port, cred = identity
            link = builder(outbound)
        except Exception as e:
            console.print(f"  [yellow]⚠ xray {protocol} 节点解析失败: {e}[/yellow]")
            continue
        nodes.append(
            Node(
                protocol=normalize_protocol(protocol),
                host=host,
                port=port,
                credential=cred,
                source=source,
                link=link,
            )
        )
    return nodes
