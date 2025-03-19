import base64
import json
from util import today, get_config,arrange_links


def gen_hysteria_share_link(config: dict) -> str:
    # hysteria2://dongtaiwang.com@195.154.33.70:42259/?sni=www.bing.com&insecure=1#hysteria2_20250123
    # 提取配置信息
    protocol = 'hysteria2'

    address = config.get('server')
    server = address.split(':')[0]
    port = address.split(':')[1].split(',')[0]

    auth = config.get('auth', '')

    if tls := config.get('tls'):
        sni = tls.get('sni', '')
        insecure = tls.get('insecure', True)
        insecure = '1' if insecure else '0'

    remark = f'hysteria2_{today()}'
    share_link = f"{protocol}://{auth}@{server}:{port}/?sni={sni}&insecure={insecure}#{remark}"

    return share_link


def get_all_links():
    for i in range(1, 5):
        url = f'https://www.gitlabip.xyz/Alvin9999/PAC/master/backup/img/1/2/ipp/hysteria2/{i}/config.json'
        config = get_config(url)
        # print(config)
        if config is None:
            continue
        link = gen_hysteria_share_link(json.loads(config))
        print(link)

        yield link


if __name__ == "__main__":
    arrange_links(get_all_links())
