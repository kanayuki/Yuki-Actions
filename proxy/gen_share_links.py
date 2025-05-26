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
    print('')

    unique_links = list(set(links))
    print('去重后链接数：', len(unique_links))
    unique_links_text = '\n'.join(unique_links)
    print(unique_links_text)

    # 保存到文件
    file = r'share_links.txt'
    with open(file, 'w', encoding='utf-8') as f:
        f.write(unique_links_text)

    print(f"\n保存{len(unique_links)}条分享链接到: {file}")


if __name__ == "__main__":

    main()
