"""从 ip_*.bat 文件中提取配置 URL，按类型输出并写入 *_config_links.txt。

用法:
    python -m pac.get_config_urls [SOURCE_DIR]

    SOURCE_DIR: 包含 Xray/clash.meta/singbox/hysteria2/mieru 目录的根路径
                默认: F:\\Download\\Chrome150_AllNew_2026.7.15
"""

import re
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console(highlight=False)

# 类型 → (目录名, 配置文件后缀)
TYPE_MAP = {
    "xray": ("Xray", "json"),
    "clash": ("clash.meta", "yaml"),
    "singbox": ("singbox", "json"),
    "hysteria": ("hysteria2", "json"),
    "mieru": ("mieru", "json"),
}

# 脚本所在目录（pac/）
PAC_DIR = Path(__file__).resolve().parent

URL_PATTERN = re.compile(r"https://\S+")


def extract_urls_from_bat(bat_path: Path) -> list[str]:
    """从 .bat 文件中提取所有 HTTPS URL。"""
    text = bat_path.read_text(encoding="gbk", errors="ignore")
    return URL_PATTERN.findall(text)


def scan_dir(source_dir: Path) -> dict[str, list[str]]:
    """扫描 source_dir 下各类型的 ip_Update/ip_*.bat，提取 URL。"""
    result: dict[str, list[str]] = {}

    for type_name, (dir_name, _) in TYPE_MAP.items():
        ip_update_dir = source_dir / dir_name / "ip_Update"
        urls: list[str] = []

        if not ip_update_dir.exists():
            console.print(f"  [yellow]⚠[/yellow] {ip_update_dir} 不存在，跳过")
            result[type_name] = urls
            continue

        bat_files = sorted(ip_update_dir.glob("ip_*.bat"))
        for bat in bat_files:
            found = extract_urls_from_bat(bat)
            urls.extend(found)

        result[type_name] = urls

    return result


def write_config_links(type_name: str, urls: list[str]) -> None:
    """将 URL 列表写入对应的 *_config_links.txt 文件。"""
    filename = f"{type_name}_config_links.txt"
    filepath = PAC_DIR / filename

    # 读取已有内容，合并去重
    existing: set[str] = set()
    if filepath.exists():
        for line in filepath.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing.add(line.strip())

    all_urls = sorted(existing | set(urls))

    with open(filepath, "w", encoding="utf-8") as f:
        for url in all_urls:
            f.write(url + "\n")

    added = len(all_urls) - len(existing)
    console.print(
        f"  [{type_name}] 写入 [bold]{filename}[/bold]: "
        f"{len(existing)} → {len(all_urls)} 条 (+{added})"
    )


def main() -> None:
    source_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"F:\Download\Chrome150_AllNew_2026.7.15"
    )

    console.print(f"[bold cyan]扫描目录:[/bold cyan] {source_dir}")

    if not source_dir.exists():
        console.print(f"[red]✗ 目录不存在: {source_dir}[/red]")
        sys.exit(1)

    result = scan_dir(source_dir)

    # 打印结果表格
    table = Table(title="配置 URL 汇总", show_lines=False, header_style="bold cyan")
    table.add_column("类型", style="bold", width=10)
    table.add_column("URL 数量", justify="right", width=10)
    table.add_column("URL", overflow="fold")

    for type_name, urls in result.items():
        if not urls:
            table.add_row(type_name, "0", "[dim]无[/dim]")
            continue
        for i, url in enumerate(urls):
            table.add_row(
                type_name if i == 0 else "",
                str(len(urls)) if i == 0 else "",
                url,
            )

    console.print(table)

    # 写入文件
    console.print("\n[bold cyan]写入配置文件:[/bold cyan]")
    for type_name, urls in result.items():
        write_config_links(type_name, urls)


if __name__ == "__main__":
    main()
