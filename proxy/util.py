
from datetime import datetime
import functools
import json

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def today():
    return datetime.today().strftime("%Y%m%d")


def get_config(url: str) -> str | None:
    """ 获取xray配置 """
    # url = "https://www.gitlabip.xyz/Alvin9999/pac2/master/xray/1/config.json"
    # url = "https://www.githubip.xyz/Alvin9999/pac2/master/xray/2/config.json"
    print('config_url:', url)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0'
    }
    try:
        resp = requests.get(url, verify=False)
        print(resp.status_code, resp.reason)
        if resp.status_code == 200:
            config = resp.text
            # save_config(config)
            return config

    except Exception as e:
        print('获取配置文件失败', e)


def load_all_config(file: str) -> dict:
    """ 加载配置文件装饰器 """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with open(file, "r") as f:
                urls = f.read().splitlines()

            urls = [url.strip() for url in urls if url.strip() != '']

            links = []
            for url in urls:
                print('')
                config = get_config(url)
                # print(config)
                if config is None:
                    print(f"Failed to get config from {url}")
                    continue
                link = func(config, *args, **kwargs)
                if link is None:
                    print(f"Failed to get share link from {url}")
                    continue
                links.append(link)
            return links

        return wrapper
    return decorator


def save_config(config):

    # print("xray_config:", config)
    protocol = config['outbounds'][0]['protocol']
    path = f"./xray/config_{protocol}_{today()}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

    return path


def arrange_links(links: list) -> list:
    links = list(links)
    print('总链接数：', len(links))
    print('\n'.join(links))
    print('')

    unique_links = list(set(links))
    print('去重后链接数：', len(unique_links))
    print('\n'.join(unique_links))
    return unique_links
