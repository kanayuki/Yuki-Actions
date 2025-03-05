from clash import get_all_links


if __name__ == "__main__":


    links = list(get_all_links())
    print('总链接数：', len(links))
    print('\n'.join(links))

    unique_links = list(set(links))
    print('去重后链接数：', len(unique_links))
    print('\n'.join(unique_links))
    
    # 保存到文件
    with open(r'share_links.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(unique_links))

