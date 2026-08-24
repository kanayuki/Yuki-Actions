"""v2rayN 订阅渲染器：节点池 → 明文链接 + base64 订阅文件。

产物（proxy/subscribe/）：
- v2rayn.txt         明文分享链接，每行一条（v2rayN 可直接订阅该 raw URL）
- v2rayn_base64.txt  base64 编码订阅（兼容旧式订阅格式）
"""

from __future__ import annotations

import base64
from pathlib import Path

from pac.nodes import NodePool
from pac.util import console

_OUTPUT_DIR = Path(__file__).parent.parent / "subscribe"


def render(pool: NodePool) -> tuple[int, Path]:
    """生成 v2rayN 订阅。返回 (节点数, base64 订阅文件路径)。"""
    links = [n.link for n in pool.all() if n.v2rayn_ok]
    if not links:
        console.print("  [yellow]⚠ v2rayN 订阅：0 个可用节点，跳过写入（保护现有文件）[/yellow]")
        return 0, _OUTPUT_DIR / "v2rayn_base64.txt"

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plain_file = _OUTPUT_DIR / "v2rayn.txt"
    b64_file = _OUTPUT_DIR / "v2rayn_base64.txt"

    text = "\n".join(links)
    plain_file.write_text(text + "\n", encoding="utf-8")
    b64_file.write_text(base64.b64encode(text.encode()).decode() + "\n", encoding="utf-8")

    console.print(
        f"  v2rayN 订阅：[bold]{len(links)}[/bold] 个节点 → "
        f"{plain_file.name} / {b64_file.name}"
    )
    return len(links), b64_file
