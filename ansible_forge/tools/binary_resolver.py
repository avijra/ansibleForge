"""Auto-download and resolve external tool binaries (Terraform, OpenTofu).

When AnsibleForge runs as a packaged app, users should never have to manually
install CLI tools. This module downloads binaries on first use and caches them
in ~/.ansibleforge/bin/.
"""

from __future__ import annotations

import asyncio
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from ansible_forge.logging import get_logger

logger = get_logger(__name__)

_BIN_DIR = Path.home() / ".ansibleforge" / "bin"

TOFU_VERSION = "1.9.1"
TOFU_BASE_URL = "https://github.com/opentofu/opentofu/releases/download"


def _platform_key() -> tuple[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()

    os_map = {"darwin": "darwin", "linux": "linux", "windows": "windows"}
    arch_map = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }

    return os_map.get(system, system), arch_map.get(machine, machine)


def _tofu_download_url(version: str) -> tuple[str, str]:
    os_name, arch = _platform_key()
    ext = "zip" if os_name == "windows" else "tar.gz"
    filename = f"tofu_{version}_{os_name}_{arch}.{ext}"
    url = f"{TOFU_BASE_URL}/v{version}/{filename}"
    return url, filename


def _extract_binary(archive_path: Path, dest_dir: Path, binary_name: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)

    if archive_path.name.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith(binary_name) or name == binary_name:
                    zf.extract(name, dest_dir)
                    extracted = dest_dir / name
                    target = dest_dir / binary_name
                    if extracted != target:
                        extracted.rename(target)
                    return target
    elif archive_path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive_path, "r:gz") as tf:
            for member in tf.getmembers():
                if member.name.endswith(binary_name) or member.name == binary_name:
                    tf.extract(member, dest_dir)
                    extracted = dest_dir / member.name
                    target = dest_dir / binary_name
                    if extracted != target:
                        extracted.rename(target)
                    return target

    raise FileNotFoundError(f"{binary_name} not found in archive {archive_path.name}")


def _download_file(url: str, dest: Path, label: str = "") -> None:
    logger.info("binary_downloading", url=url, label=label or dest.name)
    req = Request(url, headers={"User-Agent": "Tuyere/1.0"})
    with urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        downloaded = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
    logger.info("binary_downloaded", path=str(dest), size_mb=round(downloaded / 1024 / 1024, 1))


def _ensure_executable(path: Path) -> None:
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def download_tofu(version: str = TOFU_VERSION) -> Path:
    binary_name = "tofu.exe" if platform.system().lower() == "windows" else "tofu"
    cached = _BIN_DIR / binary_name

    version_marker = _BIN_DIR / ".tofu_version"
    if cached.is_file() and version_marker.is_file():
        installed = version_marker.read_text().strip()
        if installed == version:
            return cached

    url, filename = _tofu_download_url(version)

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / filename
        _download_file(url, archive, label=f"OpenTofu {version}")
        result = _extract_binary(archive, _BIN_DIR, binary_name)
        _ensure_executable(result)

    version_marker.write_text(version)
    logger.info("tofu_installed", version=version, path=str(cached))
    return cached


async def download_tofu_async(version: str = TOFU_VERSION) -> Path:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, download_tofu, version)


def resolve_terraform() -> str | None:
    bundled = _BIN_DIR / ("tofu.exe" if platform.system().lower() == "windows" else "tofu")
    if bundled.is_file():
        return str(bundled)

    if getattr(sys, "frozen", False):
        bundle_dir = Path(sys.executable).resolve().parent
        for name in ("terraform", "tofu", "terraform.exe", "tofu.exe"):
            candidate = bundle_dir / name
            if candidate.is_file():
                return str(candidate)

    system_tf = shutil.which("terraform")
    if system_tf:
        return system_tf

    system_tofu = shutil.which("tofu")
    if system_tofu:
        return system_tofu

    return None


def resolve_terraform_or_download() -> str:
    found = resolve_terraform()
    if found:
        return found

    path = download_tofu()
    return str(path)


async def resolve_terraform_or_download_async() -> str:
    found = resolve_terraform()
    if found:
        return found

    path = await download_tofu_async()
    return str(path)
