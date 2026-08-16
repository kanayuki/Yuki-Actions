import functools
import json
import shutil
from datetime import datetime
from pathlib import Path
import hashlib

import requests
import urllib3
from rich.console import Console
from rich.table import Table

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

console = Console(highlight=False)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0"
    )
}


def today():
    return datetime.today().strftime("%Y%m%d")


def get_config(url: str) -> str | None:
    console.print(f"[dim]{url}[/dim]")
    try:
        resp = requests.get(url, headers=_HEADERS, verify=False, timeout=15)
        console.print(f"[dim]{resp.status_code} {resp.reason}[/dim]")
        if resp.status_code == 200:
            # console.print("[green]✓[/green]")
            return resp.text
    except Exception as e:
        console.print(f"[red]✗ {e}[/red]")
    return None


def load_all_config(file: str):
    """Decorator: read URLs from file, fetch each config, call func per config.

    Deduplicates by config content hash: identical configs are skipped entirely
    (no parse + build overhead).
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with open(file, "r") as f:
                urls = [u.strip() for u in f.read().splitlines() if u.strip()]

            links = []
            seen = set()
            for url in urls:
                console.print(f"[dim]{'='*50}[/dim]")
                config = get_config(url)
                if config is None:
                    console.print(f"  [red]✗[/red] Failed to fetch config from {url}")
                    continue
                cfg_hash = get_hash(config)
                if cfg_hash in seen:
                    console.print(f"  [dim]↻ duplicate config, skipped[/dim]")
                    continue
                seen.add(cfg_hash)


                res = func(config, *args, **kwargs)
                if res is None:
                    console.print(f"  [yellow]⚠[/yellow] Failed to parse share link from {url}")
                    continue
                elif isinstance(res, str):
                    links.append(res)
                elif isinstance(res, list):
                    links.extend(res)
            return links

        return wrapper

    return decorator


def save_config(config):
    protocol = config["outbounds"][0]["protocol"]
    path = f"./xray/config_{protocol}_{today()}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
    return path


@functools.lru_cache(maxsize=128)
def get_country_code(ip: str = "") -> str:
    """Query ip-api.com for the country code of an IP/hostname."""
    url = f"http://ip-api.com/json/{ip}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        return data.get("countryCode", "")
    except Exception as e:
        console.print(f"  [dim]国家码查询失败 {ip}: {e}[/dim]")
        return "XX"


def arrange_links(links: list[str]) -> list[str]:
    """Print a rich table of links and return deduplicated links."""
    if not links:
        console.print("[yellow]No links found[/yellow]")
        return []

    # dedup by URL hash
    link_dict = {get_hash(link): link for link in links}

    table = Table(title="分享链接", show_lines=False, header_style="bold cyan")
    table.add_column("#", style="dim", justify="right", width=4)
    table.add_column("Key (前8位)", style="dim", width=10)
    table.add_column("链接", overflow="fold")

    for i, (k, link) in enumerate(link_dict.items(), 1):
        table.add_row(str(i), k[:8], link)

    console.print(table)
    console.print(
        f"总计 [bold]{len(links)}[/bold] 条，"
        f"去重后 [bold]{len(link_dict)}[/bold] 条"
    )
    return list(link_dict.values())


def backup(file: Path, backup_dir: Path) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"{file.stem}_{timestamp}{file.suffix}"
    shutil.copy(file, backup_file)
    console.print(f"  [dim]备份已保存: {backup_file}[/dim]")


def gen_remark(address: str, postfix: str = "") -> str:
    country_code = get_country_code(address)
    return f"{country_code}_{today()}_{postfix}"


def get_hash(string: str) -> str:
    return hashlib.sha256(string.encode()).hexdigest()


# ── 共享链接文件路径 ──
_link_file = Path(__file__).parent.parent / "share_links.txt"
_keyfile = Path(__file__).parent.parent / "share_link_keys.txt"


def save_links(links: list[str], label: str = "") -> None:
    """将链接列表与现有文件合并去重后写入 share_links.txt / share_link_keys.txt。

    去重逻辑：用 hash(url) 做 key，新链接优先（覆盖旧值）。

    Args:
        links: 分享链接列表
        label: 日志标签，如 "singbox" / "all"
    """
    label = label or "links"

    new_link_dict = {get_hash(url): url for url in links}

    existing_links = []
    if _link_file.exists():
        existing_links = [
            l for l in _link_file.read_text(encoding="utf-8").splitlines() if l.strip()
        ]

    existing_keys = []
    if _keyfile.exists():
        existing_keys = [
            l for l in _keyfile.read_text(encoding="utf-8").splitlines() if l.strip()
        ]

    if len(existing_keys) != len(existing_links):
        console.print(
            f"  [{label}] 键文件({len(existing_keys)})与链接文件({len(existing_links)})不一致，仅使用新数据"
        )
        merged = new_link_dict
    else:
        existing_dict = dict(zip(existing_keys, existing_links))
        merged = {**existing_dict, **new_link_dict}

    console.print(
        f"  [{label}] 现有 {len(existing_links)} 条 + 新 {len(new_link_dict)} 条 → 合并后 {len(merged)} 条"
    )

    with open(_link_file, "w", encoding="utf-8") as f:
        for link in merged.values():
            f.write(link + "\n")

    with open(_keyfile, "w", encoding="utf-8") as f:
        for key in merged.keys():
            f.write(key + "\n")


if __name__ == "__main__":
    get_country_code("198.40.52.26")
