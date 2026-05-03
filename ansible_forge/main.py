"""Tuyere application entry point."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ansible_forge import __version__
from ansible_forge.api.middleware.logging import RequestLoggingMiddleware
from ansible_forge.api.router import api_router
from ansible_forge.config import get_settings
from ansible_forge.logging import get_logger, setup_logging

logger = get_logger(__name__)


def _setup_frozen_env() -> None:
    """Prepend tool directories to PATH so subprocess calls find companion
    binaries (ansible-playbook, ansible-galaxy, tofu, etc.)."""
    extra_dirs: list[str] = []

    managed_bin = str(Path.home() / ".ansibleforge" / "bin")
    extra_dirs.append(managed_bin)

    if getattr(sys, "frozen", False):
        bundle_dir = str(Path(sys.executable).resolve().parent)
        extra_dirs.append(bundle_dir)

    current_path = os.environ.get("PATH", "")
    path_parts = current_path.split(os.pathsep)
    prepend = [d for d in extra_dirs if d not in path_parts]
    if prepend:
        os.environ["PATH"] = os.pathsep.join(prepend) + os.pathsep + current_path


_setup_frozen_env()

UI_DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"


async def _parent_watchdog(check_interval: int = 5) -> None:
    """Shut down if parent Electron process dies (prevents zombie backends)."""
    parent_pid_str = os.environ.get("ANSIBLEFORGE_PARENT_PID")
    if not parent_pid_str:
        return
    parent_pid = int(parent_pid_str)
    logger.info("parent_watchdog_started", parent_pid=parent_pid)
    while True:
        await asyncio.sleep(check_interval)
        try:
            os.kill(parent_pid, 0)
        except (OSError, ProcessLookupError):
            logger.info("parent_died_shutting_down", parent_pid=parent_pid)
            os._exit(0)


async def _periodic_consolidation(interval: int = 3600) -> None:
    """Consolidate repeated experiences into generalized rules and prune stale ones."""
    await asyncio.sleep(30)
    while True:
        try:
            from ansible_forge.api.endpoints.chat import get_orchestrator
            from ansible_forge.knowledge.consolidation import consolidate_experiences

            orch = get_orchestrator()
            pruned = orch._experience_store.prune_stale(max_age_days=30, min_confidence=0.3)
            if pruned:
                logger.info("periodic_prune_done", pruned=pruned)
            count = await consolidate_experiences(orch._experience_store, orch._llm)
            if count:
                logger.info("periodic_consolidation_done", rules_created=count)
        except Exception:
            logger.debug("periodic_consolidation_failed", exc_info=True)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info(
        "ansibleforge_starting",
        version=__version__,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
    )
    consolidation_task = asyncio.create_task(_periodic_consolidation())
    watchdog_task = asyncio.create_task(_parent_watchdog())
    try:
        yield
    finally:
        watchdog_task.cancel()
        consolidation_task.cancel()
        logger.info("ansibleforge_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Tuyere",
        description=(
            "The definitive AI agent harness for Ansible. "
            "Generate, validate, execute, and manage any Ansible workflow "
            "through natural language."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)

    app.include_router(api_router)

    if UI_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="ui-assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str) -> FileResponse:
            """Serve the SPA index.html for all non-API routes."""
            resolved = (UI_DIST / full_path).resolve()
            if resolved.is_relative_to(UI_DIST.resolve()) and resolved.is_file():
                return FileResponse(resolved)
            return FileResponse(UI_DIST / "index.html")

    return app


app = create_app()


def cli_entry() -> None:
    """CLI entry point for `ansible-forge` command."""
    settings = get_settings()
    uvicorn.run(
        "ansible_forge.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    cli_entry()
