import sys
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


CONFIG_FILE = Path(__file__).parent / "singbox_config_links.txt"


postfix = "singbox"


def build_hysteria_link(proxy: str) -> tuple:
    """生成hysteria分享链接"""
    # {
    #   "type": "hysteria",
    #   "tag": "dongtaiwang.com",
    #   "server": "195.154.200.178",
    #   "server_port": 46938,
    #   "up_mbps": 11,
    #   "down_mbps": 55,
    #   "auth_str": "dongtaiwang.com",
    #   "tls": {
    #     "enabled": true,
    #     "insecure": true,
    #     "server_name": "apple.com",
    #     "alpn": [
    #       "h3"
    #     ]
    #   }
    # }

    # 提取必要字段
    type = proxy["type"].lower()
    tag = proxy["tag"]
    server = proxy["server"]
    port = proxy["server_port"]
    auth_str = quote(proxy["auth_str"], safe="")

    # 可选参数
    params = []
    if tls := proxy.get("tls"):
        sni = tls.get("server_name", "")
        params.append(f"sni={sni}")
        insecure = tls.get("insecure", True)
        params.append(f"insecure={'1' if insecure else '0'}")

        alpn = proxy.get("alpn", [])  # 将数组转为逗号分隔的字符串
        params.append(f"alpn={','.join(alpn)}")

    # 构建参数部分
    param_str = "&".join(params)
    param_str = f"?{param_str}" if param_str else ""

    remark = gen_remark(server, postfix)

    # 生成 Hysteria 分享链接
    hysteria_link = f"hysteria2://{auth_str}@{server}:{port}{param_str}#{remark}"
    return hysteria_link


def build_vless_link(proxy: str) -> tuple:
    """生成vless分享链接"""
    # vless://ebfdccb6-7416-4b6e-860d-98587344d500@yh1.dtku41.xyz:443?
    # encryption=none&security=tls&sni=lg1.freessr2.xyz&fp=chrome&
    # type=ws&host=lg1.freessr2.xyz&path=%2Fxyakws#20240407

    {
        "type": "vless",
        "tag": "https://github.com/Alvin9999-newpac/fanqiang/wiki",
        "uuid": "d0b3e27d-bbfc-4a3b-8e60-6973de8fcefa",
        "packet_encoding": "xudp",
        "server": "157.254.223.44",
        "server_port": 18959,
        "flow": "",
        "tls": {
            "enabled": True,
            "server_name": "itunes.apple.com",
            "utls": {"enabled": True, "fingerprint": "chrome"},
            "reality": {
                "enabled": True,
                "public_key": "-hwVEdgFkvjku8ESuDoAA7id5yGGv_zXBvBW_RdhmHA",
                "short_id": "d557c6895d014075",
            },
        },
    }

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
            public_key = reality.get("public_key", "")
            params.append(f"pbk={public_key}")
            short_id = reality.get("short_id", "")
            params.append(f"sid={short_id}")

    param_str = "&".join(params)
    param_str = f"?{param_str}" or ""

    remark = gen_remark(server, postfix)
    url = f"vless://{uuid}@{server}:{port}{param_str}#{remark}"
    return url


protocol_map = {
    "hysteria": build_hysteria_link,
    "vless": build_vless_link,
}


def build_link(config: dict) -> str | None:
    """生成分享链接 vless, vmess, shadowsocks, trojan, hysteria, tuic"""

    # 提取第一个 proxy
    proxy = config["outbounds"][0]

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

    # NOTE: 临时处理配置重复:{}/n{}，后续需要根据实际情况调整
    import re

    if re.search(r"}\s+{", config):
        console.print(f"[yellow]⚠[/yellow] 配置重复，取第一个")

        lst = re.split(r"}\s+{", config)

        # NOTE: 20260814, 这里两个JSON配置一样，取第一个
        config = lst[0] + "}}"

    try:
        config = json.loads(config)
    except json.JSONDecodeError as e:
        print(f"Error loading JSON: {e}")
        return None

    link = build_link(config)
    # print(f"clash 分享链接：{link}")
    return link


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
    save_links(links, label="singbox")
