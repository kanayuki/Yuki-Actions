import xray
import hysteria
import clash


def get_all_links() -> list:
    links = []
    links.extend(xray.get_all_links())
    links.extend(clash.get_all_links())
    links.extend(hysteria.get_all_links())
    return links


def main():
    links = get_all_links()
    print('总链接数：', len(links))
    print('\n'.join(links))

    unique_links = list(set(links))
    print('去重后链接数：', len(unique_links))
    print('\n'.join(unique_links))

    # 保存到文件
    with open(r'share_links.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(unique_links))
        
    print('分享链接已保存到 share_links.txt')


if __name__ == "__main__":

    main()
