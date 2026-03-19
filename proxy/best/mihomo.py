"""Download and run mihomo (Clash Meta) for real proxy HTTP connectivity testing.

mihomo is the continuation of Clash Meta — it supports vmess/vless/ss/trojan/hy2/tuic
and exposes a REST API for testing individual proxy latency via real HTTP requests.

The `/proxies/{name}/delay` endpoint actually tunnels an HTTP request through the proxy
and measures the round-trip time. This is fundamentally different from a TCP port check.
"""

import gzip
import logging
import platform
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

import requests
import yaml

logger = logging.getLogger(__name__)

# mihomo release to use (pinned for reproducibility)
_MIHOMO_VERSION = "v1.19.0"
_BINARY_DIR = Path(tempfile.gettempdir()) / "mihomo-bin"

# Use non-default ports to avoid conflicts with local Clash/v2ray instances
_MIXED_PORT = 17891
_API_PORT = 19090
_API_URL = f"http://127.0.0.1:{_API_PORT}"

# Test URL: Google's generate_204 — tiny response, globally reachable
_TEST_URL = "http://www.gstatic.com/generate_204"


# ---------------------------------------------------------------------------
# Binary management
# ---------------------------------------------------------------------------


def _binary_path() -> Path:
    return _BINARY_DIR / "mihomo"


def is_supported() -> bool:
    """True on Linux x86_64/aarch64 (i.e. GitHub Actions ubuntu-latest)."""
    return platform.system() == "Linux" and platform.machine() in ("x86_64", "aarch64")


def _download() -> bool:
    arch_map = {"x86_64": "amd64", "aarch64": "arm64"}
    arch = arch_map.get(platform.machine(), "amd64")
    url = (
        f"https://github.com/MetaCubeX/mihomo/releases/download/"
        f"{_MIHOMO_VERSION}/mihomo-linux-{arch}-{_MIHOMO_VERSION}.gz"
    )
    _BINARY_DIR.mkdir(parents=True, exist_ok=True)
    gz_path = _BINARY_DIR / "mihomo.gz"
    logger.info("Downloading mihomo %s …", _MIHOMO_VERSION)
    try:
        urllib.request.urlretrieve(url, gz_path)
        with gzip.open(gz_path, "rb") as fi, open(_binary_path(), "wb") as fo:
            shutil.copyfileobj(fi, fo)
        _binary_path().chmod(0o755)
        gz_path.unlink(missing_ok=True)
        logger.info("mihomo ready at %s", _binary_path())
        return True
    except Exception as e:
        logger.error("Failed to download mihomo: %s", e)
        gz_path.unlink(missing_ok=True)
        return False


def ensure_binary() -> bool:
    """Ensure mihomo binary is present. Returns True if ready to use."""
    if not is_supported():
        logger.info("mihomo not supported on %s %s", platform.system(), platform.machine())
        return False
    if _binary_path().exists():
        return True
    return _download()


# ---------------------------------------------------------------------------
# Config generation
# ---------------------------------------------------------------------------


def _make_config(proxies: list[dict]) -> dict:
    names = [p["name"] for p in proxies]
    return {
        "mixed-port": _MIXED_PORT,
        "allow-lan": False,
        "log-level": "silent",
        "external-controller": f"127.0.0.1:{_API_PORT}",
        "proxies": proxies,
        "proxy-groups": [
            {"name": "PROXY", "type": "select", "proxies": names + ["DIRECT"]}
        ],
        "rules": ["MATCH,DIRECT"],
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class MihomoRunner:
    """Context manager: start mihomo, expose test_all(), stop on exit."""

    def __init__(self, proxies: list[dict]) -> None:
        self._proxies = proxies
        self._proc: Optional[subprocess.Popen] = None
        self._cfg_dir: Optional[Path] = None

    def __enter__(self) -> "MihomoRunner":
        self._cfg_dir = Path(tempfile.mkdtemp(prefix="mihomo-cfg-"))
        cfg_file = self._cfg_dir / "config.yaml"
        cfg_file.write_text(
            yaml.dump(_make_config(self._proxies), allow_unicode=True),
            encoding="utf-8",
        )

        self._proc = subprocess.Popen(
            [str(_binary_path()), "-d", str(self._cfg_dir)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for API to become available (up to 10 s)
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
        raise RuntimeError("mihomo did not become ready within 10 s")

    def __exit__(self, *_) -> None:
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

    def _test_one(self, name: str, timeout_ms: int) -> Optional[int]:
        """Hit mihomo's delay API for a single proxy. Returns ms or None."""
        try:
            r = requests.get(
                f"{_API_URL}/proxies/{urllib.parse.quote(name, safe='')}/delay",
                params={"timeout": timeout_ms, "url": _TEST_URL},
                timeout=timeout_ms / 1000 + 3,
            )
            if r.ok:
                return r.json().get("delay")
        except Exception as e:
            logger.debug("test_one(%s) error: %s", name, e)
        return None

    def test_all(
        self,
        timeout_ms: int = 5000,
        concurrency: int = 50,
        on_done: Optional[Callable[[str, Optional[int]], None]] = None,
    ) -> dict[str, Optional[int]]:
        """Test all proxies in parallel via mihomo API. Returns {name: latency_ms}."""
        results: dict[str, Optional[int]] = {}
        names = [p["name"] for p in self._proxies]

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(self._test_one, name, timeout_ms): name for name in names
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    lat = future.result()
                except Exception:
                    lat = None
                results[name] = lat
                if on_done:
                    on_done(name, lat)

        return results


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------


def test_proxies(
    proxies: list[dict],
    timeout_ms: int = 5000,
    concurrency: int = 50,
    on_done: Optional[Callable[[str, Optional[int]], None]] = None,
) -> dict[str, Optional[int]]:
    """
    Download mihomo if needed, start it, test all proxies, return {name: latency_ms}.
    Returns empty dict if platform is unsupported or binary download fails.
    """
    if not ensure_binary():
        return {}
    try:
        with MihomoRunner(proxies) as runner:
            return runner.test_all(timeout_ms=timeout_ms, concurrency=concurrency, on_done=on_done)
    except Exception as e:
        logger.error("mihomo run failed: %s", e)
        return {}
