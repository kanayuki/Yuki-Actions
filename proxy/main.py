from merge import merge
import gen_share_links


def main():

    # 生成分享链接
    gen_share_links.main()

    # 合并订阅链接
    merge.main()


if __name__ == "__main__":
    main()
