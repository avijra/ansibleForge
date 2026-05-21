"""Resolve a Workspace from a session ID, using the session store for project path lookup."""

from __future__ import annotations

import asyncio
from functools import partial

from ansible_forge.persistence.session_store import SessionStore
from ansible_forge.workspace.manager import Workspace, WorkspaceManager

_mgr: WorkspaceManager | None = None


def _get_store() -> SessionStore:
    return SessionStore.get_instance()


def _get_mgr() -> WorkspaceManager:
    global _mgr
    if _mgr is None:
        _mgr = WorkspaceManager()
    return _mgr


def _resolve_sync(session_id: str) -> Workspace | None:
    store = _get_store()
    mgr = _get_mgr()

    session_meta = store.get_session(session_id)
    if session_meta and session_meta.get("project_path"):
        ws = mgr.get_by_path(session_meta["project_path"])
        if ws is not None:
            return ws

    return mgr.get(session_id)


def resolve_workspace(session_id: str) -> Workspace | None:
    return _resolve_sync(session_id)


async def aresolve_workspace(session_id: str) -> Workspace | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_resolve_sync, session_id))
