"""Resolve a Workspace from a session ID, using the session store for project path lookup."""

from __future__ import annotations

from ansible_forge.persistence.session_store import SessionStore
from ansible_forge.workspace.manager import Workspace, WorkspaceManager

_store: SessionStore | None = None
_mgr: WorkspaceManager | None = None


def _get_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store


def _get_mgr() -> WorkspaceManager:
    global _mgr
    if _mgr is None:
        _mgr = WorkspaceManager()
    return _mgr


def resolve_workspace(session_id: str) -> Workspace | None:
    """Resolve a workspace for the given session.

    Checks the session store for a ``project_path`` first and falls back
    to looking up the session ID under the default base directory.
    """
    store = _get_store()
    mgr = _get_mgr()

    session_meta = store.get_session(session_id)
    if session_meta and session_meta.get("project_path"):
        ws = mgr.get_by_path(session_meta["project_path"])
        if ws is not None:
            return ws

    return mgr.get(session_id)
