import re
import requests
import subprocess
from pathlib import Path
import logging
import base64


logger = logging.getLogger(__name__)



BASE_DIR = Path(__file__).resolve().parent


def fetch_v2ray_links(sub_url: str) -> list:
    """根据订阅URL获取v2ray分享链接"""
    try:
        resp = requests.get(sub_url, timeout=15)
        resp.raise_for_status()

        text = resp.text
        # 判断是否是base64编码
        if re.match(r"^[a-zA-Z0-9+/=]+$", text):
            text = base64.b64decode(text).decode("utf-8")

        return [line.strip() for line in text.splitlines() if line.strip()]

    except Exception as e:
        logger.warning(f"获取订阅失败 {sub_url}: {e}")
        return []


def test_delay(link: str) -> float:
    """使用真连接测试延迟，返回毫秒，失败返回None"""
    # 简单示例：解析出地址端口，用tcping测试
    try:
        # 解析vmess/vless等链接，提取地址端口
        if link.startswith("vmess://"):
            raw = base64.b64decode(link[8:]).decode("utf-8")
            cfg = json.loads(raw)
            addr, port = cfg["add"], int(cfg["port"])
        elif link.startswith("vless://"):
            # vless://uuid@host:port?...
            part = link.split("@")[1].split("?")[0]
            addr, port = part.split(":")
            port = int(port)
        else:
            return None
        # 调用系统ping或tcping
        cmd = ["ping", "-c", "1", "-W", "1", addr]
        completed = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3
        )
        if completed.returncode == 0:
            # 解析ping输出，提取延迟
            stdout = completed.stdout.decode("utf-8")
            m = re.search(r"time[=<](\d+(?:\.\d+)?)\s*ms", stdout)
            if m:
                return float(m.group(1))
    except Exception:
        pass
    return None


def main():
    # 订阅链接文件
    subscribe_file = BASE_DIR / "subscribe_links.txt"
    if not subscribe_file.exists():
        subscribe_file.touch()

    # 合并文件
    merge_file = BASE_DIR / "merge_share_links_filter.txt"
    if not merge_file.exists():
        merge_file.touch()

    # 读取订阅URL, 获取所有v2ray链接
    v2ray_links = []
    for line in subscribe_file.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or line == "":
            continue

        v2ray_links.extend(fetch_v2ray_links(line))

    # 读取已有链接并合并去重
    v2ray_links.extend(merge_file.read_text().splitlines())

    all_links = list[str](set[str](v2ray_links))

    # 4. 检测延迟并过滤（阈值300ms）
    # filtered = []
    # for link in all_links:
    #     delay = test_delay(link)
    #     if delay is not None and delay <= 300:
    #         filtered.append(link)
    # 保存
    with open(merge_file, "w", encoding="utf-8") as f:
        for link in all_links:
            f.write(link + "\n")

    logger.info(f"合并后共{len(all_links)}条可用链接已保存到 {merge_file}")


if __name__ == "__main__":
    main()
