import base64
import json
from pathlib import Path

import clash
import hysteria
import singbox
import xray
from util import backup

path = Path('.')
file = path / 'share_links.txt'
# 备份目录
backup_dir = path / 'proxy' / 'backup'
if not backup_dir.exists():
    backup_dir.mkdir(parents=True)


def get_all_links() -> list:
    links = []
    links.extend(xray.get_all_links())
    links.extend(clash.get_all_links())
    links.extend(hysteria.get_all_links())
    links.extend(singbox.get_all_links())
    return links


def update():
    links = get_all_links()
    print('总链接数：', len(links))
    print('\n'.join(links))
    print('')

    unique_links = list(set(links))
    print('去重后链接数：', len(unique_links))
    unique_links_text = '\n'.join(unique_links)
    print(unique_links_text)

    # 保存到文件

    with open(file, 'w', encoding='utf-8') as f:
        f.write(unique_links_text)

    print(f"\n保存{len(unique_links)}条分享链接到: {file}")
    
    # 将新内容添加到share_links_all.txt, 并去重
    all_file = path / 'share_links_all.txt'
    if not all_file.exists():
        all_file.touch()
    with open(all_file, 'r', encoding='utf-8') as f:
        all_links = f.read().splitlines()
    all_links.extend(unique_links)
    
    # 去重
    link_dict = dict()
    
    for link in all_links:
        original_link = link
        # 解析vmess链接，去掉备注
        if link.startswith('vmess://'):
            link = link.replace('vmess://', '')
            link= base64.b64decode(link.encode('utf-8')).decode('utf-8')
            link = json.loads(link)
            del link['ps']
            link = base64.b64encode(json.dumps(link).encode('utf-8')).decode('utf-8')
            link = f'vmess://{link}'
        
        # 解析其他链接，去掉备注
        elif '#' in link:
            link = link.split('#')[0]
            
            
        if link not in link_dict:
            link_dict[link] = original_link

    # 保存到文件
    all_links = list(link_dict.values())
    
    with open(all_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(all_links))
    print(f"\n保存{len(all_links)}条分享链接到: {all_file}")
    


def main():
    # 备份文件share_links.txt
    backup(file, backup_dir)

    # 更新文件
    update()


if __name__ == "__main__":

    main()
