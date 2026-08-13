from pathlib import Path

from rich.console import Console
from rich.rule import Rule

from . import clash
from . import hysteria
from . import mieru
from . import singbox
from . import xray

console = Console(highlight=False)

link_file = Path(__file__).parent.parent / "share_links.txt"
keyfile = Path(__file__).parent.parent / "share_link_keys.txt"


def get_all_links() -> dict[str, str]:
    links = []
    links.extend(xray.get_all_links())
    links.extend(clash.get_all_links())
    links.extend(hysteria.get_all_links())
    links.extend(mieru.get_all_links())
    links.extend(singbox.get_all_links())
    return {k: link for k, link in links}


def update() -> None:
    # ── 获取配置 ──────────────────────────────────────────
    console.print(Rule("[bold cyan]获取代理配置[/bold cyan]"))
    new_link_dict = get_all_links()
    console.print(f"  配置源链接：[bold]{len(new_link_dict)}[/bold] 条")

    existing_links = []
    if link_file.exists():
        existing_links = [
            l for l in link_file.read_text(encoding="utf-8").splitlines() if l.strip()
        ]

    existing_keys = []
    if keyfile.exists():
        existing_keys = [
            l for l in keyfile.read_text(encoding="utf-8").splitlines() if l.strip()
        ]
    console.print(f"  现有链接：  [bold]{len(existing_links)}[/bold] 条")

    if len(existing_keys) != len(existing_links):
        console.print(f"  键文件与链接文件不一致：[bold]{len(existing_keys)}[/bold] 条")

        merged = new_link_dict

    else:
        existing_dict = {k: v for k, v in zip(existing_keys, existing_links)}
        merged = {**existing_dict, **new_link_dict}

    console.print(f"  合并去重后：[bold]{len(merged)}[/bold] 条")

    # 覆写 share_links.txt：
    with open(link_file, "w", encoding="utf-8") as f:
        for link in merged.values():
            f.write(link + "\n")

    # 同步重写 keyfile
    with open(keyfile, "w", encoding="utf-8") as f:
        for key in merged.keys():
            f.write(key + "\n")


def main() -> None:
    update()


if __name__ == "__main__":
    main()
