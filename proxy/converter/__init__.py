"""proxy/converter 公共 API：富 IR Node + 解析/生成/桥接。

subconverter-ng 风格代理协议转换工具：
    parse_config(text, ptype)              # 源配置 → Node[]
    parse_share_link(link)                  # 单条分享链接 → Node
    generate(node, target="clash")          # Node → 目标格式
    from_pac_node(old)                      # pac.nodes.Node → converter.Node

后续 Phase 扩展：
    - 新 source format：converter/parser/<name>.py，实现 Parser 协议，
      再到 parser/__init__.py: PARSERS 注册
    - 新 target format：converter/generator/<name>.py，实现 Generator 协议，
      再到 generator/__init__.py: GENERATORS 注册
"""

from __future__ import annotations

from converter.compat import from_pac_node, to_pac_node
from converter.generator import available_targets, generate
from converter.models import Node, normalize_protocol
from converter.parser import available_ptypes, parse_config
from converter.parser.share_link import parse_share_link

__all__ = [
    "Node",
    "normalize_protocol",
    "parse_config",
    "parse_share_link",
    "generate",
    "from_pac_node",
    "to_pac_node",
    "available_ptypes",
    "available_targets",
]
