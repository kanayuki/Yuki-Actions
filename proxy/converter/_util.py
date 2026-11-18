"""converter 模块共享工具：Rich console 实例与 JSON 上游损坏修复。

- `console`：全局 Rich console（与 `pac/util.py` 同款设置，highlight=False）
- `extract_first_json` / `find_json_seams`：应对上游把多份 JSON 配置直接拼接、
  或拼接处丢失一个收尾括号的损坏（对 JSON 字符串字面量中的花括号免疫）
"""

from __future__ import annotations

import json

from rich.console import Console

console = Console(highlight=False)


def find_json_seams(text: str) -> list[tuple[int, int]]:
    """定位可能的多文档接缝：收尾括号紧跟开头括号，中间仅空白（字符串之外）。

    返回 `[(closer_idx, opener_idx), ...]`，即"一个完整文档的收尾括号"后跟
    "另一个文档的开头括号"的位置。跳过字符串字面量与转义字符。
    """
    seams: list[tuple[int, int]] = []
    in_str = False
    esc = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            i += 1
            continue
        if ch in "}]":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "{[":
                seams.append((i, j))
        i += 1
    return seams


def extract_first_json(text: str) -> str:
    """文本意外拼接了多份 JSON（或尾随垃圾）时，截取第一份完整文档。

    覆盖两类上游损坏：
    1. 「完整文档 + 完整文档（或尾随垃圾）」直接拼接 → `raw_decode` 天然只吃第一份；
    2. 拼接处丢失一个收尾括号（如 `}{\r\n` 紧邻，第一份少了根括号）→
       在接缝处补回括号还原第一份。
    正常（单份且完整）的文本原样返回。
    """
    text = text.strip().lstrip("\ufeff")

    decoder = json.JSONDecoder()
    try:
        end = decoder.raw_decode(text)[1]
    except json.JSONDecodeError:
        pass
    else:
        if end < len(text):
            return text[:end].rstrip()
        return text

    for _close_idx, open_idx in find_json_seams(text):
        prefix = text[:open_idx].rstrip()
        for candidate in (prefix, prefix + "}", prefix + "]"):
            try:
                json.loads(candidate)
            except json.JSONDecodeError:
                continue
            return candidate
    return text


__all__ = ["console", "extract_first_json", "find_json_seams"]