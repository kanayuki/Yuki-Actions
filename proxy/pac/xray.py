import sys
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import base64
import json

from pac.util import arrange_links, console, gen_remark, load_all_config, save_links


CONFIG_FILE = Path(__file__).parent / "xray_config_links.txt"

postfix = "xray"


def build_vless_link(config) -> tuple:
    """生成vless分享链接"""
    # vless://ebfdccb6-7416-4b6e-860d-98587344d500@yh1.dtku41.xyz:443?
    # encryption=none&security=tls&sni=lg1.freessr2.xyz&fp=chrome&
    # type=ws&host=lg1.freessr2.xyz&path=%2Fxyakws#20240407
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
        # network = ws (type)
        wsSettings = streamSettings["wsSettings"]
        path = wsSettings["path"]
        host = wsSettings["headers"]["Host"]

        query += f"&host={host}&path={path}"

    elif network == "grpc":
        grpcSettings = streamSettings["grpcSettings"]
        serviceName = grpcSettings["serviceName"]
        # multiMode = grpcSettings['multiMode']
        query += f"&serviceName={serviceName}"

    elif network == "tcp":
        pass

    elif network == "splithttp":
        splithttpSettings = streamSettings["splithttpSettings"]
        path = splithttpSettings["path"]
        host = splithttpSettings["host"]
        # maxUploadSize = splithttpSettings['maxUploadSize']
        # maxConcurrentUploads = splithttpSettings['maxConcurrentUploads']

        query += f"&host={host}&path={path}"

    elif network == "xhttp":
        xhttpSettings = streamSettings["xhttpSettings"]
        path = xhttpSettings.get("path", "/")
        host = xhttpSettings.get("host", "")
        query += f"&host={host}&path={path}"

    # 传输层安全:  security : tls reality
    security = streamSettings["security"]
    query += f"&security={security}"

    if security == "reality":
        # encryption=none&flow=xtls-rprx-vision&security=reality&sni=www.yahoo.com&fp=chrome&pbk=U5hsLybYWhJrWAqqsTa052k-VeKt8bDFPxBh3CQk51M&sid=0b4badde&type=tcp&headerType=none
        realitySettings = streamSettings["realitySettings"]
        serverName = realitySettings["serverName"]
        fingerprint = realitySettings["fingerprint"]
        # show=realitySettings['show']
        publicKey = realitySettings["publicKey"]
        shortId = realitySettings["shortId"]
        # spiderX=realitySettings['spiderX']

        query += f"&sni={serverName}&fp={fingerprint}&pbk={publicKey}&sid={shortId}"

    elif security == "tls":
        tlsSettings = streamSettings["tlsSettings"]
        serverName = tlsSettings["serverName"]
        fingerprint = tlsSettings.get("fingerprint", "chrome")
        # allowInsecure = tlsSettings['allowInsecure']

        query += f"&sni={serverName}&fp={fingerprint}"

    remark = gen_remark(address, postfix)
    address = (
        f"[{address}]" if ":" in address and not address.startswith("[") else address
    )
    url = f"{protocol}://{user_id}@{address}:{port}?{query}#{remark}"
    return url


def build_vmess_link(config) -> tuple:
    """生成vmess分享链接"""
    #     {
    #   "v": "2",
    #   "ps": "vmess_20241002",
    #   "add": "104.21.238.112",
    #   "port": "443",
    #   "id": "25d1b318-87e8-4c1e-a784-69783be4b30a",
    #   "aid": "0",
    #   "scy": "auto",
    #   "net": "ws",
    #   "type": "none",
    #   "host": "ip1.589643.xyz",
    #   "path": "dongtaiwang.com",
    #   "tls": "tls",
    #   "sni": "ip1.589643.xyz",
    #   "alpn": "",
    #   "fp": "chrome"
    # }
    # protocol = 'vmess'
    protocol = config["protocol"]
    settings = config["settings"]
    vnext = settings["vnext"][0]
    address = vnext["address"]
    port = vnext["port"]
    user = vnext["users"][0]
    streamSettings = config["streamSettings"]

    remark = gen_remark(address, postfix)

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


def build_shadowsocks_link(config) -> tuple:
    """生成shadowsocks分享链接"""
    # ss://MjAyMi1ibGFrZTMtYWVzLTI1Ni1nY206b2F0cys3dmRhU09iNE5zeFd3Q0JRbGw0cVR3UHUvZGhwZWdpSUducWQ5Yz0=
    # @www.dtku44.xyz:22335#shadowsocks_20240409
    # base64(2022-blake3-aes-256-gcm:oats+7vdaSOb4NsxWwCBQll4qTwPu/dhpegiIGnqd9c=)

    # protocol = config['protocol']
    protocol = "ss"
    settings = config["settings"]
    server = settings["servers"][0]

    address = server["address"]
    port = server["port"]
    method = server["method"]
    password = server["password"]

    # streamSettings
    # streamSettings = config['streamSettings']
    # network = streamSettings['network']  # tcp

    text = f"{method}:{password}"
    id = base64.urlsafe_b64encode(text.encode()).decode()
    remark = gen_remark(address, postfix)
    url = f"{protocol}://{id}@{address}:{port}#{remark}"
    return url


protocol_map = {
    "vless": build_vless_link,
    "vmess": build_vmess_link,
    "shadowsocks": build_shadowsocks_link,
}


def build_link(config: dict) -> str | None:
    """构建分享链接 vless, vmess, shadowsocks"""
    outbounds: list = config["outbounds"]
    proxy: dict = [item for item in outbounds if item["tag"] == "proxy"][0]

    protocol = proxy["protocol"]

    if protocol in protocol_map:
        url = protocol_map[protocol](proxy)
        console.print(f"[cyan]{url}[/cyan]")
        return url
    else:
        raise ValueError(f"Unsupported protocol: {proxy}")



@load_all_config(CONFIG_FILE)
def get_all_links(config: str) -> str:
    """获取所有可能的配置文件的分享链接"""

    try:
        return build_link(json.loads(config))
    except ValueError as e:
        console.print(f"[red]✗ {e}[/red]")
        return None


if __name__ == "__main__":
    links = get_all_links()
    arrange_links(links)
    save_links(links, label="xray")
