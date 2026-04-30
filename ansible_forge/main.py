"""AnsibleForge application entry point."""

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
from ansible_forge.workspace.manager import WorkspaceManager

logger = get_logger(__name__)


def _setup_frozen_env() -> None:
    """When running as a PyInstaller bundle, prepend the bundle directory to
    PATH so that companion CLI executables (ansible-playbook, ansible-galaxy,
    etc.) are found by ansible-runner and subprocess calls."""
    if not getattr(sys, "frozen", False):
        return
    bundle_dir = Path(sys.executable).resolve().parent
    current_path = os.environ.get("PATH", "")
    if str(bundle_dir) not in current_path.split(os.pathsep):
        os.environ["PATH"] = str(bundle_dir) + os.pathsep + current_path


_setup_frozen_env()

UI_DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"


async def _periodic_cleanup(interval: int = 300) -> None:
    """Remove expired workspaces every *interval* seconds."""
    mgr = WorkspaceManager()
    while True:
        await asyncio.sleep(interval)
        try:
            mgr.cleanup_expired()
        except Exception:
            logger.warning("workspace_cleanup_error", exc_info=True)


async def _periodic_consolidation(interval: int = 3600) -> None:
    """Consolidate repeated experiences into generalized rules."""
    await asyncio.sleep(30)
    while True:
        try:
            from ansible_forge.api.endpoints.chat import get_orchestrator
            from ansible_forge.knowledge.consolidation import consolidate_experiences

            orch = get_orchestrator()
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
    cleanup_task = asyncio.create_task(_periodic_cleanup())
    consolidation_task = asyncio.create_task(_periodic_consolidation())
    try:
        yield
    finally:
        cleanup_task.cancel()
        consolidation_task.cancel()
        logger.info("ansibleforge_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="AnsibleForge",
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
