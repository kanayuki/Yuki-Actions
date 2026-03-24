"""Protocol parsers and format converters for proxy share links.

Public API
----------
parse_link(link)                       -> ParsedProxy | None
health_key(link)                       -> str
link_to_clash(link, name)              -> dict | None   (Clash/mihomo proxy dict)
link_to_xray_outbound(link, tag)       -> dict | None   (xray outbound dict)
link_to_singbox_outbound(link, tag)    -> dict | None   (sing-box outbound dict)

Supported protocols: vmess, vless, ss, trojan, hysteria, hysteria2 (hy2), tuic, anytls, mieru
"""

from __future__ import annotations

import base64
import hashlib
import json
import urllib.parse
from typing import Optional

from .models import ParsedProxy


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _b64decode(s: str) -> bytes:
    s = s.replace("-", "+").replace("_", "/")
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    return base64.b64decode(s)


def _strip_fragment(url: str) -> tuple[str, str]:
    idx = url.find("#")
    if idx == -1:
        return url, ""
    return url[:idx], urllib.parse.unquote(url[idx + 1:])


# ---------------------------------------------------------------------------
# parse_link — minimal host/port extraction for health-key generation
# ---------------------------------------------------------------------------


def _parse_vmess(link: str) -> ParsedProxy | None:
    b64 = _strip_fragment(link[8:])[0].strip()
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
    return ParsedProxy(protocol="vmess", host=host, port=port, raw_link=link)


def _parse_url_based(link: str, protocol: str) -> ParsedProxy | None:
    """Generic parser for vless, trojan, hysteria, hysteria2, tuic, anytls."""
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port
    except Exception:
        return None
    if not (host and port):
        return None
    return ParsedProxy(protocol=protocol, host=host, port=port, raw_link=link)


def _parse_ss(link: str) -> ParsedProxy | None:
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port
        if host and port:
            return ParsedProxy(protocol="ss", host=host, port=port, raw_link=link)
        # Old format: ss://BASE64(cipher:password@host:port)
        b64_part = url[5:].split("#")[0].split("?")[0]
        decoded = _b64decode(b64_part).decode()
        at = decoded.rfind("@")
        if at == -1:
            return None
        hostport = decoded[at + 1:]
        if ":" not in hostport:
            return None
        host, port_str = hostport.rsplit(":", 1)
        port = int(port_str)
    except Exception:
        return None
    if not (host and port):
        return None
    return ParsedProxy(protocol="ss", host=host, port=port, raw_link=link)


def _parse_mieru(link: str) -> ParsedProxy | None:
    """mieru://BASE64(JSON) — extract first server's host/port."""
    b64 = link[len("mieru://"):]
    try:
        cfg = json.loads(_b64decode(b64).decode())
    except Exception:
        return None
    servers = cfg.get("servers") or cfg.get("profiles", [{}])[0].get("servers", [])
    if not servers:
        return None
    first = servers[0] if isinstance(servers, list) else next(iter(servers.values()), {})
    host = (
        first.get("ipOrDomainName")
        or first.get("host")
        or first.get("address")
        or ""
    )
    # mieru port is in portBindings: [{"port": N, "protocol": "TCP"}]
    bindings = first.get("portBindings") or []
    port = next((b.get("port") for b in bindings if b.get("port")), 0)
    if not (host and port):
        return None
    return ParsedProxy(protocol="mieru", host=host, port=port, raw_link=link)


_PARSERS = {
    "vmess": _parse_vmess,
    "ss": _parse_ss,
    "mieru": _parse_mieru,
}
_URL_PROTOCOLS = {"vless", "trojan", "hysteria", "hysteria2", "hy2", "tuic", "anytls"}


def parse_link(link: str) -> ParsedProxy | None:
    """Parse any proxy share link and return a ParsedProxy, or None if unsupported/malformed."""
    link = link.strip()
    if "://" not in link:
        return None
    scheme = link.split("://", 1)[0].lower()
    # Normalise hy2 → hysteria2
    proto = "hysteria2" if scheme == "hy2" else scheme

    if scheme in _PARSERS:
        return _PARSERS[scheme](link)
    if proto in _URL_PROTOCOLS:
        return _parse_url_based(link, proto)
    return None


def health_key(link: str) -> str:
    """Return the stable health key for a share link (sha256 of protocol:host:port)."""
    proxy = parse_link(link)
    if proxy:
        return proxy.health_key
    return hashlib.sha256(link.split("#")[0].encode()).hexdigest()


# ---------------------------------------------------------------------------
# Clash / mihomo proxy dict converters
# ---------------------------------------------------------------------------


def _clash_vmess(link: str, name: str) -> Optional[dict]:
    b64 = _strip_fragment(link[8:])[0].strip()
    try:
        cfg = json.loads(_b64decode(b64).decode())
    except Exception:
        return None
    server = str(cfg.get("add", "")).strip()
    uuid = str(cfg.get("id", "")).strip()
    try:
        port = int(cfg.get("port", 0))
    except (TypeError, ValueError):
        return None
    if not (server and port and uuid):
        return None

    net = str(cfg.get("net") or "tcp")
    proxy: dict = {
        "name": name, "type": "vmess", "server": server, "port": port,
        "uuid": uuid, "alterId": int(cfg.get("aid") or 0),
        "cipher": str(cfg.get("scy") or "auto"), "network": net,
    }
    if cfg.get("tls") == "tls":
        proxy["tls"] = True
        sni = str(cfg.get("sni") or cfg.get("host") or "").strip()
        if sni:
            proxy["servername"] = sni
        if cfg.get("fp"):
            proxy["client-fingerprint"] = cfg["fp"]
    if net == "ws":
        wo: dict = {"path": str(cfg.get("path") or "/")}
        host = str(cfg.get("host") or "").strip()
        if host:
            wo["headers"] = {"Host": host}
        proxy["ws-opts"] = wo
    elif net == "grpc":
        proxy["grpc-opts"] = {"grpc-service-name": str(cfg.get("path") or "")}
    elif net == "h2":
        proxy["h2-opts"] = {"path": str(cfg.get("path") or "/"), "host": [str(cfg.get("host") or server)]}
    return proxy


def _clash_vless(link: str, name: str) -> Optional[dict]:
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        uuid = parsed.username or ""
        server = parsed.hostname or ""
        port = parsed.port
        params = dict(urllib.parse.parse_qsl(parsed.query))
    except Exception:
        return None
    if not (server and port and uuid):
        return None

    security = params.get("security", "none")
    net = params.get("type", "tcp")
    proxy: dict = {
        "name": name, "type": "vless", "server": server, "port": port,
        "uuid": uuid, "network": net, "tls": security in ("tls", "reality"),
    }
    if security == "tls":
        sni = params.get("sni") or params.get("host") or ""
        if sni:
            proxy["servername"] = sni
        if params.get("fp"):
            proxy["client-fingerprint"] = params["fp"]
        alpn = params.get("alpn", "")
        if alpn:
            proxy["alpn"] = alpn.split(",")
    elif security == "reality":
        proxy["reality-opts"] = {"public-key": params.get("pbk", ""), "short-id": params.get("sid", "")}
        sni = params.get("sni") or ""
        if sni:
            proxy["servername"] = sni
        if params.get("fp"):
            proxy["client-fingerprint"] = params["fp"]
    if net == "ws":
        wo: dict = {"path": params.get("path") or "/"}
        host = params.get("host") or ""
        if host:
            wo["headers"] = {"Host": host}
        proxy["ws-opts"] = wo
    elif net == "grpc":
        proxy["grpc-opts"] = {"grpc-service-name": params.get("serviceName") or ""}
    elif net == "h2":
        proxy["h2-opts"] = {"path": params.get("path") or "/"}
    return proxy


def _clash_ss(link: str, name: str) -> Optional[dict]:
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port
        if host and port:
            userinfo = parsed.username or ""
            try:
                decoded = _b64decode(userinfo).decode()
                cipher, password = decoded.split(":", 1)
            except Exception:
                cipher = urllib.parse.unquote(userinfo)
                password = urllib.parse.unquote(parsed.password or "")
        else:
            b64_part = url[5:].split("#")[0].split("?")[0]
            decoded = _b64decode(b64_part).decode()
            at = decoded.rfind("@")
            if at == -1:
                return None
            userinfo, hostport = decoded[:at], decoded[at + 1:]
            cipher, password = userinfo.split(":", 1)
            if ":" not in hostport:
                return None
            host, portstr = hostport.rsplit(":", 1)
            port = int(portstr)
    except Exception:
        return None
    if not (host and port and cipher and password):
        return None
    return {"name": name, "type": "ss", "server": host, "port": port, "cipher": cipher.lower(), "password": password}


def _clash_trojan(link: str, name: str) -> Optional[dict]:
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        server = parsed.hostname or ""
        port = parsed.port
        password = urllib.parse.unquote(parsed.username or "")
    except Exception:
        return None
    if not (server and port and password):
        return None
    proxy: dict = {"name": name, "type": "trojan", "server": server, "port": port, "password": password}
    sni = params.get("sni") or params.get("peer") or ""
    if sni:
        proxy["sni"] = sni
    if params.get("allowInsecure") == "1" or params.get("insecure") == "1":
        proxy["skip-cert-verify"] = True
    alpn = params.get("alpn", "")
    if alpn:
        proxy["alpn"] = alpn.split(",")
    net = params.get("type", "")
    if net == "ws":
        wo: dict = {"path": params.get("path") or "/"}
        host = params.get("host") or ""
        if host:
            wo["headers"] = {"Host": host}
        proxy["network"] = "ws"
        proxy["ws-opts"] = wo
    elif net == "grpc":
        proxy["network"] = "grpc"
        proxy["grpc-opts"] = {"grpc-service-name": params.get("serviceName") or ""}
    return proxy


def _clash_hysteria2(link: str, name: str) -> Optional[dict]:
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        server = parsed.hostname or ""
        port = parsed.port
        pw = urllib.parse.unquote(parsed.username or "")
        if parsed.password:
            pw = urllib.parse.unquote(parsed.password)
    except Exception:
        return None
    if not (server and port and pw):
        return None
    proxy: dict = {"name": name, "type": "hysteria2", "server": server, "port": port, "password": pw}
    sni = params.get("sni") or ""
    if sni:
        proxy["sni"] = sni
    if params.get("insecure") == "1":
        proxy["skip-cert-verify"] = True
    obfs = params.get("obfs") or ""
    if obfs:
        proxy["obfs"] = obfs
        proxy["obfs-password"] = params.get("obfs-password") or params.get("obfs-pwd") or ""
    return proxy


def _clash_tuic(link: str, name: str) -> Optional[dict]:
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        server = parsed.hostname or ""
        port = parsed.port
        uuid = urllib.parse.unquote(parsed.username or "")
        password = urllib.parse.unquote(parsed.password or "")
    except Exception:
        return None
    if not (server and port and uuid):
        return None
    cc = params.get("congestion_control") or params.get("congestion-control") or "bbr"
    alpn_str = params.get("alpn") or "h3"
    proxy: dict = {
        "name": name, "type": "tuic", "server": server, "port": port,
        "uuid": uuid, "password": password, "congestion-controller": cc,
        "alpn": alpn_str.split(","),
    }
    sni = params.get("sni") or ""
    if sni:
        proxy["sni"] = sni
    if params.get("allow_insecure") == "1" or params.get("insecure") == "1":
        proxy["skip-cert-verify"] = True
    return proxy


_CLASH_CONVERTERS: dict[str, object] = {
    "vmess": _clash_vmess, "vless": _clash_vless, "ss": _clash_ss,
    "trojan": _clash_trojan, "hysteria2": _clash_hysteria2, "hy2": _clash_hysteria2,
    "tuic": _clash_tuic,
}


def link_to_clash(link: str, name: str) -> Optional[dict]:
    """Convert a share link to a Clash/mihomo proxy dict. Returns None if unsupported/malformed."""
    link = link.strip()
    if "://" not in link:
        return None
    scheme = link.split("://", 1)[0].lower()
    conv = _CLASH_CONVERTERS.get(scheme)
    if conv is None:
        return None
    try:
        return conv(link, name)  # type: ignore[operator]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# xray outbound converters
# ---------------------------------------------------------------------------


def _xray_stream_settings(params: dict, security: str = "") -> dict:
    net = params.get("type", "tcp")
    sec = security or params.get("security", "none")
    ss: dict = {"network": net}
    if sec == "tls":
        tls: dict = {}
        sni = params.get("sni") or params.get("host") or ""
        if sni:
            tls["serverName"] = sni
        if params.get("fp"):
            tls["fingerprint"] = params["fp"]
        alpn = params.get("alpn") or ""
        if alpn:
            tls["alpn"] = alpn.split(",")
        ss["security"] = "tls"
        ss["tlsSettings"] = tls
    elif sec == "reality":
        reality: dict = {"publicKey": params.get("pbk", ""), "shortId": params.get("sid", "")}
        sni = params.get("sni") or ""
        if sni:
            reality["serverName"] = sni
        if params.get("fp"):
            reality["fingerprint"] = params["fp"]
        ss["security"] = "reality"
        ss["realitySettings"] = reality
    if net == "ws":
        ws: dict = {"path": params.get("path") or "/"}
        host = params.get("host") or ""
        if host:
            ws["headers"] = {"Host": host}
        ss["wsSettings"] = ws
    elif net == "grpc":
        ss["grpcSettings"] = {"serviceName": params.get("serviceName") or ""}
    elif net == "h2":
        h2: dict = {"path": params.get("path") or "/"}
        host = params.get("host") or ""
        if host:
            h2["host"] = [host]
        ss["httpSettings"] = h2
    return ss


def _xray_vmess(link: str, tag: str) -> Optional[dict]:
    b64 = _strip_fragment(link[8:])[0].strip()
    try:
        cfg = json.loads(_b64decode(b64).decode())
    except Exception:
        return None
    server = str(cfg.get("add", "")).strip()
    uuid = str(cfg.get("id", "")).strip()
    try:
        port = int(cfg.get("port", 0))
    except (TypeError, ValueError):
        return None
    if not (server and port and uuid):
        return None
    net = str(cfg.get("net") or "tcp")
    sec = "tls" if cfg.get("tls") == "tls" else "none"
    params: dict = {
        "type": net, "security": sec,
        "path": str(cfg.get("path") or "/"), "host": str(cfg.get("host") or ""),
        "sni": str(cfg.get("sni") or ""), "fp": str(cfg.get("fp") or ""),
    }
    return {
        "tag": tag, "protocol": "vmess",
        "settings": {"vnext": [{"address": server, "port": port, "users": [{"id": uuid, "alterId": int(cfg.get("aid") or 0), "security": str(cfg.get("scy") or "auto")}]}]},
        "streamSettings": _xray_stream_settings(params, sec),
    }


def _xray_vless(link: str, tag: str) -> Optional[dict]:
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        uuid = parsed.username or ""
        server = parsed.hostname or ""
        port = parsed.port
        params = dict(urllib.parse.parse_qsl(parsed.query))
    except Exception:
        return None
    if not (server and port and uuid):
        return None
    flow = params.get("flow", "")
    user: dict = {"id": uuid, "encryption": "none"}
    if flow:
        user["flow"] = flow
    return {
        "tag": tag, "protocol": "vless",
        "settings": {"vnext": [{"address": server, "port": port, "users": [user]}]},
        "streamSettings": _xray_stream_settings(params),
    }


def _xray_ss(link: str, tag: str) -> Optional[dict]:
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port
        if host and port:
            userinfo = parsed.username or ""
            try:
                decoded = _b64decode(userinfo).decode()
                cipher, password = decoded.split(":", 1)
            except Exception:
                cipher = urllib.parse.unquote(userinfo)
                password = urllib.parse.unquote(parsed.password or "")
        else:
            b64_part = url[5:].split("#")[0].split("?")[0]
            decoded_str = _b64decode(b64_part).decode()
            at = decoded_str.rfind("@")
            if at == -1:
                return None
            userinfo_str, hostport = decoded_str[:at], decoded_str[at + 1:]
            cipher, password = userinfo_str.split(":", 1)
            if ":" not in hostport:
                return None
            host, port_str = hostport.rsplit(":", 1)
            port = int(port_str)
    except Exception:
        return None
    if not (host and port and cipher and password):
        return None
    return {
        "tag": tag, "protocol": "shadowsocks",
        "settings": {"servers": [{"address": host, "port": port, "method": cipher.lower(), "password": password}]},
    }


def _xray_trojan(link: str, tag: str) -> Optional[dict]:
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        server = parsed.hostname or ""
        port = parsed.port
        password = urllib.parse.unquote(parsed.username or "")
    except Exception:
        return None
    if not (server and port and password):
        return None
    return {
        "tag": tag, "protocol": "trojan",
        "settings": {"servers": [{"address": server, "port": port, "password": password}]},
        "streamSettings": _xray_stream_settings(params, params.get("security", "tls")),
    }


_XRAY_CONVERTERS = {
    "vmess": _xray_vmess, "vless": _xray_vless, "ss": _xray_ss, "trojan": _xray_trojan,
}


def link_to_xray_outbound(link: str, tag: str) -> Optional[dict]:
    """Convert a share link to an xray outbound dict. Returns None if unsupported/malformed."""
    link = link.strip()
    if "://" not in link:
        return None
    scheme = link.split("://", 1)[0].lower()
    conv = _XRAY_CONVERTERS.get(scheme)
    if conv is None:
        return None
    try:
        return conv(link, tag)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# sing-box outbound converters
# ---------------------------------------------------------------------------


def _sb_tls_opts(params: dict) -> Optional[dict]:
    sec = params.get("security", "none")
    if sec not in ("tls", "reality"):
        return None
    tls: dict = {"enabled": True}
    sni = params.get("sni") or params.get("host") or ""
    if sni:
        tls["server_name"] = sni
    alpn = params.get("alpn") or ""
    if alpn:
        tls["alpn"] = alpn.split(",")
    if sec == "reality":
        tls["reality"] = {"enabled": True, "public_key": params.get("pbk", ""), "short_id": params.get("sid", "")}
    if params.get("allowInsecure") == "1" or params.get("insecure") == "1":
        tls["insecure"] = True
    return tls


def _sb_transport(params: dict) -> Optional[dict]:
    net = params.get("type", "tcp")
    if net == "ws":
        t: dict = {"type": "ws", "path": params.get("path") or "/"}
        host = params.get("host") or ""
        if host:
            t["headers"] = {"Host": host}
        return t
    if net == "grpc":
        return {"type": "grpc", "service_name": params.get("serviceName") or ""}
    if net == "h2":
        t = {"type": "http", "path": params.get("path") or "/"}
        host = params.get("host") or ""
        if host:
            t["host"] = [host]
        return t
    return None


def _sb_vmess(link: str, tag: str) -> Optional[dict]:
    b64 = _strip_fragment(link[8:])[0].strip()
    try:
        cfg = json.loads(_b64decode(b64).decode())
    except Exception:
        return None
    server = str(cfg.get("add", "")).strip()
    uuid = str(cfg.get("id", "")).strip()
    try:
        port = int(cfg.get("port", 0))
    except (TypeError, ValueError):
        return None
    if not (server and port and uuid):
        return None
    out: dict = {
        "type": "vmess", "tag": tag, "server": server, "server_port": port,
        "uuid": uuid, "security": str(cfg.get("scy") or "auto"), "alter_id": int(cfg.get("aid") or 0),
    }
    params = {
        "type": str(cfg.get("net") or "tcp"), "security": "tls" if cfg.get("tls") == "tls" else "none",
        "path": str(cfg.get("path") or "/"), "host": str(cfg.get("host") or ""),
        "sni": str(cfg.get("sni") or ""),
    }
    tls = _sb_tls_opts(params)
    if tls:
        out["tls"] = tls
    transport = _sb_transport(params)
    if transport:
        out["transport"] = transport
    return out


def _sb_vless(link: str, tag: str) -> Optional[dict]:
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        uuid = parsed.username or ""
        server = parsed.hostname or ""
        port = parsed.port
        params = dict(urllib.parse.parse_qsl(parsed.query))
    except Exception:
        return None
    if not (server and port and uuid):
        return None
    out: dict = {"type": "vless", "tag": tag, "server": server, "server_port": port, "uuid": uuid}
    flow = params.get("flow", "")
    if flow:
        out["flow"] = flow
    tls = _sb_tls_opts(params)
    if tls:
        out["tls"] = tls
    transport = _sb_transport(params)
    if transport:
        out["transport"] = transport
    return out


def _sb_ss(link: str, tag: str) -> Optional[dict]:
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port
        if host and port:
            userinfo = parsed.username or ""
            try:
                decoded = _b64decode(userinfo).decode()
                cipher, password = decoded.split(":", 1)
            except Exception:
                cipher = urllib.parse.unquote(userinfo)
                password = urllib.parse.unquote(parsed.password or "")
        else:
            b64_part = url[5:].split("#")[0].split("?")[0]
            decoded_str = _b64decode(b64_part).decode()
            at = decoded_str.rfind("@")
            if at == -1:
                return None
            userinfo_str, hostport = decoded_str[:at], decoded_str[at + 1:]
            cipher, password = userinfo_str.split(":", 1)
            if ":" not in hostport:
                return None
            host, port_str = hostport.rsplit(":", 1)
            port = int(port_str)
    except Exception:
        return None
    if not (host and port and cipher and password):
        return None
    return {"type": "shadowsocks", "tag": tag, "server": host, "server_port": port, "method": cipher.lower(), "password": password}


def _sb_trojan(link: str, tag: str) -> Optional[dict]:
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        server = parsed.hostname or ""
        port = parsed.port
        password = urllib.parse.unquote(parsed.username or "")
    except Exception:
        return None
    if not (server and port and password):
        return None
    out: dict = {"type": "trojan", "tag": tag, "server": server, "server_port": port, "password": password}
    tls = _sb_tls_opts(params)
    out["tls"] = tls if tls else {"enabled": True}
    transport = _sb_transport(params)
    if transport:
        out["transport"] = transport
    return out


def _sb_hysteria2(link: str, tag: str) -> Optional[dict]:
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        server = parsed.hostname or ""
        port = parsed.port
        pw = urllib.parse.unquote(parsed.username or "")
        if parsed.password:
            pw = urllib.parse.unquote(parsed.password)
    except Exception:
        return None
    if not (server and port and pw):
        return None
    out: dict = {"type": "hysteria2", "tag": tag, "server": server, "server_port": port, "password": pw}
    sni = params.get("sni") or ""
    tls: dict = {"enabled": True}
    if sni:
        tls["server_name"] = sni
    if params.get("insecure") == "1":
        tls["insecure"] = True
    out["tls"] = tls
    obfs = params.get("obfs") or ""
    if obfs:
        out["obfs"] = {"type": obfs, "password": params.get("obfs-password") or params.get("obfs-pwd") or ""}
    return out


def _sb_tuic(link: str, tag: str) -> Optional[dict]:
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        server = parsed.hostname or ""
        port = parsed.port
        uuid = urllib.parse.unquote(parsed.username or "")
        password = urllib.parse.unquote(parsed.password or "")
    except Exception:
        return None
    if not (server and port and uuid):
        return None
    cc = params.get("congestion_control") or params.get("congestion-control") or "bbr"
    out: dict = {
        "type": "tuic", "tag": tag, "server": server, "server_port": port,
        "uuid": uuid, "password": password, "congestion_control": cc,
    }
    sni = params.get("sni") or ""
    tls: dict = {"enabled": True}
    if sni:
        tls["server_name"] = sni
    alpn = params.get("alpn") or "h3"
    tls["alpn"] = alpn.split(",")
    if params.get("allow_insecure") == "1" or params.get("insecure") == "1":
        tls["insecure"] = True
    out["tls"] = tls
    return out


_SB_CONVERTERS = {
    "vmess": _sb_vmess, "vless": _sb_vless, "ss": _sb_ss, "trojan": _sb_trojan,
    "hysteria2": _sb_hysteria2, "hy2": _sb_hysteria2, "tuic": _sb_tuic,
}


def link_to_singbox_outbound(link: str, tag: str) -> Optional[dict]:
    """Convert a share link to a sing-box outbound dict. Returns None if unsupported/malformed."""
    link = link.strip()
    if "://" not in link:
        return None
    scheme = link.split("://", 1)[0].lower()
    conv = _SB_CONVERTERS.get(scheme)
    if conv is None:
        return None
    try:
        return conv(link, tag)
    except Exception:
        return None
