import sys
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import base64
import json
from urllib.parse import quote

import yaml
from pac.util import (
    arrange_links,
    console,
    gen_remark,
    get_config,
    load_all_config,
    save_links,
)

CONFIG_FILE = Path(__file__).parent / "clash_config_links.txt"


postfix = "clash"


def build_vless_link(config) -> tuple[str, str]:
    """生成vless分享链接"""
    # vless://ebfdccb6-7416-4b6e-860d-98587344d500@yh1.dtku41.xyz:443?
    # encryption=none&security=tls&sni=lg1.freessr2.xyz&fp=chrome&
    # type=ws&host=lg1.freessr2.xyz&path=%2Fxyakws#20240407

    name = config["name"]
    protocol = config["type"]
    server = config["server"]
    port = config["port"]
    uuid = config["uuid"]
    udp = config["udp"]

    flow = config["flow"]

    # query paramaters of shared link
    query = f"flow={flow}"

    # encryption=none&flow=xtls-rprx-vision
    # &type=tcp&headerType=none
    # 传输协议 (network)type: ws / tcp
    network = config["network"]
    query += f"&type={network}"

    if network == "tcp":
        pass

    elif network == "ws":
        # network = ws (type)
        # wsSettings = streamSettings['wsSettings']
        # path = wsSettings['path']
        # host = wsSettings['headers']['Host']

        # query += f"&host={host}&path={path}"
        pass

    elif network == "tcp":
        pass

    elif network == "splithttp":
        # splithttpSettings = streamSettings['splithttpSettings']
        # path = splithttpSettings['path']
        # host = splithttpSettings['host']
        # # maxUploadSize = splithttpSettings['maxUploadSize']
        # # maxConcurrentUploads = splithttpSettings['maxConcurrentUploads']

        # query += f"&host={host}&path={path}"
        pass

    elif network == "grpc":
        grpc_opts = config["grpc-opts"]
        serviceName = grpc_opts["grpc-service-name"]
        # multiMode = grpcSettings['multiMode']
        query += f"&serviceName={serviceName}"
        pass
    # &security=reality&sni=www.yahoo.com&fp=chrome
    # &pbk=U5hsLybYWhJrWAqqsTa052k-VeKt8bDFPxBh3CQk51M&sid=0b4badde

    # 传输层安全:  tls reality
    # if tls := config['tls']:

    #     query += f"&security={tls}"
    # allowInsecure = tlsSettings['allowInsecure']
    # alpn = tlsSettings['alpn']

    # reality
    if reality_opts := config["reality-opts"]:
        query += f"&security=reality"
        public_key = reality_opts["public-key"]
        short_id = reality_opts["short-id"]
        query += f"&pbk={public_key}&sid={short_id}"

    servername = config["servername"]
    fingerprint = config["client-fingerprint"]
    query += f"&sni={servername}&fp={fingerprint}"

    remark = gen_remark(server, postfix)
    # 如果 server 是 IPv6 地址，则需要加上中括号
    server = f"[{server}]" if ":" in server else server
    url = f"{protocol}://{uuid}@{server}:{port}?{query}#{remark}"
    return url


def build_vmess_link(config) -> str:
    """生成vmess分享链接"""
    # {
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
            "host": streamSettings["wsSettings"]["headers"]["Host"],
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


def build_shadowsocks_link(config) -> str:
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


def build_trojan_link(config) -> str:
    """生成trojan分享链接"""
    # trojan://password@server:port#trojan_20240409
    protocol = config["protocol"]
    settings = config["settings"]
    server = settings["servers"][0]


def build_tuic_link(proxy) -> str:
    # TUIC 分享链接格式: tuic://uuid:password@server:port?参数#备注
    uuid = proxy["uuid"]
    password = proxy["password"]
    server = proxy["server"]
    port = proxy["port"]
    # name = proxy['name']
    name = gen_remark(server, postfix)

    # 可选参数
    params = []
    if proxy.get("sni"):
        params.append(f"sni={proxy['sni']}")
    if proxy.get("alpn"):
        alpn = ",".join(proxy["alpn"])  # 将数组转为逗号分隔的字符串
        params.append(f"alpn={alpn}")
    if proxy.get("skip-cert-verify"):
        params.append(f"allowInsecure={1 if proxy['skip-cert-verify'] else 0}")
    if proxy.get("congestion-controller"):
        params.append(f"congestion_control={proxy['congestion-controller']}")

    # 构建参数部分
    param_str = "&".join(params) if params else ""
    param_str = f"?{param_str}" if param_str else ""

    # 如果 server 是 IPv6 地址，则需要加上中括号
    server = f"[{server}]" if ":" in server else server

    # 生成 TUIC 分享链接
    tuic_link = f"tuic://{uuid}:{password}@{server}:{port}{param_str}#{name}"
    return tuic_link


def build_hysteria_link(proxy) -> str:
    """生成hysteria分享链接"""
    # 提取必要字段
    server = proxy["server"]
    port = proxy["port"]
    auth_str = quote(proxy["auth-str"], safe="")
    # name = proxy['name']
    name = gen_remark(server, postfix)

    # 可选参数
    params = []
    if proxy.get("protocol"):
        params.append(f"protocol={proxy['protocol']}")

    if proxy.get("sni"):
        params.append(f"sni={proxy['sni']}")
    if proxy.get("alpn"):
        alpn = ",".join(proxy["alpn"])  # 将数组转为逗号分隔的字符串
        params.append(f"alpn={alpn}")
    if proxy.get("skip-cert-verify"):
        # params.append(f"insecure={1 if proxy['skip-cert-verify'] else 0}")
        params.append(f"allowInsecure={1 if proxy['skip-cert-verify'] else 0}")

    # 构建参数部分
    param_str = "&".join(params)
    param_str = f"?{param_str}" if param_str else ""

    # 如果 server 是 IPv6 地址，则需要加上中括号
    server = f"[{server}]" if ":" in server else server

    # 生成 Hysteria 分享链接
    hysteria_link = f"hysteria2://{auth_str}@{server}:{port}{param_str}#{name}"
    return hysteria_link


def build_anytls_link(proxy: dict) -> str | None:
    """生成anytls分享链接"""
    # anytls://dongtaiwang.com@fan2.856098.xyz:8443?security=tls&alpn=h2%2Chttp%2F1.1&fp=chrome&allowInsecure=1&type=tcp#333333333333

    # 提取必要字段
    server = proxy["server"]
    port = proxy["port"]
    password = proxy["password"]
    # name = proxy['name']
    name = gen_remark(server, postfix)

    # 可选参数
    params = []
    # if proxy.get("protocol"):
    #     params.append(f"protocol={proxy['protocol']}")

    # if proxy.get("sni"):
    #     params.append(f"sni={proxy['sni']}")
    if fp := proxy.get("client-fingerprint"):
        params.append(f"fp={fp}")

    if alpn := proxy.get("alpn"):
        # 将数组转为逗号分隔的字符串
        params.append(f"alpn={','.join(alpn)}")

    if cv := proxy.get("skip-cert-verify"):
        params.append(f"allowInsecure={1 if cv else 0}")

    # 构建参数部分
    param_str = "&".join(params)
    param_str = f"?{param_str}" if param_str else ""

    # 如果 server 是 IPv6 地址，则需要加上中括号
    server = f"[{server}]" if ":" in server else server

    # 生成 anytls 分享链接
    anytls_link = f"anytls://{password}@{server}:{port}{param_str}#{name}"
    return anytls_link


protocol_map = {
    "vless": build_vless_link,
    "vmess": build_vmess_link,
    "shadowsocks": build_shadowsocks_link,
    "trojan": build_trojan_link,
    "hysteria": build_hysteria_link,
    "tuic": build_tuic_link,
    "anytls": build_anytls_link,
}


def build_link(config: dict) -> str | None:
    """构建分享链接 vless, vmess, shadowsocks, trojan, hysteria, tuic"""

    # 提取第一个 proxy
    proxy = config["proxies"][0]

    # 检查协议类型
    protocol = proxy["type"].lower()

    if protocol in protocol_map:
        url = protocol_map[protocol](proxy)
        console.print(f"[cyan]{url}[/cyan]")
        return url
    else:
        print(f"Unsupported protocol: {proxy}")

    return None


@load_all_config(CONFIG_FILE)
def get_all_links(config: str) -> str:
    """获取所有可能的配置文件的分享链接"""
    # print("获取所有clash配置的分享链接")

    res = build_link(yaml.safe_load(config))

    # print(f"clash 分享链接：{link}")
    return res


def test_vless():
    config = get_config(
        "https://www.gitlabip.xyz/Alvin9999/PAC/master/backup/img/1/2/ip/quick/4/config.yaml"
    )
    config = yaml.safe_load(config)
    print(config)
    link = build_link(config)
    print(link)


if __name__ == "__main__":
    links = get_all_links()
    arrange_links(links)
    save_links(links, label="clash")
