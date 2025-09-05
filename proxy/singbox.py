import json

import yaml
from util import arrange_links, gen_remark, get_config, load_all_config


postfix = "singbox"


def gen_hysteria_share_link(proxy: str) -> str:
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
    auth_str = proxy["auth_str"]

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

    # 输出结果
    # print("Hysteria2 分享链接:", hysteria_link)
    return hysteria_link


def gen_share_link(config: dict) -> str | None:
    """生成分享链接 vless, vmess, shadowsocks, trojan, hysteria, tuic"""

    protocol_map = {
        "hysteria": gen_hysteria_share_link,
    }

    # 提取第一个 proxy
    proxy = config["outbounds"][0]

    # 检查协议类型
    protocol = proxy["type"].lower()

    if protocol in protocol_map:
        url = protocol_map[protocol](proxy)
        print(f"{protocol} 分享链接: {url}")
        return url
    else:
        print(f"Unsupported protocol: {proxy}")

    return None


@load_all_config("./proxy/singbox_config_links.txt")
def get_all_links(config: str) -> str:
    """获取所有可能的配置文件的分享链接"""
    # print("获取所有clash配置的分享链接")

    link = gen_share_link(json.loads(config))
    # print(f"clash 分享链接：{link}")
    return link


def test_vless():
    config = get_config(
        "https://www.gitlabip.xyz/Alvin9999/PAC/master/backup/img/1/2/ip/quick/4/config.yaml"
    )
    config = yaml.safe_load(config)
    print(config)
    link = gen_share_link(config)
    print(link)


if __name__ == "__main__":

    arrange_links(get_all_links())

    # test_vless()
