"""Resolve or auto-install a standalone Python for Ansible module execution.

PyInstaller's frozen Python cannot run AnsiballZ (Ansible's module wrapper)
because it relies on restricted importlib, _MEIPASS temp dirs, and missing
dynamic module loading. This module provides a *real* CPython interpreter
downloaded on first use via uv (python-build-standalone), cached at
~/.ansibleforge/python/.

The standalone Python is used ONLY as the Ansible target interpreter
(ansible_python_interpreter) for localhost/local connections. Remote hosts
continue to use their own Python via auto-discovery.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from ansible_forge.logging import get_logger

logger = get_logger(__name__)

_ANSIBLEFORGE_DIR = Path.home() / ".ansibleforge"
_PYTHON_DIR = _ANSIBLEFORGE_DIR / "python"
_PYTHON_VERSION = "3.12"
_VERSION_MARKER = _PYTHON_DIR / ".python_version"

_cached_interpreter: str | None = None


def _find_standalone_python() -> str | None:
    """Return the path to the standalone Python binary, or None if not installed."""
    if not _PYTHON_DIR.is_dir():
        return None

    for candidate in _PYTHON_DIR.rglob("bin/python3"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    for candidate in _PYTHON_DIR.rglob("python.exe"):
        if candidate.is_file():
            return str(candidate)

    return None


def _resolve_uv() -> str | None:
    """Find uv binary: cached in ~/.ansibleforge/bin/ or on system PATH."""
    binary_name = "uv.exe" if platform.system().lower() == "windows" else "uv"
    cached = _ANSIBLEFORGE_DIR / "bin" / binary_name
    if cached.is_file():
        return str(cached)
    return shutil.which("uv")


def _sanitized_env() -> dict[str, str]:
    """Build a clean environment for spawning the standalone Python.

    Strips PyInstaller-specific vars (_MEIPASS, LD_LIBRARY_PATH anchored to
    frozen bundle) that would interfere with a real CPython.
    """
    env = os.environ.copy()

    meipass = env.pop("_MEIPASS", None)

    for key in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"):
        val = env.get(key, "")
        if not val:
            continue
        if meipass:
            parts = [p for p in val.split(os.pathsep) if meipass not in p]
        else:
            parts = [p for p in val.split(os.pathsep) if "_internal" not in p]
        if parts:
            env[key] = os.pathsep.join(parts)
        else:
            env.pop(key, None)

    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)

    return env


def install_standalone_python() -> str:
    """Install a standalone Python via uv and return its path.

    Uses `uv python install` which downloads python-build-standalone and
    handles path fixups automatically.
    """
    _PYTHON_DIR.mkdir(parents=True, exist_ok=True)

    uv = _resolve_uv()
    if not uv:
        from ansible_forge.dep_manager import download_uv
        uv = str(download_uv())

    env = _sanitized_env()
    env["UV_PYTHON_INSTALL_DIR"] = str(_PYTHON_DIR)

    logger.info("standalone_python_installing", version=_PYTHON_VERSION, via="uv")

    result = subprocess.run(
        [uv, "python", "install", _PYTHON_VERSION],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )

    if result.returncode != 0:
        error = result.stderr[:500]
        logger.error("standalone_python_install_failed", rc=result.returncode, stderr=error)
        raise RuntimeError(f"Failed to install standalone Python {_PYTHON_VERSION}: {error}")

    python_path = _find_standalone_python()
    if not python_path:
        raise RuntimeError(
            f"uv python install succeeded but no python3 binary found under {_PYTHON_DIR}"
        )

    _validate_interpreter(python_path)

    _VERSION_MARKER.write_text(f"{_PYTHON_VERSION}\n{python_path}\n")
    logger.info("standalone_python_installed", path=python_path)
    return python_path


async def install_standalone_python_async() -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, install_standalone_python)


def _validate_interpreter(python_path: str) -> None:
    """Verify the standalone Python can execute basic operations AnsiballZ needs."""
    test_code = "import sys, json, zipimport, tempfile; print(json.dumps({'ok': True}))"
    result = subprocess.run(
        [python_path, "-c", test_code],
        capture_output=True,
        text=True,
        env=_sanitized_env(),
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Standalone Python validation failed (rc={result.returncode}): "
            f"{result.stderr[:300]}"
        )


def resolve_standalone_python() -> str | None:
    """Return the standalone Python path if available.

    Does NOT trigger installation — call install_standalone_python() for that.
    Uses version marker for fast lookups.
    """
    if _VERSION_MARKER.is_file():
        lines = _VERSION_MARKER.read_text().strip().splitlines()
        if len(lines) >= 2:
            cached_path = lines[1]
            if Path(cached_path).is_file():
                return cached_path

    return _find_standalone_python()


def resolve_python_for_localhost() -> str:
    """Return the best Python interpreter for localhost Ansible execution.

    Priority:
    1. Cached result from a previous resolution
    2. Standalone Python (real CPython, handles AnsiballZ)
    3. System Python (dev mode only, from venv)
    4. 'auto_silent' (let Ansible discover — last resort)
    """
    global _cached_interpreter
    if _cached_interpreter:
        return _cached_interpreter

    standalone = resolve_standalone_python()
    if standalone:
        _cached_interpreter = standalone
        return standalone

    if not getattr(sys, "frozen", False):
        _cached_interpreter = sys.executable
        return sys.executable

    return "auto_silent"


def resolve_or_install_python_for_localhost() -> str:
    """Like resolve_python_for_localhost but installs if missing (frozen mode).

    This is the function all execution paths should use. It ensures the
    standalone Python is available before returning, downloading it via
    uv if necessary. The result is cached module-wide so subsequent calls
    are free.
    """
    global _cached_interpreter
    if _cached_interpreter:
        return _cached_interpreter

    standalone = resolve_standalone_python()
    if standalone:
        _cached_interpreter = standalone
        return standalone

    if not getattr(sys, "frozen", False):
        _cached_interpreter = sys.executable
        return sys.executable

    try:
        path = install_standalone_python()
        _cached_interpreter = path
        return path
    except Exception as exc:
        logger.error("standalone_python_install_failed", error=str(exc))
        return "auto_silent"


async def resolve_or_install_python_async() -> str:
    """Async variant — runs installation in a thread pool to avoid blocking
    the event loop.  Safe to call from any async context; the first call
    may take a few seconds if uv needs to download Python."""
    global _cached_interpreter
    if _cached_interpreter:
        return _cached_interpreter

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, resolve_or_install_python_for_localhost)
