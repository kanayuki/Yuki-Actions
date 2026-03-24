"""mihomo (Clash Meta) engine — REST API based proxy testing.

Supports all platforms (Linux/Windows/macOS). Auto-downloads binary if needed.
Best batch testing efficiency via REST API /proxies/{name}/delay.
"""

from __future__ import annotations

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
import yaml

from . import TestEngine, TestResult

logger = logging.getLogger(__name__)

_MIXED_PORT = 17891
_API_PORT = 19090
_API_URL = f"http://127.0.0.1:{_API_PORT}"

# Protocols mihomo can handle (via Clash proxy format)
_SUPPORTED = {"vmess", "vless", "ss", "trojan", "hysteria2", "tuic"}


def _link_to_clash(link: str, name: str) -> dict | None:
    from core.parse import link_to_clash
    return link_to_clash(link, name)


class _MihomoProcess:
    """Context manager: start mihomo, expose delay API, stop on exit."""

    def __init__(self, binary: Path, proxies: list[dict]) -> None:
        self._binary = binary
        self._proxies = proxies
        self._proc: subprocess.Popen | None = None
        self._cfg_dir: Path | None = None

    def __enter__(self) -> _MihomoProcess:
        self._cfg_dir = Path(tempfile.mkdtemp(prefix="mihomo-cfg-"))
        names = [p["name"] for p in self._proxies]
        cfg = {
            "mixed-port": _MIXED_PORT,
            "allow-lan": False,
            "log-level": "silent",
            "external-controller": f"127.0.0.1:{_API_PORT}",
            "proxies": self._proxies,
            "proxy-groups": [
                {"name": "PROXY", "type": "select", "proxies": names + ["DIRECT"]},
            ],
            "rules": ["MATCH,DIRECT"],
        }
        cfg_file = self._cfg_dir / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")

        self._proc = subprocess.Popen(
            [str(self._binary), "-d", str(self._cfg_dir)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                r = requests.get(f"{_API_URL}/version", timeout=1)
                if r.ok:
                    logger.info("mihomo started (pid=%d, %d proxies)", self._proc.pid, len(self._proxies))
                    return self
            except Exception:
                pass
            time.sleep(0.25)

        self.__exit__(None, None, None)
        raise RuntimeError("mihomo did not become ready within 10s")

    def __exit__(self, *_: object) -> None:
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        if self._cfg_dir:
            shutil.rmtree(self._cfg_dir, ignore_errors=True)
            self._cfg_dir = None

    def test_delay(self, name: str, timeout_ms: int, test_url: str) -> int | None:
        try:
            r = requests.get(
                f"{_API_URL}/proxies/{urllib.parse.quote(name, safe='')}/delay",
                params={"timeout": timeout_ms, "url": test_url},
                timeout=timeout_ms / 1000 + 3,
            )
            if r.ok:
                return r.json().get("delay")
        except Exception as e:
            logger.debug("mihomo delay(%s) error: %s", name, e)
        return None


class MihomoEngine(TestEngine):
    _bin_path: Path | None = None

    @classmethod
    def name(cls) -> str:
        return "mihomo"

    @classmethod
    def supported_protocols(cls) -> set[str]:
        return _SUPPORTED

    @classmethod
    def is_available(cls) -> bool:
        from core.binary import ensure_binary
        path = ensure_binary("mihomo")
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
            return [TestResult(link=l, ok=False, error="mihomo_unavailable") for l in links]

        # Convert links to Clash proxy dicts
        name_to_link: dict[str, str] = {}
        clash_proxies: list[dict] = []
        unconvertible: list[str] = []

        for i, link in enumerate(links):
            tag = f"p{i}"
            proxy = _link_to_clash(link, tag)
            if proxy:
                clash_proxies.append(proxy)
                name_to_link[tag] = link
            else:
                unconvertible.append(link)

        results: list[TestResult] = []
        # Unconvertible → fail
        for link in unconvertible:
            r = TestResult(link=link, ok=False, error="clash_convert_failed")
            results.append(r)
            if on_done:
                on_done(r)

        if not clash_proxies:
            return results

        try:
            with _MihomoProcess(self._bin_path, clash_proxies) as proc:
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    futures = {
                        pool.submit(proc.test_delay, tag, timeout_ms, test_url): tag
                        for tag in name_to_link
                    }
                    for future in as_completed(futures):
                        tag = futures[future]
                        link = name_to_link[tag]
                        try:
                            lat = future.result()
                        except Exception:
                            lat = None
                        if lat is not None:
                            r = TestResult(link=link, ok=True, latency_ms=lat)
                        else:
                            r = TestResult(link=link, ok=False, error="timeout")
                        results.append(r)
                        if on_done:
                            on_done(r)
        except Exception as e:
            logger.error("mihomo engine failed: %s", e)
            for link in name_to_link.values():
                r = TestResult(link=link, ok=False, error=str(e))
                results.append(r)
                if on_done:
                    on_done(r)

        return results
