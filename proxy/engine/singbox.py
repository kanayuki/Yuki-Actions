"""sing-box engine — multi-port SOCKS proxy testing."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import requests

from . import TestEngine, TestResult
from core.binary import ensure_binary
from core.parse import link_to_singbox_outbound

logger = logging.getLogger(__name__)

_BASE_SOCKS_PORT = 21001
_SUPPORTED = {"vmess", "vless", "ss", "trojan", "hysteria2", "tuic"}


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
        path = ensure_binary("sing-box")
        if path:
            cls._bin_path = path
        return cls._bin_path is not None

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
            chunk = links[chunk_start: chunk_start + concurrency]
            results.extend(self._test_chunk(chunk, timeout_ms, concurrency, test_url, on_done))
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

            inbounds.append({"type": "socks", "tag": socks_tag, "listen": "127.0.0.1", "listen_port": socks_port})
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
                futures = {pool.submit(self._test_via_socks, port, test_url, timeout_s): port for port in port_to_link}
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
        proxies = {"http": f"socks5h://127.0.0.1:{port}", "https": f"socks5h://127.0.0.1:{port}"}
        start = time.monotonic()
        resp = requests.get(test_url, proxies=proxies, timeout=timeout_s, verify=False)
        latency = (time.monotonic() - start) * 1000.0
        if resp.status_code not in (200, 204):
            raise RuntimeError(f"HTTP {resp.status_code}")
        return latency
