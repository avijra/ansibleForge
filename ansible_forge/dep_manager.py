"""Auto-install Python SDK dependencies for Ansible collections on demand.

When a user targets infrastructure (AWS, Azure, GCP, VMware, etc.), the
required Python libraries are installed automatically into a managed
site-packages directory (~/.ansibleforge/site-packages/). This eliminates
the need for users to manually install SDKs.

The architecture mirrors binary_resolver.py — download `uv` on first use
and cache packages locally.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import platform
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from ansible_forge.logging import get_logger

logger = get_logger(__name__)

_BIN_DIR = Path.home() / ".ansibleforge" / "bin"
MANAGED_SITE_PACKAGES = Path.home() / ".ansibleforge" / "site-packages"

UV_VERSION = "0.7.3"
UV_BASE_URL = "https://github.com/astral-sh/uv/releases/download"

# ---------------------------------------------------------------------------
# Collection -> pip packages mapping
# ---------------------------------------------------------------------------

COLLECTION_DEPS: dict[str, list[str]] = {
    # AWS
    "amazon.aws": ["boto3", "botocore", "jmespath"],
    "community.aws": ["boto3", "botocore", "jmespath"],
    # Azure
    "azure.azcollection": [
        "azure-identity",
        "azure-mgmt-resource",
        "azure-mgmt-compute",
        "azure-mgmt-network",
        "azure-mgmt-storage",
        "azure-mgmt-containerservice",
        "azure-mgmt-authorization",
        "azure-mgmt-dns",
        "azure-mgmt-keyvault",
        "azure-mgmt-web",
        "azure-mgmt-monitor",
    ],
    # GCP
    "google.cloud": [
        "google-auth",
        "google-cloud-compute",
        "google-cloud-storage",
        "google-cloud-dns",
        "google-api-python-client",
    ],
    # Kubernetes / OpenShift
    "kubernetes.core": ["kubernetes", "jsonpatch"],
    "redhat.openshift": ["kubernetes", "openshift-client"],
    # VMware
    "community.vmware": ["pyvmomi", "requests"],
    "vmware.vmware": ["pyvmomi", "requests"],
    # Docker
    "community.docker": ["docker"],
    # DigitalOcean
    "digitalocean.digital_ocean": ["pydo", "azure-core"],
    # Hetzner
    "hetzner.hcloud": ["hcloud"],
    # OVirt
    "ovirt.ovirt": ["ovirt-engine-sdk-python"],
    # Cisco
    "cisco.nxos": ["paramiko", "ncclient", "xmltodict"],
    "cisco.ios": ["paramiko", "ncclient", "xmltodict"],
    "cisco.iosxr": ["paramiko", "ncclient", "xmltodict"],
    "cisco.aci": ["requests"],
    "cisco.meraki": ["meraki"],
    # F5
    "f5networks.f5_modules": ["f5-sdk"],
    # Fortinet
    "fortinet.fortios": ["requests"],
    "fortinet.fortimanager": ["requests"],
    # Juniper
    "junipernetworks.junos": ["ncclient", "jxmlease", "xmltodict"],
    # Arista
    "arista.eos": ["paramiko"],
    # CloudFlare
    "community.cloudflare": ["requests"],
    # Windows / WinRM
    "ansible.windows": ["pywinrm"],
    "community.windows": ["pywinrm"],
    # General / common utilities
    "community.general": ["paramiko"],
    "community.network": ["paramiko", "ncclient"],
    # Proxmox
    "community.proxmox": ["proxmoxer", "requests"],
    # Grafana
    "community.grafana": ["requests"],
    # PostgreSQL
    "community.postgresql": ["psycopg2-binary"],
    # MySQL
    "community.mysql": ["pymysql"],
    # MongoDB
    "community.mongodb": ["pymongo"],
    # Consul / Vault
    "community.hashi_vault": ["hvac"],
    # Libvirt
    "community.libvirt": ["libvirt-python"],
    # Openstack
    "openstack.cloud": ["openstacksdk"],
    # Netbox
    "netbox.netbox": ["pynetbox"],
    # Palo Alto
    "paloaltonetworks.panos": ["pan-os-python"],
    # ServiceNow
    "servicenow.servicenow": ["pysnow"],
    # Infoblox
    "infoblox.nios_modules": ["infoblox-client"],
    # Zabbix
    "community.zabbix": ["zabbix-api"],
    # Datadog
    "community.datadog": ["datadog"],
    # Splunk
    "splunk.es": ["httpx"],
}

# Python import name -> pip package name (non-obvious mappings)
_MODULE_TO_PIP: dict[str, str] = {
    "yaml": "pyyaml",
    "OpenSSL": "pyopenssl",
    "Crypto": "pycryptodome",
    "cv2": "opencv-python",
    "PIL": "pillow",
    "git": "gitpython",
    "dateutil": "python-dateutil",
    "dns": "dnspython",
    "ldap": "python-ldap",
    "lxml": "lxml",
    "psycopg2": "psycopg2-binary",
    "pymysql": "pymysql",
    "botocore": "botocore",
    "boto3": "boto3",
    "azure": "azure-identity",
    "azure.identity": "azure-identity",
    "azure.mgmt": "azure-mgmt-resource",
    "google.auth": "google-auth",
    "google.cloud": "google-cloud-core",
    "kubernetes": "kubernetes",
    "openshift": "openshift-client",
    "docker": "docker",
    "pyVmomi": "pyvmomi",
    "pyvmomi": "pyvmomi",
    "ncclient": "ncclient",
    "paramiko": "paramiko",
    "winrm": "pywinrm",
    "xmltodict": "xmltodict",
    "jmespath": "jmespath",
    "requests": "requests",
    "hvac": "hvac",
    "proxmoxer": "proxmoxer",
    "pymongo": "pymongo",
    "psutil": "psutil",
    "netbox": "pynetbox",
    "pynetbox": "pynetbox",
    "hcloud": "hcloud",
    "ovirt": "ovirt-engine-sdk-python",
    "ovirtsdk4": "ovirt-engine-sdk-python",
    "libvirt": "libvirt-python",
    "openstacksdk": "openstacksdk",
    "openstack": "openstacksdk",
}

# Regex patterns for detecting missing modules in Ansible error output
_MISSING_MODULE_PATTERNS = [
    re.compile(r"ModuleNotFoundError:\s*No module named ['\"]([^'\"]+)['\"]"),
    re.compile(r"ImportError:\s*No module named ['\"]([^'\"]+)['\"]"),
    re.compile(r"Failed to import the required Python library \(([^)]+)\)"),
    re.compile(r"missing required library[:\s]+['\"]?(\w[\w.-]*)['\"]?", re.IGNORECASE),
    re.compile(r"requires the ([^\s]+) Python (?:library|module|package)"),
    re.compile(r'You need to install ["\']([^"\']+)["\'] prior to running'),
    re.compile(r"ansible\.errors\.AnsibleFilterError:.*install [\"']([^\"']+)[\"']"),
]


# ---------------------------------------------------------------------------
# UV download (mirrors binary_resolver.py pattern)
# ---------------------------------------------------------------------------


def _platform_key() -> tuple[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()

    os_map = {"darwin": "apple-darwin", "linux": "unknown-linux-gnu", "windows": "pc-windows-msvc"}
    arch_map = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }
    return arch_map.get(machine, machine), os_map.get(system, system)


def _uv_download_url(version: str) -> tuple[str, str]:
    arch, os_target = _platform_key()
    filename = f"uv-{arch}-{os_target}.zip"
    url = f"{UV_BASE_URL}/{version}/{filename}"
    return url, filename


def _download_file(url: str, dest: Path, label: str = "") -> None:
    logger.info("dep_downloading", url=url, label=label or dest.name)
    req = Request(url, headers={"User-Agent": "Tuyere/2.0"})
    with urlopen(req, timeout=180) as resp, open(dest, "wb") as f:  # noqa: S310
        downloaded = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
    logger.info("dep_downloaded", path=str(dest), size_mb=round(downloaded / 1024 / 1024, 1))


def _ensure_executable(path: Path) -> None:
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def download_uv(version: str = UV_VERSION) -> Path:
    """Download the uv binary and cache it in ~/.ansibleforge/bin/."""
    binary_name = "uv.exe" if platform.system().lower() == "windows" else "uv"
    cached = _BIN_DIR / binary_name

    version_marker = _BIN_DIR / ".uv_version"
    if cached.is_file() and version_marker.is_file():
        installed = version_marker.read_text().strip()
        if installed == version:
            return cached

    _BIN_DIR.mkdir(parents=True, exist_ok=True)
    url, filename = _uv_download_url(version)

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / filename
        _download_file(url, archive, label=f"uv {version}")

        dest = Path(tmp) / "extracted"
        dest.mkdir()
        with zipfile.ZipFile(archive, "r") as zf:
            for name in zf.namelist():
                if name.endswith(binary_name):
                    zf.extract(name, dest)
                    extracted = dest / name
                    target = _BIN_DIR / binary_name
                    if extracted != target:
                        shutil.move(str(extracted), str(target))
                    _ensure_executable(target)
                    break
            else:
                raise FileNotFoundError(f"{binary_name} not found in archive {filename}")

    version_marker.write_text(version)
    logger.info("uv_installed", version=version, path=str(cached))
    return cached


async def download_uv_async(version: str = UV_VERSION) -> Path:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, download_uv, version)


# ---------------------------------------------------------------------------
# Package installer resolution
# ---------------------------------------------------------------------------


def _resolve_uv_binary() -> str:
    """Find the uv binary: cached, system, or download."""
    binary_name = "uv.exe" if platform.system().lower() == "windows" else "uv"
    cached_uv = _BIN_DIR / binary_name
    if cached_uv.is_file():
        return str(cached_uv)

    system_uv = shutil.which("uv")
    if system_uv:
        return system_uv

    path = download_uv()
    return str(path)


def _resolve_installer() -> tuple[str, list[str]]:
    """Find the best available package installer.

    In frozen mode with a standalone Python, installs into that interpreter's
    site-packages via ``uv pip install --python <path>``. Otherwise falls back
    to ``--target ~/.ansibleforge/site-packages/``.

    Returns (binary_path, base_args).
    """
    standalone_python = _get_standalone_python()

    if standalone_python:
        uv = _resolve_uv_binary()
        return uv, ["pip", "install", "--python", standalone_python, "--break-system-packages"]

    binary_name = "uv.exe" if platform.system().lower() == "windows" else "uv"
    cached_uv = _BIN_DIR / binary_name
    if cached_uv.is_file():
        return str(cached_uv), ["pip", "install", "--target"]

    system_uv = shutil.which("uv")
    if system_uv:
        return system_uv, ["pip", "install", "--target"]

    system_pip = shutil.which("pip3") or shutil.which("pip")
    if system_pip:
        return system_pip, ["install", "--target"]

    path = download_uv()
    return str(path), ["pip", "install", "--target"]


def _get_standalone_python() -> str | None:
    """Return standalone Python path if available (frozen mode only)."""
    import sys
    if not getattr(sys, "frozen", False):
        return None
    try:
        from ansible_forge.tools.python_resolver import resolve_standalone_python
        return resolve_standalone_python()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def _dir_has_package(directory: Path, normalized: str) -> bool:
    """Check if a normalized package name exists as a dist-info in a directory."""
    if not directory.is_dir():
        return False
    for entry in directory.iterdir():
        entry_name = entry.name.lower().replace("-", "_").replace(".", "_")
        if entry_name == normalized:
            return True
        if entry_name.startswith(normalized + "-") or entry_name.startswith(normalized + "_"):
            return True
    return False


def _standalone_site_packages() -> Path | None:
    """Derive site-packages from the standalone Python binary path."""
    standalone = _get_standalone_python()
    if not standalone:
        return None
    bin_dir = Path(standalone).parent
    lib_dir = bin_dir.parent / "lib"
    if not lib_dir.is_dir():
        return None
    for child in lib_dir.iterdir():
        sp = child / "site-packages"
        if sp.is_dir():
            return sp
    return None


def _is_package_installed(package: str) -> bool:
    """Check if a package is already installed (managed site-packages or standalone Python)."""
    normalized = package.lower().replace("-", "_").replace(".", "_")

    if _dir_has_package(MANAGED_SITE_PACKAGES, normalized):
        return True

    standalone_sp = _standalone_site_packages()
    return bool(standalone_sp and _dir_has_package(standalone_sp, normalized))


async def ensure_packages(packages: list[str], reason: str = "") -> tuple[bool, str]:
    """Install packages into managed site-packages if not already present.

    Returns (success, human_readable_message).
    """
    if not packages:
        return True, ""

    needed = [p for p in packages if not _is_package_installed(p)]
    if not needed:
        logger.info("deps_already_installed", packages=packages, reason=reason)
        return True, ""

    MANAGED_SITE_PACKAGES.mkdir(parents=True, exist_ok=True)

    try:
        installer, base_args = _resolve_installer()
    except Exception as exc:
        msg = f"Failed to resolve package installer: {exc}"
        logger.error("dep_installer_resolve_failed", error=str(exc))
        return False, msg

    uses_python_target = "--python" in base_args
    if uses_python_target:
        cmd = [installer, *base_args, *needed]
    else:
        cmd = [installer, *base_args, str(MANAGED_SITE_PACKAGES), "--system", *needed]
        if "pip" in Path(installer).name.lower() and base_args[0] != "pip":
            cmd = [installer, *base_args, str(MANAGED_SITE_PACKAGES), *needed]

    logger.info("dep_installing", packages=needed, reason=reason, cmd=" ".join(cmd))

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_installer_env(),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    except asyncio.CancelledError:
        if proc is not None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
        raise
    except TimeoutError:
        if proc is not None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
        msg = f"Package install timed out after 300s: {needed}"
        logger.error("dep_install_timeout", packages=needed)
        return False, msg
    except Exception as exc:
        msg = f"Package install failed: {exc}"
        logger.error("dep_install_error", packages=needed, error=str(exc))
        return False, msg

    if proc.returncode != 0:
        error_text = stderr.decode(errors="replace").strip()
        msg = f"Failed to install {needed}: {error_text[:500]}"
        logger.error("dep_install_failed", packages=needed, rc=proc.returncode, stderr=error_text[:500])
        return False, msg

    msg = f"Installed Python dependencies: {', '.join(needed)}"
    logger.info("dep_install_success", packages=needed, reason=reason)
    return True, msg


def _installer_env() -> dict[str, str]:
    """Build environment for the installer subprocess.

    When a standalone Python is in use, strips PyInstaller-specific vars
    that could interfere with the real CPython interpreter.
    """
    standalone = _get_standalone_python()
    if standalone:
        from ansible_forge.tools.python_resolver import _sanitized_env
        env = _sanitized_env()
    else:
        env = os.environ.copy()

    ssl_cert = env.get("SSL_CERT_FILE", "")
    if ssl_cert:
        env.setdefault("REQUESTS_CA_BUNDLE", ssl_cert)
    return env


async def ensure_deps_for_playbook(playbook_path: Path) -> None:
    """Scan a playbook (and its roles) for collection module usage and
    proactively install the required Python packages.

    This runs before execution so the user never sees a missing-package
    error for a known collection.
    """
    collections_used: set[str] = set()
    try:
        _scan_yaml_for_collections(playbook_path, collections_used)
        ws = playbook_path.parent
        if ws.name == "playbooks":
            ws = ws.parent
        roles_dir = ws / "roles"
        if roles_dir.is_dir():
            for task_file in roles_dir.rglob("tasks/*.yml"):
                _scan_yaml_for_collections(task_file, collections_used)
            for task_file in roles_dir.rglob("tasks/*.yaml"):
                _scan_yaml_for_collections(task_file, collections_used)
    except Exception as exc:
        logger.debug("playbook_dep_scan_error", error=str(exc)[:200])
        return

    all_deps: list[str] = []
    for collection in collections_used:
        deps = COLLECTION_DEPS.get(collection, [])
        all_deps.extend(deps)

    if all_deps:
        seen: set[str] = set()
        unique = [d for d in all_deps if d not in seen and not seen.add(d)]  # type: ignore[func-returns-value]
        ok, msg = await ensure_packages(unique, reason=f"collections: {', '.join(collections_used)}")
        if ok and unique:
            logger.info("proactive_deps_installed", packages=unique, collections=list(collections_used))


def _scan_yaml_for_collections(path: Path, out: set[str]) -> None:
    """Read a YAML file and extract collection namespace prefixes from
    module names (e.g. ``amazon.aws.ec2_instance`` → ``amazon.aws``)."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for match in re.finditer(r"(\w+\.\w+)\.\w+", content):
        candidate = match.group(1)
        if candidate in COLLECTION_DEPS:
            out.add(candidate)


async def ensure_collection_deps(collection_name: str) -> tuple[bool, str]:
    """Install Python dependencies required by an Ansible collection.

    Looks up the collection in COLLECTION_DEPS and installs any missing packages.
    """
    deps = COLLECTION_DEPS.get(collection_name)
    if not deps:
        # Try partial match (e.g. "amazon.aws" from "amazon.aws:7.0.0")
        base_name = collection_name.split(":")[0].strip()
        deps = COLLECTION_DEPS.get(base_name)

    if not deps:
        return True, ""

    return await ensure_packages(deps, reason=f"collection:{collection_name}")


# ---------------------------------------------------------------------------
# Error parsing
# ---------------------------------------------------------------------------


def parse_missing_module(error_text: str) -> str | None:
    """Extract the missing Python module name from Ansible error output.

    Returns the first detected module name (root package only).
    For multi-package errors like ``(botocore and boto3)``, use
    ``parse_missing_modules`` which returns all of them.
    """
    modules = parse_missing_modules(error_text)
    return modules[0] if modules else None


def parse_missing_modules(error_text: str) -> list[str]:
    """Extract all missing Python module names from Ansible error output.

    Handles single modules, ``X and Y``, and ``X, Y, and Z`` formats
    commonly produced by Ansible's module-level import error messages.
    """
    if not error_text:
        return []

    for pattern in _MISSING_MODULE_PATTERNS:
        match = pattern.search(error_text)
        if match:
            raw = match.group(1).strip()
            parts = re.split(r"\s+and\s+|,\s*", raw)
            modules = []
            for part in parts:
                cleaned = part.strip().strip("'\"")
                if cleaned:
                    modules.append(cleaned.split(".")[0])
            return [m for m in modules if m]
    return []


def guess_pip_package(module_name: str) -> str:
    """Map a Python module import name to the corresponding pip package name."""
    if module_name in _MODULE_TO_PIP:
        return _MODULE_TO_PIP[module_name]
    return module_name


def guess_pip_packages(module_names: list[str]) -> list[str]:
    """Map a list of module import names to pip package names (deduplicated)."""
    seen: set[str] = set()
    result: list[str] = []
    for name in module_names:
        pkg = guess_pip_package(name)
        if pkg not in seen:
            seen.add(pkg)
            result.append(pkg)
    return result
