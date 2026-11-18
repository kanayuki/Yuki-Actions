"""分享链接解析：单条 URL/链接 → Node。

支持的 scheme：vmess / vless / ss / trojan / hysteria2 / hy2 / tuic / anytls。
返回 Node | None（无法解析时返回 None，不抛异常）。

注意：与 9 个源 parser (`xray.py` 等) 不同——后者接受多节点配置文件文本，
本模块接受单条分享链接。命名 `parse_share_link` 以示区分。
"""

from __future__ import annotations

import json
import urllib.parse

from converter.models import Node, _b64decode, normalize_protocol


def parse_share_link(link: str, source: str = "") -> Node | None:
    """单条分享链接 → 富 IR Node。无法解析返回 None。"""
    link = link.strip()
    if "://" not in link:
        return None
    scheme = link.split("://", 1)[0].lower()
    try:
        if scheme == "vmess":
            node = _parse_vmess(link)
        elif scheme == "vless":
            node = _parse_vless(link)
        elif scheme == "ss":
            node = _parse_ss(link)
        elif scheme == "trojan":
            node = _parse_trojan(link)
        elif scheme in ("hysteria2", "hy2"):
            node = _parse_hysteria2(link)
        elif scheme == "tuic":
            node = _parse_tuic(link)
        elif scheme == "anytls":
            node = _parse_anytls(link)
        else:
            return None
    except Exception:
        return None
    if node is None:
        return None
    node.raw_link = link
    if source:
        node.source = source
    return node


# ── vmess ──────────────────────────────────────────────


def _parse_vmess(link: str) -> Node | None:
    """vmess://base64(JSON) — JSON 字段: v/ps/add/port/id/aid/scy/net/type/host/path/tls/sni/fp/alpn。"""
    b64 = link[len("vmess://"):].split("#", 1)[0].strip()
    try:
        cfg = json.loads(_b64decode(b64).decode())
    except Exception:
        return None
    host = str(cfg.get("add", "")).strip()
    try:
        port = int(cfg.get("port", 0))
    except (TypeError, ValueError):
        return None
    if not (host and port):
        return None

    node = Node(
        protocol="vmess",
        host=host,
        port=port,
        uuid=str(cfg.get("id", "")),
        alter_id=int(cfg.get("aid") or 0),
        cipher=str(cfg.get("scy") or "auto"),
        name=str(cfg.get("ps") or ""),
    )

    # 网络层
    net = str(cfg.get("net") or "tcp")
    if net in ("ws", "grpc", "h2", "http", "httpupgrade", "splithttp", "xhttp"):
        node.transport = net
    if net == "ws":
        node.path = str(cfg.get("path") or "/")
        if cfg.get("host"):
            node.host_headers = [str(cfg["host"])]
    elif net == "grpc":
        node.service_name = str(cfg.get("path") or "")
    elif net == "h2":
        node.path = str(cfg.get("path") or "/")
        if cfg.get("host"):
            node.host_headers = [str(cfg["host"])]
    elif net == "httpupgrade":
        node.path = str(cfg.get("path") or "")
        if cfg.get("host"):
            node.host_headers = [str(cfg["host"])]
    # net == "tcp" 时的 headerType (http伪装)
    if net == "tcp" and cfg.get("type") == "http":
        node.header_type = "http"

    # TLS
    if str(cfg.get("tls") or "").lower() == "tls":
        node.tls = True
        sni = str(cfg.get("sni") or cfg.get("host") or "").strip()
        if sni:
            node.sni = sni
        if cfg.get("fp"):
            node.fingerprint = str(cfg["fp"])
        if cfg.get("alpn"):
            node.alpn = [a for a in str(cfg["alpn"]).split(",") if a]

    return node


# ── vless ──────────────────────────────────────────────


def _parse_vless(link: str) -> Node | None:
    """vless://uuid@host:port?type=...&security=...&...#remark"""
    url, _ = _urldrop_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        uuid = urllib.parse.unquote(parsed.username or "")
        host = parsed.hostname or ""
        port = parsed.port
        params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    except Exception:
        return None
    if not (host and port and uuid):
        return None

    node = Node(
        protocol="vless",
        host=host,
        port=port,
        uuid=uuid,
        name=urllib.parse.unquote(parsed.fragment or ""),
    )

    # 传输层
    net = params.get("type", "tcp")
    if net in ("ws", "grpc", "h2", "http", "httpupgrade", "splithttp", "xhttp"):
        node.transport = net
    if net in ("ws", "h2", "httpupgrade", "xhttp", "splithttp", "http"):
        node.path = params.get("path") or "/"
    if net in ("ws", "h2", "httpupgrade", "xhttp", "splithttp") and params.get("host"):
        node.host_headers = [params["host"]]
    if net == "grpc":
        node.service_name = params.get("serviceName") or ""

    # Flow
    if params.get("flow"):
        node.flow = params["flow"]

    # Security
    sec = params.get("security", "none")
    if sec == "tls":
        node.tls = True
    elif sec == "reality":
        node.reality = True
        node.reality_public_key = params.get("pbk", "")
        node.reality_short_id = params.get("sid", "")

    # TLS 字段
    if node.tls or node.reality:
        sni = params.get("sni") or params.get("host") or ""
        if sni:
            node.sni = sni
        if params.get("fp"):
            node.fingerprint = params["fp"]
        if params.get("alpn"):
            node.alpn = [a for a in params["alpn"].split(",") if a]
        if params.get("allowInsecure") == "1" or params.get("insecure") == "1":
            node.skip_cert_verify = True

    return node


# ── ss ──────────────────────────────────────────────


def _parse_ss(link: str) -> Node | None:
    """ss://BASE64(method:password)@host:port#remark  或  ss://BASE64(method:password@host:port)#remark"""
    url, _ = _urldrop_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port
        cipher = ""
        password = ""

        if host and port and parsed.username:
            userinfo = parsed.username
            try:
                decoded = _b64decode(userinfo).decode()
                cipher, password = decoded.split(":", 1)
            except Exception:
                cipher = urllib.parse.unquote(userinfo)
                password = urllib.parse.unquote(parsed.password or "")
        else:
            # 旧格式：ss://BASE64(method:password@host:port)
            b64_part = url[len("ss://"):].split("#", 1)[0].split("?", 1)[0]
            decoded = _b64decode(b64_part).decode()
            at = decoded.rfind("@")
            if at == -1:
                return None
            userinfo, hostport = decoded[:at], decoded[at + 1:]
            cipher, password = userinfo.split(":", 1)
            if ":" not in hostport:
                return None
            host, port_str = hostport.rsplit(":", 1)
            port = int(port_str)
    except Exception:
        return None
    if not (host and port and cipher and password):
        return None

    return Node(
        protocol="ss",
        host=host,
        port=port,
        cipher=cipher.lower(),
        password=password,
        cipher_2022=cipher.lower().startswith("2022-"),
        name=urllib.parse.unquote(urllib.parse.urlparse(url).fragment or ""),
    )


# ── trojan ──────────────────────────────────────────────


def _parse_trojan(link: str) -> Node | None:
    """trojan://password@host:port?sni=..&type=..&allowInsecure=1#remark"""
    url, _ = _urldrop_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        host = parsed.hostname or ""
        port = parsed.port
        password = urllib.parse.unquote(parsed.username or "")
    except Exception:
        return None
    if not (host and port and password):
        return None

    node = Node(
        protocol="trojan",
        host=host,
        port=port,
        password=password,
        name=urllib.parse.unquote(parsed.fragment or ""),
    )

    if params.get("sni") or params.get("peer"):
        node.tls = True
        node.sni = params.get("sni") or params.get("peer") or ""
    if params.get("alpn"):
        node.alpn = [a for a in params["alpn"].split(",") if a]
    if params.get("allowInsecure") == "1" or params.get("insecure") == "1":
        node.skip_cert_verify = True
        if not node.tls:
            node.tls = True

    net = params.get("type", "")
    if net in ("ws", "grpc"):
        node.transport = net
        if net == "ws":
            node.path = params.get("path") or "/"
            if params.get("host"):
                node.host_headers = [params["host"]]
        elif net == "grpc":
            node.service_name = params.get("serviceName") or ""

    return node


# ── hysteria2 ──────────────────────────────────────────────


def _parse_hysteria2(link: str) -> Node | None:
    """hysteria2://auth@host:port/?sni=..&insecure=1&obfs=..&obfs-password=..#remark"""
    url, _ = _urldrop_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        host = parsed.hostname or ""
        port = parsed.port
        auth = urllib.parse.unquote(parsed.username or "")
    except Exception:
        return None
    if not (host and port and auth):
        return None

    node = Node(
        protocol="hysteria2",
        host=host,
        port=port,
        password=auth,
        tls=True,
        sni=params.get("sni", ""),
        name=urllib.parse.unquote(parsed.fragment or ""),
    )
    if params.get("insecure") == "1":
        node.skip_cert_verify = True
    if params.get("obfs"):
        node.obfs = params["obfs"]
        node.obfs_password = params.get("obfs-password") or params.get("obfs-pwd") or ""
    return node


# ── tuic ──────────────────────────────────────────────


def _parse_tuic(link: str) -> Node | None:
    """tuic://uuid:password@host:port?sni=..&alpn=..&allow_insecure=1&congestion_control=bbr#remark"""
    url, _ = _urldrop_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        host = parsed.hostname or ""
        port = parsed.port
        uuid = urllib.parse.unquote(parsed.username or "")
        password = urllib.parse.unquote(parsed.password or "")
    except Exception:
        return None
    if not (host and port and uuid):
        return None

    alpn_str = params.get("alpn", "h3")
    node = Node(
        protocol="tuic",
        host=host,
        port=port,
        uuid=uuid,
        password=password,
        tls=True,
        sni=params.get("sni", ""),
        alpn=[a for a in alpn_str.split(",") if a],
        congestion_controller=params.get("congestion_control")
        or params.get("congestion-control")
        or "bbr",
        name=urllib.parse.unquote(parsed.fragment or ""),
    )
    if params.get("allow_insecure") == "1" or params.get("insecure") == "1":
        node.skip_cert_verify = True
    return node


# ── anytls ──────────────────────────────────────────────


def _parse_anytls(link: str) -> Node | None:
    """anytls://password@host:port?fp=..&alpn=..&allowInsecure=1#remark"""
    url, _ = _urldrop_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        host = parsed.hostname or ""
        port = parsed.port
        password = urllib.parse.unquote(parsed.username or "")
    except Exception:
        return None
    if not (host and port and password):
        return None

    node = Node(
        protocol="anytls",
        host=host,
        port=port,
        password=password,
        tls=True,
        fingerprint=params.get("fp", ""),
        name=urllib.parse.unquote(parsed.fragment or ""),
    )
    if params.get("alpn"):
        node.alpn = [a for a in params["alpn"].split(",") if a]
    if params.get("allowInsecure") == "1" or params.get("insecure") == "1":
        node.skip_cert_verify = True
    return node


# ── helpers ──────────────────────────────────────────────


def _urldrop_fragment(link: str) -> tuple[str, str]:
    idx = link.find("#")
    if idx == -1:
        return link, ""
    return link[:idx], urllib.parse.unquote(link[idx + 1:])


__all__ = ["parse_share_link"]
