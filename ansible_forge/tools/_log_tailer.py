"""Shared workspace log-file tailing for long-running tools.

Scans the workspace (and optional extra directories) for new or changed
.log / .out files and streams their content as live_log events via an
asyncio queue.  Used by execute_playbook, run_adhoc, and terraform_exec.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

LOG_EXTENSIONS = {".log", ".out"}
LOG_MAX_PREVIEW = 2000
LOG_MAX_FILES = 10
LOG_MAX_READ = 512 * 1024

TAIL_POLL_INTERVAL = 3.0
TAIL_MAX_LINE_LEN = 500

_SKIP_DIRS = frozenset({".tuyere", "node_modules", ".git", "__pycache__"})


def _should_skip(path: Path) -> bool:
    return bool(_SKIP_DIRS & set(path.parts))


def _iter_log_files(
    directories: list[Path],
) -> list[tuple[Path, Path]]:
    """Yield (base_dir, file_path) for all log files in *directories*."""
    results: list[tuple[Path, Path]] = []
    seen: set[str] = set()
    for d in directories:
        if not d.is_dir():
            continue
        try:
            for ext in LOG_EXTENSIONS:
                for f in d.rglob(f"*{ext}"):
                    if _should_skip(f):
                        continue
                    real_str = str(f.resolve())
                    if real_str not in seen:
                        seen.add(real_str)
                        results.append((d, f))
        except Exception:
            pass
    return results


def snapshot_log_files(
    ws: Path,
    extra_dirs: list[Path] | None = None,
) -> dict[str, float]:
    snapshot: dict[str, float] = {}
    dirs = [ws] + (extra_dirs or [])
    for _base, f in _iter_log_files(dirs):
        with contextlib.suppress(OSError):
            key = str(f.resolve())
            snapshot[key] = f.stat().st_mtime
    return snapshot


def tail_text(path: Path, max_chars: int) -> str:
    size = path.stat().st_size
    read_bytes = min(size, max_chars * 4)
    with path.open("rb") as fh:
        if size > read_bytes:
            fh.seek(size - read_bytes)
        raw = fh.read(read_bytes)
    text = raw.decode("utf-8", errors="replace")
    return text[-max_chars:] if len(text) > max_chars else text


def detect_new_log_files(
    ws: Path,
    before: dict[str, float],
    extra_dirs: list[Path] | None = None,
) -> list[dict[str, str]]:
    detected: list[dict[str, str]] = []
    dirs = [ws] + (extra_dirs or [])
    for _base, f in _iter_log_files(dirs):
        try:
            real = f.resolve(strict=True)
            key = str(real)
            fsize = real.stat().st_size
            if fsize > LOG_MAX_READ:
                continue
            mtime = real.stat().st_mtime
            if key not in before or mtime > before[key]:
                preview = tail_text(real, LOG_MAX_PREVIEW)
                detected.append({
                    "path": str(real),
                    "size": str(fsize),
                    "preview": preview,
                })
        except OSError:
            pass
    return detected[:LOG_MAX_FILES]


async def tail_new_logs(
    ws: Path,
    baseline: dict[str, float],
    queue: asyncio.Queue[dict[str, Any]],
    extra_dirs: list[Path] | None = None,
) -> None:
    positions: dict[str, int] = {}
    dirs = [ws] + (extra_dirs or [])

    while True:
        await asyncio.sleep(TAIL_POLL_INTERVAL)
        try:
            for _base, f in _iter_log_files(dirs):
                try:
                    real = f.resolve(strict=True)
                    key = str(real)
                    stat_info = real.stat()
                    if stat_info.st_size > LOG_MAX_READ:
                        continue
                    old_mtime = baseline.get(key, 0)
                    if stat_info.st_mtime <= old_mtime and key not in positions:
                        continue

                    pos = positions.get(key, 0)
                    if stat_info.st_size <= pos:
                        continue

                    with real.open("r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(pos)
                        new_data = fh.read(8192)
                        positions[key] = fh.tell()

                    if new_data.strip():
                        lines = new_data.strip().splitlines()
                        preview = "\n".join(
                            ln[:TAIL_MAX_LINE_LEN] for ln in lines[-10:]
                        )
                        display = real.name
                        try:
                            display = str(f.relative_to(ws))
                        except ValueError:
                            display = str(real)
                        with contextlib.suppress(Exception):
                            queue.put_nowait({
                                "source": "log_file",
                                "file": display,
                                "content": preview,
                            })
                except OSError:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
