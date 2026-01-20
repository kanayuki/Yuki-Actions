# Yuki-Actions

Yuki's Actions 是一个用于管理和生成多种代理工具分享链接的自动化项目。

## 📋 功能特性

- **多代理支持**：兼容 Xray、Clash、Hysteria、Mieru 和 Singbox 等多种代理工具
- **自动生成分享链接**：批量生成各代理工具的分享链接
- **去重处理**：自动去除重复的代理链接
- **定时更新**：通过 GitHub Actions 每天自动运行两次（UTC 时间 00:00 和 12:00）
- **手动触发**：支持手动运行工作流更新链接
- **历史备份**：自动备份生成的分享链接

## 📁 项目结构

```
Yuki-Actions/
├── .github/
│   └── workflows/
│       └── proxy-script.yml  # GitHub Actions 工作流配置
├── proxy/
│   ├── backup/              # 分享链接备份目录
│   ├── main.py              # 主入口文件
│   ├── gen_share_links.py   # 生成分享链接的核心脚本
│   ├── xray.py              # Xray 代理配置处理
│   ├── clash.py             # Clash 代理配置处理
│   ├── hysteria.py          # Hysteria 代理配置处理
│   ├── mieru.py             # Mieru 代理配置处理
│   ├── singbox.py           # Singbox 代理配置处理
│   └── util.py              # 工具函数
├── share_links.txt          # 最新生成的分享链接
└── share_links_all.txt      # 包含所有历史去重后的分享链接
```

## 🚀 使用方法

### 1. 自动运行

项目已配置 GitHub Actions，会自动在以下时间运行：
- UTC 时间 00:00（北京时间 08:00）
- UTC 时间 12:00（北京时间 20:00）

### 2. 手动触发

1. 进入项目 GitHub 仓库页面
2. 点击 "Actions" 标签页
3. 选择 "Run Python Script" 工作流
4. 点击 "Run workflow" 按钮

### 3. 本地运行

```bash
# 克隆仓库
git clone https://github.com/kanayuki/Yuki-Actions.git
cd Yuki-Actions

# 安装依赖
pip install requests pyyaml

# 运行脚本
python proxy/main.py
```

## 📦 依赖

- Python 3.11+
- requests
- pyyaml

## 🔗 相关链接

- [项目仓库](https://github.com/kanayuki/Yuki-Actions)

## 📄 许可证

MIT License
