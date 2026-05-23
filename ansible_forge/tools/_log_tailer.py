"""Shared workspace log-file tailing for long-running tools.

Scans the workspace for new or changed .log / .out files and streams
their content as live_log events via an asyncio queue.  Used by
execute_playbook, run_adhoc, local_exec, and terraform_exec.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
from typing import Any

LOG_EXTENSIONS = {".log", ".out"}
LOG_MAX_PREVIEW = 2000
LOG_MAX_FILES = 10
LOG_MAX_READ = 64 * 1024

TAIL_POLL_INTERVAL = 3.0
TAIL_MAX_LINE_LEN = 500

_SKIP_DIRS = frozenset({".tuyere", "node_modules", ".git", "__pycache__"})


def _should_skip(path: Path) -> bool:
    return bool(_SKIP_DIRS & set(path.parts))


def snapshot_log_files(ws: Path) -> dict[str, float]:
    snapshot: dict[str, float] = {}
    try:
        for ext in LOG_EXTENSIONS:
            for f in ws.rglob(f"*{ext}"):
                if _should_skip(f):
                    continue
                with contextlib.suppress(OSError):
                    snapshot[str(f.relative_to(ws))] = f.stat().st_mtime
    except Exception:
        pass
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
    ws: Path, before: dict[str, float]
) -> list[dict[str, str]]:
    detected: list[dict[str, str]] = []
    try:
        ws_real = ws.resolve()
        for ext in LOG_EXTENSIONS:
            for f in ws.rglob(f"*{ext}"):
                if _should_skip(f):
                    continue
                try:
                    real = f.resolve(strict=True)
                    if not str(real).startswith(str(ws_real) + os.sep) and real != ws_real:
                        continue
                    rel = str(f.relative_to(ws))
                    mtime = real.stat().st_mtime
                    fsize = real.stat().st_size
                    if fsize > LOG_MAX_READ:
                        continue
                    if rel not in before or mtime > before[rel]:
                        preview = tail_text(real, LOG_MAX_PREVIEW)
                        detected.append({
                            "path": rel,
                            "size": str(fsize),
                            "preview": preview,
                        })
                except OSError:
                    pass
    except Exception:
        pass
    return detected[:LOG_MAX_FILES]


async def tail_new_logs(
    ws: Path, baseline: dict[str, float], queue: asyncio.Queue[dict[str, Any]]
) -> None:
    positions: dict[str, int] = {}
    ws_resolved = ws.resolve()

    while True:
        await asyncio.sleep(TAIL_POLL_INTERVAL)
        try:
            for ext in LOG_EXTENSIONS:
                for f in ws.rglob(f"*{ext}"):
                    if _should_skip(f):
                        continue
                    try:
                        real = f.resolve(strict=True)
                        if not str(real).startswith(str(ws_resolved) + os.sep) and real != ws_resolved:
                            continue
                        rel = str(f.relative_to(ws))
                        stat_info = real.stat()
                        if stat_info.st_size > LOG_MAX_READ:
                            continue
                        old_mtime = baseline.get(rel, 0)
                        if stat_info.st_mtime <= old_mtime and rel not in positions:
                            continue

                        pos = positions.get(rel, 0)
                        if stat_info.st_size <= pos:
                            continue

                        with real.open("r", encoding="utf-8", errors="replace") as fh:
                            fh.seek(pos)
                            new_data = fh.read(8192)
                            positions[rel] = fh.tell()

                        if new_data.strip():
                            lines = new_data.strip().splitlines()
                            preview = "\n".join(
                                ln[:TAIL_MAX_LINE_LEN] for ln in lines[-10:]
                            )
                            with contextlib.suppress(Exception):
                                queue.put_nowait({
                                    "source": "log_file",
                                    "file": rel,
                                    "content": preview,
                                })
                    except OSError:
                        pass
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
