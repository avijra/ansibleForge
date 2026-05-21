"""WebSocket terminal endpoint — spawns a PTY shell inside the session workspace."""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import os
import pty
import signal
import struct
import termios

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ansible_forge.logging import get_logger
from ansible_forge.workspace.resolver import resolve_workspace

logger = get_logger(__name__)
router = APIRouter()


@router.websocket("/terminal/{session_id}")
async def terminal_ws(websocket: WebSocket, session_id: str) -> None:
    ws = resolve_workspace(session_id)

    await websocket.accept()

    if ws is None:
        await websocket.send_text("\r\nSession workspace not found.\r\n")
        await websocket.close()
        return

    master_fd, slave_fd = pty.openpty()

    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env["LANG"] = "en_US.UTF-8"

    pid = os.fork()

    if pid == 0:
        os.close(master_fd)
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        os.close(slave_fd)
        os.chdir(str(ws.path))
        os.execvpe("/bin/bash", ["/bin/bash", "--login"], env)

    os.close(slave_fd)

    loop = asyncio.get_running_loop()
    closed = False

    async def read_pty() -> None:
        nonlocal closed
        try:
            while not closed:
                data = await loop.run_in_executor(None, os.read, master_fd, 4096)
                if not data:
                    break
                await websocket.send_text(data.decode(errors="replace"))
        except (OSError, WebSocketDisconnect):
            logger.debug("pty_read_ended", exc_info=True)
        finally:
            closed = True

    reader_task = asyncio.create_task(read_pty())

    try:
        while not closed:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if isinstance(msg, dict) and msg.get("type") == "resize":
                    cols = int(msg.get("cols", 80))
                    rows = int(msg.get("rows", 24))
                    winsize = struct.pack("HHHH", rows, cols, 0, 0)
                    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                    os.kill(pid, signal.SIGWINCH)
                    continue
            except (json.JSONDecodeError, ValueError):
                logger.debug("terminal_msg_parse_failed", exc_info=True)
            os.write(master_fd, raw.encode())
    except WebSocketDisconnect:
        logger.debug("terminal_ws_disconnected", session_id=session_id)
    finally:
        closed = True
        reader_task.cancel()
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
        with contextlib.suppress(OSError):
            os.close(master_fd)
        try:
            _pid, _ = os.waitpid(pid, os.WNOHANG)
            if _pid == 0:
                await asyncio.sleep(2)
                try:
                    os.kill(pid, 0)
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, ChildProcessError):
                    pass
                with contextlib.suppress(ChildProcessError):
                    os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
        logger.debug("terminal_closed", session_id=session_id)
