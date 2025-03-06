import base64
import json
import os
import re
import subprocess
from datetime import datetime
from pprint import pprint
from typing import Iterator
from urllib.parse import quote_plus

import requests
import urllib3
from util import get_config, today, arrange_links


def gen_vless_share_link(config):
    """ 生成vless分享链接 """
    # vless://ebfdccb6-7416-4b6e-860d-98587344d500@yh1.dtku41.xyz:443?
    # encryption=none&security=tls&sni=lg1.freessr2.xyz&fp=chrome&
    # type=ws&host=lg1.freessr2.xyz&path=%2Fxyakws#20240407
    protocol = config['protocol']
    settings = config['settings']
    vnext = settings['vnext'][0]

    address = vnext['address']
    port = vnext['port']
    user = vnext['users'][0]
    user_id = user['id']

    encryption = f"encryption={user['encryption']}"
    flow = f"flow={user.get('flow', '')}"
    # query paramaters of shared link
    query = f"{encryption}&{flow}"

    # streamSettings
    streamSettings = config['streamSettings']

    # 传输协议 type: ws / tcp
    network = streamSettings['network']

    query += f"&type={network}"

    if network == "ws":
        # network = ws (type)
        wsSettings = streamSettings['wsSettings']
        path = wsSettings['path']
        host = wsSettings['headers']['Host']

        query += f"&host={host}&path={path}"

    elif network == "tcp":
        pass

    elif network == "splithttp":
        splithttpSettings = streamSettings['splithttpSettings']
        path = splithttpSettings['path']
        host = splithttpSettings['host']
        # maxUploadSize = splithttpSettings['maxUploadSize']
        # maxConcurrentUploads = splithttpSettings['maxConcurrentUploads']

        query += f"&host={host}&path={path}"

    # 传输层安全:  tls reality
    security = streamSettings['security']
    query += f"&security={security}"

    if security == "reality":
        # encryption=none&flow=xtls-rprx-vision&security=reality&sni=www.yahoo.com&fp=chrome&pbk=U5hsLybYWhJrWAqqsTa052k-VeKt8bDFPxBh3CQk51M&sid=0b4badde&type=tcp&headerType=none
        realitySettings = streamSettings['realitySettings']
        serverName = realitySettings['serverName']
        fingerprint = realitySettings['fingerprint']
        # show=realitySettings['show']
        publicKey = realitySettings['publicKey']
        shortId = realitySettings['shortId']
        # spiderX=realitySettings['spiderX']

        query += f"&sni={serverName}&fp={fingerprint}&pbk={publicKey}&sid={shortId}"

    elif security == "tls":
        tlsSettings = streamSettings['tlsSettings']
        serverName = tlsSettings['serverName']
        fingerprint = tlsSettings.get('fingerprint', 'chrome')
        # allowInsecure = tlsSettings['allowInsecure']

        query += f"&sni={serverName}&fp={fingerprint}"

    remark = f"{protocol}_{today()}"
    url = f"{protocol}://{user_id}@{address}:{port}?{query}#{remark}"
    return url


def gen_vmess_share_link(config):
    """ 生成vmess分享链接 """
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
    protocol = config['protocol']
    settings = config['settings']
    vnext = settings['vnext'][0]
    user = vnext['users'][0]
    streamSettings = config['streamSettings']

    vmess_dict = {
        "v": "2",
        "ps": f"{protocol}_{today()}",
        'add': vnext['address'],
        'port': vnext['port'],
        'id': user['id'],
        'aid': user['alterId'],
        'scy': user['security'],
        'net': streamSettings['network'],
        'type': "none",

    }

    if streamSettings['network'] == "ws":
        ws_info = {
            "net": "ws",
            "host": streamSettings['wsSettings']['headers']['Host'],
            "path": streamSettings['wsSettings']['path'],
        }
        vmess_dict.update(ws_info)

    elif streamSettings['network'] == "httpupgrade":
        httpupgrade_info = {
            "http": "",
            "host": streamSettings['httpupgradeSettings']['host'],
            "path": streamSettings['httpupgradeSettings']['path'],

        }
        vmess_dict.update(httpupgrade_info)

    if streamSettings.get('security') == "tls":
        tls_info = {
            "tls": 'tls',
            "sni": streamSettings.get('tlsSettings')['serverName'],
            "alpn": "",
            'fp': "chrome",
        }
        vmess_dict.update(tls_info)

    text = json.dumps(vmess_dict)
    id = base64.urlsafe_b64encode(text.encode()).decode()

    url = f"{protocol}://{id}"
    return url


def gen_shadowsocks_share_link(config):
    """ 生成shadowsocks分享链接 """
    # ss://MjAyMi1ibGFrZTMtYWVzLTI1Ni1nY206b2F0cys3dmRhU09iNE5zeFd3Q0JRbGw0cVR3UHUvZGhwZWdpSUducWQ5Yz0=
    # @www.dtku44.xyz:22335#shadowsocks_20240409
    # base64(2022-blake3-aes-256-gcm:oats+7vdaSOb4NsxWwCBQll4qTwPu/dhpegiIGnqd9c=)

    # protocol = config['protocol']
    protocol = "ss"
    settings = config['settings']
    server = settings['servers'][0]

    address = server['address']
    port = server['port']
    method = server['method']
    password = server['password']

    # streamSettings
    # streamSettings = config['streamSettings']
    # network = streamSettings['network']  # tcp

    text = f"{method}:{password}"
    id = base64.urlsafe_b64encode(text.encode()).decode()
    remark = f"{protocol}_{today()}"
    url = f"{protocol}://{id}@{address}:{port}#{remark}"
    return url


def gen_share_link(config: dict) -> str:
    ''' 生成分享链接 vless, vmess, shadowsocks,  '''
    outbounds: list = config['outbounds']
    proxy: dict = [item for item in outbounds if item['tag'] == 'proxy'][0]

    protocol = proxy['protocol']

    protocol_map = {
        'vless': gen_vless_share_link,
        'vmess': gen_vmess_share_link,
        'shadowsocks': gen_shadowsocks_share_link,

    }

    if protocol in protocol_map:
        url = protocol_map[protocol](proxy)
        return url
    else:
        print(f"Unsupported protocol: {proxy}")

    return None


def get_all_links() -> Iterator[str]:
    """ 获取所有可能的配置文件的分享链接 """

    path = f"./proxy/xray_config_links.txt"
    with open(path, "r") as f:
        urls = f.read().splitlines()

    urls = [url for url in urls if url.strip() != '']

    for url in urls:
        print('####################')

        config = json.loads(get_config(url))
        # print(config)
        if config is None:
            continue

        link = gen_share_link(config)
        print(link)
        print('####################')
        yield link


if __name__ == "__main__":
    # url='https://www.githubip.xyz/Alvin9999/pac2/master/xray/2/config.json'
    # config = get_xray_config()
    # save_config(config)

    # config = read_config("config_shadowsocks.json")
    # config = read_config("config_vless.json")
    # url = get_share_link(config)
    # print(url)

    arrange_links(get_all_links())

    # 保存到文件
    # with open(r'D:\Code\Python\practice\v2ray_links.txt', 'w', encoding='utf-8') as f:
    #     f.write('\n'.join(unique_links))

    # url = 'https://www.githubip.xyz/Alvin9999/pac2/master/xray/config.json'
    # resp = requests.get(url, verify=False)
    # print(resp.text)
    # print(resp.status_code)
    # print(resp.reason)

    # url = 'https://gitlab.com/free9999/ipupdate/-/raw/master/v2rayN/guiNConfig.json'
    # url = 'https://gitlab.com/free9999/ipupdate/-/raw/master/v2rayN/2/guiNConfig.json'
    # url = 'https://www.githubip.xyz/Alvin9999/PAC/master/guiNConfig.json'
    # url = 'https://www.githubip.xyz/Alvin9999/PAC/master/1/guiNConfig.json'
    # url = 'https://www.githubip.xyz/Alvin9999/PAC/master/2/guiNConfig.json'
    # url = 'https://www.githubip.xyz/Alvin9999/PAC/master/3/guiNConfig.json'
    # url = 'https://fastly.jsdelivr.net/gh/Alvin9999/PAC@latest/guiNConfig.json'
    # url = 'https://fastly.jsdelivr.net/gh/Alvin9999/PAC@latest/2/guiNConfig.json'
