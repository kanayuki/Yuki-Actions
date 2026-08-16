import sys
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json

from pac.util import arrange_links, console, gen_remark, load_all_config, save_links

CONFIG_FILE = Path(__file__).parent / "hysteria_config_links.txt"

postfix = "hysteria"


def build_hysteria_link(config: dict) -> str:
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
    url = f"{protocol}://{auth}@{server}:{port}/?sni={sni}&insecure={insecure}#{remark}"
    return url


@load_all_config(CONFIG_FILE)
def get_all_links(config: str) -> str:

    link = build_hysteria_link(json.loads(config))
    console.print(f"  [cyan]hysteria2[/cyan]  {link}")

    return link


if __name__ == "__main__":
    links = get_all_links()
    arrange_links(links)
    save_links(links, label="hysteria")
