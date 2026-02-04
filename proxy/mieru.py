import json
import base64

from util import gen_remark, load_all_config

postfix = "mieru"


def gen_mieru_share_link(config):
    """生成Mieru分享链接"""
    # profileName = config["profileName"]

    user = config["user"]
    name = user["name"]
    password = user["password"]
    server = config["servers"][0]

    ipAddress = server["ipAddress"]
    portBindings = server["portBindings"]

    params = []

    for portBinding in portBindings:
        port = portBinding["port"]
        protocol = portBinding["protocol"]
        params.append(f"port={port}&protocol={protocol}")

    # 生成备注
    remark = gen_remark(ipAddress, postfix)
    profile = f"profile={remark}"
    params.append(profile)

    params_str = "&".join(params)

    # Mieru分享链接格式：
    # mieru://CpsBCgdkZWZhdWx0ElgKBWJhb3ppEg1tYW5saWFucGVuZmVuGkA0MGFiYWM0MGY1OWRhNTVkYWQ2YTk5ODMxYTUxMTY1MjJmYmM4MGUzODViYjFhYjE0ZGM1MmRiMzY4ZjczOGE0Gi8SCWxvY2FsaG9zdBoFCIo0EAIaDRACGgk5OTk5LTk5OTkaBQjZMhABGgUIoCYQASD4CioCCAQSB2RlZmF1bHQYnUYguAgwBTgA
    # mierus://用户名:密码@服务器地址?参数列表
    # mierus://baozi:manlianpenfen@1.2.3.4?handshake-mode=HANDSHAKE_NO_WAIT&mtu=1400&multiplexing=MULTIPLEXING_HIGH&port=6666&port=9998-9999&port=6489&port=4896&profile=default&protocol=TCP&protocol=TCP&protocol=UDP&protocol=UDP
    link = f"{name}:{password}@{ipAddress}?{params_str}"
    # mierus_link = f"mierus://{link}"
    encoded_link = base64.b64encode(link.encode("utf-8")).decode("utf-8")
    mieru_link = f"mieru://{encoded_link}"

    key = get_hash(f"{name}:{password}@{ipAddress}") 
    return key, mieru_link


@load_all_config("./proxy/mieru_config_links.txt")
def get_all_links(config: str) -> str:
    """获取所有可能的配置文件的分享链接"""
    try:
        config_dict = json.loads(config)
        link = gen_mieru_share_link(config_dict.get("profiles")[0])
        return link
    except Exception as e:
        print(f"解析Mieru配置失败: {e}")
        return None


if __name__ == "__main__":
    # 测试函数
    links = get_all_links()
    print(links)
