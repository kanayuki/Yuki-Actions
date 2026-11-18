"""拉取任意订阅 URL → 自动识别格式 → 解析为 Node[]。

与 fetch.py 的区别：fetch 走 urls.yaml（bat 分组配置），pull 接受任意 URL，
适合测试单个订阅源是否可用。

数据流：
    URL → 直连 + gh-proxy 镜像后备下载 → 格式探测
    ├─ 分享链接列表（明文 / 整篇 base64）→ parse_share_link 逐条解析
    ├─ clash yaml（proxies / proxy-providers）→ ClashParser
    │     无内联 proxies 且有 proxy-providers 时，跟随一层 provider URL
    ├─ singbox json（outbounds[].type）→ SingboxParser
    └─ xray json（outbounds[].protocol）→ XrayParser
    → PullResult(fmt, nodes, skipped, providers)

用法（从 Yuki-Actions 根目录）：
    uv run python -m proxy.new_pac.pull <url>
"""

from __future__ import annotations

import sys
import urllib3
from argparse import ArgumentParser
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import requests

# 确保 proxy/ 在 sys.path（converter 是 proxy 的子包）
_PROXY_DIR = Path(__file__).resolve().parent.parent
if str(_PROXY_DIR) not in sys.path:
    sys.path.insert(0, str(_PROXY_DIR))

from converter._util import extract_first_json  # noqa: E402
from converter.models import Node  # noqa: E402
from converter.parser import parse_config  # noqa: E402
from converter.parser.share_link import parse_share_link  # noqa: E402

from new_pac.logger import get_logger, setup_logger  # noqa: E402

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    )
}
TIMEOUT = 20

# gh-proxy 风格镜像前缀（直连 raw.githubusercontent.com 被墙时的后备）
MIRRORS = (
    "https://gh-proxy.com/",
    "https://ghfast.top/",
    "https://ghproxy.net/",
)

# 分享链接 scheme（按前缀识别，ssr 等不支持的也会被识别进 links 流程）
LINK_SCHEMES = (
    "vmess://", "vless://", "ss://", "trojan://",
    "hysteria2://", "hy2://", "tuic://", "anytls://",
    "hysteria://", "ssr://",
)


@dataclass
class PullResult:
    """单次 pull 的解析结果。"""

    fmt: str                       # links / links_base64 / clash / singbox / xray
    nodes: list[Node] = field(default_factory=list)
    skipped: int = 0               # 无法解析的行数（如不支持的 ssr://）
    providers: list[str] = field(default_factory=list)  # clash proxy-providers URL


def _download(url: str, timeout: int = TIMEOUT) -> str | None:
    """下载单个 URL：直连失败后依次尝试镜像前缀。失败返回 None。"""
    log = get_logger()
    candidates = [url] + [m + url for m in MIRRORS if not url.startswith(m)]
    for cand in candidates:
        try:
            resp = requests.get(cand, headers=HEADERS, verify=False, timeout=timeout)
            if resp.status_code == 200 and resp.text.strip():
                if cand != url:
                    log.info("镜像命中: %s", cand)
                return resp.text
            log.debug("[%d] %s", resp.status_code, cand)
        except Exception as e:
            log.debug("%s — %s", cand, e)
    log.warning("下载失败（含镜像）: %s", url)
    return None


def _parse_links(text: str, source: str) -> tuple[list[Node], int]:
    """分享链接列表逐条解析，返回 (nodes, skipped)。"""
    nodes: list[Node] = []
    skipped = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "//")):
            continue
        node = parse_share_link(line, source=source)
        if node is None:
            skipped += 1
            continue
        nodes.append(node)
    return nodes, skipped


def _try_base64(text: str) -> str | None:
    """整篇 base64 订阅 → 解码文本。不是 base64 返回 None。"""
    from converter.models import _b64decode

    try:
        decoded = _b64decode("".join(text.split())).decode("utf-8")
    except Exception:
        return None
    return decoded if decoded.strip() else None


def _detect_fmt(text: str) -> str | None:
    """内容格式探测：links / links_base64 / clash / singbox / xray / None。"""
    import json

    import yaml

    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    low = first.lower()
    if any(low.startswith(s) for s in LINK_SCHEMES):
        return "links"

    # 整篇 base64（解码后以链接 scheme 开头）
    if not (first.startswith(("{", "[")) or "://" in first):
        decoded = _try_base64(text)
        if decoded and any(
            decoded.strip().lower().startswith(s) for s in LINK_SCHEMES
        ):
            return "links_base64"

    # JSON 配置：singbox outbounds 带 type，xray outbounds 带 protocol
    try:
        obj = json.loads(extract_first_json(text))
    except Exception:
        obj = None
    if isinstance(obj, dict):
        outbounds = [o for o in (obj.get("outbounds") or []) if isinstance(o, dict)]
        if outbounds and any(("type" in o or "protocol" in o) for o in outbounds):
            return "singbox" if any("type" in o for o in outbounds) else "xray"

    # YAML 配置：clash
    try:
        obj = yaml.safe_load(text)
    except Exception:
        obj = None
    if isinstance(obj, dict) and ("proxies" in obj or "proxy-providers" in obj):
        return "clash"

    return None


def _provider_urls(clash: dict) -> list[str]:
    """提取 clash proxy-providers 的全部 http url。"""
    providers = clash.get("proxy-providers") or {}
    return [
        p["url"]
        for p in providers.values()
        if isinstance(p, dict) and isinstance(p.get("url"), str)
    ]


def pull_text(text: str, source: str) -> PullResult | None:
    """对已下载的订阅文本做格式探测 + 解析。无法识别返回 None。"""
    log = get_logger()
    fmt = _detect_fmt(text)
    if fmt is None:
        return None

    result = PullResult(fmt=fmt)
    if fmt == "links":
        result.nodes, result.skipped = _parse_links(text, source)
    elif fmt == "links_base64":
        decoded = _try_base64(text)
        assert decoded is not None  # _detect_fmt 已验证可解码
        result.nodes, result.skipped = _parse_links(decoded, source)
    elif fmt == "clash":
        import yaml

        obj = yaml.safe_load(text)
        if obj.get("proxies"):
            result.nodes = parse_config(text, ptype="clash", source=source)
        result.providers = _provider_urls(obj)
    else:  # singbox / xray
        try:
            result.nodes = parse_config(text, ptype=fmt, source=source)
        except Exception as e:
            log.warning("[%s] parser 失败: %s — %s", fmt, source, e)

    return result


def pull(url: str, timeout: int = TIMEOUT, follow_providers: bool = True) -> list[PullResult]:
    """拉取订阅 URL 并解析。clash 无内联节点时跟随一层 proxy-providers。"""
    log = get_logger()
    text = _download(url, timeout=timeout)
    if text is None:
        return []

    results: list[PullResult] = []
    top = pull_text(text, source=url)
    if top is None:
        log.warning("无法识别格式: %s", url)
        return []
    results.append(top)

    if follow_providers and top.fmt == "clash" and not top.nodes and top.providers:
        log.info("clash 无内联 proxies，跟随 %d 个 proxy-providers", len(top.providers))
        for purl in top.providers:
            ptext = _download(purl, timeout=timeout)
            if ptext is None:
                continue
            sub = pull_text(ptext, source=purl)
            if sub is None:
                log.warning("provider 无法识别格式: %s", purl)
                continue
            results.append(sub)

    # 汇总
    all_nodes: list[Node] = []
    for r in results:
        all_nodes.extend(r.nodes)
    log.info(
        "pull 完成: %s — %d 份配置, %d 节点, %d 跳过, 协议分布 %s",
        url,
        len(results),
        len(all_nodes),
        sum(r.skipped for r in results),
        dict(Counter(n.protocol for n in all_nodes)),
    )
    return results


def main(argv: list[str] | None = None) -> None:
    parser = ArgumentParser(prog="pull", description="拉取订阅 URL 并解析节点")
    parser.add_argument("url", help="订阅 URL")
    parser.add_argument("--timeout", type=int, default=TIMEOUT, help="下载超时秒数")
    parser.add_argument(
        "--no-follow", action="store_true", help="不跟随 clash proxy-providers"
    )
    args = parser.parse_args(argv)

    setup_logger()
    results = pull(args.url, timeout=args.timeout, follow_providers=not args.no_follow)
    if not results:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
