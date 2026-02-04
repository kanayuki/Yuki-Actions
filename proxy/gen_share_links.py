from pathlib import Path

import clash
import hysteria
import mieru
import singbox
import xray
from util import backup

path = Path(".")
keyfile = path / "share_link_keys.txt"
link_file = path / "share_links.txt"

# 备份目录
backup_dir = path / "proxy" / "backup"
if not backup_dir.exists():
    backup_dir.mkdir(parents=True)


def get_all_links() -> dict:
    links = []
    # links.extend(xray.get_all_links())
    # links.extend(clash.get_all_links())
    # links.extend(hysteria.get_all_links())
    # links.extend(mieru.get_all_links())
    links.extend(singbox.get_all_links())
    return {k: link for k, link in links}


def update():
    link_dict = get_all_links()
    print("获取链接总数：", len(link_dict))
    print("\n".join(link_dict.values()))
    print("")

    # 读取keyfile文件
    with open(keyfile, "r", encoding="utf-8") as f:
        old_keys = f.read().splitlines()

    key_set = set[str](link_dict.keys()) - set[str](old_keys)

    new_links = [link_dict[key] for key in key_set]

    print("新增链接数：", len(new_links))

    # 保存new_links到文件
    with open(link_file, "a", encoding="utf-8") as f:
        f.write("\n".join(new_links))
    # 保存new_keys到文件
    with open(keyfile, "a", encoding="utf-8") as f:
        f.write("\n".join(key_set))


def main():
    # 备份文件share_links.txt
    # backup(link_file, backup_dir)

    # 更新文件
    update()


if __name__ == "__main__":

    main()
