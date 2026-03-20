"""sing-box engine — multi-port SOCKS proxy testing.

Same approach as xray: starts a single sing-box process with N inbound/outbound
pairs, tests each proxy via its dedicated SOCKS port.
"""

from __future__ import annotations

import base64
import json
import logging
import shutil
import subprocess
import tempfile
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import requests

from . import TestEngine, TestResult
from .binary import ensure_binary

logger = logging.getLogger(__name__)

_BASE_SOCKS_PORT = 21001
_SUPPORTED = {"vmess", "vless", "ss", "trojan", "hysteria2", "tuic"}


# ---------------------------------------------------------------------------
# Share link → sing-box outbound converter
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
    return url[:idx], urllib.parse.unquote(url[idx + 1 :])


def _tls_opts(params: dict) -> dict | None:
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
        tls["reality"] = {
            "enabled": True,
            "public_key": params.get("pbk", ""),
            "short_id": params.get("sid", ""),
        }
    if params.get("allowInsecure") == "1" or params.get("insecure") == "1":
        tls["insecure"] = True
    return tls


def _transport_opts(params: dict) -> dict | None:
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


def _vmess_outbound(link: str, tag: str) -> dict | None:
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
        "type": "vmess",
        "tag": tag,
        "server": server,
        "server_port": port,
        "uuid": uuid,
        "security": str(cfg.get("scy") or "auto"),
        "alter_id": int(cfg.get("aid") or 0),
    }

    params = {
        "type": str(cfg.get("net") or "tcp"),
        "security": "tls" if cfg.get("tls") == "tls" else "none",
        "path": str(cfg.get("path") or "/"),
        "host": str(cfg.get("host") or ""),
        "sni": str(cfg.get("sni") or ""),
    }
    tls = _tls_opts(params)
    if tls:
        out["tls"] = tls
    transport = _transport_opts(params)
    if transport:
        out["transport"] = transport
    return out


def _vless_outbound(link: str, tag: str) -> dict | None:
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

    out: dict = {
        "type": "vless",
        "tag": tag,
        "server": server,
        "server_port": port,
        "uuid": uuid,
    }
    flow = params.get("flow", "")
    if flow:
        out["flow"] = flow
    tls = _tls_opts(params)
    if tls:
        out["tls"] = tls
    transport = _transport_opts(params)
    if transport:
        out["transport"] = transport
    return out


def _ss_outbound(link: str, tag: str) -> dict | None:
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
            userinfo_str, hostport = decoded_str[:at], decoded_str[at + 1 :]
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
        "type": "shadowsocks",
        "tag": tag,
        "server": host,
        "server_port": port,
        "method": cipher.lower(),
        "password": password,
    }


def _trojan_outbound(link: str, tag: str) -> dict | None:
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

    out: dict = {
        "type": "trojan",
        "tag": tag,
        "server": server,
        "server_port": port,
        "password": password,
    }
    tls = _tls_opts(params)
    if tls:
        out["tls"] = tls
    else:
        out["tls"] = {"enabled": True}
    transport = _transport_opts(params)
    if transport:
        out["transport"] = transport
    return out


def _hysteria2_outbound(link: str, tag: str) -> dict | None:
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

    out: dict = {
        "type": "hysteria2",
        "tag": tag,
        "server": server,
        "server_port": port,
        "password": pw,
    }
    sni = params.get("sni") or ""
    tls: dict = {"enabled": True}
    if sni:
        tls["server_name"] = sni
    if params.get("insecure") == "1":
        tls["insecure"] = True
    out["tls"] = tls
    obfs = params.get("obfs") or ""
    if obfs:
        out["obfs"] = {
            "type": obfs,
            "password": params.get("obfs-password") or params.get("obfs-pwd") or "",
        }
    return out


def _tuic_outbound(link: str, tag: str) -> dict | None:
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
        "type": "tuic",
        "tag": tag,
        "server": server,
        "server_port": port,
        "uuid": uuid,
        "password": password,
        "congestion_control": cc,
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


_CONVERTERS = {
    "vmess": _vmess_outbound,
    "vless": _vless_outbound,
    "ss": _ss_outbound,
    "trojan": _trojan_outbound,
    "hysteria2": _hysteria2_outbound,
    "tuic": _tuic_outbound,
}


def link_to_singbox_outbound(link: str, tag: str) -> dict | None:
    link = link.strip()
    if "://" not in link:
        return None
    scheme = link.split("://", 1)[0].lower()
    conv = _CONVERTERS.get(scheme)
    if conv is None:
        return None
    try:
        return conv(link, tag)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class SingboxEngine(TestEngine):
    _bin_path: Path | None = None

    @classmethod
    def name(cls) -> str:
        return "singbox"

    @classmethod
    def supported_protocols(cls) -> set[str]:
        return _SUPPORTED

    @classmethod
    def is_available(cls) -> bool:
        from ..config import load_config
        cfg = load_config()
        path = ensure_binary("sing-box", cfg.singbox_bin)
        if path:
            cls._bin_path = path
            return True
        return False

    def test_batch(
        self,
        links: list[str],
        *,
        timeout_ms: int = 6000,
        concurrency: int = 50,
        test_url: str = "http://www.gstatic.com/generate_204",
        on_done: Callable[[TestResult], None] | None = None,
    ) -> list[TestResult]:
        if not self._bin_path:
            self.is_available()
        if not self._bin_path:
            return [TestResult(link=l, ok=False, error="singbox_unavailable") for l in links]

        results: list[TestResult] = []
        for chunk_start in range(0, len(links), concurrency):
            chunk = links[chunk_start : chunk_start + concurrency]
            chunk_results = self._test_chunk(chunk, timeout_ms, concurrency, test_url, on_done)
            results.extend(chunk_results)
        return results

    def _test_chunk(
        self,
        links: list[str],
        timeout_ms: int,
        concurrency: int,
        test_url: str,
        on_done: Callable[[TestResult], None] | None,
    ) -> list[TestResult]:
        assert self._bin_path is not None

        inbounds: list[dict] = []
        outbounds: list[dict] = []
        route_rules: list[dict] = []
        port_to_link: dict[int, str] = {}
        unconvertible: list[str] = []

        for i, link in enumerate(links):
            tag = f"proxy-{i}"
            socks_tag = f"socks-{i}"
            socks_port = _BASE_SOCKS_PORT + i

            outbound = link_to_singbox_outbound(link, tag)
            if outbound is None:
                unconvertible.append(link)
                continue

            inbounds.append({
                "type": "socks",
                "tag": socks_tag,
                "listen": "127.0.0.1",
                "listen_port": socks_port,
            })
            outbounds.append(outbound)
            route_rules.append({"inbound": [socks_tag], "outbound": tag})
            port_to_link[socks_port] = link

        results: list[TestResult] = []
        for link in unconvertible:
            r = TestResult(link=link, ok=False, error="singbox_convert_failed")
            results.append(r)
            if on_done:
                on_done(r)

        if not outbounds:
            return results

        # Add a direct outbound for route default
        outbounds.append({"type": "direct", "tag": "direct"})
        singbox_cfg = {
            "log": {"level": "error"},
            "inbounds": inbounds,
            "outbounds": outbounds,
            "route": {"rules": route_rules, "final": "direct"},
        }

        cfg_dir = Path(tempfile.mkdtemp(prefix="singbox-cfg-"))
        cfg_file = cfg_dir / "config.json"
        cfg_file.write_text(json.dumps(singbox_cfg, ensure_ascii=False), encoding="utf-8")

        proc = subprocess.Popen(
            [str(self._bin_path), "run", "-c", str(cfg_file)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            time.sleep(1.0)
            if proc.poll() is not None:
                logger.error("sing-box exited early with code %d", proc.returncode)
                for link in port_to_link.values():
                    r = TestResult(link=link, ok=False, error="singbox_start_failed")
                    results.append(r)
                    if on_done:
                        on_done(r)
                return results

            timeout_s = timeout_ms / 1000.0
            with ThreadPoolExecutor(max_workers=min(concurrency, len(port_to_link))) as pool:
                futures = {
                    pool.submit(self._test_via_socks, port, test_url, timeout_s): port
                    for port in port_to_link
                }
                for future in as_completed(futures):
                    port = futures[future]
                    link = port_to_link[port]
                    try:
                        latency = future.result()
                        r = TestResult(link=link, ok=True, latency_ms=round(latency, 1))
                    except Exception as e:
                        r = TestResult(link=link, ok=False, error=str(e))
                    results.append(r)
                    if on_done:
                        on_done(r)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            shutil.rmtree(cfg_dir, ignore_errors=True)

        return results

    @staticmethod
    def _test_via_socks(port: int, test_url: str, timeout_s: float) -> float:
        proxies = {
            "http": f"socks5h://127.0.0.1:{port}",
            "https": f"socks5h://127.0.0.1:{port}",
        }
        start = time.monotonic()
        resp = requests.get(test_url, proxies=proxies, timeout=timeout_s, verify=False)
        latency = (time.monotonic() - start) * 1000.0
        if resp.status_code not in (200, 204):
            raise RuntimeError(f"HTTP {resp.status_code}")
        return latency
