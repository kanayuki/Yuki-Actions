"""Proxy engine binary management.

Manages xray-core, sing-box, and mihomo binaries in proxy/bin/.
Fetches latest versions from GitHub Releases API.

Public API
----------
BIN_DIR          : Path  — proxy/bin/ (persistent binary cache)
find_binary(name, config_path="") -> Path | None
ensure_binary(name, config_path="") -> Path | None
get_latest_version(name, token="") -> str | None
check_updates(token="") -> dict[str, tuple[str|None, str|None]]
update_binary(name, token="") -> Path | None
update_all(token="")  — update all binaries to latest

CLI
---
python proxy/core/binary.py --check       # print version status
python proxy/core/binary.py --update      # update all to latest
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import platform
import shutil
import stat
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

logger = logging.getLogger(__name__)

# Persistent binary directory — stored in data branch
BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
_VERSIONS_FILE = BIN_DIR / "versions.json"


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


def _system() -> str:
    return platform.system().lower()  # linux | windows | darwin


def _arch() -> str:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "amd64"
    if m in ("aarch64", "arm64"):
        return "arm64"
    return m


def _exe(name: str) -> str:
    return name + (".exe" if _system() == "windows" else "")


# ---------------------------------------------------------------------------
# Version file
# ---------------------------------------------------------------------------


def _load_versions() -> dict[str, str]:
    if _VERSIONS_FILE.exists():
        try:
            return json.loads(_VERSIONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_versions(versions: dict[str, str]) -> None:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    _VERSIONS_FILE.write_text(json.dumps(versions, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Binary registry
# ---------------------------------------------------------------------------


@dataclass
class BinarySpec:
    repo: str                                           # GitHub "owner/repo"
    exe: str                                            # binary name without .exe
    asset_fn: Callable[[], str]                         # returns asset filename for platform
    extract_fn: Callable[[bytes, Path], Path | None]    # returns path to extracted binary


def _xray_asset() -> str:
    sys_, arch = _system(), _arch()
    if sys_ == "windows":
        return "Xray-windows-64.zip" if arch == "amd64" else "Xray-windows-arm64-v8a.zip"
    if sys_ == "linux":
        return "Xray-linux-64.zip" if arch == "amd64" else "Xray-linux-arm64-v8a.zip"
    if sys_ == "darwin":
        return "Xray-macos-64.zip" if arch == "amd64" else "Xray-macos-arm64-v8a.zip"
    return ""


def _singbox_asset() -> str:
    sys_, arch, ver = _system(), _arch(), "{version}"
    suffix = "zip" if sys_ == "windows" else "tar.gz"
    return f"sing-box-{ver}-{sys_}-{arch}.{suffix}"


def _mihomo_asset() -> str:
    sys_, arch, ver = _system(), _arch(), "{version}"
    if sys_ == "windows":
        return f"mihomo-windows-{arch}-{ver}.zip"
    if sys_ == "darwin":
        return f"mihomo-darwin-{arch}-{ver}.gz"
    return f"mihomo-linux-{arch}-{ver}.gz"


def _extract_zip_match(data: bytes, dest: Path) -> Path | None:
    """Extract first matching binary from a zip archive."""
    exe = _exe(dest.name)
    stem = dest.stem
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                fname = Path(info.filename).name.lower()
                if fname in (exe.lower(), stem.lower(), stem.lower() + ".exe"):
                    with zf.open(info) as src:
                        dest.write_bytes(src.read())
                    _make_executable(dest)
                    return dest
    except Exception as e:
        logger.error("zip extract failed: %s", e)
    return None


def _extract_archive(data: bytes, dest: Path) -> Path | None:
    """Extract binary from tar.gz or zip, choosing by asset suffix."""
    exe = _exe(dest.name)
    stem = dest.stem
    try:
        if data[:2] == b"PK":  # zip magic
            return _extract_zip_match(data, dest)
        # tar.gz
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for member in tf.getmembers():
                fname = Path(member.name).name.lower()
                if fname in (exe.lower(), stem.lower(), stem.lower() + ".exe"):
                    f = tf.extractfile(member)
                    if f:
                        dest.write_bytes(f.read())
                        _make_executable(dest)
                        return dest
    except Exception as e:
        logger.error("archive extract failed: %s", e)
    return None


def _extract_gz_or_zip(data: bytes, dest: Path) -> Path | None:
    """Mihomo: either .gz (single file) or .zip."""
    try:
        if data[:2] == b"PK":
            return _extract_zip_match(data, dest)
        # .gz single-file
        dest.write_bytes(gzip.decompress(data))
        _make_executable(dest)
        return dest
    except Exception as e:
        logger.error("gz/zip extract failed: %s", e)
    return None


def _make_executable(path: Path) -> None:
    if _system() != "windows":
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


BINARY_REGISTRY: dict[str, BinarySpec] = {
    "xray": BinarySpec(
        repo="XTLS/Xray-core",
        exe="xray",
        asset_fn=_xray_asset,
        extract_fn=_extract_zip_match,
    ),
    "sing-box": BinarySpec(
        repo="SagerNet/sing-box",
        exe="sing-box",
        asset_fn=_singbox_asset,
        extract_fn=_extract_archive,
    ),
    "mihomo": BinarySpec(
        repo="MetaCubeX/mihomo",
        exe="mihomo",
        asset_fn=_mihomo_asset,
        extract_fn=_extract_gz_or_zip,
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_binary(name: str, config_path: str = "") -> Path | None:
    """Locate a binary. Search order: config_path → BIN_DIR → system PATH."""
    if config_path:
        p = Path(config_path)
        if p.exists():
            return p

    spec = BINARY_REGISTRY.get(name)
    exe = _exe(spec.exe if spec else name)

    cached = BIN_DIR / exe
    if cached.exists():
        return cached

    found = shutil.which(exe)
    if found:
        return Path(found)

    return None


def ensure_binary(name: str, config_path: str = "") -> Path | None:
    """Find binary or download it to BIN_DIR. Returns path or None."""
    existing = find_binary(name, config_path)
    if existing:
        return existing
    logger.info("Binary '%s' not found — downloading to %s", name, BIN_DIR)
    return _download_binary(name, version=None)


def get_latest_version(name: str, token: str = "") -> str | None:
    """Query GitHub Releases API for the latest tag of *name*."""
    spec = BINARY_REGISTRY.get(name)
    if not spec:
        return None
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{spec.repo}/releases/latest"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.ok:
            return resp.json().get("tag_name")
        logger.warning("GitHub API %d for %s", resp.status_code, spec.repo)
    except Exception as e:
        logger.warning("GitHub API error for %s: %s", name, e)
    return None


def check_updates(token: str = "") -> dict[str, tuple[str | None, str | None]]:
    """Return {name: (installed_version, latest_version)} for all binaries."""
    versions = _load_versions()
    result: dict[str, tuple[str | None, str | None]] = {}
    for name in BINARY_REGISTRY:
        installed = versions.get(name)
        latest = get_latest_version(name, token)
        result[name] = (installed, latest)
    return result


def _download_binary(name: str, version: str | None) -> Path | None:
    spec = BINARY_REGISTRY.get(name)
    if not spec:
        logger.error("Unknown binary: %s", name)
        return None

    if version is None:
        version = get_latest_version(name)
    if version is None:
        logger.error("Could not determine latest version for %s", name)
        return None

    # Resolve version placeholder in asset name
    asset = spec.asset_fn()
    asset = asset.replace("{version}", version.lstrip("v"))

    if not asset:
        logger.error("No asset name for platform %s/%s", _system(), _arch())
        return None

    tag = version if version.startswith("v") else f"v{version}"
    url = f"https://github.com/{spec.repo}/releases/download/{tag}/{asset}"
    logger.info("Downloading %s %s from %s", name, version, url)

    try:
        resp = requests.get(url, timeout=180, stream=True)
        resp.raise_for_status()
        data = resp.content
    except Exception as e:
        logger.error("Download failed for %s: %s", name, e)
        return None

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    dest = BIN_DIR / _exe(spec.exe)
    result = spec.extract_fn(data, dest)

    if result:
        versions = _load_versions()
        versions[name] = version
        _save_versions(versions)
        logger.info("%s %s installed at %s", name, version, dest)

    return result


def update_binary(name: str, token: str = "") -> Path | None:
    """Download latest version if newer than installed. Returns path or None."""
    versions = _load_versions()
    installed = versions.get(name)
    latest = get_latest_version(name, token)

    if latest is None:
        logger.warning("Could not fetch latest version for %s", name)
        return None

    if installed == latest:
        logger.info("%s is up to date (%s)", name, installed)
        existing = find_binary(name)
        return existing

    logger.info("%s: %s → %s", name, installed or "none", latest)
    return _download_binary(name, latest)


def update_all(token: str = "") -> None:
    """Update all binaries to their latest GitHub releases."""
    for name in BINARY_REGISTRY:
        result = update_binary(name, token)
        status = f"✓ {result}" if result else "✗ failed"
        print(f"  {name:12s} {status}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _cli() -> None:
    import os

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    token = os.environ.get("GITHUB_TOKEN", "")
    args = sys.argv[1:]

    if "--check" in args:
        print(f"{'Binary':<12}  {'Installed':<16}  {'Latest':<16}  Status")
        print("-" * 60)
        for name, (installed, latest) in check_updates(token).items():
            status = "up-to-date" if installed == latest else ("update available" if latest else "unknown")
            print(f"{name:<12}  {installed or '—':<16}  {latest or '—':<16}  {status}")

    elif "--update" in args:
        print("Updating binaries…")
        update_all(token)
        print("Done.")

    else:
        print("Usage: python proxy/core/binary.py [--check | --update]")
        sys.exit(1)


if __name__ == "__main__":
    _cli()
