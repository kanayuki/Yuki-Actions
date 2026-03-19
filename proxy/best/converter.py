"""Convert proxy share links to Clash/mihomo proxy config dicts.

Supported: vmess, vless, ss, trojan, hysteria2, tuic
(anytls and mieru are not supported by Clash/mihomo — fall back to TCP check only)
"""

import base64
import json
import urllib.parse
from typing import Optional


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
# Per-protocol converters
# ---------------------------------------------------------------------------


def _vmess(link: str, name: str) -> Optional[dict]:
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
        "name": name,
        "type": "vmess",
        "server": server,
        "port": port,
        "uuid": uuid,
        "alterId": int(cfg.get("aid") or 0),
        "cipher": str(cfg.get("scy") or "auto"),
        "network": net,
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
        proxy["h2-opts"] = {
            "path": str(cfg.get("path") or "/"),
            "host": [str(cfg.get("host") or server)],
        }

    return proxy


def _vless(link: str, name: str) -> Optional[dict]:
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
        "name": name,
        "type": "vless",
        "server": server,
        "port": port,
        "uuid": uuid,
        "network": net,
        "tls": security in ("tls", "reality"),
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
        proxy["reality-opts"] = {
            "public-key": params.get("pbk", ""),
            "short-id": params.get("sid", ""),
        }
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


def _ss(link: str, name: str) -> Optional[dict]:
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port

        if host and port:
            # New format: ss://BASE64(cipher:password)@host:port
            userinfo = parsed.username or ""
            try:
                decoded = _b64decode(userinfo).decode()
                cipher, password = decoded.split(":", 1)
            except Exception:
                cipher = urllib.parse.unquote(userinfo)
                password = urllib.parse.unquote(parsed.password or "")
        else:
            # Old format: ss://BASE64(cipher:password@host:port)
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

    return {
        "name": name,
        "type": "ss",
        "server": host,
        "port": port,
        "cipher": cipher.lower(),
        "password": password,
    }


def _trojan(link: str, name: str) -> Optional[dict]:
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

    proxy: dict = {
        "name": name,
        "type": "trojan",
        "server": server,
        "port": port,
        "password": password,
    }
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


def _hysteria2(link: str, name: str) -> Optional[dict]:
    url, _ = _strip_fragment(link)
    try:
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        server = parsed.hostname or ""
        port = parsed.port
        # password can be username or username:password (some clients)
        pw = urllib.parse.unquote(parsed.username or "")
        if parsed.password:
            pw = urllib.parse.unquote(parsed.password)
    except Exception:
        return None
    if not (server and port and pw):
        return None

    proxy: dict = {
        "name": name,
        "type": "hysteria2",
        "server": server,
        "port": port,
        "password": pw,
    }
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


def _tuic(link: str, name: str) -> Optional[dict]:
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

    cc = (
        params.get("congestion_control")
        or params.get("congestion-control")
        or "bbr"
    )
    alpn_str = params.get("alpn") or "h3"
    proxy: dict = {
        "name": name,
        "type": "tuic",
        "server": server,
        "port": port,
        "uuid": uuid,
        "password": password,
        "congestion-controller": cc,
        "alpn": alpn_str.split(","),
    }
    sni = params.get("sni") or ""
    if sni:
        proxy["sni"] = sni
    if params.get("allow_insecure") == "1" or params.get("insecure") == "1":
        proxy["skip-cert-verify"] = True

    return proxy


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_CONVERTERS = {
    "vmess": _vmess,
    "vless": _vless,
    "ss": _ss,
    "trojan": _trojan,
    "hysteria2": _hysteria2,
    "tuic": _tuic,
}


def link_to_clash(link: str, name: str) -> Optional[dict]:
    """Convert a share link to a Clash proxy dict. Returns None if unsupported or malformed."""
    link = link.strip()
    if "://" not in link:
        return None
    scheme = link.split("://", 1)[0].lower()
    conv = _CONVERTERS.get(scheme)
    if conv is None:
        return None
    try:
        return conv(link, name)
    except Exception:
        return None
