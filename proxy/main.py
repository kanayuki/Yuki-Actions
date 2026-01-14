from merge import merge
import gen_share_links


def main():
    # 合并订阅链接
    merge.main()
    
    # 生成分享链接
    gen_share_links.main()


if __name__ == "__main__":
    main()
