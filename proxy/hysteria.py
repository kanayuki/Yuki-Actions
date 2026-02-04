import json

from util import arrange_links, gen_remark, load_all_config, get_hash


postfix = "hysteria"


def gen_hysteria_share_link(config: dict) -> str:
    # hysteria2://dongtaiwang.com@195.154.33.70:42259/?sni=www.bing.com&insecure=1#hysteria2_20250123
    # 提取配置信息
    # {
    #   "server": "51.159.111.32:31180",
    #   "auth": "dongtaiwang.com",
    #   "bandwidth": {
    #     "up": "11 mbps",
    #     "down": "55 mbps"
    #   },
    #   "tls": {
    #     "sni": "apple.com",
    #     "insecure": true
    #   },
    #   "quic": {
    #     "initStreamReceiveWindow": 16777216,
    #     "maxStreamReceiveWindow": 16777216,
    #     "initConnReceiveWindow": 33554432,
    #     "maxConnReceiveWindow": 33554432
    #   },
    #   "socks5": {
    #     "listen": "127.0.0.1:1080"
    #   },
    #   "transport": {
    #     "udp": {
    #       "hopInterval": "30s"
    #     }
    #   }
    # }
    protocol = "hysteria2"

    address: str = config.get("server")

    index = address.rfind(":")
    if index == -1:
        print(f"Invalid address: {address}")
        return ""

    server = address[:index]
    port = address[index + 1 :].split(",")[0]

    auth = config.get("auth", "")

    if tls := config.get("tls"):
        sni = tls.get("sni", "")
        insecure = tls.get("insecure", True)
        insecure = "1" if insecure else "0"

    remark = gen_remark(server, postfix)
    url = f"{protocol}://{auth}@{server}:{port}/?sni={sni}&insecure={insecure} "
    key = get_hash(url)
    url = f"{url}#{remark}"
    return key, url


@load_all_config("./proxy/hysteria_config_links.txt")
def get_all_links(config: str) -> str:

    link = gen_hysteria_share_link(json.loads(config))
    print(f"hysteria2 分享链接：{link}")

    return link


if __name__ == "__main__":
    arrange_links(get_all_links())
