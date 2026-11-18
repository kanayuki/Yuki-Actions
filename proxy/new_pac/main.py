"""new_pac CLI 入口。

子命令（无参数时默认 all）：
    scan        web 源 → 云盘压缩包 → cache 解压 → urls.yaml（失败沿用现有 urls.yaml）
    fetch       下载 urls.yaml → 规范化 → config_store/
    render      节点池 → clash.yaml（默认拉取；--from-store 从 store 重读）
    all         scan → fetch → render 串联

用法（从 Yuki-Actions 根目录）：
    uv run python -m proxy.new_pac.main                # 等价于 all
    uv run python -m proxy.new_pac.main scan
    uv run python -m proxy.new_pac.main fetch --types xray clash
    uv run python -m proxy.new_pac.main render --from-store
    uv run python -m proxy.new_pac.main all --log-level DEBUG
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from rich.rule import Rule

# 确保 proxy/ 在 sys.path（converter 是 proxy 的子包）
_PROXY_DIR = Path(__file__).resolve().parent.parent
if str(_PROXY_DIR) not in sys.path:
    sys.path.insert(0, str(_PROXY_DIR))

from converter.models import Node  # noqa: E402

from new_pac.config import (  # noqa: E402
    CONFIG_STORE_DIR,
    URLS_FILE,
)
from new_pac.fetch import fetch_all  # noqa: E402
from new_pac.logger import get_logger, setup_logger  # noqa: E402
from new_pac.normalize import normalize  # noqa: E402
from new_pac.pool import NodePool  # noqa: E402
from new_pac.render import print_stats, render  # noqa: E402
from new_pac.scan import run as run_scan  # noqa: E402
from new_pac.source import prepare as prepare_source  # noqa: E402


def _cmd_scan(args: argparse.Namespace) -> None:
    get_logger().info(Rule("[bold cyan]Scan ip_*.bat[/bold cyan]"))
    # --source-root 手动指定本地目录（调试用）；否则走 web 源
    root = Path(args.source_root) if args.source_root else prepare_source()
    if root is None:
        # 稳定优先：源获取失败不致命，沿用现有 urls.yaml 继续跑 fetch
        if URLS_FILE.exists():
            get_logger().error("源获取失败，沿用现有 urls.yaml")
            return
        raise SystemExit(1)
    run_scan(root, write=True)


def _cmd_fetch(args: argparse.Namespace) -> None:
    get_logger().info(Rule("[bold cyan]Fetch configs[/bold cyan]"))
    results = fetch_all(types=args.types)
    get_logger().info(
        "Fetched %d 份配置, 节点数 %d",
        len(results),
        sum(len(r.nodes) for r in results),
    )


def _load_from_store(types: list[str] | None = None) -> list[Node]:
    """从 config_store 全部月份重读全部配置并解析为 Node[]。

    Args:
        types: 限定 ptype 列表（None=全部）
    """
    nodes: list[Node] = []
    if not CONFIG_STORE_DIR.is_dir():
        return nodes
    for path in sorted(CONFIG_STORE_DIR.glob("*/*.*")):
        if path.suffix not in (".yaml", ".json"):
            continue
        # 文件名形如 {ptype}_{hash12}.{ext}
        ptype = path.name.split("_", 1)[0]
        if types and ptype not in types:
            continue
        try:
            _, _, parsed = normalize(path.read_text(encoding="utf-8"), ptype)
        except Exception:
            continue
        nodes.extend(parsed)
    return nodes


def _cmd_render(args: argparse.Namespace) -> None:
    get_logger().info(Rule("[bold cyan]Render clash.yaml[/bold cyan]"))
    pool = NodePool()

    if getattr(args, "from_store", False):
        nodes = _load_from_store(types=args.types)
        pool.extend(nodes)
        get_logger().info(
            "从 store 读出 %d 节点", len(pool)
        )
    else:
        results = fetch_all(types=args.types)
        for r in results:
            pool.extend(r.nodes)
        get_logger().info(
            "Fetched %d 份配置, 节点数 %d",
            len(results),
            len(pool),
        )

    if len(pool) == 0:
        get_logger().error("节点池为空，跳过渲染（保护 clash.yaml）")
        raise SystemExit(1)

    pool.finalize_names()
    print_stats(pool)
    n, skipped, path = render(pool)
    get_logger().info("渲染完成: %d 节点 → %s", n, path)


def _cmd_all(args: argparse.Namespace) -> None:
    _cmd_scan(args)
    _cmd_fetch(args)
    _cmd_render(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="new_pac",
        description="new_pac: 独立 PAC 管线，基于 converter",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )

    sub = parser.add_subparsers(dest="command")  # 无子命令时默认 all
    scan_parser = sub.add_parser("scan", help="扫描 bat → urls.yaml")
    scan_parser.add_argument(
        "--source-root",
        default=None,
        help="bat 根目录",
    )

    fetch_parser = sub.add_parser("fetch", help="下载+规范化+落盘")
    fetch_parser.add_argument(
        "--types",
        nargs="+",
        default=None,
        help="限定 ptype 列表",
    )

    render_parser = sub.add_parser("render", help="节点池 → clash.yaml")
    render_parser.add_argument(
        "--from-store",
        action="store_true",
        help="从 config_store 全部月份重读（不重新下载）",
    )
    render_parser.add_argument(
        "--types",
        nargs="+",
        default=None,
        help="限定 ptype 列表",
    )

    all_parser = sub.add_parser("all", help="scan + fetch + render 一把梭")
    all_parser.add_argument(
        "--source-root",
        default=None,
        help="bat 根目录",
    )
    all_parser.add_argument(
        "--types",
        nargs="+",
        default=None,
        help="限定 ptype 列表",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    # 默认行为 = all（补齐 all 子命令所需的属性）
    if args.command is None:
        args.command = "all"
        args.source_root = None
        args.types = None
        args.from_store = False

    setup_logger(level=getattr(logging, args.log_level))
    log = get_logger()
    try:
        {
            "scan": _cmd_scan,
            "fetch": _cmd_fetch,
            "render": _cmd_render,
            "all": _cmd_all,
        }[args.command](args)
    except SystemExit:
        raise
    except Exception as e:
        log.exception("执行失败: %s", e)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
