# Yuki-Actions

自动抓取、验证并生成多种代理工具分享链接的自动化项目，通过 GitHub Actions 定时运行。

## 功能特性

- **多协议支持**：Xray (vless/vmess/shadowsocks)、Clash、Hysteria2、Mieru、Singbox (TUIC/VLESS/AnyTLS)
- **真实连通性验证**：TCP 直连（vless/vmess/ss/trojan/anytls）或 DNS 解析（hysteria2/tuic），并发检测
- **智能过滤**：连续失败 3 次才移除节点，避免因网络抖动误删有效链接
- **订阅合并**：支持 base64 编码订阅链接，去重后验证
- **按延迟排序**：输出文件中有效节点按实测延迟从低到高排列
- **定时更新**：GitHub Actions 每天 UTC 00:00 / 12:00 自动运行

## 输出文件

| 文件 | 内容 |
|---|---|
| `share_links.txt` | 当前有效分享链接（主输出，按延迟排序） |
| `share_link_keys.txt` | 存活链接的去重 key |
| `proxy/share_link_health.json` | 各节点连续失败计数（健康状态持久化） |
| `proxy/merge/merge_share_links_filter.txt` | 订阅合并后的有效链接 |

## 本地运行

```bash
git clone https://github.com/kanayuki/Yuki-Actions.git
cd Yuki-Actions

pip install requests pyyaml rich

# 完整流程（生成 + 验证 + 合并订阅）
python proxy/main.py

# 单独验证一个链接文件
python proxy/verify.py share_links.txt
```

## 依赖

- Python 3.12+
- `requests`
- `pyyaml`
- `rich`

## 手动触发 Actions

仓库页面 → Actions → Update Proxy Share Links → Run workflow

## License

MIT
