"""Top-level API router — mounts all endpoint modules."""

from __future__ import annotations

from fastapi import APIRouter

from ansible_forge.api.endpoints import (
    chat,
    collections,
    execute,
    health,
    inventory,
    knowledge,
    lint,
    playbooks,
    secrets,
    sessions,
    settings,
    terminal,
    workspace_files,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router, tags=["health"])
api_router.include_router(chat.router, tags=["chat"])
api_router.include_router(secrets.router, tags=["secrets"])
api_router.include_router(execute.router, tags=["execute"])
api_router.include_router(playbooks.router, tags=["playbooks"])
api_router.include_router(inventory.router, tags=["inventory"])
api_router.include_router(collections.router, tags=["collections"])
api_router.include_router(settings.router, tags=["settings"])
api_router.include_router(knowledge.router, tags=["knowledge"])
api_router.include_router(sessions.router, tags=["sessions"])
api_router.include_router(workspace_files.router, tags=["workspace"])
api_router.include_router(lint.router, tags=["lint"])
api_router.include_router(terminal.router, tags=["terminal"])
