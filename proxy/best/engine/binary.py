"""Binary download and management for proxy test engines.

Handles platform detection, PATH lookup, cache directory, and auto-download
from GitHub Releases for xray-core, sing-box, and mihomo.
"""

from __future__ import annotations

import gzip
import io
import logging
import platform
import shutil
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

CACHE_DIR = Path(tempfile.gettempdir()) / "best-proxy-bin"


def _system() -> str:
    return platform.system().lower()  # linux, windows, darwin


def _arch() -> str:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "amd64"
    if m in ("aarch64", "arm64"):
        return "arm64"
    return m


def find_binary(name: str, config_path: str = "") -> Path | None:
    """Find a binary by: 1) config path, 2) PATH, 3) cache dir."""
    # 1. Explicit config path
    if config_path:
        p = Path(config_path)
        if p.exists():
            return p

    # 2. System PATH
    exe = name + (".exe" if _system() == "windows" else "")
    found = shutil.which(exe)
    if found:
        return Path(found)

    # 3. Cache dir
    cached = CACHE_DIR / exe
    if cached.exists():
        return cached

    return None


def _download_file(url: str) -> bytes | None:
    logger.info("Downloading %s …", url)
    try:
        resp = requests.get(url, timeout=120, stream=True)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.error("Download failed: %s", e)
        return None


def _make_executable(path: Path) -> None:
    if _system() != "windows":
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


# ---------------------------------------------------------------------------
# Xray
# ---------------------------------------------------------------------------

_XRAY_VERSION = "v25.3.6"


def _xray_asset_name() -> str:
    sys = _system()
    arch = _arch()
    if sys == "windows":
        return f"Xray-windows-64.zip" if arch == "amd64" else f"Xray-windows-arm64-v8a.zip"
    if sys == "linux":
        return f"Xray-linux-64.zip" if arch == "amd64" else f"Xray-linux-arm64-v8a.zip"
    if sys == "darwin":
        return f"Xray-macos-64.zip" if arch == "amd64" else f"Xray-macos-arm64-v8a.zip"
    return ""


def download_xray() -> Path | None:
    asset = _xray_asset_name()
    if not asset:
        return None
    url = f"https://github.com/XTLS/Xray-core/releases/download/{_XRAY_VERSION}/{asset}"
    data = _download_file(url)
    if not data:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    exe = "xray.exe" if _system() == "windows" else "xray"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if info.filename.lower() in (exe, "xray", "xray.exe"):
                    dest = CACHE_DIR / exe
                    with zf.open(info) as src, open(dest, "wb") as dst:
                        dst.write(src.read())
                    _make_executable(dest)
                    logger.info("xray ready at %s", dest)
                    return dest
    except Exception as e:
        logger.error("Failed to extract xray: %s", e)
    return None


# ---------------------------------------------------------------------------
# sing-box
# ---------------------------------------------------------------------------

_SINGBOX_VERSION = "1.11.8"


def _singbox_asset_name() -> str:
    sys = _system()
    arch = _arch()
    if sys == "windows":
        return f"sing-box-{_SINGBOX_VERSION}-{sys}-{arch}.zip"
    return f"sing-box-{_SINGBOX_VERSION}-{sys}-{arch}.tar.gz"


def download_singbox() -> Path | None:
    asset = _singbox_asset_name()
    url = (
        f"https://github.com/SagerNet/sing-box/releases/download/"
        f"v{_SINGBOX_VERSION}/{asset}"
    )
    data = _download_file(url)
    if not data:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    exe = "sing-box.exe" if _system() == "windows" else "sing-box"
    dest = CACHE_DIR / exe
    try:
        if asset.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    if Path(info.filename).name in (exe, "sing-box", "sing-box.exe"):
                        with zf.open(info) as src, open(dest, "wb") as dst:
                            dst.write(src.read())
                        _make_executable(dest)
                        logger.info("sing-box ready at %s", dest)
                        return dest
        else:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                for member in tf.getmembers():
                    if Path(member.name).name in (exe, "sing-box", "sing-box.exe"):
                        f = tf.extractfile(member)
                        if f:
                            dest.write_bytes(f.read())
                            _make_executable(dest)
                            logger.info("sing-box ready at %s", dest)
                            return dest
    except Exception as e:
        logger.error("Failed to extract sing-box: %s", e)
    return None


# ---------------------------------------------------------------------------
# mihomo
# ---------------------------------------------------------------------------

_MIHOMO_VERSION = "v1.19.0"


def _mihomo_asset_name() -> str:
    sys = _system()
    arch = _arch()
    if sys == "windows":
        return f"mihomo-windows-{arch}-{_MIHOMO_VERSION}.zip"
    if sys == "darwin":
        return f"mihomo-darwin-{arch}-{_MIHOMO_VERSION}.gz"
    return f"mihomo-linux-{arch}-{_MIHOMO_VERSION}.gz"


def download_mihomo() -> Path | None:
    asset = _mihomo_asset_name()
    url = (
        f"https://github.com/MetaCubeX/mihomo/releases/download/"
        f"{_MIHOMO_VERSION}/{asset}"
    )
    data = _download_file(url)
    if not data:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    exe = "mihomo.exe" if _system() == "windows" else "mihomo"
    dest = CACHE_DIR / exe
    try:
        if asset.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    if info.filename.lower() in (exe, "mihomo", "mihomo.exe"):
                        with zf.open(info) as src, open(dest, "wb") as dst:
                            dst.write(src.read())
                        break
        elif asset.endswith(".gz"):
            dest.write_bytes(gzip.decompress(data))
        _make_executable(dest)
        logger.info("mihomo ready at %s", dest)
        return dest
    except Exception as e:
        logger.error("Failed to extract mihomo: %s", e)
    return None


def ensure_binary(name: str, config_path: str = "") -> Path | None:
    """Find or download a binary. Returns path or None."""
    existing = find_binary(name, config_path)
    if existing:
        return existing
    downloaders = {
        "xray": download_xray,
        "sing-box": download_singbox,
        "mihomo": download_mihomo,
    }
    dl = downloaders.get(name)
    if dl:
        return dl()
    return None
