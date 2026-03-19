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
    console.print(f"  [dim]{url}[/dim]", end="  ")
    try:
        resp = requests.get(url, headers=_HEADERS, verify=False, timeout=15)
        if resp.status_code == 200:
            console.print("[green]✓[/green]")
            return resp.text
        console.print(f"[red]✗ {resp.status_code} {resp.reason}[/red]")
    except Exception as e:
        console.print(f"[red]✗ {e}[/red]")
    return None


def load_all_config(file: str):
    """Decorator: read URLs from file, fetch each config, call func per config."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with open(file, "r") as f:
                urls = [u.strip() for u in f.read().splitlines() if u.strip()]

            links = []
            for url in urls:
                config = get_config(url)
                if config is None:
                    console.print(f"  [red]✗[/red] Failed to fetch config from {url}")
                    continue
                link = func(config, *args, **kwargs)
                if link is None:
                    console.print(f"  [yellow]⚠[/yellow] Failed to parse share link from {url}")
                    continue
                links.append(link)
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


def arrange_links(links: list[tuple[str, str]]) -> list[str]:
    """Print a rich table of (key, link) pairs and return deduplicated links."""
    if not links:
        console.print("[yellow]No links found[/yellow]")
        return []

    link_dict = {k: link for k, link in links}

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


if __name__ == "__main__":
    get_country_code("198.40.52.26")
