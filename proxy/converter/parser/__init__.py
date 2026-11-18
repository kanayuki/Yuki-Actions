"""源格式解析器注册表：parse_config(text, ptype, source) -> list[Node]。

新协议支持：实现 `Parser` 协议（ptype + parse_config），然后在此注册。
本轮支持：xray / clash / singbox / hysteria / hysteria1 / mieru / juicity /
naive / shadowquic。分享链接走 `parse_share_link`（与源 config 分开）。
"""

from __future__ import annotations

from converter.models import Node
from converter.parser._base import Parser
from converter.parser.clash import ClashParser
from converter.parser.hysteria import Hysteria2Parser
from converter.parser.hysteria1 import Hysteria1Parser
from converter.parser.juicity import JuicityParser
from converter.parser.mieru import MieruParser
from converter.parser.naive import NaiveParser
from converter.parser.shadowquic import ShadowquicParser
from converter.parser.singbox import SingboxParser
from converter.parser.xray import XrayParser

PARSERS: dict[str, type[Parser]] = {
    "xray": XrayParser,
    "clash": ClashParser,
    "singbox": SingboxParser,
    "hysteria2": Hysteria2Parser,
    "hysteria1": Hysteria1Parser,
    "mieru": MieruParser,
    "juicity": JuicityParser,
    "naive": NaiveParser,
    "shadowquic": ShadowquicParser,
}


def parse_config(text: str, ptype: str, source: str = "") -> list[Node]:
    """按 ptype 解析一份源配置文本，返回 Node 列表。未知 ptype 抛 ValueError。"""
    cls = PARSERS.get(ptype)
    if cls is None:
        msg = f"Unknown ptype: {ptype!r} (available: {', '.join(PARSERS)})"
        raise ValueError(msg)
    return cls.parse_config(text, source=source)


def available_ptypes() -> list[str]:
    """返回已注册的 ptype 列表。"""
    return list(PARSERS.keys())


__all__ = ["Parser", "PARSERS", "parse_config", "available_ptypes"]
