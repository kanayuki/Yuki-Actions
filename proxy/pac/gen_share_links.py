import sys
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.rule import Rule

from pac import clash
from pac import hysteria
from pac import mieru
from pac import singbox
from pac import xray
from pac.util import console, save_links


def get_all_links() -> list[str]:
    links = []
    links.extend(xray.get_all_links())
    links.extend(clash.get_all_links())
    links.extend(hysteria.get_all_links())
    links.extend(mieru.get_all_links())
    links.extend(singbox.get_all_links())
    return links


def update() -> None:
    # ── 获取配置 ──────────────────────────────────────────
    console.print(Rule("[bold cyan]获取代理配置[/bold cyan]"))
    links = get_all_links()
    console.print(f"  配置源链接：[bold]{len(links)}[/bold] 条")
    save_links(links, label="all")


def main() -> None:
    update()


if __name__ == "__main__":
    main()
