import functools
import json
import shutil
from datetime import datetime
from pathlib import Path
import hashlib

import requests
import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def today():
    return datetime.today().strftime("%Y%m%d")


def get_config(url: str) -> str | None:
    """获取xray配置"""
    # url = "https://www.gitlabip.xyz/Alvin9999/pac2/master/xray/1/config.json"
    # url = "https://www.githubip.xyz/Alvin9999/pac2/master/xray/2/config.json"
    print("config_url:", url)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0"
    }
    try:
        resp = requests.get(url, verify=False)
        print(resp.status_code, resp.reason)
        if resp.status_code == 200:
            config = resp.text
            # save_config(config)
            return config

    except Exception as e:
        print("获取配置文件失败", e)


def load_all_config(file: str) -> dict:
    """加载配置文件装饰器"""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with open(file, "r") as f:
                urls = f.read().splitlines()

            urls = [url.strip() for url in urls if url.strip() != ""]

            links = []
            for url in urls:
                print("")
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
    protocol = config["outbounds"][0]["protocol"]
    path = f"./xray/config_{protocol}_{today()}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

    return path


@functools.lru_cache(maxsize=128)
def get_country_code(ip=""):
    """
    The API base path is http://ip-api.com/json/{query}
    {query} can be a single IPv4/IPv6 address or a domain name.
    If you don't supply a query the current IP address will be used.
    """
    url = f"http://ip-api.com/json/{ip}"
    # url = f'https://api.ip.sb/geoip/{ip}'
    try:
        response = requests.get(url)
        data = response.json()
        # print(data)
        return data.get("countryCode", "")
    except Exception as e:
        print("获取国家码失败", e)
        return "Failed"


def arrange_links(links: list[tuple[str, str]]) -> list:
    links = list(links)
    print("总链接数：", len(links))
    print("\n".join([f"{k}. {link}" for k, link in links]))
    print("")

    link_dict = {k: link for k, link in links}
    print("去重后链接数：", len(link_dict))
   


def backup(file: Path, backup_dir: Path):
    """
    备份文件
    """

    # 获取当前日期和时间
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")

    # 构建备份文件的名称
    backup_file = backup_dir / f"{file.stem}_{timestamp}{file.suffix}"

    # 执行备份操作
    shutil.copy(file, backup_file)

    print(f"备份文件已保存到: {backup_file}")


def gen_remark(address: str, postfix: str = "") -> str:
    """生成备注"""
    country_code = get_country_code(address)
    remark = f"{country_code}_{today()}_{postfix}"
    return remark


def get_hash(string: str) -> str:
    """计算字符串的哈希值"""

    return hashlib.sha256(string.encode()).hexdigest()


if __name__ == "__main__":
    get_country_code("198.40.52.26")
